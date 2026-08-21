"""
SIGNUM ― 解析・スクリーニングモジュール (並列対応 + 過去日バックテスト)
"""

from __future__ import annotations

import warnings
try:
    from bs4 import XMLParsedAsHTMLWarning
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
except Exception:
    pass
warnings.filterwarnings("ignore", category=FutureWarning)

import io
import json
import math
import re
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
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
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
# キャッシュ
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


def clear_scrape_cache() -> None:
    if SCRAPE_CACHE_PATH.exists():
        try:
            SCRAPE_CACHE_PATH.unlink()
        except Exception:
            pass


# ----------------------------------------------------------------------
# パースヘルパー (karauri.net 用)
# ----------------------------------------------------------------------
def _coerce_number(v) -> Optional[float]:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    s = str(v).strip()
    if not s or s in ("-", "ー", "‐", "—"):
        return None
    s = s.replace(",", "").replace("%", "").replace("＋", "+").replace("−", "-")
    s = re.sub(r"[^0-9.+\-eE]", "", s)
    if not s or s in (".", "-", "+"):
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _coerce_date(v) -> Optional[pd.Timestamp]:
    if v is None:
        return None
    s = str(v).strip()
    if not s:
        return None
    s2 = re.sub(r"年|月", "-", s).replace("日", "").strip("-")
    for cand in (s2, s):
        try:
            d = pd.to_datetime(cand, errors="coerce")
            if pd.notna(d) and pd.Timestamp("2015-01-01") < d <= pd.Timestamp.now() + pd.Timedelta(days=7):
                return d
        except Exception:
            continue
    return None


def _is_date_string(v) -> bool:
    return _coerce_date(v) is not None


def _is_pure_number(v) -> bool:
    s = str(v).strip()
    if not s:
        return False
    return bool(re.fullmatch(r"[+\-±]?\d[\d,.]*\s*%?", s))


def _normalize_institution_name(name: str) -> str:
    if not name:
        return ""
    s = re.sub(r"\s+", " ", str(name).strip())
    s = re.sub(r"[（）\(\)（）]", "", s)
    s = re.sub(
        r"(株式会社|有限会社|合同会社|Co\.,?\s*Ltd\.?|Ltd\.?|LLC|L\.L\.C\.|"
        r"S\.A\.?|Inc\.?|Corp\.?|Limited|Holdings|Group|Securities|証券)",
        "", s, flags=re.IGNORECASE,
    )
    return re.sub(r"\W+", "", s.lower())[:40]


def _fetch_karauri_html(code: str) -> str:
    if requests is None:
        return ""
    code = str(code).zfill(4)
    for url in (f"https://karauri.net/{code}/", f"https://karauri.net/{code}"):
        try:
            r = requests.get(url, headers=USER_AGENT_HEADERS, timeout=20)
            if r.status_code == 200 and r.text:
                r.encoding = r.apparent_encoding or "utf-8"
                return r.text
        except Exception:
            continue
    return ""


def _parse_karauri_records(html: str) -> list[dict]:
    """karauri.net の銘柄ページから機関別空売り残高の報告履歴を抽出する。

    対象テーブル: 計算日 / 空売り機関 / 残高割合 / 増減(割合) / 残高数量 / 増減(数量) / 備考
    1行 = 1機関の1報告。増減(割合) は前回報告比のポイント差。
    """
    if not html:
        return []
    records: list[dict] = []
    try:
        tables = pd.read_html(io.StringIO(html))
    except Exception:
        return []

    for t_idx, table in enumerate(tables):
        if table is None or len(table) == 0 or len(table.columns) < 3:
            continue
        cols = [str(c) for c in table.columns]
        has_date = any(k in c for c in cols for k in ("計算", "報告日", "日付"))
        has_name = any(k in c for c in cols for k in ("空売り者", "機関", "商号", "投資家", "報告者"))
        has_ratio = any(k in c for c in cols for k in ("割合", "比率"))
        if not (has_date and has_name and has_ratio):
            continue
        date_col = name_col = ratio_col = change_col = None
        for c in table.columns:
            cs = str(c)
            if date_col is None and any(k in cs for k in ("計算", "報告日", "日付")):
                date_col = c
            elif name_col is None and any(k in cs for k in ("空売り者", "機関", "商号", "投資家", "報告者")):
                name_col = c
            elif ratio_col is None and any(k in cs for k in ("割合", "比率")):
                ratio_col = c
            elif (change_col is None and ratio_col is not None
                  and any(k in cs for k in ("増減", "変化", "前回比"))):
                # 残高割合の直後の増減列のみ採用 (残高数量の増減は対象外)
                change_col = c
        if date_col is None or name_col is None or ratio_col is None:
            continue

        for _, row in table.iterrows():
            rec_date = _coerce_date(row.get(date_col))
            raw_name = row.get(name_col)
            rec_name = "" if raw_name is None or (isinstance(raw_name, float) and math.isnan(raw_name)) \
                else str(raw_name).strip()
            if (rec_date is None or not rec_name
                    or _is_pure_number(rec_name) or _is_date_string(rec_name)
                    or "株" in rec_name and _is_pure_number(rec_name.replace("株", ""))):
                continue
            rec_ratio = _coerce_number(row.get(ratio_col))
            if rec_ratio is None or not (0 <= rec_ratio < 50):
                continue
            rec_change = _coerce_number(row.get(change_col)) if change_col is not None else None
            if rec_change is not None and abs(rec_change) >= 50:
                rec_change = None
            records.append({
                "name": rec_name[:80],
                "date": rec_date,
                "ratio": float(rec_ratio),
                "change": rec_change,
                "table_idx": t_idx,
            })
    return records


