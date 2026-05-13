"""
SIGNUM ― 解析・スクリーニングモジュール (並列対応 + 自動スクレイピング)
"""

from __future__ import annotations

import io
import json
import math
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    yf = None  # type: ignore

try:
    import requests
except ImportError:
    requests = None  # type: ignore


SCRAPE_CACHE_PATH = Path(__file__).with_name(".scrape_cache.json")
SCRAPE_CACHE_TTL_HOURS = 24
USER_AGENT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
}
_cache_lock = threading.Lock()


# ----------------------------------------------------------------------
# yfinance ラッパー
# ----------------------------------------------------------------------
def to_yf_symbol(code: str | int) -> str:
    s = str(code).strip()
    if "." in s:
        return s
    return f"{s}.T"


def fetch_history(code: str | int, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    if yf is None:
        raise RuntimeError("yfinance がインストールされていません。")
    symbol = to_yf_symbol(code)
    try:
        df = yf.download(symbol, period=period, interval=interval,
                         auto_adjust=True, progress=False, threads=False)
    except Exception:
        return pd.DataFrame()
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns=str.title)
    needed = {"Open", "High", "Low", "Close", "Volume"}
    if not needed.issubset(df.columns):
        return pd.DataFrame()
    return df.dropna(subset=["Close"])


def fetch_history_batch(codes: Iterable[str | int], period: str = "2y",
                        interval: str = "1d") -> dict[str, pd.DataFrame]:
    if yf is None:
        return {}
    codes = [str(c).zfill(4) for c in codes]
    if not codes:
        return {}
    symbols = [to_yf_symbol(c) for c in codes]
    sym_to_code = {s: c for s, c in zip(symbols, codes)}
    try:
        df = yf.download(
            " ".join(symbols),
            period=period, interval=interval,
            auto_adjust=True, progress=False, threads=True,
            group_by="ticker",
        )
    except Exception:
        return {}
    result: dict[str, pd.DataFrame] = {}
    if df is None or df.empty:
        return result
    if isinstance(df.columns, pd.MultiIndex):
        for t in df.columns.get_level_values(0).unique():
            try:
                sub = df[t].dropna(subset=["Close"])
            except Exception:
                continue
            if sub is None or sub.empty:
                continue
            sub = sub.rename(columns=str.title)
            code = sym_to_code.get(t)
            if code is None:
                continue
            if not {"Open", "High", "Low", "Close", "Volume"}.issubset(sub.columns):
                continue
            result[code] = sub
    else:
        if len(symbols) == 1:
            sub = df.dropna(subset=["Close"])
            if not sub.empty:
                result[codes[0]] = sub.rename(columns=str.title)
    return result


def fetch_info(code: str | int) -> dict:
    if yf is None:
        return {}
    try:
        return yf.Ticker(to_yf_symbol(code)).info or {}
    except Exception:
        return {}


def fetch_quarterly_financials(code: str | int) -> pd.DataFrame:
    if yf is None:
        return pd.DataFrame()
    try:
        t = yf.Ticker(to_yf_symbol(code))
        qf = t.quarterly_financials
        if qf is None or (isinstance(qf, pd.DataFrame) and qf.empty):
            return pd.DataFrame()
        return qf
    except Exception:
        return pd.DataFrame()


