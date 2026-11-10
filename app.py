import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
import io
import warnings
from datetime import datetime

warnings.filterwarnings('ignore')

st.set_page_config(
    page_title="Nifty 500 Demand Zone Screener & 5-Year Backtester",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling
st.markdown("""
<style>
    .metric-box {
        background-color: #1e293b;
        border: 1px solid #334155;
        border-radius: 8px;
        padding: 12px 16px;
        text-align: center;
    }
    .metric-val {
        font-size: 1.5rem;
        font-weight: 700;
        color: #38bdf8;
    }
    .metric-lbl {
        font-size: 0.8rem;
        color: #94a3b8;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }
    .win-text { color: #10b981; font-weight: 600; }
    .loss-text { color: #ef4444; font-weight: 600; }
</style>
""", unsafe_allow_html=True)

# -------------------------------------------------------------
# 1. NSE NIFTY 500 UNIVERSE FETCH
# -------------------------------------------------------------
@st.cache_data(ttl=86400)
def get_nifty500_symbols():
    url = "https://niftyindices.com/IndexConstituent/ind_nifty500list.csv"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        df = pd.read_csv(io.StringIO(res.text))
        syms = [str(s).strip() for s in df['Symbol'].dropna().unique()]
        return syms
    except Exception:
        return [
            "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "BHARTIARTL", "INFY", "ITC", "SBIN",
            "LT", "HINDUNILVR", "BAJFINANCE", "HCLTECH", "MARUTI", "SUNPHARMA", "ADANIENT",
            "KOTAKBANK", "TITAN", "ONGC", "TATAMOTORS", "NTPC", "AXISBANK", "BANKINDIA",
            "PNB", "CANBK", "UNIONBANK", "IDFCFIRSTB", "FEDERALBNK", "TRENT", "ZOMATO"
        ]

# -------------------------------------------------------------
# 2. YAHOO FINANCE DATA ENGINE (auto_adjust=False + fast_info)
# -------------------------------------------------------------
def fetch_stock_data(symbol, period="5y", interval="1d"):
    yf_sym = symbol if symbol.endswith(".NS") else f"{symbol}.NS"
    try:
        ticker = yf.Ticker(yf_sym)
        df = ticker.history(period=period, interval=interval, auto_adjust=False)
        if df.empty or len(df) < 10:
            return None, None, None
        
        # fast_info live tick
        try:
            cmp = float(ticker.fast_info.last_price)
            day_low = float(ticker.fast_info.day_low)
        except Exception:
            try:
                cmp = float(ticker.info.get('currentPrice', df['Close'].iloc[-1]))
                day_low = float(ticker.info.get('dayLow', df['Low'].iloc[-1]))
            except Exception:
                cmp = float(df['Close'].iloc[-1])
                day_low = float(df['Low'].iloc[-1])
                
        df.attrs['symbol'] = symbol
        return df, cmp, day_low
    except Exception:
        return None, None, None

# -------------------------------------------------------------
# 3. CORE DEMAND ZONE LOGIC & FORWARD-TEST ENGINE
# -------------------------------------------------------------
def analyze_demand_zones(df, cmp, day_low, min_price=60.0, base_ratio_max=0.40,
                         leg_ratio_min=0.65, bo_pct=0.01, min_move_pct=7.0,
                         buffer_pct=0.0025, allow_pause=True, lookback_years=5):
    if df is None or len(df) < 5 or pd.isna(cmp) or cmp <= min_price:
        return [], []

    df = df.copy()
    cutoff_dt = df.index[-1] - pd.DateOffset(years=lookback_years)

    df['Range'] = df['High'] - df['Low']
    df['Body'] = (df['Close'] - df['Open']).abs()
    df['Range'] = df['Range'].replace(0, np.nan)
    df['Body_Ratio'] = df['Body'] / df['Range']

    df['isLegIn'] = df['Body_Ratio'] > leg_ratio_min
    df['isBase'] = df['Body_Ratio'] < base_ratio_max
    df['isBullish'] = df['Close'] > df['Open']
    df['isLegOut'] = df['isBullish'] & (df['Body_Ratio'] > leg_ratio_min)

    n = len(df)
    active_zones = []
    backtest_records = []

    for i in range(3, n):
        if not df['isLegOut'].iloc[i]:
            continue

        is_1base = df['isBase'].iloc[i-1] and df['isLegIn'].iloc[i-2]
        is_2base = False
        if i >= 4:
            is_2base = df['isBase'].iloc[i-1] and df['isBase'].iloc[i-2] and df['isLegIn'].iloc[i-3]

        if not (is_1base or is_2base):
            continue

        base_date_dt = df.index[i-1]
        if base_date_dt < cutoff_dt:
            continue

        first_legout_range = df['Range'].iloc[i]
        first_legout_close = df['Close'].iloc[i]
        base_close = df['Close'].iloc[i-1]

        if is_1base:
            legin_range = df['Range'].iloc[i-2]
            base_high = df['High'].iloc[i-1]
            proximal = max(df['Open'].iloc[i-1], df['Close'].iloc[i-1])
            distal = df['Low'].iloc[i-1]
            base_date_str = df.index[i-1].strftime('%Y-%m-%d')
            pattern_name = "1-Base (DBR/RBR)"
            base_start_idx = i - 1
        else:
            legin_range = df['Range'].iloc[i-3]
            base_high = max(df['High'].iloc[i-1], df['High'].iloc[i-2])
            proximal = max(df['Open'].iloc[i-1], df['Close'].iloc[i-1], df['Open'].iloc[i-2], df['Close'].iloc[i-2])
            distal = min(df['Low'].iloc[i-1], df['Low'].iloc[i-2])
            base_date_str = f"{df.index[i-2].strftime('%Y-%m-%d')} to {df.index[i-1].strftime('%Y-%m-%d')}"
            pattern_name = "2-Base (DBR/RBR)"
            base_start_idx = i - 2

        # Rule: Leg-In >= 50% of First Leg-Out
        if legin_range < 0.5 * first_legout_range:
            continue
        # Rule: Breakout strength >= 1% above Base High
        if first_legout_close < (base_high * (1.0 + bo_pct)):
            continue

        # Consecutive Leg-Outs with Pause Base Exception
        curr = i
        total_legouts = 1
        pause_used = False

        while curr + 1 < n:
            if df['isLegOut'].iloc[curr + 1]:
                curr += 1
                total_legouts += 1
            elif allow_pause and not pause_used and df['isBase'].iloc[curr + 1] and (curr + 2 < n) and df['isLegOut'].iloc[curr + 2]:
                curr += 2
                total_legouts += 1
                pause_used = True
            else:
                break

        last_legout_idx = curr
        move_end_price = df['Close'].iloc[last_legout_idx]
        pct_move = ((move_end_price - base_close) / base_close) * 100.0

        if pct_move < min_move_pct:
            continue

        risk = proximal - distal
        if risk <= 0:
            continue

        target_2r = proximal + 2.0 * risk
        target_3r = proximal + 3.0 * risk
        tripwire = proximal * (1.0 + buffer_pct)

        # ---------------------------------------------------------
        # FORWARD BACKTESTING ENGINE: Trace Every Subsequent Bar
        # ---------------------------------------------------------
        tested = False
        tested_date = None
        tested_bar = None
        outcome = "Active / Untested"
        exit_date = None
        exit_price = None
        r_mult = 0.0
        holding_bars = 0

        if i + 1 < n:
            sub = df.iloc[i + 1:]
            for step_idx, (dt, row) in enumerate(sub.iterrows(), start=i+1):
                dt_str = dt.strftime('%Y-%m-%d')
                if not tested:
                    # Invalidation before ever being tested
                    if row['Close'] < distal:
                        outcome = "Destroyed (Closed Below Distal)"
                        exit_date = dt_str
                        exit_price = row['Close']
                        r_mult = 0.0
                        break
                    # Test touch
                    if row['Low'] <= tripwire:
                        tested = True
                        tested_date = dt_str
                        tested_bar = step_idx
                        # Same bar flush through distal
                        if row['Close'] < distal:
                            outcome = "SL Hit (-1R)"
                            exit_date = dt_str
                            exit_price = distal
                            r_mult = -1.0
                            holding_bars = 1
                            break
                        elif row['High'] >= target_2r:
                            outcome = "Target 2R Hit"
                            exit_date = dt_str
                            exit_price = target_2r
                            r_mult = 2.0
                            holding_bars = 1
                            break
                else:
                    # Position is active post-mitigation
                    holding_bars = step_idx - tested_bar + 1
                    if row['Close'] < distal:
                        outcome = "SL Hit (-1R)"
                        exit_date = dt_str
                        exit_price = distal
                        r_mult = -1.0
                        break
                    elif row['High'] >= target_3r:
                        outcome = "Target 3R Hit"
                        exit_date = dt_str
                        exit_price = target_3r
                        r_mult = 3.0
                        break
                    elif row['High'] >= target_2r:
                        outcome = "Target 2R Hit"
                        exit_date = dt_str
                        exit_price = target_2r
                        r_mult = 2.0
                        break

            # If tested but hasn't hit SL or Target yet by today
            if tested and outcome == "Active / Untested":
                outcome = "Currently Open / In Trade"
                r_mult = (cmp - proximal) / risk
                exit_price = cmp
                exit_date = "Open"

        # Check live intraday test for current session
        if not tested:
            if day_low <= tripwire or cmp <= tripwire:
                tested = True
                tested_date = "Today (Live Tick)"
                outcome = "Triggered Today"

        sym = df.attrs.get('symbol', '')
        req_fall_pct = ((cmp - proximal) / cmp) * 100.0

        rec_base = {
            "Gfinance ticket": f"NSE:{sym}",
            "Symbol": sym,
            "CMP": round(cmp, 2),
            "Base date": base_date_str,
            "Proximal": round(proximal, 2),
            "Distal": round(distal, 2),
            "Legout candles": f"{total_legouts} (incl. pause)" if pause_used else str(total_legouts),
            "Legout % move": f"{round(pct_move, 2)}%",
            "Required fall %": round(req_fall_pct, 2),
            "Risk (₹)": round(risk, 2),
            "Pattern": pattern_name,
            "Base Index": base_start_idx,
            "Last Legout Index": last_legout_idx
        }

        # Backtest table full historical log
        bt_rec = {
            **rec_base,
            "Tested": "Yes" if tested else "No",
            "Test Date": tested_date or "Untested",
            "Outcome": outcome,
            "Exit Date": exit_date or "-",
            "Exit Price (₹)": round(exit_price, 2) if exit_price else "-",
            "R-Multiple": round(r_mult, 2),
            "Target 2R (₹)": round(target_2r, 2),
            "Target 3R (₹)": round(target_3r, 2),
            "Holding Bars": holding_bars
        }
        backtest_records.append(bt_rec)

        # Active Unmitigated Demand Zones Only
        if not tested and outcome == "Active / Untested":
            active_zones.append(rec_base)

    return active_zones, backtest_records

# -------------------------------------------------------------
# 4. PLOTLY CHART VISUALIZER
# -------------------------------------------------------------
def plot_candlestick_zone(df, symbol, proximal, distal, base_date, cmp):
    target_2r = proximal + 2.0 * (proximal - distal)
    target_3r = proximal + 3.0 * (proximal - distal)
    
    # Slice to last 250 bars for responsive charting
    plot_df = df.tail(250).copy()
    
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                        vertical_spacing=0.03, row_heights=[0.8, 0.2])

    fig.add_trace(go.Candlestick(
        x=plot_df.index.strftime('%Y-%m-%d'),
        open=plot_df['Open'],
        high=plot_df['High'],
        low=plot_df['Low'],
        close=plot_df['Close'],
        name=symbol,
        increasing_line_color='#10b981',
        decreasing_line_color='#ef4444'
    ), row=1, col=1)

    colors = ['#10b981' if c >= o else '#ef4444' for c, o in zip(plot_df['Close'], plot_df['Open'])]
    fig.add_trace(go.Bar(
        x=plot_df.index.strftime('%Y-%m-%d'),
        y=plot_df['Volume'],
        name="Volume",
        marker_color=colors,
        opacity=0.4
    ), row=2, col=1)

    # Shaded Demand Zone Rect
    start_dt = base_date.split(' to ')[0]
    end_dt = plot_df.index[-1].strftime('%Y-%m-%d')

    fig.add_shape(
        type="rect",
        xref="x", yref="y",
        x0=start_dt, x1=end_dt,
        y0=distal, y1=proximal,
        fillcolor="rgba(16, 185, 129, 0.25)",
        line=dict(color="#10b981", width=1.5),
        row=1, col=1
    )

    # Proximal, Distal, Target lines
    for val, col, dash, lbl in [
        (proximal, "#10b981", "solid", f"Proximal Entry: ₹{proximal}"),
        (distal, "#ef4444", "solid", f"Distal SL: ₹{distal}"),
        (target_2r, "#38bdf8", "dash", f"2R Target: ₹{target_2r:.2f}"),
        (target_3r, "#a855f7", "dot", f"3R Target: ₹{target_3r:.2f}")
    ]:
        fig.add_trace(go.Scatter(
            x=[start_dt, end_dt],
            y=[val, val],
            mode="lines+text",
            line=dict(color=col, width=1.5, dash=dash),
            text=["", lbl],
            textposition="top right",
            name=lbl,
            showlegend=False
        ), row=1, col=1)

    fig.update_layout(
        title=f"<b>NSE:{symbol}</b> • CMP: ₹{cmp:.2f} | Base Date: {base_date}",
        template="plotly_dark",
        paper_bgcolor="#0f172a",
        plot_bgcolor="#0f172a",
        height=550,
        margin=dict(l=40, r=40, t=50, b=40),
        xaxis_rangeslider_visible=False,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    return fig

# -------------------------------------------------------------
# 5. SIDEBAR: PARAMETERS & FILTERS
# -------------------------------------------------------------
st.sidebar.title("⚙️ Strategy Parameters")

preset = st.sidebar.selectbox(
    "Load Strategy Preset",
    ["Daily (3Y • 7% Move • 1% BO)", "Custom 5-Year Backtest", "Weekly (10Y • 10% Move)", "Monthly (10Y • 10% Move)"]
)

if preset == "Daily (3Y • 7% Move • 1% BO)":
    default_tf = "1d"
    default_years = 3
    default_bo = 1.0
    default_move = 7.0
    default_pause = True
elif preset == "Custom 5-Year Backtest":
    default_tf = "1d"
    default_years = 5
    default_bo = 1.0
    default_move = 7.0
    default_pause = True
elif preset == "Weekly (10Y • 10% Move)":
    default_tf = "1wk"
    default_years = 5
    default_bo = 2.0
    default_move = 10.0
    default_pause = True
else:
    default_tf = "1mo"
    default_years = 5
    default_bo = 5.0
    default_move = 10.0
    default_pause = False

tf = st.sidebar.selectbox("Candle Timeframe", ["1d", "1wk", "1mo"], index=["1d", "1wk", "1mo"].index(default_tf))
backtest_years = st.sidebar.slider("Historical Lookback (Years)", min_value=1, max_value=5, value=default_years)
min_cmp = st.sidebar.number_input("Penny Stock Filter (CMP > ₹)", value=60.0, step=5.0)

st.sidebar.markdown("---")
st.sidebar.subheader("Candle & Pattern Rules")
col_p1, col_p2 = st.sidebar.columns(2)
with col_p1:
    base_body_pct = st.number_input("Base Body < %", value=40.0, step=5.0)
    leg_body_pct = st.number_input("Leg Body > %", value=65.0, step=5.0)
with col_p2:
    bo_strength_pct = st.number_input("Breakout Close > %", value=default_bo, step=0.5)
    min_momentum_pct = st.number_input("Min Thrust Move %", value=default_move, step=0.5)

col_p3, col_p4 = st.sidebar.columns(2)
with col_p3:
    test_buffer_pct = st.number_input("Untested Buffer %", value=0.25, step=0.05, help="0.25% buffer prevents mitigation leakage")
with col_p4:
    pause_candle = st.selectbox("Pause Base Candle", [True, False], index=0 if default_pause else 1)

st.sidebar.markdown("---")
max_stocks_scan = st.sidebar.slider("Number of Nifty Stocks to Scan", min_value=10, max_value=500, value=50, step=10,
                                    help="Scan 500 for full market coverage, or fewer for quick testing.")

# -------------------------------------------------------------
# 6. MAIN APP TABS: LIVE SCANNER vs 5-YEAR BACKTESTER
# -------------------------------------------------------------
st.title("🎯 Nifty 500 Demand Zone Engine")
tab_live, tab_backtest, tab_chart = st.tabs(["🚀 Same-Day Live Screener", "📊 5-Year Forward Backtester", "📈 Interactive Chart Studio"])

symbols = get_nifty500_symbols()[:max_stocks_scan]

# Session state containers
if "active_results" not in st.session_state:
    st.session_state.active_results = pd.DataFrame()
if "backtest_results" not in st.session_state:
    st.session_state.backtest_results = pd.DataFrame()
if "cached_stock_dfs" not in st.session_state:
    st.session_state.cached_stock_dfs = {}

# -------------------------------------------------------------
# TAB 1: SAME-DAY LIVE ANALYSIS
# -------------------------------------------------------------
with tab_live:
    col_ctrl1, col_ctrl2, col_ctrl3 = st.columns([2, 1, 1])
    with col_ctrl1:
        run_scan = st.button("⚡ Run Live Screener Scan", type="primary", use_container_width=True)
    with col_ctrl2:
        st.write("")
    with col_ctrl3:
        search_sym = st.text_input("Filter Stock", placeholder="e.g. BANKINDIA, RELIANCE").upper()

    if run_scan:
        all_active = []
        all_bt = []
        progress_bar = st.progress(0.0)
        status_txt = st.empty()

        for idx, s in enumerate(symbols):
            status_txt.text(f"Scanning [{idx+1}/{len(symbols)}]: NSE:{s}...")
            df, cmp_val, day_low_val = fetch_stock_data(s, period=f"{backtest_years}y", interval=tf)
            if df is not None:
                st.session_state.cached_stock_dfs[s] = (df, cmp_val)
                active, bt = analyze_demand_zones(
                    df, cmp_val, day_low_val,
                    min_price=min_cmp,
                    base_ratio_max=base_body_pct / 100.0,
                    leg_ratio_min=leg_body_pct / 100.0,
                    bo_pct=bo_strength_pct / 100.0,
                    min_move_pct=min_momentum_pct,
                    buffer_pct=test_buffer_pct / 100.0,
                    allow_pause=pause_candle,
                    lookback_years=backtest_years
                )
                all_active.extend(active)
                all_bt.extend(bt)

            progress_bar.progress((idx + 1) / len(symbols))

        status_txt.success(f"Scan Finished! Found {len(all_active)} fresh untested demand zones across {len(symbols)} stocks.")
        st.session_state.active_results = pd.DataFrame(all_active)
        st.session_state.backtest_results = pd.DataFrame(all_bt)

    if not st.session_state.active_results.empty:
        df_display = st.session_state.active_results.copy()
        if search_sym:
            df_display = df_display[df_display['Symbol'].str.contains(search_sym)]

        df_display = df_display.sort_values(by="Required fall %", ascending=True).reset_index(drop=True)

        # Exact 8-Column Format Requested
        view_cols = [
            "Gfinance ticket", "CMP", "Base date", "Proximal",
            "Distal", "Legout candles", "Legout % move", "Required fall %"
        ]
        
        # Display Key Summary Metrics
        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.markdown(f'<div class="metric-box"><div class="metric-val">{len(df_display)}</div><div class="metric-lbl">Pristine Untested Zones</div></div>', unsafe_allow_html=True)
        with m2:
            closest_stock = df_display.iloc[0]['Symbol'] if len(df_display) > 0 else "-"
            st.markdown(f'<div class="metric-box"><div class="metric-val">{closest_stock}</div><div class="metric-lbl">Closest to Entry</div></div>', unsafe_allow_html=True)
        with m3:
            avg_fall = df_display['Required fall %'].mean() if len(df_display) > 0 else 0
            st.markdown(f'<div class="metric-box"><div class="metric-val">{avg_fall:.1f}%</div><div class="metric-lbl">Avg Required Drop</div></div>', unsafe_allow_html=True)
        with m4:
            under_3pct = len(df_display[df_display['Required fall %'] <= 3.0])
            st.markdown(f'<div class="metric-box"><div class="metric-val">{under_3pct}</div><div class="metric-lbl">Within 3% of Entry</div></div>', unsafe_allow_html=True)

        st.markdown("### 📋 Active Untested Demand Zones (Sorted by Proximity)")
        st.dataframe(
            df_display[view_cols].style.format({
                "CMP": "₹{:.2f}",
                "Proximal": "₹{:.2f}",
                "Distal": "₹{:.2f}",
                "Required fall %": "{:.2f}%"
            }).background_gradient(subset=["Required fall %"], cmap="Greens_r"),
            use_container_width=True,
            height=450
        )

        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            csv_data = df_display[view_cols].to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Download CSV for Excel",
                data=csv_data,
                file_name=f"Nifty500_Daily_Demand_Zones_{datetime.today().strftime('%Y-%m-%d')}.csv",
                mime="text/csv",
                use_container_width=True
            )
        with col_dl2:
            # Build Google Sheets copyable text with live formulas
            gsheet_lines = ["\t".join(view_cols)]
            for r_idx, r in df_display.iterrows():
                row_n = r_idx + 2
                gsheet_lines.append(f"{r['Gfinance ticket']}\t=GOOGLEFINANCE(A{row_n}, \"price\")\t{r['Base date']}\t{r['Proximal']}\t{r['Distal']}\t{r['Legout candles']}\t{r['Legout % move']}\t=(B{row_n}-D{row_n})/B{row_n}")
            st.download_button(
                label="📋 Download Google Sheets TSV (with GOOGLEFINANCE formulas)",
                data="\n".join(gsheet_lines),
                file_name="GoogleSheets_Demand_Zones_Formulas.tsv",
                mime="text/tab-separated-values",
                use_container_width=True
            )
    else:
        st.info("👆 Click **'Run Live Screener Scan'** to fetch live NSE market data and scan for Demand Zones.")