def _cover_streak(recs: list[dict]) -> tuple[int, float]:
    """最新報告から遡って何回連続で残高割合を減らした(=買い戻した)かを数える。

    recs は日付降順。増減列があればそれを使い、無ければ前後の残高割合差で判定。
    増減 0 (変わらず) や増加・新規IN でストリークは途切れる。
    """
    streak = 0
    total_delta = 0.0
    for i, rec in enumerate(recs):
        delta = rec.get("change")
        if delta is None and i + 1 < len(recs):
            older = recs[i + 1]
            if rec.get("ratio") is not None and older.get("ratio") is not None:
                delta = rec["ratio"] - older["ratio"]
        if delta is not None and delta < 0:
            streak += 1
            total_delta += float(delta)
        else:
            break
    return streak, total_delta


def analyse_karauri(code: str, within_days: int = 7,
                    min_consecutive: int = 2) -> dict:
    """機関投資家ごとに最新報告から min_consecutive 回以上連続で買い戻しており、
    かつ最新の買戻し報告が within_days 日以内の場合のみシグナルとしてカウントする。"""
    code = str(code).zfill(4)
    html = _fetch_karauri_html(code)
    records = _parse_karauri_records(html)
    if not records:
        return {"found": False, "info": "", "count": 0,
                "records_total": 0, "institutions": [], "covering": []}
    by_inst: dict[str, list[dict]] = {}
    display_name: dict[str, str] = {}
    for rec in records:
        key = _normalize_institution_name(rec["name"])
        if not key:
            continue
        by_inst.setdefault(key, []).append(rec)
        if key not in display_name or len(rec["name"]) > len(display_name[key]):
            display_name[key] = rec["name"]
    today = pd.Timestamp.now().normalize()
    covering = []
    for key, recs in by_inst.items():
        recs = sorted(recs, key=lambda x: x["date"], reverse=True)
        latest = recs[0]
        if within_days and (today - latest["date"].normalize()).days > within_days:
            continue
        streak, total_delta = _cover_streak(recs)
        if streak >= min_consecutive:
            covering.append({
                "name": display_name[key],
                "latest_date": latest["date"].strftime("%Y-%m-%d"),
                "latest_ratio": latest["ratio"],
                "streak": streak,
                "total_delta": round(total_delta, 3),
            })
    covering.sort(key=lambda x: (-x["streak"], x["total_delta"]))
    count = len(covering)
    if count == 0:
        return {"found": False, "info": "", "count": 0,
                "records_total": len(records),
                "institutions": list(display_name.values()), "covering": []}
    names = ", ".join(f"{c['name'][:25]}×{c['streak']}連続" for c in covering[:3])
    info = f"{count}機関が{min_consecutive}回以上連続買戻し ({names})"
    return {"found": True, "info": info, "count": count,
            "records_total": len(records),
            "institutions": list(display_name.values()), "covering": covering}


def has_recent_short_cover(code: str, within_days: int = 7, sc_df=None) -> tuple[bool, str]:
    code = str(code).zfill(4)
    cached = _cache_get(f"karauri:{code}")
    if cached is not None:
        return cached.get("found", False), cached.get("info", "")
    res = analyse_karauri(code, within_days=within_days)
    _cache_set(f"karauri:{code}", res)
    return res.get("found", False), res.get("info", "")


def short_cover_count(code: str) -> int:
    code = str(code).zfill(4)
    cached = _cache_get(f"karauri:{code}")
    if cached is not None:
        return int(cached.get("count", 0))
    res = analyse_karauri(code)
    _cache_set(f"karauri:{code}", res)
    return int(res.get("count", 0))