# ----------------------------------------------------------------------
# 指標計算
# ----------------------------------------------------------------------
def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    out["SMA25"] = out["Close"].rolling(25).mean()
    out["SMA75"] = out["Close"].rolling(75).mean()
    out["SMA200"] = out["Close"].rolling(200).mean()
    delta = out["Close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    out["RSI14"] = 100 - 100 / (1 + rs)
    tr = pd.concat([
        (out["High"] - out["Low"]).abs(),
        (out["High"] - out["Close"].shift()).abs(),
        (out["Low"] - out["Close"].shift()).abs(),
    ], axis=1)
    out["TR"] = tr.max(axis=1)
    out["ATR14"] = out["TR"].rolling(14).mean()
    out["Vol60"] = out["Volume"].rolling(60).mean()
    out["Vol20"] = out["Volume"].rolling(20).mean()
    out["VolSurge10_60"] = out["Volume"].rolling(10).mean() / out["Vol60"]
    return out


# ----------------------------------------------------------------------
# 黒字転換
# ----------------------------------------------------------------------
ORDINARY_INCOME_LABELS = (
    "Pretax Income", "Income Before Tax", "Pretax Profit",
    "Ordinary Income", "Operating Income", "Net Income",
)


def quarterly_turnaround(code: str | int,
                         qf: Optional[pd.DataFrame] = None) -> tuple[bool, str]:
    if qf is None:
        qf = fetch_quarterly_financials(code)
    if qf.empty:
        return False, ""
    for label in ORDINARY_INCOME_LABELS:
        if label in qf.index:
            series = qf.loc[label].dropna()
            if len(series) >= 2:
                latest = float(series.iloc[0])
                prev = float(series.iloc[1])
                if latest > 0 and prev <= 0:
                    period = qf.columns[0]
                    period_str = period.strftime("%Y-%m") if hasattr(period, "strftime") else str(period)
                    return True, f"{label} {period_str}: {prev/1e8:+.1f}億 → {latest/1e8:+.1f}億"
            break
    return False, ""


# ----------------------------------------------------------------------
# 永続キャッシュ (24時間)
# ----------------------------------------------------------------------
def _cache_load() -> dict:
    if not SCRAPE_CACHE_PATH.exists():
        return {}
    try:
        return json.loads(SCRAPE_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _cache_save(cache: dict) -> None:
    try:
        SCRAPE_CACHE_PATH.write_text(
            json.dumps(cache, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass


def _cache_get(key: str) -> Optional[dict]:
    with _cache_lock:
        cache = _cache_load()
    entry = cache.get(key)
    if not entry:
        return None
    try:
        cached_at = pd.Timestamp(entry["t"])
        if (pd.Timestamp.now() - cached_at).total_seconds() / 3600 > SCRAPE_CACHE_TTL_HOURS:
            return None
        return entry["d"]
    except Exception:
        return None


def _cache_set(key: str, data: dict) -> None:
    with _cache_lock:
        cache = _cache_load()
        cache[key] = {"t": str(pd.Timestamp.now()), "d": data}
        _cache_save(cache)


# ----------------------------------------------------------------------
# 株探スクレイピング: ストックオプション関連 IR
# ----------------------------------------------------------------------
def _scrape_options_kabutan(code: str, within_days: int = 365) -> dict:
    """株探の適時開示から SO 関連IRを取得 (キャッシュなしの実体)"""
    if requests is None:
        return {"found": False, "info": "", "error": "requests未インストール"}
    code = str(code).zfill(4)
    cutoff = pd.Timestamp.now() - pd.Timedelta(days=within_days)
    keywords = ["ストックオプション", "新株予約権"]
    best_date = None
    best_title = ""

    for keyword in keywords:
        try:
            r = requests.get(
                "https://kabutan.jp/disclosures/",
                params={"code": code, "keyword": keyword},
                headers=USER_AGENT_HEADERS,
                timeout=15,
            )
            if r.status_code != 200:
                continue
            r.encoding = r.apparent_encoding or "utf-8"
            tables = pd.read_html(io.StringIO(r.text))
        except Exception:
            continue

        for t in tables:
            if len(t) == 0 or len(t.columns) < 2:
                continue
            for _, row in t.iterrows():
                # 行から日付と見出しを抽出
                vals = [str(v) for v in row.values if pd.notna(v)]
                joined = " ".join(vals)
                if not any(kw in joined for kw in keywords):
                    continue
                date = None
                for v in vals:
                    try:
                        d = pd.to_datetime(v, errors="coerce")
                        if pd.notna(d) and pd.Timestamp("2015-01-01") < d <= pd.Timestamp.now():
                            date = d
                            break
                    except Exception:
                        continue
                if date is None or date < cutoff:
                    continue
                title = max(vals, key=len)
                if best_date is None or date > best_date:
                    best_date = date
                    best_title = title[:200]

    if best_date is not None:
        return {
            "found": True,
            "info": f"{best_date.strftime('%Y-%m-%d')}: {best_title[:100]}",
        }
    return {"found": False, "info": ""}


def has_recent_paid_so(code: str, within_days: int = 365,
                       paid_so_df=None) -> tuple[bool, str]:
    """旧API互換: 自動スクレイピング結果を返す。 paid_so_df は無視。"""
    cached = _cache_get(f"options:{code}:{within_days}")
    if cached is not None:
        return cached.get("found", False), cached.get("info", "")
    res = _scrape_options_kabutan(code, within_days)
    _cache_set(f"options:{code}:{within_days}", res)
    return res.get("found", False), res.get("info", "")


# ----------------------------------------------------------------------
# 株探スクレイピング: 空売り残高 → 連続買戻し検出
# ----------------------------------------------------------------------
def _scrape_short_cover_kabutan(code: str) -> dict:
    """株探の空売りページから直近残高が連続減少しているか判定"""
    if requests is None:
        return {"found": False, "info": "", "error": "requests未インストール"}
    code = str(code).zfill(4)
    try:
        r = requests.get(
            "https://kabutan.jp/stock/karauri",
            params={"code": code},
            headers=USER_AGENT_HEADERS,
            timeout=15,
        )
        if r.status_code != 200:
            return {"found": False, "info": ""}
        r.encoding = r.apparent_encoding or "utf-8"
        tables = pd.read_html(io.StringIO(r.text))
    except Exception:
        return {"found": False, "info": ""}

    for t in tables:
        col_str = " ".join(str(c) for c in t.columns)
        if not ("残高" in col_str or "株数" in col_str or "比率" in col_str):
            continue
        if len(t) < 3:
            continue
        # 数値が3つ以上ある列を探す
        numeric_col = None
        for c in t.columns:
            try:
                vals = pd.to_numeric(
                    t[c].astype(str).str.replace(",", "").str.replace("%", "").str.strip(),
                    errors="coerce",
                )
                if vals.notna().sum() >= 3:
                    numeric_col = c
                    break
            except Exception:
                continue
        if numeric_col is None:
            continue
        try:
            vals = pd.to_numeric(
                t[numeric_col].astype(str).str.replace(",", "").str.replace("%", "").str.strip(),
                errors="coerce",
            ).dropna()
        except Exception:
            continue
        if len(vals) < 3:
            continue
        recent = vals.head(5).tolist()  # 直近5件 (新しい順を想定)
        # 直近3件すべて減少していれば「連続買戻し」
        if len(recent) >= 3 and recent[0] < recent[1] < recent[2]:
            pct = (recent[0] - recent[2]) / max(abs(recent[2]), 1e-9) * 100
            return {
                "found": True,
                "info": f"連続3回減少 {recent[2]:,.1f} → {recent[0]:,.1f} ({pct:+.1f}%)",
            }
        if len(recent) >= 2 and recent[0] < recent[1]:
            return {
                "found": True,
                "info": f"直近2回減少 {recent[1]:,.1f} → {recent[0]:,.1f}",
            }
    return {"found": False, "info": ""}


def has_recent_short_cover(code: str, within_days: int = 60,
                           sc_df=None) -> tuple[bool, str]:
    """旧API互換: 自動スクレイピング結果を返す。 sc_df は無視。"""
    cached = _cache_get(f"short:{code}")
    if cached is not None:
        return cached.get("found", False), cached.get("info", "")
    res = _scrape_short_cover_kabutan(code)
    _cache_set(f"short:{code}", res)
    return res.get("found", False), res.get("info", "")


def clear_scrape_cache() -> None:
    """スクレイピングキャッシュをクリア"""
    if SCRAPE_CACHE_PATH.exists():
        try:
            SCRAPE_CACHE_PATH.unlink()
        except Exception:
            pass


# ----------------------------------------------------------------------
# 銘柄メトリクス
# ----------------------------------------------------------------------
@dataclass
class StockMetrics:
    code: str
    name: str = ""
    sector: str = ""
    theme: str = ""
    market: str = ""
    last_close: float = float("nan")
    last_volume: float = float("nan")
    avg_volume_60: float = float("nan")
    high_6m: float = float("nan")
    high_1y: float = float("nan")
    drawdown_6m: float = float("nan")
    drawdown_1y: float = float("nan")
    market_cap_oku: float = float("nan")
    shares_outstanding: float = float("nan")
    atr_pct: float = float("nan")
    rsi14: float = float("nan")
    momentum_20: float = float("nan")
    volume_surge: float = float("nan")
    rr_score: float = float("nan")
    paid_so_recent: bool = False
    paid_so_info: str = ""
    q_turnaround: bool = False
    q_turnaround_info: str = ""
    short_cover_recent: bool = False
    short_cover_info: str = ""
    error: str = ""


def _safe(v):
    if v is None:
        return float("nan")
    if isinstance(v, float) and math.isnan(v):
        return float("nan")
    return v


def metrics_from_history(df: pd.DataFrame, code: str, name: str = "",
                         sector: str = "", theme: str = "",
                         market: str = "") -> StockMetrics:
    m = StockMetrics(code=code, name=name, sector=sector, theme=theme, market=market)
    if df.empty:
        m.error = "履歴なし"
        return m
    df = compute_indicators(df)
    last = df.iloc[-1]
    m.last_close = float(last["Close"])
    m.last_volume = float(last["Volume"])
    m.avg_volume_60 = float(df["Volume"].tail(60).mean())
    atr = last.get("ATR14")
    m.atr_pct = float(atr / last["Close"]) if atr and last["Close"] else float("nan")
    m.rsi14 = float(_safe(last.get("RSI14")))
    try:
        m.momentum_20 = float(df["Close"].pct_change(20).iloc[-1])
    except Exception:
        m.momentum_20 = float("nan")
    m.volume_surge = float(_safe(df["VolSurge10_60"].iloc[-1]))
    m.high_1y = float(df["High"].tail(252).max())
    m.high_6m = float(df["High"].tail(126).max())
    if m.high_1y > 0:
        m.drawdown_1y = m.last_close / m.high_1y - 1
    if m.high_6m > 0:
        m.drawdown_6m = m.last_close / m.high_6m - 1
    return m


def evaluate_stock(code: str | int, name: str = "", sector: str = "",
                   theme: str = "", market: str = "", period: str = "2y",
                   paid_so_window_days: int = 365,
                   short_cover_window_days: int = 60,
                   check_turnaround: bool = False,
                   fetch_signals: bool = True,
                   # 旧API互換
                   paid_so_df=None,
                   short_cover_df=None) -> StockMetrics:
    df = fetch_history(code, period=period)
    m = metrics_from_history(df, str(code), name, sector, theme, market)
    if m.error:
        return m
    info = fetch_info(code)
    mc = info.get("marketCap")
    if mc:
        m.market_cap_oku = float(mc) / 1e8
    shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
    if shares:
        m.shares_outstanding = float(shares)
    if fetch_signals:
        paid_recent, paid_info = has_recent_paid_so(str(code).zfill(4), paid_so_window_days)
        m.paid_so_recent = paid_recent
        m.paid_so_info = paid_info
        sc_recent, sc_info = has_recent_short_cover(str(code).zfill(4), short_cover_window_days)
        m.short_cover_recent = sc_recent
        m.short_cover_info = sc_info
    if check_turnaround:
        is_turn, turn_info = quarterly_turnaround(code)
        m.q_turnaround = is_turn
        m.q_turnaround_info = turn_info
    m.rr_score = compute_rr_score(m)
    return m


def compute_rr_score(m: StockMetrics) -> float:
    score = 50.0
    dd = m.drawdown_6m if not math.isnan(m.drawdown_6m) else 0
    score += min(max(-dd, 0) * 80, 25)
    vs = m.volume_surge if m.volume_surge and not math.isnan(m.volume_surge) else 1
    score += min(max(vs - 1, 0) * 10, 15)
    atr = m.atr_pct if m.atr_pct and not math.isnan(m.atr_pct) else 0.02
    score += min(max(atr - 0.02, 0) * 200, 10)
    domestic = {
        "DX・SaaS", "AI・データ", "教育・HR", "バイオ・医療",
        "内需・ディフェンシブ", "インバウンド", "EC・物流",
        "フィンテック・暗号資産", "ゲーム・エンタメ", "セキュリティ",
        "環境・再エネ", "IoT・AI", "ロボット・FA",
    }
    if m.theme in domestic:
        score += 5
    if m.paid_so_recent:
        score += 8
    if m.q_turnaround:
        score += 10
    if m.short_cover_recent:
        score += 10
    return max(0.0, min(100.0, round(score, 2)))


def backtest_forward_return(df: pd.DataFrame, drawdown_threshold: float = -0.5,
                            volume_surge_threshold: float = 1.5,
                            forward_days: int = 21) -> dict:
    if df.empty or len(df) < 260:
        return {"samples": 0}
    work = compute_indicators(df).dropna()
    work["High252"] = work["High"].rolling(252, min_periods=120).max()
    work["DD"] = work["Close"] / work["High252"] - 1
    triggers = work[(work["DD"] <= drawdown_threshold) &
                    (work["VolSurge10_60"] >= volume_surge_threshold)]
    if triggers.empty:
        return {"samples": 0}
    forwards: list[float] = []
    for ts in triggers.index:
        try:
            pos = work.index.get_loc(ts)
        except KeyError:
            continue
        if pos + forward_days >= len(work):
            continue
        future = work.iloc[pos + forward_days]
        forwards.append(float(future["Close"] / work.iloc[pos]["Close"] - 1))
    if not forwards:
        return {"samples": 0}
    arr = np.array(forwards)
    return {
        "samples": len(arr),
        "mean": float(arr.mean()),
        "median": float(np.median(arr)),
        "win_rate": float((arr > 0).mean()),
        "p20": float(np.percentile(arr, 20)),
        "p80": float(np.percentile(arr, 80)),
    }


@dataclass
class ScreenConfig:
    drawdown_min: float = -0.95
    drawdown_max: float = -0.5
    market_cap_min_oku: float = 30
    market_cap_max_oku: float = 500
    avg_volume_min: int = 10_000
    avg_volume_max: int = 500_000
    volume_surge_min: float = 1.0
    volume_surge_enabled: bool = False
    themes: tuple[str, ...] = ()
    exclude_war_sensitive: bool = True
    require_paid_so: bool = False
    paid_so_window_days: int = 365
    require_turnaround: bool = False
    require_short_cover: bool = False
    short_cover_window_days: int = 60
    fetch_signals: bool = True


WAR_GAFA_SENSITIVE_THEMES = {"半導体関連"}


def _passes_history_filters(m: StockMetrics, c: ScreenConfig) -> bool:
    if math.isnan(m.last_close):
        return False
    if not (c.avg_volume_min <= m.avg_volume_60 <= c.avg_volume_max):
        return False
    if not math.isnan(m.drawdown_1y):
        if not (c.drawdown_min <= m.drawdown_1y <= c.drawdown_max):
            return False
    if c.volume_surge_enabled and not math.isnan(m.volume_surge):
        if m.volume_surge < c.volume_surge_min:
            return False
    if c.themes and m.theme not in c.themes:
        return False
    if c.exclude_war_sensitive and m.theme in WAR_GAFA_SENSITIVE_THEMES:
        return False
    return True


def _passes_market_cap_filter(m: StockMetrics, c: ScreenConfig) -> bool:
    if math.isnan(m.market_cap_oku):
        return True
    return c.market_cap_min_oku <= m.market_cap_oku <= c.market_cap_max_oku


def _passes_filters(m: StockMetrics, c: ScreenConfig) -> bool:
    if not _passes_history_filters(m, c):
        return False
    if not _passes_market_cap_filter(m, c):
        return False
    if c.require_turnaround and not m.q_turnaround:
        return False
    if c.require_paid_so and not m.paid_so_recent:
        return False
    if c.require_short_cover and not m.short_cover_recent:
        return False
    return True


def screen_universe_parallel(
    universe: pd.DataFrame,
    config: ScreenConfig,
    *,
    batch_size: int = 80,
    max_workers: int = 10,
    period: str = "2y",
    progress_callback: Optional[Callable[[float, str], None]] = None,
    paid_so_df=None,  # 旧API互換 (未使用)
    short_cover_df=None,
) -> list[StockMetrics]:
    rows = universe.to_dict("records")
    total = len(rows)
    if total == 0:
        return []

    def _progress(p: float, msg: str):
        if progress_callback:
            try:
                progress_callback(min(max(p, 0.0), 1.0), msg)
            except Exception:
                pass

    # Stage 1: バッチ履歴取得
    history_map: dict[str, pd.DataFrame] = {}
    fetched = 0
    for i in range(0, total, batch_size):
        batch_rows = rows[i:i + batch_size]
        codes = [str(r["code"]).zfill(4) for r in batch_rows]
        try:
            hmap = fetch_history_batch(codes, period=period)
            history_map.update(hmap)
        except Exception:
            pass
        fetched += len(codes)
        _progress(0.05 + 0.4 * fetched / total,
                  f"履歴取得 {fetched}/{total}")

    # Stage 2: 履歴ベースの粗フィルタ
    survivors: list[StockMetrics] = []
    for r in rows:
        code = str(r["code"]).zfill(4)
        df = history_map.get(code)
        if df is None or df.empty:
            continue
        m = metrics_from_history(
            df, code,
            name=r.get("name", ""), sector=r.get("sector", ""),
            theme=r.get("theme", ""), market=r.get("market", ""),
        )
        if _passes_history_filters(m, config):
            survivors.append(m)

    if not survivors:
        _progress(1.0, "詳細解析対象なし")
        return []
    _progress(0.45, f"履歴フィルタ通過 {len(survivors)} 銘柄を詳細解析へ")

    # Stage 3: 並列 info + スクレイピング + turnaround
    needs_turnaround = config.require_turnaround
    needs_signals = config.fetch_signals or config.require_paid_so or config.require_short_cover

    def _enrich(m: StockMetrics) -> Optional[StockMetrics]:
        try:
            info = fetch_info(m.code)
            mc = info.get("marketCap")
            if mc:
                m.market_cap_oku = float(mc) / 1e8
            shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
            if shares:
                m.shares_outstanding = float(shares)
        except Exception:
            pass
        if not _passes_market_cap_filter(m, config):
            return None
        # 自動スクレイピング (キャッシュ付き)
        if needs_signals:
            try:
                pr, pi = has_recent_paid_so(m.code, config.paid_so_window_days)
                m.paid_so_recent = pr
                m.paid_so_info = pi
            except Exception:
                pass
            try:
                sr, si = has_recent_short_cover(m.code, config.short_cover_window_days)
                m.short_cover_recent = sr
                m.short_cover_info = si
            except Exception:
                pass
            if config.require_paid_so and not m.paid_so_recent:
                return None
            if config.require_short_cover and not m.short_cover_recent:
                return None
        if needs_turnaround:
            try:
                is_turn, turn_info = quarterly_turnaround(m.code)
                m.q_turnaround = is_turn
                m.q_turnaround_info = turn_info
            except Exception:
                pass
            if not m.q_turnaround:
                return None
        m.rr_score = compute_rr_score(m)
        return m

    final: list[StockMetrics] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_enrich, s): s for s in survivors}
        done = 0
        n_surv = len(survivors)
        for fut in as_completed(futures):
            done += 1
            try:
                res = fut.result()
                if res is not None:
                    final.append(res)
            except Exception:
                pass
            if done % max(1, n_surv // 50) == 0 or done == n_surv:
                _progress(0.45 + 0.55 * done / n_surv,
                          f"詳細解析 {done}/{n_surv} (ヒット {len(final)})")
    _progress(1.0, f"完了: ヒット {len(final)} 銘柄")
    final.sort(key=lambda x: x.rr_score, reverse=True)
    return final


def external_links(code: str | int, name: str = "") -> list[tuple[str, str]]:
    code = str(code)
    return [
        ("Yahoo!ファイナンス チャート", f"https://finance.yahoo.co.jp/quote/{code}.T"),
        ("Yahoo!ファイナンス ニュース", f"https://finance.yahoo.co.jp/quote/{code}.T/news"),
        ("Yahoo!ファイナンス 業績", f"https://finance.yahoo.co.jp/quote/{code}.T/performance"),
        ("みんかぶ", f"https://minkabu.jp/stock/{code}"),
        ("株探 ニュース", f"https://kabutan.jp/stock/news?code={code}"),
        ("株探 業績", f"https://kabutan.jp/stock/finance?code={code}"),
        ("株探 空売り推移", f"https://kabutan.jp/stock/karauri?code={code}"),
        ("ストックオプション検索 (株探)",
         f"https://kabutan.jp/disclosures/?code={code}&keyword=%E3%82%B9%E3%83%88%E3%83%83%E3%82%AF%E3%82%AA%E3%83%97%E3%82%B7%E3%83%A7%E3%83%B3"),
        ("新株予約権検索 (株探)",
         f"https://kabutan.jp/disclosures/?code={code}&keyword=%E6%96%B0%E6%A0%AA%E4%BA%88%E7%B4%84%E6%A8%A9"),
        ("TDnet 適時開示 (検索)", "https://www.release.tdnet.info/inbs/I_main_00.html"),
        ("EDINET 有報検索", "https://disclosure2.edinet-fsa.go.jp/WEEK0010.aspx"),
        ("バフェットコード", f"https://www.buffett-code.com/company/{code}"),
        ("IR BANK", f"https://irbank.net/{code}"),
        ("空売り残高 (JPX)", "https://www.jpx.co.jp/markets/public/short-selling/index.html"),
    ]


# 旧 API のスタブ (互換性のため残す)
def load_paid_so() -> pd.DataFrame:
    return pd.DataFrame(columns=["code", "ir_date", "description"])


def load_short_cover() -> pd.DataFrame:
    return pd.DataFrame(columns=["code", "date", "status", "description"])