# -------------------------------------------------------------
# TAB 2: 5-YEAR BACKTESTER
# -------------------------------------------------------------
with tab_backtest:
    st.subheader(f"📊 Quantitative Forward Backtest Results ({backtest_years}-Year Horizon)")
    st.caption("Traces historical zones from formation day forward through subsequent bars to track mitigation, 2R target hit, 3R target hit, or distal invalidation (SL hit).")

    if not st.session_state.backtest_results.empty:
        bt_df = st.session_state.backtest_results.copy()
        
        # Filter for zones that were tested
        tested_trades = bt_df[bt_df['Tested'] == "Yes"]
        completed_trades = tested_trades[tested_trades['Outcome'].isin(["Target 2R Hit", "Target 3R Hit", "SL Hit (-1R)"])]

        total_setups = len(bt_df)
        total_tested = len(tested_trades)
        wins = len(completed_trades[completed_trades['Outcome'].str.contains("Target")])
        losses = len(completed_trades[completed_trades['Outcome'].str.contains("SL Hit")])
        win_rate = (wins / len(completed_trades) * 100.0) if len(completed_trades) > 0 else 0.0
        net_r = completed_trades['R-Multiple'].sum() if len(completed_trades) > 0 else 0.0

        # Performance Scorecard
        b1, b2, b3, b4, b5 = st.columns(5)
        with b1:
            st.markdown(f'<div class="metric-box"><div class="metric-val">{total_setups}</div><div class="metric-lbl">Total Setups Formed</div></div>', unsafe_allow_html=True)
        with b2:
            st.markdown(f'<div class="metric-box"><div class="metric-val">{total_tested}</div><div class="metric-lbl">Setups Tested / Triggered</div></div>', unsafe_allow_html=True)
        with b3:
            st.markdown(f'<div class="metric-box"><div class="metric-val win-text">{win_rate:.1f}%</div><div class="metric-lbl">Win Rate (2R+)</div></div>', unsafe_allow_html=True)
        with b4:
            st.markdown(f'<div class="metric-box"><div class="metric-val">{net_r:+.1f}R</div><div class="metric-lbl">Cumulative Profit (R)</div></div>', unsafe_allow_html=True)
        with b5:
            profit_factor = (completed_trades[completed_trades['R-Multiple'] > 0]['R-Multiple'].sum() / abs(completed_trades[completed_trades['R-Multiple'] < 0]['R-Multiple'].sum())) if losses > 0 else np.nan
            st.markdown(f'<div class="metric-box"><div class="metric-val">{profit_factor:.2f}</div><div class="metric-lbl">Profit Factor</div></div>', unsafe_allow_html=True)

        st.markdown("---")

        # Outcome Breakdown & Equity Curve
        col_c1, col_c2 = st.columns([1, 2])
        with col_c1:
            st.markdown("#### Trade Outcome Breakdown")
            outcome_counts = bt_df['Outcome'].value_counts()
            fig_pie = go.Figure(data=[go.Pie(
                labels=outcome_counts.index,
                values=outcome_counts.values,
                hole=0.45,
                marker=dict(colors=['#10b981', '#38bdf8', '#ef4444', '#f59e0b', '#64748b'])
            )])
            fig_pie.update_layout(template="plotly_dark", paper_bgcolor="#0f172a", height=320, margin=dict(l=20, r=20, t=20, b=20))
            st.plotly_chart(fig_pie, use_container_width=True)

        with col_c2:
            st.markdown("#### Cumulative R-Multiple Curve")
            if len(completed_trades) > 0:
                completed_sorted = completed_trades.sort_values(by="Base date").reset_index(drop=True)
                completed_sorted['Cum_R'] = completed_sorted['R-Multiple'].cumsum()

                fig_equity = go.Figure()
                fig_equity.add_trace(go.Scatter(
                    x=completed_sorted['Base date'],
                    y=completed_sorted['Cum_R'],
                    mode="lines+markers",
                    line=dict(color="#38bdf8", width=2.5),
                    fill="tozeroy",
                    fillcolor="rgba(56, 189, 248, 0.15)",
                    name="Cumulative R"
                ))
                fig_equity.update_layout(
                    template="plotly_dark",
                    paper_bgcolor="#0f172a",
                    plot_bgcolor="#0f172a",
                    height=320,
                    margin=dict(l=30, r=30, t=20, b=30),
                    xaxis=dict(title="Zone Formation Date"),
                    yaxis=dict(title="Cumulative R")
                )
                st.plotly_chart(fig_equity, use_container_width=True)
            else:
                st.info("No completed closed trades in the current sample to build equity curve.")

        st.markdown("#### Detailed Trade Log")
        bt_cols_show = [
            "Symbol", "Base date", "Pattern", "Proximal", "Distal",
            "Legout % move", "Tested", "Test Date", "Outcome", "Exit Date", "R-Multiple"
        ]
        st.dataframe(
            bt_df[bt_cols_show].style.applymap(
                lambda val: 'color: #10b981; font-weight: bold;' if "Target" in str(val) else ('color: #ef4444; font-weight: bold;' if "SL Hit" in str(val) else ''),
                subset=['Outcome']
            ),
            use_container_width=True,
            height=400
        )
    else:
        st.info("Run a screener scan in Tab 1 to populate the 5-Year Backtest analytics.")