def debug_karauri(code: str) -> dict:
    code = str(code).zfill(4)
    res = analyse_karauri(code)
    _cache_set(f"karauri:{code}", res)
    return res


def has_recent_paid_so(code: str, within_days: int = 365, paid_so_df=None) -> tuple[bool, str]:
    return False, ""


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
    short_cover_count: int = 0
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
                   short_cover_window_days: int = 7,
                   check_turnaround: bool = False,
                   fetch_signals: bool = True,
                   paid_so_df=None, short_cover_df=None) -> StockMetrics:
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
        try:
            sr, si = has_recent_short_cover(str(code).zfill(4),
                                            within_days=short_cover_window_days)
            m.short_cover_recent = sr
            m.short_cover_info = si
            m.short_cover_count = short_cover_count(str(code).zfill(4))
        except Exception:
            pass
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
    if m.short_cover_recent and m.short_cover_count > 0:
        bonus = 6 + min(m.short_cover_count - 1, 3) * 4
        score += bonus
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
    return {"samples": len(arr), "mean": float(arr.mean()),
            "median": float(np.median(arr)),
            "win_rate": float((arr > 0).mean()),
            "p20": float(np.percentile(arr, 20)),
            "p80": float(np.percentile(arr, 80))}


# ----------------------------------------------------------------------
# Forward Returns (新規)
# ----------------------------------------------------------------------
def forward_returns(df: pd.DataFrame, as_of_date,
                    horizons_bdays: tuple[int, ...] = (5, 21, 63, 126, 252)) -> dict[int, float]:
    """
    指定された as_of_date 以降の N営業日のフォワードリターンを計算。
    返り値: {5: 0.012, 21: 0.045, ...} 形式
    """
    out: dict[int, float] = {h: float("nan") for h in horizons_bdays}
    if df is None or df.empty:
        return out
    df = df.sort_index()
    as_of_date = pd.Timestamp(as_of_date)
    mask = df.index <= as_of_date
    if not mask.any():
        return out
    base_idx = df.index[mask][-1]
    try:
        base_pos = df.index.get_loc(base_idx)
        if isinstance(base_pos, slice):
            base_pos = base_pos.start
    except Exception:
        return out
    base_close = float(df.loc[base_idx, "Close"])
    if base_close <= 0:
        return out
    for h in horizons_bdays:
        target_pos = base_pos + h
        if target_pos >= len(df):
            out[h] = float("nan")
            continue
        try:
            target_close = float(df["Close"].iloc[target_pos])
            out[h] = (target_close / base_close) - 1
        except Exception:
            out[h] = float("nan")
    return out


# ----------------------------------------------------------------------
# Screener config
# ----------------------------------------------------------------------
@dataclass
class ScreenConfig:
    drawdown_min: float = -0.95
    drawdown_max: float = -0.5
    market_cap_min_oku: float = 30
    market_cap_max_oku: float = 500
    avg_volume_min: int = 10_000
    avg_volume_max: int = 500_000
    price_min: float = 300.0
    volume_surge_min: float = 1.0
    volume_surge_enabled: bool = False
    themes: tuple[str, ...] = ()
    exclude_war_sensitive: bool = True
    require_paid_so: bool = False
    paid_so_window_days: int = 365
    require_turnaround: bool = False
    require_short_cover: bool = False
    short_cover_window_days: int = 7
    fetch_signals: bool = True


WAR_GAFA_SENSITIVE_THEMES = {"半導体関連"}


def _passes_history_filters(m: StockMetrics, c: ScreenConfig) -> bool:
    if math.isnan(m.last_close):
        return False
    if m.last_close < c.price_min:
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
    paid_so_df=None, short_cover_df=None,
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
        _progress(0.05 + 0.4 * fetched / total, f"Price history {fetched}/{total}")

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
        _progress(1.0, "No survivors after history filter")
        return []
    _progress(0.45, f"Survivors: {len(survivors)} — running enrichment")

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
        if needs_signals:
            try:
                sr, si = has_recent_short_cover(
                    m.code, within_days=config.short_cover_window_days)
                m.short_cover_recent = sr
                m.short_cover_info = si
                m.short_cover_count = short_cover_count(m.code)
            except Exception:
                pass
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
                          f"Enrichment {done}/{n_surv} (matches {len(final)})")
    _progress(1.0, f"Done: {len(final)} matches")
    final.sort(key=lambda x: x.rr_score, reverse=True)
    return final


# ----------------------------------------------------------------------
# 過去日バックテスト (新規)
# ----------------------------------------------------------------------
DEFAULT_HORIZONS_BDAYS = (5, 21, 63, 126, 252)  # 1W, 1M, 3M, 6M, 1Y


