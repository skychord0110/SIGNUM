"""
SIGNUM ― Tokyo Equity Setup Scanner
"""

from __future__ import annotations

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


APP_DIR = Path(__file__).parent
UNIVERSE_PATH = APP_DIR / "universe.csv"
UNIVERSE_BOOTSTRAP_THRESHOLD = 500

st.set_page_config(
    page_title="SIGNUM ― Tokyo Equity Setup Scanner",
    page_icon="◆",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ----------------------------------------------------------------------
# Stylish typography
# ----------------------------------------------------------------------
GLOBAL_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');

:root {
    --signum-red: #ff5252;
    --signum-coral: #ff8a65;
    --signum-deep: #c0392b;
    --signum-bg: #fafafa;
    --signum-fg: #1a1a1a;
    --signum-muted: #6b7280;
    --signum-border: rgba(0, 0, 0, 0.08);
}

html, body, [class*="css"] {
    font-family: 'Inter', 'Hiragino Sans', sans-serif !important;
    font-feature-settings: 'cv11', 'ss01';
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}

.signum-block {
    padding: 4px 0 6px 0;
    margin-bottom: 22px;
}
.signum-mark {
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 700;
    font-size: 3.8rem;
    letter-spacing: 0.30em;
    background: linear-gradient(110deg, var(--signum-red) 0%, var(--signum-coral) 45%, var(--signum-deep) 90%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    line-height: 1.0;
    margin: 0 0 6px 0;
}
.signum-sub {
    font-family: 'Inter', sans-serif;
    font-weight: 400;
    font-size: 0.72rem;
    letter-spacing: 0.55em;
    text-transform: uppercase;
    color: var(--signum-muted);
    margin-top: 6px;
}
.signum-rule {
    height: 1px;
    width: 96px;
    background: linear-gradient(90deg, var(--signum-red), transparent);
    margin: 14px 0 6px 0;
}

h1, h2, h3 {
    font-family: 'Space Grotesk', sans-serif !important;
    font-weight: 600 !important;
    letter-spacing: 0.02em;
    text-transform: none;
}
h4, h5, h6 {
    font-family: 'Space Grotesk', sans-serif !important;
    font-weight: 500 !important;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    font-size: 0.78rem !important;
    color: var(--signum-muted) !important;
    margin-top: 1.2rem !important;
}

.stTabs [data-baseweb="tab-list"] button [data-testid="stMarkdownContainer"] p {
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 500;
    letter-spacing: 0.10em;
    text-transform: uppercase;
    font-size: 0.78rem;
}

div[data-testid="stMetricValue"] {
    font-family: 'Space Grotesk', sans-serif !important;
    font-weight: 600 !important;
    letter-spacing: 0.01em;
}
div[data-testid="stMetricLabel"] {
    font-family: 'Inter', sans-serif !important;
    font-weight: 500 !important;
    text-transform: uppercase;
    letter-spacing: 0.10em;
    font-size: 0.66rem !important;
    color: var(--signum-muted) !important;
}

[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {
    font-family: 'Space Grotesk', sans-serif !important;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    font-size: 0.78rem !important;
    color: var(--signum-muted) !important;
}

.stButton > button {
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 500;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    font-size: 0.78rem;
    border-radius: 4px;
}

code, pre, .stCode {
    font-family: 'JetBrains Mono', 'Consolas', monospace !important;
    font-size: 0.82rem !important;
}

.excel-banner {
    background: linear-gradient(110deg, #16a34a 0%, #22c55e 100%);
    color: white;
    padding: 16px 22px;
    border-radius: 6px;
    margin: 14px 0 8px 0;
    font-weight: 500;
    box-shadow: 0 4px 14px rgba(34, 197, 94, 0.18);
}
.excel-banner .title {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 1.0rem;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    margin-bottom: 6px;
}
.excel-banner .path {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.82rem;
    font-weight: 400;
    opacity: 0.95;
    word-break: break-all;
}

.section-divider {
    border-top: 1px solid var(--signum-border);
    margin: 24px 0 16px 0;
}

.chart-card {
    border: 1px solid var(--signum-border);
    border-radius: 6px;
    padding: 8px 12px 4px 12px;
    margin-bottom: 12px;
    background: white;
}
.chart-card-header {
    font-family: 'Space Grotesk', sans-serif;
    font-size: 0.92rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    margin-bottom: 4px;
    display: flex;
    justify-content: space-between;
    align-items: baseline;
}
.chart-card-rank {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.72rem;
    color: var(--signum-muted);
    letter-spacing: 0.10em;
}
.chart-card-meta {
    font-family: 'JetBrains Mono', monospace;
    font-size: 0.70rem;
    color: var(--signum-muted);
    letter-spacing: 0.05em;
    margin-bottom: 6px;
}
.chart-card-rr {
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 600;
    color: var(--signum-deep);
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
                    fetch_signals: bool = False, cache_version: str = "v12"):
    m = az.evaluate_stock(
        code=code, name=name, sector=sector, theme=theme, market=market,
        paid_so_window_days=365, short_cover_window_days=60,
        check_turnaround=True, fetch_signals=fetch_signals,
    )
    return m.__dict__


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
        col2.caption("Pulls JPX official listing (data_j.xls) and rebuilds universe.csv. ETFs/REITs are excluded.")


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
    st.sidebar.subheader("Auxiliary Signals")
    fetch_signals = st.sidebar.checkbox(
        "Auto-fetch from Kabutan",
        value=False,
        help="Best-effort scrape for Stock Option IRs and short-cover signals."
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
    st.sidebar.caption("Data: yfinance (delayed) + Kabutan. For research only — not investment advice.")
    return {
        "period": period,
        "chosen_code": chosen_code,
        "batch_size": batch_size,
        "max_workers": max_workers,
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
        ),
        row=1, col=1,
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


def open_csv_in_excel(view: pd.DataFrame) -> Path:
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    target = Path(tempfile.gettempdir()) / f"signum_{ts}.csv"
    view.to_csv(target, index=False, encoding="utf-8-sig")
    if sys.platform.startswith("win"):
        os.startfile(str(target))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(target)])
    else:
        subprocess.Popen(["xdg-open", str(target)])
    return target


def open_in_excel_button(view: pd.DataFrame) -> None:
    col1, col2 = st.columns([1, 3])
    if col1.button("📊 OPEN IN EXCEL", type="primary", key="open_excel_btn"):
        try:
            target = open_csv_in_excel(view)
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
            st.balloons()
        except Exception as e:
            st.error(f"❌ Excel launch failed: {type(e).__name__}: {e}")
    else:
        col2.caption("Writes the result table to a temp CSV and opens it in Excel (default app).")


def render_compact_chart(df: pd.DataFrame, height: int = 260) -> None:
    """Compact chart used in the post-screen grid."""
    if df.empty:
        st.caption("No history.")
        return
    df = az.compute_indicators(df)
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
    except ImportError:
        return
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03,
        row_heights=[0.78, 0.22],
    )
    fig.add_trace(
        go.Candlestick(
            x=df.index, open=df["Open"], high=df["High"],
            low=df["Low"], close=df["Close"], name="",
            increasing_line_color="#d23f31", decreasing_line_color="#1f77b4",
            showlegend=False,
        ),
        row=1, col=1,
    )
    for sma, color in (("SMA25", "#ff7f0e"), ("SMA75", "#2ca02c")):
        if sma in df:
            fig.add_trace(
                go.Scatter(x=df.index, y=df[sma], name=sma,
                           line=dict(width=1.0, color=color),
                           showlegend=False),
                row=1, col=1,
            )
    colors = ["#d23f31" if c >= o else "#1f77b4" for o, c in zip(df["Open"], df["Close"])]
    fig.add_trace(
        go.Bar(x=df.index, y=df["Volume"], marker_color=colors, opacity=0.55,
               showlegend=False),
        row=2, col=1,
    )
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=4, b=8),
        xaxis_rangeslider_visible=False,
        font=dict(family="Inter, sans-serif", size=9),
    )
    fig.update_xaxes(showticklabels=False, row=1, col=1)
    fig.update_yaxes(showticklabels=True, row=1, col=1)
    fig.update_yaxes(showticklabels=False, row=2, col=1)
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def render_screened_charts(df_results: pd.DataFrame, period: str = "1y") -> None:
    """Render candle charts of screened stocks in rank order, 2 per row."""
    st.markdown("<div class='section-divider'></div>", unsafe_allow_html=True)
    st.markdown("#### Candle Chart Grid (Ranked)")
    n_total = len(df_results)
    show_n = st.slider(
        "Show top N charts",
        min_value=1, max_value=min(n_total, 100), value=min(20, n_total), step=1,
    )
    period_local = st.selectbox(
        "Chart period", ["6mo", "1y", "2y"], index=1, key="grid_period",
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
            with col:
                st.markdown(
                    f"""
                    <div class="chart-card">
                      <div class="chart-card-header">
                        <span>{code} &nbsp; <span style="color:#666;font-weight:500">{name}</span></span>
                        <span class="chart-card-rank">#{i + j + 1} &middot; <span class="chart-card-rr">R/R {rr:.1f}</span></span>
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


# ----------------------------------------------------------------------
# Tabs
# ----------------------------------------------------------------------
def tab_screener(universe: pd.DataFrame, sidebar_cfg: dict) -> None:
    st.subheader("Screener")
    st.caption(f"Parallel batch download + ThreadPool over {len(universe):,} tickers.")

    with st.expander("Filter Criteria", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            dd_low, dd_high = st.slider(
                "Drawdown from 12M High (%)",
                min_value=-95, max_value=0, value=(-90, -50), step=5,
            )
            mc_low, mc_high = st.slider(
                "Market Cap (¥100M)",
                min_value=10, max_value=2000, value=(30, 500), step=10,
            )
        with c2:
            st.markdown("**60D Avg Volume (shares)**")
            v_col1, v_col2 = st.columns(2)
            vol_min = v_col1.number_input("Min", value=10_000, step=1_000, min_value=0)
            vol_max = v_col2.number_input("Max", value=500_000, step=10_000, min_value=1_000)
            st.caption("Default: 10,000 — 500,000")
            st.markdown("**Volume Surge (10D / 60D)**")
            sc_col1, sc_col2 = st.columns([1, 2])
            volume_surge_enabled = sc_col1.checkbox("Enable", value=False)
            vs_min = sc_col2.number_input(
                "Min multiplier", value=1.5, step=0.1, format="%.2f",
                disabled=not volume_surge_enabled,
                label_visibility="collapsed",
            )
        with c3:
            theme_options = sorted(universe["theme"].dropna().unique().tolist())
            themes = st.multiselect(
                "Theme filter (empty = all)",
                options=theme_options, default=[],
            )
            exclude_war = st.checkbox(
                "Exclude War/GAFA-sensitive sectors (e.g. Semis)",
                value=True,
            )
            limit = st.slider(
                "Universe size to evaluate",
                20, len(universe), len(universe), 10,
            )

    work = universe.copy()
    if themes:
        work = work[work["theme"].isin(themes)]
    work = work.head(limit).reset_index(drop=True)

    if st.button("🚀 RUN SCREEN", type="primary"):
        if vol_min > vol_max:
            st.error("Volume: min exceeds max.")
            return

        config = az.ScreenConfig(
            drawdown_min=dd_low / 100,
            drawdown_max=dd_high / 100,
            market_cap_min_oku=mc_low,
            market_cap_max_oku=mc_high,
            avg_volume_min=int(vol_min),
            avg_volume_max=int(vol_max),
            volume_surge_min=float(vs_min) if volume_surge_enabled else 0.0,
            volume_surge_enabled=bool(volume_surge_enabled),
            themes=tuple(themes),
            exclude_war_sensitive=exclude_war,
            require_paid_so=False,
            require_turnaround=False,
            require_short_cover=False,
            fetch_signals=bool(sidebar_cfg.get("fetch_signals", False)),
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
            period="2y",
            progress_callback=_cb,
        )
        elapsed = time.time() - t0
        progress.empty()
        status.caption(f"✅ Done ({elapsed:.1f}s) — {len(results)}/{len(work)} matches")

        if not results:
            st.info("No matches. Try loosening the criteria.")
            return

        df = pd.DataFrame([r.__dict__ for r in results])
        view = pd.DataFrame({
            "Ticker": df["code"],
            "Name": df["name"],
            "Market": df["market"],
            "Theme": df["theme"],
            "Close": df["last_close"].round(0),
            "MCap (¥100M)": df["market_cap_oku"].round(1),
            "12M DD (%)": (df["drawdown_1y"] * 100).round(1),
            "6M DD (%)": (df["drawdown_6m"] * 100).round(1),
            "Vol Surge (10/60)": df["volume_surge"].round(2),
            "60D Avg Vol": df["avg_volume_60"].round(0).astype("Int64"),
            "ATR (%)": (df["atr_pct"] * 100).round(2),
            "20D Mom (%)": (df["momentum_20"] * 100).round(2),
            "R/R Score": df["rr_score"].round(1),
        })
        st.success(f"{len(view)} matches — sorted by R/R Score")
        st.dataframe(view, width="stretch", height=480)
        st.session_state["last_screen_result"] = view
        st.session_state["last_screen_full"] = df  # for chart grid
        open_in_excel_button(view)

        # Chart grid below the table
        render_screened_charts(df, period="1y")
    else:
        # Re-render persistent results if available
        if "last_screen_full" in st.session_state:
            st.markdown("<div class='section-divider'></div>", unsafe_allow_html=True)
            st.caption("Showing previous run. Press RUN SCREEN to refresh.")
            st.dataframe(
                st.session_state.get("last_screen_result", pd.DataFrame()),
                width="stretch", height=420,
            )
            open_in_excel_button(st.session_state["last_screen_result"])
            render_screened_charts(st.session_state["last_screen_full"], period="1y")


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
               fetch_signals: bool = False) -> None:
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
    m_dict = cached_evaluate(code, name, sector, theme, market,
                             fetch_signals=fetch_signals)
    m = az.StockMetrics(**m_dict)
    g1, g2, g3, g4, g5 = st.columns(5)
    g1.metric("Market Cap (¥100M)",
              f"{m.market_cap_oku:,.0f}" if not math.isnan(m.market_cap_oku) else "—")
    g2.metric("12M Drawdown",
              f"{m.drawdown_1y*100:.1f}%" if not math.isnan(m.drawdown_1y) else "—")
    g3.metric("Vol Surge (10/60)",
              f"{m.volume_surge:.2f}×" if not math.isnan(m.volume_surge) else "—")
    g4.metric("ATR (%)",
              f"{m.atr_pct*100:.2f}%" if not math.isnan(m.atr_pct) else "—")
    g5.metric("R/R Score", f"{m.rr_score:.1f}/100")

    st.markdown("##### 1-Month Forward Return (Backtest)")
    bt = az.backtest_forward_return(df)
    if bt["samples"] == 0:
        st.caption("Insufficient historical setups to evaluate.")
    else:
        b1, b2, b3, b4 = st.columns(4)
        b1.metric("Samples", bt["samples"])
        b2.metric("Mean Return", f"{bt['mean']*100:+.2f}%")
        b3.metric("Win Rate", f"{bt['win_rate']*100:.1f}%")
        b4.metric("P20–P80 Range",
                  f"{bt['p20']*100:+.1f}% / {bt['p80']*100:+.1f}%")

    with st.expander("Quarterly Financials (yfinance)", expanded=False):
        try:
            qf = az.fetch_quarterly_financials(code)
            if isinstance(qf, pd.DataFrame) and not qf.empty:
                pretty = qf.copy()
                pretty.columns = [c.strftime("%Y-%m") if hasattr(c, "strftime") else c
                                  for c in pretty.columns]
                st.dataframe(pretty.style.format("{:,.0f}"), width="stretch")
            else:
                st.caption("No quarterly data available.")
        except Exception as exc:
            st.caption(f"Fetch error: {exc}")

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

    sb = sidebar(universe)
    tabs = st.tabs(["🔎 SCREENER", "📊 CHART", "🔬 DETAIL", "📚 UNIVERSE"])
    with tabs[0]:
        tab_screener(universe, sb)
    with tabs[1]:
        tab_chart(universe, period=sb["period"], default_code=sb["chosen_code"])
    with tabs[2]:
        tab_detail(universe, period=sb["period"],
                   default_code=sb["chosen_code"],
                   fetch_signals=sb.get("fetch_signals", False))
    with tabs[3]:
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