# -------------------------------------------------------------
# TAB 3: INTERACTIVE CHART STUDIO
# -------------------------------------------------------------
with tab_chart:
    st.subheader("📈 Interactive Candlestick & Zone Inspector")
    
    col_sel1, col_sel2 = st.columns([1, 3])
    with col_sel1:
        custom_ticker = st.text_input("Enter NSE Stock Symbol", value="BANKINDIA").upper()
        render_btn = st.button("Load Chart & Zone", type="secondary", use_container_width=True)

    if render_btn or custom_ticker:
        with st.spinner(f"Loading chart for NSE:{custom_ticker}..."):
            df_chart, chart_cmp, chart_low = fetch_stock_data(custom_ticker, period="3y", interval=tf)
            if df_chart is not None:
                # Find zones on this specific stock
                czones, _ = analyze_demand_zones(
                    df_chart, chart_cmp, chart_low,
                    min_price=min_cmp,
                    base_ratio_max=base_body_pct / 100.0,
                    leg_ratio_min=leg_body_pct / 100.0,
                    bo_pct=bo_strength_pct / 100.0,
                    min_move_pct=min_momentum_pct,
                    buffer_pct=test_buffer_pct / 100.0,
                    allow_pause=pause_candle,
                    lookback_years=3
                )

                if czones:
                    selected_zone = czones[0]
                    fig_c = plot_candlestick_zone(
                        df_chart, custom_ticker,
                        selected_zone['Proximal'],
                        selected_zone['Distal'],
                        selected_zone['Base date'],
                        chart_cmp
                    )
                    st.plotly_chart(fig_c, use_container_width=True)

                    c_info1, c_info2, c_info3, c_info4 = st.columns(4)
                    c_info1.metric("Proximal Entry", f"₹{selected_zone['Proximal']}")
                    c_info2.metric("Distal Stop Loss", f"₹{selected_zone['Distal']}")
                    c_info3.metric("Required Drop to Entry", f"{selected_zone['Required fall %']}%")
                    c_info4.metric("2R Target", f"₹{(selected_zone['Proximal'] + 2*(selected_zone['Proximal']-selected_zone['Distal'])):.2f}")
                else:
                    st.warning(f"No active, untested demand zones found for NSE:{custom_ticker} under current criteria.")
                    # Plot basic candlestick without zone
                    fig_basic = go.Figure(data=[go.Candlestick(
                        x=df_chart.tail(200).index.strftime('%Y-%m-%d'),
                        open=df_chart.tail(200)['Open'],
                        high=df_chart.tail(200)['High'],
                        low=df_chart.tail(200)['Low'],
                        close=df_chart.tail(200)['Close'],
                        increasing_line_color='#10b981',
                        decreasing_line_color='#ef4444'
                    )])
                    fig_basic.update_layout(
                        title=f"NSE:{custom_ticker} • CMP: ₹{chart_cmp:.2f} (No Fresh Zone Found)",
                        template="plotly_dark",
                        paper_bgcolor="#0f172a",
                        plot_bgcolor="#0f172a",
                        height=500
                    )
                    st.plotly_chart(fig_basic, use_container_width=True)
            else:
                st.error(f"Could not load data for symbol '{custom_ticker}'. Check the spelling.")