def screen_universe_as_of_parallel(
    universe: pd.DataFrame,
    config: ScreenConfig,
    as_of_date,
    *,
    horizons_bdays: tuple[int, ...] = DEFAULT_HORIZONS_BDAYS,
    batch_size: int = 80,
    max_workers: int = 10,
    period: str = "5y",
    progress_callback: Optional[Callable[[float, str], None]] = None,
) -> list[dict]:
    """
    過去日 (as_of_date) 時点でスクリーニングを実行し、
    抽出された各銘柄について N営業日後のフォワードリターンを計算して返す。
    返り値: list of dict (StockMetricsのフィールド + fwd_5d/21d/63d/126d/252d)
    """
    as_of_date = pd.Timestamp(as_of_date)
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

    # Stage 1: バッチ履歴取得 (フォワード用に長めに取得)
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
        _progress(0.05 + 0.4 * fetched / total, f"Price history {fetched}/{total}")

    # Stage 2: as-of でフィルタ (履歴を切り詰めて metrics 計算)
    survivors: list[tuple[StockMetrics, pd.DataFrame]] = []
    for r in rows:
        code = str(r["code"]).zfill(4)
        df_full = history_map.get(code)
        if df_full is None or df_full.empty:
            continue
        df_past = df_full[df_full.index <= as_of_date]
        if df_past.empty or len(df_past) < 60:  # 最低60営業日の履歴必要
            continue
        m = metrics_from_history(
            df_past, code,
            name=r.get("name", ""), sector=r.get("sector", ""),
            theme=r.get("theme", ""), market=r.get("market", ""),
        )
        if _passes_history_filters(m, config):
            survivors.append((m, df_full))

    if not survivors:
        _progress(1.0, "No survivors as of date")
        return []
    _progress(0.45, f"Survivors: {len(survivors)} — computing forward returns")

    # Stage 3: 並列で info 取得 (時価総額近似) + フォワードリターン計算
    def _enrich(item) -> Optional[dict]:
        m, df_full = item
        try:
            info = fetch_info(m.code)
            shares = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
            if shares:
                m.shares_outstanding = float(shares)
                # 時価総額の近似 (as_of の終値 × 現在の発行済株式数)
                m.market_cap_oku = (m.last_close * float(shares)) / 1e8
        except Exception:
            pass
        if not _passes_market_cap_filter(m, config):
            return None
        # フォワードリターン
        fwd = forward_returns(df_full, as_of_date, horizons_bdays)
        m.rr_score = compute_rr_score(m)
        d = m.__dict__.copy()
        d["forward_returns"] = fwd
        for h in horizons_bdays:
            d[f"fwd_{h}d"] = fwd.get(h, float("nan"))
        return d

    final: list[dict] = []
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_enrich, item): item for item in survivors}
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
                          f"Forward returns {done}/{n_surv} (matches {len(final)})")
    _progress(1.0, f"Done: {len(final)} matches")
    final.sort(key=lambda x: x.get("rr_score", 0), reverse=True)
    return final


# ----------------------------------------------------------------------
# 外部リンク
# ----------------------------------------------------------------------
def external_links(code: str | int, name: str = "") -> list[tuple[str, str]]:
    code = str(code)
    return [
        ("Yahoo!ファイナンス チャート", f"https://finance.yahoo.co.jp/quote/{code}.T"),
        ("Yahoo!ファイナンス ニュース", f"https://finance.yahoo.co.jp/quote/{code}.T/news"),
        ("Yahoo!ファイナンス 業績", f"https://finance.yahoo.co.jp/quote/{code}.T/performance"),
        ("みんかぶ", f"https://minkabu.jp/stock/{code}"),
        ("株探 ニュース", f"https://kabutan.jp/stock/news?code={code}"),
        ("株探 業績", f"https://kabutan.jp/stock/finance?code={code}"),
        ("karauri.net 機関別空売り", f"https://karauri.net/{code}/"),
        ("TDnet 適時開示 (検索)", "https://www.release.tdnet.info/inbs/I_main_00.html"),
        ("EDINET 有報検索", "https://disclosure2.edinet-fsa.go.jp/WEEK0010.aspx"),
        ("バフェットコード", f"https://www.buffett-code.com/company/{code}"),
        ("IR BANK", f"https://irbank.net/{code}"),
        ("空売り残高 (JPX)", "https://www.jpx.co.jp/markets/public/short-selling/index.html"),
    ]


def load_paid_so() -> pd.DataFrame:
    return pd.DataFrame(columns=["code", "ir_date", "description"])


def load_short_cover() -> pd.DataFrame:
    return pd.DataFrame(columns=["code", "date", "status", "description"])
