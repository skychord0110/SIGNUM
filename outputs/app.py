"""
SIGNUM ― Tokyo Equity Setup Scanner
(screener + backtest + index contributors with point impact & index daily change)
"""

from __future__ import annotations

import warnings
try:
    from bs4 import XMLParsedAsHTMLWarning
    warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)
except Exception:
    pass

import datetime as dt
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

import analysis as az
import indices as idx


APP_DIR = Path(__file__).parent
UNIVERSE_PATH = APP_DIR / "universe.csv"
UNIVERSE_BOOTSTRAP_THRESHOLD = 500

st.set_page_config(
    page_title="SIGNUM ― Tokyo Equity Setup Scanner",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="expanded",
)


GLOBAL_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
:root {
    --signum-red: #ff5252;
    --signum-coral: #ff8a65;
    --signum-deep: #c0392b;
    --signum-muted: #6b7280;
    --signum-border: rgba(0, 0, 0, 0.08);
    --signum-green: #16a34a;
    --signum-blue: #6366f1;
}
html, body, [class*="css"] {
    font-family: 'Inter', 'Hiragino Sans', sans-serif !important;
    -webkit-font-smoothing: antialiased;
}
.signum-block { padding: 4px 0 6px 0; margin-bottom: 22px; }
.signum-mark {
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 700; font-size: 3.8rem; letter-spacing: 0.30em;
    background: linear-gradient(110deg, var(--signum-red) 0%, var(--signum-coral) 45%, var(--signum-deep) 90%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
    background-clip: text; line-height: 1.0; margin: 0 0 6px 0;
}
.signum-sub {
    font-family: 'Inter', sans-serif; font-weight: 400;
    font-size: 0.72rem; letter-spacing: 0.55em; text-transform: uppercase;
    color: var(--signum-muted); margin-top: 6px;
}
.signum-rule {
    height: 1px; width: 96px;
    background: linear-gradient(90deg, var(--signum-red), transparent);
    margin: 14px 0 6px 0;
}
h1, h2, h3 {
    font-family: 'Space Grotesk', sans-serif !important;
    font-weight: 600 !important; letter-spacing: 0.02em;
}
h4, h5, h6 {
    font-family: 'Space Grotesk', sans-serif !important;
    font-weight: 500 !important; letter-spacing: 0.06em;
    text-transform: uppercase; font-size: 0.78rem !important;
    color: var(--signum-muted) !important; margin-top: 1.2rem !important;
}
.stTabs [data-baseweb="tab-list"] button [data-testid="stMarkdownContainer"] p {
    font-family: 'Space Grotesk', sans-serif; font-weight: 500;
    letter-spacing: 0.10em; text-transform: uppercase; font-size: 0.78rem;
}
div[data-testid="stMetricValue"] {
    font-family: 'Space Grotesk', sans-serif !important;
    font-weight: 600 !important;
}
div[data-testid="stMetricLabel"] {
    font-family: 'Inter', sans-serif !important; font-weight: 500 !important;
    text-transform: uppercase; letter-spacing: 0.10em;
    font-size: 0.66rem !important; color: var(--signum-muted) !important;
}
[data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {
    font-family: 'Space Grotesk', sans-serif !important;
    letter-spacing: 0.18em; text-transform: uppercase;
    font-size: 0.78rem !important; color: var(--signum-muted) !important;
}
.stButton > button {
    font-family: 'Space Grotesk', sans-serif; font-weight: 500;
    letter-spacing: 0.06em; text-transform: uppercase;
    font-size: 0.78rem; border-radius: 4px;
}
code, pre, .stCode {
    font-family: 'JetBrains Mono', 'Consolas', monospace !important;
    font-size: 0.82rem !important;
}
.excel-banner {
    background: linear-gradient(110deg, #16a34a 0%, #22c55e 100%);
    color: white; padding: 16px 22px; border-radius: 6px;
    margin: 14px 0 8px 0; font-weight: 500;
    box-shadow: 0 4px 14px rgba(34, 197, 94, 0.18);
}
.excel-banner .title {
    font-family: 'Space Grotesk', sans-serif; font-size: 1.0rem;
    letter-spacing: 0.16em; text-transform: uppercase; margin-bottom: 6px;
}
.excel-banner .path {
    font-family: 'JetBrains Mono', monospace; font-size: 0.82rem;
    font-weight: 400; opacity: 0.95; word-break: break-all;
}
.section-divider {
    border-top: 1px solid var(--signum-border);
    margin: 24px 0 16px 0;
}
.chart-card {
    border: 1px solid var(--signum-border); border-radius: 6px;
    padding: 8px 12px 4px 12px; margin-bottom: 12px; background: white;
}
.chart-card-header {
    font-family: 'Space Grotesk', sans-serif; font-size: 0.92rem;
    font-weight: 600; letter-spacing: 0.04em; margin-bottom: 4px;
    display: flex; justify-content: space-between; align-items: baseline;
}
.chart-card-rank {
    font-family: 'JetBrains Mono', monospace; font-size: 0.72rem;
    color: var(--signum-muted); letter-spacing: 0.10em;
}
.chart-card-meta {
    font-family: 'JetBrains Mono', monospace; font-size: 0.70rem;
    color: var(--signum-muted); letter-spacing: 0.05em; margin-bottom: 6px;
}
.chart-card-rr {
    font-family: 'Space Grotesk', sans-serif; font-weight: 600;
    color: var(--signum-deep);
}
.chart-card-cover {
    font-family: 'Space Grotesk', sans-serif; font-weight: 600;
    color: var(--signum-green); font-size: 0.70rem; letter-spacing: 0.06em;
}
.backtest-banner {
    background: linear-gradient(110deg, var(--signum-blue) 0%, #8b5cf6 100%);
    color: white; padding: 14px 18px; border-radius: 6px;
    margin: 8px 0 16px 0; font-family: 'Space Grotesk', sans-serif;
    letter-spacing: 0.08em; font-size: 0.86rem; text-transform: uppercase;
}
.index-header {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.2rem; font-weight: 600;
    letter-spacing: 0.04em;
    margin: 18px 0 4px 0;
    border-left: 4px solid var(--signum-red);
    padding-left: 12px;
    display: flex; flex-wrap: wrap; align-items: baseline; gap: 14px;
}
.index-header .change-up {
    color: var(--signum-green);
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 600;
    font-size: 0.95rem;
    letter-spacing: 0.02em;
}
.index-header .change-down {
    color: var(--signum-deep);
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 600;
    font-size: 0.95rem;
    letter-spacing: 0.02em;
}
.index-header .change-flat {
    color: var(--signum-muted);
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 500;
    font-size: 0.95rem;
}
.index-header .level {
    color: var(--signum-muted);
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.86rem;
    font-weight: 400;
}
.index-meta {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.74rem; color: var(--signum-muted);
    letter-spacing: 0.04em;
    margin-bottom: 12px;
}
.contrib-up {
    color: var(--signum-green); font-weight: 600;
    font-family: 'Space Grotesk', sans-serif;
    letter-spacing: 0.08em; text-transform: uppercase;
    font-size: 0.86rem;
}
.contrib-down {
    color: var(--signum-deep); font-weight: 600;
    font-family: 'Space Grotesk', sans-serif;
    letter-spacing: 0.08em; text-transform: uppercase;
    font-size: 0.86rem;
}
</style>
"""

BRAND_BLOCK = """
<div class="signum-block">
  <div class="signum-mark">SIGNUM</div>
  <div class="signum-sub">Tokyo Equity Setup Scanner</div>
  <div class="signum-rule"></div>
</div>
"""


@st.cache_data(show_spinner=False)
def load_universe() -> pd.DataFrame:
    if not UNIVERSE_PATH.exists():
        return pd.DataFrame(columns=["code", "name", "market", "sector", "theme"])
    df = pd.read_csv(UNIVERSE_PATH, dtype={"code": str})
    df["code"] = df["code"].str.zfill(4)
    return df.drop_duplicates(subset=["code"]).reset_index(drop=True)


@st.cache_data(show_spinner=False, ttl=60 * 30)
def cached_history(code: str, period: str) -> pd.DataFrame:
    return az.fetch_history(code, period=period)


@st.cache_data(show_spinner=False, ttl=60 * 60)
def cached_info(code: str) -> dict:
    return az.fetch_info(code)


@st.cache_data(show_spinner=False, ttl=60 * 30)
def cached_evaluate(code: str, name: str, sector: str, theme: str, market: str,
                    fetch_signals: bool = True, cache_version: str = "v18"):
    m = az.evaluate_stock(
        code=code, name=name, sector=sector, theme=theme, market=market,
        paid_so_window_days=365, short_cover_window_days=60,
        check_turnaround=True, fetch_signals=fetch_signals,
    )
    return m.__dict__


@st.cache_data(show_spinner=False, ttl=60 * 10)
def cached_index_contributors(index_name: str, _refresh_token: int = 0) -> dict:
    if index_name == "nikkei225":
        return idx.get_nikkei_225_contributors(top_n=10)
    if index_name == "growth250":
        return idx.get_growth_250_contributors(top_n=10)
    if index_name == "dow30":
        return idx.get_dow_30_contributors(top_n=10)
    if index_name == "nasdaq100":
        return idx.get_nasdaq_100_contributors(top_n=10)
    return {"as_of": "", "up": [], "down": [], "total_processed": 0, "errors": 0}


def run_jpx_update() -> tuple[bool, str]:
    try:
        result = subprocess.run(
            [sys.executable, str(APP_DIR / "build_universe.py")],
            capture_output=True, text=True,
            encoding="utf-8", errors="replace",
            cwd=str(APP_DIR), timeout=180,
        )
        out_full = (result.stdout or "") + (result.stderr or "")
        if result.returncode == 0:
            last_line = ""
            for line in (result.stdout or "").splitlines()[::-1]:
                if line.strip():
                    last_line = line.strip()
                    break
            return True, last_line or "Update complete"
        tail = "\n".join(out_full.splitlines()[-30:])
        return False, tail
    except subprocess.TimeoutExpired:
        return False, "Timeout (180s)"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def universe_bootstrap_banner(universe: pd.DataFrame) -> None:
    if len(universe) >= UNIVERSE_BOOTSTRAP_THRESHOLD:
        return
    with st.container(border=True):
        st.warning(
            f"⚠ Current universe contains only **{len(universe):,} tickers**. "
            f"Click below to fetch the full TSE universe (~4,000 tickers) from JPX."
        )
        col1, col2 = st.columns([1, 4])
        if col1.button("🌐 FETCH FULL TSE UNIVERSE", type="primary", width="stretch"):
            with st.status("Fetching from JPX (~30s)...", expanded=True) as status:
                ok, msg = run_jpx_update()
                if ok:
                    status.update(label=f"✅ {msg}", state="complete", expanded=False)
                    st.cache_data.clear()
                    st.success("Universe updated. Reloading...")
                    st.rerun()
                else:
                    status.update(label="❌ Failed", state="error")
                    st.error("JPX update failed:")
                    st.code(msg, language="text")
        col2.caption("Pulls JPX official listing (data_j.xls) and rebuilds universe.csv.")


def sidebar(universe: pd.DataFrame) -> dict:
    st.sidebar.markdown("## ◆ SIGNUM")
    st.sidebar.caption("Tokyo Equity Setup Scanner")
    st.sidebar.divider()

    period = st.sidebar.selectbox(
        "Lookback Period (chart)",
        ["6mo", "1y", "2y", "5y"], index=2,
    )
    st.sidebar.divider()
    st.sidebar.subheader("Universe")
    st.sidebar.caption(f"Loaded: **{len(universe):,}** tickers")
    if st.sidebar.button("🔄 REFRESH FROM JPX", width="stretch"):
        with st.sidebar.status("Fetching from JPX..."):
            ok, msg = run_jpx_update()
            if ok:
                st.sidebar.success(f"✅ {msg}")
                st.cache_data.clear()
            else:
                st.sidebar.error("❌ Failed")
                st.sidebar.code(msg[:500], language="text")

    st.sidebar.divider()
    st.sidebar.subheader("Parallel Execution")
    batch_size = st.sidebar.slider("Batch Size", 20, 200, 80, 10)
    max_workers = st.sidebar.slider("Workers", 2, 24, 10, 2)

    st.sidebar.divider()
    st.sidebar.subheader("Signals")
    fetch_signals = st.sidebar.checkbox(
        "Auto-detect Short Cover (karauri.net)", value=True,
    )
    if st.sidebar.button("🗑 CLEAR SIGNAL CACHE", width="stretch"):
        az.clear_scrape_cache()
        st.cache_data.clear()
        st.sidebar.success("Cache cleared")

    st.sidebar.divider()
    st.sidebar.subheader("Watchlist")
    favs: list[str] = st.session_state.setdefault("favorites", [])
    chosen_code = ""
    if favs:
        labels = []
        for c in favs:
            row = universe[universe["code"] == c]
            label = f"{c} {row['name'].iloc[0]}" if not row.empty else c
            labels.append(label)
        chosen = st.sidebar.radio("Select", labels, index=0, key="fav_select")
        chosen_code = chosen.split()[0]
    else:
        st.sidebar.caption("Add tickers from the Detail tab via the ★ button.")

    st.sidebar.divider()
    st.sidebar.caption("Data: yfinance (delayed) + karauri.net.")
    return {
        "period": period, "chosen_code": chosen_code,
        "batch_size": batch_size, "max_workers": max_workers,
        "fetch_signals": fetch_signals,
    }


def render_chart(df: pd.DataFrame, title: str = "", height: int = 620,
                 show_volume: bool = True) -> None:
    if df.empty:
        st.warning("No historical data available.")
        return
    df = az.compute_indicators(df)
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        st.error("plotly not installed: pip install plotly")
        return
    if show_volume:
        fig = make_subplots(
            rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.04,
            row_heights=[0.72, 0.28], subplot_titles=(title or "", "Volume"),
        )
    else:
        fig = make_subplots(rows=1, cols=1, subplot_titles=(title or "",))
    fig.add_trace(
        go.Candlestick(
            x=df.index, open=df["Open"], high=df["High"],
            low=df["Low"], close=df["Close"], name="Price",
            increasing_line_color="#d23f31", decreasing_line_color="#1f77b4",
        ), row=1, col=1,
    )
    for sma, color in (("SMA25", "#ff7f0e"), ("SMA75", "#2ca02c"), ("SMA200", "#9467bd")):
        if sma in df:
            fig.add_trace(
                go.Scatter(x=df.index, y=df[sma], name=sma,
                           line=dict(width=1.0, color=color)),
                row=1, col=1,
            )
    if show_volume:
        colors = ["#d23f31" if c >= o else "#1f77b4" for o, c in zip(df["Open"], df["Close"])]
        fig.add_trace(
            go.Bar(x=df.index, y=df["Volume"], name="Volume",
                   marker_color=colors, opacity=0.6),
            row=2, col=1,
        )
        if "Vol60" in df:
            fig.add_trace(
                go.Scatter(x=df.index, y=df["Vol60"], name="60D Avg Vol",
                           line=dict(width=1.0, color="#888")),
                row=2, col=1,
            )
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=30, b=10),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", y=-0.05),
        font=dict(family="Inter, sans-serif", size=11),
    )
    fig.update_yaxes(title_text="Price", row=1, col=1)
    if show_volume:
        fig.update_yaxes(title_text="Vol", row=2, col=1)
    st.plotly_chart(fig, width="stretch")


def open_csv_in_excel(view: pd.DataFrame, prefix: str = "signum") -> Path:
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    target = Path(tempfile.gettempdir()) / f"{prefix}_{ts}.csv"
    view.to_csv(target, index=False, encoding="utf-8-sig")
    if sys.platform.startswith("win"):
        os.startfile(str(target))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target)])
    return target


def open_in_excel_button(view: pd.DataFrame, key_suffix: str = "", prefix: str = "signum") -> None:
    col1, col2 = st.columns([1, 3])
    btn_key = f"open_excel_btn_{key_suffix}" if key_suffix else "open_excel_btn"
    if col1.button("📊 OPEN IN EXCEL", type="primary", key=btn_key):
        try:
            target = open_csv_in_excel(view, prefix=prefix)
            st.markdown(
                f"""
                <div class="excel-banner">
                    <div class="title">✅ Opened in Excel</div>
                    <div class="path">{target.resolve()}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            st.toast("📊 Opened in Excel", icon="✅")
        except Exception as e:
            st.error(f"❌ Excel launch failed: {type(e).__name__}: {e}")
    else:
        col2.caption("Writes a temp CSV and opens it in Excel.")


def render_compact_chart(df: pd.DataFrame, height: int = 260) -> None:
    if df.empty:
        st.caption("No history.")
        return
    df = az.compute_indicators(df)
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        return
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03,
                        row_heights=[0.78, 0.22])
    fig.add_trace(
        go.Candlestick(
            x=df.index, open=df["Open"], high=df["High"],
            low=df["Low"], close=df["Close"], name="",
            increasing_line_color="#d23f31", decreasing_line_color="#1f77b4",
            showlegend=False,
        ), row=1, col=1,
    )
    for sma, color in (("SMA25", "#ff7f0e"), ("SMA75", "#2ca02c")):
        if sma in df:
            fig.add_trace(
                go.Scatter(x=df.index, y=df[sma], name=sma,
                           line=dict(width=1.0, color=color), showlegend=False),
                row=1, col=1,
            )
    colors = ["#d23f31" if c >= o else "#1f77b4" for o, c in zip(df["Open"], df["Close"])]
    fig.add_trace(
        go.Bar(x=df.index, y=df["Volume"], marker_color=colors, opacity=0.55,
               showlegend=False),
        row=2, col=1,
    )
    fig.update_layout(
        height=height, margin=dict(l=8, r=8, t=4, b=8),
        xaxis_rangeslider_visible=False,
        font=dict(family="Inter, sans-serif", size=9),
    )
    fig.update_xaxes(showticklabels=False, row=1, col=1)
    fig.update_yaxes(showticklabels=True, row=1, col=1)
    fig.update_yaxes(showticklabels=False, row=2, col=1)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def render_screened_charts(df_results: pd.DataFrame, period: str = "1y",
                           key_prefix: str = "scr") -> None:
    st.markdown("<div class='section-divider'></div>", unsafe_allow_html=True)
    st.markdown("#### Candle Chart Grid (Ranked)")
    n_total = len(df_results)
    show_n = st.slider(
        "Show top N charts",
        min_value=1, max_value=min(n_total, 100), value=min(20, n_total), step=1,
        key=f"{key_prefix}_show_n",
    )
    period_local = st.selectbox(
        "Chart period", ["6mo", "1y", "2y"], index=1, key=f"{key_prefix}_grid_period",
    )
    rows = df_results.head(show_n).to_dict("records")
    for i in range(0, len(rows), 2):
        cols = st.columns(2)
        for j, col in enumerate(cols):
            if i + j >= len(rows):
                break
            r = rows[i + j]
            code = str(r.get("code", "")).zfill(4)
            name = r.get("name", "")
            market = r.get("market", "")
            theme = r.get("theme", "")
            rr = r.get("rr_score", float("nan"))
            dd = r.get("drawdown_1y", float("nan"))
            mc = r.get("market_cap_oku", float("nan"))
            sc_recent = r.get("short_cover_recent", False)
            sc_count = r.get("short_cover_count", 0)
            cover_badge = (
                f"<span class='chart-card-cover'> · 📉 {sc_count} inst covering</span>"
                if sc_recent and sc_count > 0 else ""
            )
            with col:
                st.markdown(
                    f"""
                    <div class="chart-card">
                      <div class="chart-card-header">
                        <span>{code} &nbsp; <span style="color:#666;font-weight:500">{name}</span></span>
                        <span class="chart-card-rank">#{i + j + 1} &middot; <span class="chart-card-rr">R/R {rr:.1f}</span>{cover_badge}</span>
                      </div>
                      <div class="chart-card-meta">
                        {market} &middot; {theme} &middot;
                        12M DD {dd*100:+.1f}% &middot;
                        MCap {mc:,.0f}億
                      </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                df = cached_history(code, period_local)
                render_compact_chart(df)


def render_filter_ui(universe: pd.DataFrame, key_prefix: str = "scr",
                     show_short_cover_filter: bool = True) -> dict:
    c1, c2, c3 = st.columns(3)
    with c1:
        dd_low, dd_high = st.slider(
            "Drawdown from 12M High (%)",
            min_value=-95, max_value=0, value=(-90, -50), step=5,
            key=f"{key_prefix}_dd",
        )
        mc_low, mc_high = st.slider(
            "Market Cap (¥100M)",
            min_value=10, max_value=2000, value=(30, 500), step=10,
            key=f"{key_prefix}_mc",
        )
    with c2:
        st.markdown("**60D Avg Volume (shares)**")
        v_col1, v_col2 = st.columns(2)
        vol_min = v_col1.number_input("Min", value=10_000, step=1_000, min_value=0,
                                      key=f"{key_prefix}_vmin")
        vol_max = v_col2.number_input("Max", value=500_000, step=10_000, min_value=1_000,
                                      key=f"{key_prefix}_vmax")
        st.caption("Default: 10,000 — 500,000")
        st.markdown("**Volume Surge (10D / 60D)**")
        sc_col1, sc_col2 = st.columns([1, 2])
        volume_surge_enabled = sc_col1.checkbox("Enable", value=False, key=f"{key_prefix}_vse")
        vs_min = sc_col2.number_input(
            "Min mult", value=1.5, step=0.1, format="%.2f",
            disabled=not volume_surge_enabled, label_visibility="collapsed",
            key=f"{key_prefix}_vs",
        )
    with c3:
        theme_options = sorted(universe["theme"].dropna().unique().tolist())
        themes = st.multiselect("Theme filter (empty = all)", options=theme_options,
                                default=[], key=f"{key_prefix}_themes")
        exclude_war = st.checkbox("Exclude War/GAFA-sensitive sectors",
                                  value=True, key=f"{key_prefix}_warexc")
        require_short_cover = False
        if show_short_cover_filter:
            require_short_cover = st.checkbox(
                "🆕 Short Cover Signal Only", value=False, key=f"{key_prefix}_scfilter")
        limit = st.slider("Universe size to evaluate", 20, len(universe),
                          len(universe), 10, key=f"{key_prefix}_limit")
    return {
        "dd_low": dd_low, "dd_high": dd_high,
        "mc_low": mc_low, "mc_high": mc_high,
        "vol_min": int(vol_min), "vol_max": int(vol_max),
        "volume_surge_enabled": bool(volume_surge_enabled),
        "vs_min": float(vs_min),
        "themes": tuple(themes),
        "exclude_war": bool(exclude_war),
        "require_short_cover": bool(require_short_cover),
        "limit": int(limit),
    }


def build_screen_config(f: dict, fetch_signals: bool = True,
                        require_short_cover: bool = False) -> az.ScreenConfig:
    return az.ScreenConfig(
        drawdown_min=f["dd_low"] / 100,
        drawdown_max=f["dd_high"] / 100,
        market_cap_min_oku=f["mc_low"],
        market_cap_max_oku=f["mc_high"],
        avg_volume_min=f["vol_min"],
        avg_volume_max=f["vol_max"],
        volume_surge_min=f["vs_min"] if f["volume_surge_enabled"] else 0.0,
        volume_surge_enabled=f["volume_surge_enabled"],
        themes=f["themes"],
        exclude_war_sensitive=f["exclude_war"],
        require_short_cover=require_short_cover or f["require_short_cover"],
        fetch_signals=fetch_signals,
    )


def tab_screener(universe: pd.DataFrame, sidebar_cfg: dict) -> None:
    st.subheader("Screener")
    st.caption(f"Parallel batch download + ThreadPool over {len(universe):,} tickers.")

    with st.expander("Filter Criteria", expanded=True):
        f = render_filter_ui(universe, key_prefix="scr", show_short_cover_filter=True)

    work = universe.copy()
    if f["themes"]:
        work = work[work["theme"].isin(f["themes"])]
    work = work.head(f["limit"]).reset_index(drop=True)

    if st.button("🚀 RUN SCREEN", type="primary", key="run_screen_btn"):
        if f["vol_min"] > f["vol_max"]:
            st.error("Volume: min exceeds max.")
            return
        config = build_screen_config(
            f, fetch_signals=bool(sidebar_cfg.get("fetch_signals", True)),
            require_short_cover=f["require_short_cover"],
        )
        progress = st.progress(0.0, text="Starting...")
        status = st.empty()
        t0 = time.time()

        def _cb(p: float, msg: str):
            elapsed = time.time() - t0
            progress.progress(p, text=msg)
            status.caption(f"⏱ {elapsed:.0f}s · {p*100:.0f}% · {msg}")

        results = az.screen_universe_parallel(
            work, config,
            batch_size=int(sidebar_cfg["batch_size"]),
            max_workers=int(sidebar_cfg["max_workers"]),
            period="2y", progress_callback=_cb,
        )
        elapsed = time.time() - t0
        progress.empty()
        status.caption(f"✅ Done ({elapsed:.1f}s) — {len(results)}/{len(work)} matches")

        if not results:
            st.info("No matches.")
            return

        df = pd.DataFrame([r.__dict__ for r in results])
        view = pd.DataFrame({
            "Ticker": df["code"], "Name": df["name"],
            "Market": df["market"], "Theme": df["theme"],
            "Close": df["last_close"].round(0),
            "MCap (¥100M)": df["market_cap_oku"].round(1),
            "12M DD (%)": (df["drawdown_1y"] * 100).round(1),
            "6M DD (%)": (df["drawdown_6m"] * 100).round(1),
            "Vol Surge (10/60)": df["volume_surge"].round(2),
            "60D Avg Vol": df["avg_volume_60"].round(0).astype("Int64"),
            "ATR (%)": (df["atr_pct"] * 100).round(2),
            "20D Mom (%)": (df["momentum_20"] * 100).round(2),
            "Short Cover": df["short_cover_recent"].map({True: "✅", False: ""}),
            "Cover Insts": df["short_cover_count"],
            "Cover Detail": df["short_cover_info"],
            "R/R Score": df["rr_score"].round(1),
        })
        st.success(f"{len(view)} matches — sorted by R/R Score")
        st.dataframe(view, width="stretch", height=480)
        st.session_state["last_screen_result"] = view
        st.session_state["last_screen_full"] = df
        open_in_excel_button(view, key_suffix="screen", prefix="signum_screen")
        render_screened_charts(df, period="1y", key_prefix="scr")
    else:
        if "last_screen_full" in st.session_state:
            st.markdown("<div class='section-divider'></div>", unsafe_allow_html=True)
            st.caption("Showing previous run.")
            st.dataframe(st.session_state.get("last_screen_result", pd.DataFrame()),
                         width="stretch", height=420)
            open_in_excel_button(st.session_state["last_screen_result"],
                                 key_suffix="screen_prev", prefix="signum_screen")
            render_screened_charts(st.session_state["last_screen_full"], period="1y",
                                   key_prefix="scr_prev")


HORIZON_LABELS = [(5, "1W"), (21, "1M"), (63, "3M"), (126, "6M"), (252, "1Y")]


def render_horizon_stats(df: pd.DataFrame) -> None:
    st.markdown("#### Aggregate Forward Performance")
    for h, label in HORIZON_LABELS:
        col_name = f"fwd_{h}d"
        if col_name not in df.columns:
            continue
        vals = df[col_name].dropna()
        if len(vals) == 0:
            continue
        cols = st.columns(6)
        cols[0].markdown(
            f"<div style='font-family:Space Grotesk;font-weight:600;"
            f"letter-spacing:0.12em;font-size:0.9rem;color:#6366f1;"
            f"text-transform:uppercase;padding-top:10px;'>{label}</div>",
            unsafe_allow_html=True,
        )
        cols[1].metric("Samples", len(vals))
        cols[2].metric("Mean", f"{vals.mean()*100:+.2f}%")
        cols[3].metric("Median", f"{vals.median()*100:+.2f}%")
        cols[4].metric("Win Rate", f"{(vals > 0).mean()*100:.1f}%")
        cols[5].metric("StDev", f"{vals.std()*100:.2f}%")


def tab_backtest(universe: pd.DataFrame, sidebar_cfg: dict) -> None:
    st.subheader("Historical Backtest")
    st.markdown(
        "<div class='backtest-banner'>"
        "📈 Run the screener AS OF a past date and view subsequent performance "
        "(1W / 1M / 3M / 6M / 1Y forward returns)."
        "</div>",
        unsafe_allow_html=True,
    )

    today = dt.date.today()
    default_date = today - dt.timedelta(days=180)
    min_date = today - dt.timedelta(days=365 * 5)
    max_date = today - dt.timedelta(days=7)

    c_date1, c_date2 = st.columns([1, 3])
    as_of_date = c_date1.date_input(
        "As-of date", value=default_date, min_value=min_date, max_value=max_date,
        key="bt_as_of_date",
    )
    c_date2.caption(
        f"Screen this date's snapshot, then track forward performance up to today "
        f"({(today - as_of_date).days} days of forward data available)."
    )

    with st.expander("Filter Criteria (applied as of date)", expanded=True):
        f = render_filter_ui(universe, key_prefix="bt", show_short_cover_filter=False)

    work = universe.copy()
    if f["themes"]:
        work = work[work["theme"].isin(f["themes"])]
    work = work.head(f["limit"]).reset_index(drop=True)

    if st.button("📈 RUN BACKTEST", type="primary", key="run_bt_btn"):
        if f["vol_min"] > f["vol_max"]:
            st.error("Volume: min exceeds max.")
            return
        config = build_screen_config(f, fetch_signals=False, require_short_cover=False)
        progress = st.progress(0.0, text="Starting backtest...")
        status = st.empty()
        t0 = time.time()

        def _cb(p: float, msg: str):
            elapsed = time.time() - t0
            progress.progress(p, text=msg)
            status.caption(f"⏱ {elapsed:.0f}s · {p*100:.0f}% · {msg}")

        results = az.screen_universe_as_of_parallel(
            work, config, as_of_date=pd.Timestamp(as_of_date),
            horizons_bdays=tuple(h for h, _ in HORIZON_LABELS),
            batch_size=int(sidebar_cfg["batch_size"]),
            max_workers=int(sidebar_cfg["max_workers"]),
            period="5y", progress_callback=_cb,
        )
        elapsed = time.time() - t0
        progress.empty()
        status.caption(f"✅ Done ({elapsed:.1f}s) — {len(results)}/{len(work)} matches as of {as_of_date}")

        if not results:
            st.info("No matches as of that date.")
            return
        df = pd.DataFrame(results)
        st.session_state["bt_result_df"] = df
        st.session_state["bt_as_of"] = as_of_date

    if "bt_result_df" in st.session_state:
        df = st.session_state["bt_result_df"]
        as_of = st.session_state.get("bt_as_of", as_of_date)
        render_horizon_stats(df)
        st.markdown("<div class='section-divider'></div>", unsafe_allow_html=True)
        sort_options = ["R/R Score"] + [f"{label} Forward Return" for _, label in HORIZON_LABELS]
        sort_choice = st.selectbox("Sort table by", sort_options, index=0, key="bt_sort")
        sort_map = {"R/R Score": "rr_score"}
        for h, label in HORIZON_LABELS:
            sort_map[f"{label} Forward Return"] = f"fwd_{h}d"
        df_sorted = df.sort_values(sort_map[sort_choice], ascending=False)
        view_cols = {
            "Ticker": df_sorted["code"], "Name": df_sorted["name"],
            "Market": df_sorted["market"], "Theme": df_sorted["theme"],
            f"Close @ {as_of}": df_sorted["last_close"].round(0),
            "MCap (¥100M)": df_sorted["market_cap_oku"].round(1),
            "12M DD (%)": (df_sorted["drawdown_1y"] * 100).round(1),
            "Vol Surge (10/60)": df_sorted["volume_surge"].round(2),
        }
        for h, label in HORIZON_LABELS:
            col = f"fwd_{h}d"
            if col in df_sorted.columns:
                view_cols[f"{label} (%)"] = (df_sorted[col] * 100).round(2)
        view_cols["R/R Score"] = df_sorted["rr_score"].round(1)
        view = pd.DataFrame(view_cols)
        st.success(f"{len(view)} stocks matched on {as_of}")
        st.dataframe(view, width="stretch", height=520)
        open_in_excel_button(view, key_suffix="bt", prefix="signum_backtest")
        render_screened_charts(df_sorted, period="1y", key_prefix="bt")


# ----------------------------------------------------------------------
# Index Contributors tab (with Δ Index Points column + index daily change)
# ----------------------------------------------------------------------
INDEX_DEFINITIONS = [
    ("Nikkei 225 — 日経平均", "nikkei225", "¥", "price"),
    ("TOPIX Growth 250 — グロース250", "growth250", "¥", "mcap"),
    ("Dow Jones Industrial Average", "dow30", "$", "price"),
    ("NASDAQ 100", "nasdaq100", "$", "mcap"),
]


def _render_contributor_table(rows: list[dict], currency: str, direction: str) -> None:
    if not rows:
        st.caption("No data.")
        return
    df = pd.DataFrame(rows)
    if "code" in df.columns:
        df = df.rename(columns={"code": "ticker"})
    has_index_pts = "index_points" in df.columns
    view_dict = {
        "#": range(1, len(df) + 1),
        "Ticker": df["ticker"],
        "Name": df["name"],
        "Close": df["close"].round(2),
        f"Δ Price ({currency})": df["price_change"].round(2),
        "Change %": (df["pct_change"] * 100).round(2),
    }
    if has_index_pts:
        view_dict["Δ Index Pts"] = df["index_points"].round(3)
    view = pd.DataFrame(view_dict)
    st.dataframe(view, width="stretch", hide_index=True)


def _format_index_change_html(snap: dict) -> str:
    """指数の現在値 + 変動幅 + 変動率 を色付きHTMLで返す"""
    if not snap or snap.get("level") is None:
        return ""
    level = snap.get("level", 0.0)
    change = snap.get("change")
    pct = snap.get("pct_change", 0.0)
    if change is None:
        return f"<span class='level'>{level:,.2f} pts</span>"
    if change > 0:
        cls = "change-up"
        sign = "+"
        arrow = "▲"
    elif change < 0:
        cls = "change-down"
        sign = ""
        arrow = "▼"
    else:
        cls = "change-flat"
        sign = ""
        arrow = "—"
    return (
        f"<span class='level'>{level:,.2f}</span>"
        f"<span class='{cls}'>{arrow} {sign}{change:,.2f} pts "
        f"({sign}{pct*100:.2f}%)</span>"
    )


def tab_index_contributors(refresh_token: int) -> None:
    st.subheader("Index Contributors")
    st.caption(
        "Top 10 gainers / losers by daily index-point contribution for each major index. "
        "Cached for 10 minutes."
    )

    col_btn, col_info = st.columns([1, 4])
    if col_btn.button("🔄 REFRESH ALL", type="primary", key="idx_refresh_btn"):
        cached_index_contributors.clear()
        st.rerun()
    col_info.caption(
        "**Index-point impact** is computed using divisors for Nikkei 225 (≈28.5) / "
        "Dow Jones (≈0.1517), and via market-cap weighting for Growth 250 / NASDAQ 100 "
        "(using close × volume as the market-cap proxy and live index level)."
    )

    for label, name_key, currency, weight in INDEX_DEFINITIONS:
        with st.spinner(f"Loading {label}..."):
            res = cached_index_contributors(name_key, refresh_token)

        # 指数本体の当日変動を見出しに併記
        snap = (res or {}).get("index_snapshot", {})
        change_html = _format_index_change_html(snap)
        header_html = f"<span>{label}</span>"
        if change_html:
            header_html += f" {change_html}"
        st.markdown(f"<div class='index-header'>{header_html}</div>",
                    unsafe_allow_html=True)

        if not res or res.get("total_processed", 0) == 0:
            st.warning(
                "No data could be retrieved. yfinance batch may be rate-limited — "
                "wait a moment and click REFRESH ALL again."
            )
            continue

        # メタ情報 (構成銘柄数 / 除数 / 加重方式)
        meta_lines = [f"As of {res.get('as_of', 'n/a')}"]
        meta_lines.append(f"Processed {res.get('total_processed', 0)} stocks")
        if res.get("divisor"):
            meta_lines.append(f"Divisor {res['divisor']:.4f}")
        meta_lines.append(f"Weighting: {weight}")
        st.markdown(
            f"<div class='index-meta'>{' · '.join(meta_lines)}</div>",
            unsafe_allow_html=True,
        )

        # Top10 合計の指数押上げ/押下げポイント
        tot_up = res.get("total_index_points_up", 0.0)
        tot_down = res.get("total_index_points_down", 0.0)
        sum_cols = st.columns(2)
        sum_cols[0].metric(
            "Top 10 UP total impact", f"+{tot_up:,.2f} pts",
            help="上位10銘柄が指数を押し上げた合計ポイント",
        )
        sum_cols[1].metric(
            "Top 10 DOWN total impact", f"{tot_down:,.2f} pts",
            help="下位10銘柄が指数を押し下げた合計ポイント",
        )

        c1, c2 = st.columns(2)
        with c1:
            st.markdown(
                "<div class='contrib-up'>📈 TOP CONTRIBUTORS (UP)</div>",
                unsafe_allow_html=True,
            )
            _render_contributor_table(res.get("up", []), currency, "up")
        with c2:
            st.markdown(
                "<div class='contrib-down'>📉 TOP CONTRIBUTORS (DOWN)</div>",
                unsafe_allow_html=True,
            )
            _render_contributor_table(res.get("down", []), currency, "down")
        st.markdown("<div class='section-divider'></div>", unsafe_allow_html=True)


# ----------------------------------------------------------------------
# Chart / Detail / Universe tabs
# ----------------------------------------------------------------------
def tab_chart(universe: pd.DataFrame, period: str, default_code: str = "") -> None:
    st.subheader("Chart")
    code = stock_picker(universe, default_code, key="chart_pick")
    if not code:
        return
    info = cached_info(code)
    name = info.get("longName") or info.get("shortName") or _name_of(universe, code)
    df = cached_history(code, period)
    render_chart(df, title=f"{code} {name}")
    cols = st.columns(4)
    if not df.empty:
        cols[0].metric("Close", f"¥{df['Close'].iloc[-1]:.0f}")
        chg = df["Close"].pct_change().iloc[-1] * 100
        cols[1].metric("1D Change", f"{chg:+.2f}%")
        cols[2].metric("Volume", f"{int(df['Volume'].iloc[-1]):,}")
        cols[3].metric("60D Avg Vol", f"{int(df['Volume'].tail(60).mean()):,}")


def tab_detail(universe: pd.DataFrame, period: str, default_code: str = "",
               fetch_signals: bool = True) -> None:
    st.subheader("Detail")
    code = stock_picker(universe, default_code, key="detail_pick")
    if not code:
        return
    info = cached_info(code)
    name = info.get("longName") or info.get("shortName") or _name_of(universe, code)
    sector = _attr(universe, code, "sector")
    theme = _attr(universe, code, "theme")
    market = _attr(universe, code, "market")
    favs: list[str] = st.session_state.setdefault("favorites", [])
    is_fav = code in favs
    cols = st.columns([1, 5])
    if cols[0].button("★ REMOVE" if is_fav else "☆ ADD", key="fav_toggle"):
        if is_fav:
            favs.remove(code)
        else:
            favs.insert(0, code)
        st.rerun()
    cols[1].markdown(f"**{code} / {name}** &nbsp; — {market} · {sector} · `{theme}`")

    df = cached_history(code, period)
    render_chart(df, title=f"{code} {name}")
    m_dict = cached_evaluate(code, name, sector, theme, market, fetch_signals=fetch_signals)
    m = az.StockMetrics(**m_dict)
    g1, g2, g3, g4, g5 = st.columns(5)
    g1.metric("Market Cap (¥100M)",
              f"{m.market_cap_oku:,.0f}" if not math.isnan(m.market_cap_oku) else "—")
    g2.metric("12M Drawdown",
              f"{m.drawdown_1y*100:.1f}%" if not math.isnan(m.drawdown_1y) else "—")
    g3.metric("Vol Surge (10/60)",
              f"{m.volume_surge:.2f}×" if not math.isnan(m.volume_surge) else "—")
    g4.metric("Short Cover Inst.", m.short_cover_count)
    g5.metric("R/R Score", f"{m.rr_score:.1f}/100")

    st.markdown("##### Short Cover Signal — karauri.net")
    debug_col1, debug_col2 = st.columns([3, 1])
    if m.short_cover_recent:
        debug_col1.success(f"📉➡️📈 連続買戻し検出 — {m.short_cover_info}")
    else:
        debug_col1.info("No short cover signal detected from karauri.net.")
    if debug_col2.button("🔄 Re-fetch", key=f"refresh_{code}"):
        az.clear_scrape_cache()
        st.cache_data.clear()
        st.rerun()

    with st.expander("🔧 Debug: karauri.net raw parse", expanded=False):
        if st.button("Run live debug fetch", key=f"debug_{code}"):
            with st.spinner("Fetching karauri.net..."):
                debug = az.debug_karauri(code)
            st.write(f"**Total records parsed:** {debug.get('records_total', 0)}")
            st.write(f"**Institutions found:** {len(debug.get('institutions', []))}")
            if debug.get("institutions"):
                st.code("\n".join(debug["institutions"][:30]), language="text")
            st.write(f"**Covering institutions:** {debug.get('count', 0)}")
            if debug.get("covering"):
                st.dataframe(pd.DataFrame(debug["covering"]),
                             width="stretch", hide_index=True)
            st.caption(f"Source: https://karauri.net/{code}/")

    st.markdown("##### External Links — News / IR / Financials")
    links = az.external_links(code, name)
    cols = st.columns(2)
    for i, (label, url) in enumerate(links):
        cols[i % 2].markdown(f"- [{label}]({url})")


def stock_picker(universe: pd.DataFrame, default_code: str = "", key: str = "pick") -> str:
    c1, c2 = st.columns([2, 3])
    code_in = c1.text_input("Ticker (4 digits)", value=default_code, key=f"{key}_code").strip()
    name_q = c2.text_input("Search by name", value="", key=f"{key}_name").strip()
    if name_q:
        cands = universe[universe["name"].str.contains(name_q, case=False, na=False)]
        if not cands.empty:
            label = c2.selectbox(
                "Candidates", [f"{r.code} {r['name']}" for _, r in cands.iterrows()],
                key=f"{key}_cand",
            )
            code_in = label.split()[0]
    if code_in:
        code_in = code_in.zfill(4)
    return code_in


def _name_of(universe: pd.DataFrame, code: str) -> str:
    row = universe[universe["code"] == code]
    return row["name"].iloc[0] if not row.empty else ""


def _attr(universe: pd.DataFrame, code: str, col: str) -> str:
    row = universe[universe["code"] == code]
    return row[col].iloc[0] if not row.empty and col in row.columns else ""


def main() -> None:
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)
    st.markdown(BRAND_BLOCK, unsafe_allow_html=True)

    universe = load_universe()
    universe_bootstrap_banner(universe)

    if universe.empty:
        st.error("universe.csv not found. Click 'REFRESH FROM JPX' in the sidebar.")
        return

    refresh_token = st.session_state.setdefault("idx_refresh_token", 0)

    sb = sidebar(universe)
    tabs = st.tabs([
        "🔎 SCREENER",
        "📈 BACKTEST",
        "📊 INDICES",
        "📊 CHART",
        "🔬 DETAIL",
        "📚 UNIVERSE",
    ])
    with tabs[0]:
        tab_screener(universe, sb)
    with tabs[1]:
        tab_backtest(universe, sb)
    with tabs[2]:
        tab_index_contributors(refresh_token)
    with tabs[3]:
        tab_chart(universe, period=sb["period"], default_code=sb["chosen_code"])
    with tabs[4]:
        tab_detail(universe, period=sb["period"],
                   default_code=sb["chosen_code"],
                   fetch_signals=sb.get("fetch_signals", True))
    with tabs[5]:
        st.subheader("Universe")
        st.caption(f"Total: {len(universe):,} tickers")
        f1, f2 = st.columns(2)
        sel_market = f1.multiselect("Market", sorted(universe["market"].dropna().unique()))
        sel_theme = f2.multiselect("Theme", sorted(universe["theme"].dropna().unique()))
        view = universe.copy()
        if sel_market:
            view = view[view["market"].isin(sel_market)]
        if sel_theme:
            view = view[view["theme"].isin(sel_theme)]
        st.dataframe(view, width="stretch", height=600)


if __name__ == "__main__":
    main()
