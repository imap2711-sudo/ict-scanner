import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import io
import concurrent.futures
from datetime import datetime
import pytz
import plotly.graph_objects as go

st.set_page_config(page_title="ICT 15m Scanner", layout="wide", page_icon="⚡")
ist = pytz.timezone('Asia/Kolkata')

@st.cache_data(ttl=3600)
def get_nifty500_symbols():
    url = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
    headers = {"User-Agent": "Mozilla/5.0"}
    for _ in range(3):
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                df = pd.read_csv(io.StringIO(response.text))
                return [str(symbol).strip() + '.NS' for symbol in df['Symbol']]
        except Exception:
            pass
    return ['RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'ICICIBANK.NS', 'INFY.NS', 'ITC.NS', 'SBIN.NS']

def get_trading_days(limit=5):
    ref = yf.Ticker('RELIANCE.NS')
    df = ref.history(period="15d", interval="1d")
    if df.index.tz is not None:
        df.index = df.index.tz_convert('Asia/Kolkata').tz_localize(None)
    return df.index[-limit:].strftime('%Y-%m-%d').tolist()

def find_entry_zone(leg_df, sweep_idx, bo_idx, eq_50, direction):
    zones = []
    
    # Identify DZ / SZ (Last opposing candle before breakout)
    dz_sz_zone = None
    pre_bo_leg = leg_df.loc[:bo_idx].iloc[:-1] 
    if direction == "Bullish":
        bearish_candles = pre_bo_leg[pre_bo_leg['Close'] < pre_bo_leg['Open']]
        if not bearish_candles.empty:
            last_bear = bearish_candles.iloc[-1]
            dz_sz_zone = (last_bear['Low'], last_bear['High'], "15m DZ")
    else:
        bullish_candles = pre_bo_leg[pre_bo_leg['Close'] > pre_bo_leg['Open']]
        if not bullish_candles.empty:
            last_bull = bullish_candles.iloc[-1]
            dz_sz_zone = (last_bull['Low'], last_bull['High'], "15m SZ")
            
    if dz_sz_zone:
        center = (dz_sz_zone[0] + dz_sz_zone[1]) / 2
        pct_diff = abs(center - eq_50) / eq_50 * 100
        if pct_diff <= 2.0:
            zones.append({"top": dz_sz_zone[1], "bot": dz_sz_zone[0], "type": dz_sz_zone[2], "diff": pct_diff})

    # Identify FVGs in the leg
    for i in range(len(leg_df)-2):
        if direction == "Bullish":
            if leg_df['Low'].iloc[i+2] > leg_df['High'].iloc[i]:
                top, bot = leg_df['Low'].iloc[i+2], leg_df['High'].iloc[i]
                center = (top + bot) / 2
                pct_diff = abs(center - eq_50) / eq_50 * 100
                if pct_diff <= 2.0:
                    zones.append({"top": top, "bot": bot, "type": "15m FVG", "diff": pct_diff})
        else:
            if leg_df['High'].iloc[i+2] < leg_df['Low'].iloc[i]:
                top, bot = leg_df['Low'].iloc[i], leg_df['High'].iloc[i+2]
                center = (top + bot) / 2
                pct_diff = abs(center - eq_50) / eq_50 * 100
                if pct_diff <= 2.0:
                    zones.append({"top": top, "bot": bot, "type": "15m FVG", "diff": pct_diff})
                    
    if not zones: return None
    
    # Check for Overlaps between FVG and DZ/SZ
    overlaps = []
    fvgs = [z for z in zones if z['type'] == "15m FVG"]
    dzszs = [z for z in zones if "DZ" in z['type'] or "SZ" in z['type']]
    
    for f in fvgs:
        for d in dzszs:
            if f['bot'] <= d['top'] and f['top'] >= d['bot']:
                o_top = min(f['top'], d['top'])
                o_bot = max(f['bot'], d['bot'])
                o_center = (o_top + o_bot) / 2
                o_diff = abs(o_center - eq_50) / eq_50 * 100
                if o_diff <= 2.0:
                    overlaps.append({"top": o_top, "bot": o_bot, "type": "Overlap (FVG+DZ)", "diff": o_diff})
                    
    # Priority: 1. Overlaps 2. Nearest to 50%
    if overlaps:
        return sorted(overlaps, key=lambda x: x['diff'])[0]
    return sorted(zones, key=lambda x: x['diff'])[0]


def process_setup_logic(df, daily_df, eval_day, day_start, day_end, ticker, cmp, mss_limit, strict_pdh_filter):
    hist_daily = daily_df.loc[daily_df.index < day_start]
    if hist_daily.empty: return []
        
    pdh = hist_daily['High'].iloc[-1]
    pdl = hist_daily['Low'].iloc[-1]
            
    eval_window = df.loc[(df.index >= day_start) & (df.index < day_end)]
    if eval_window.empty: return []
    
    day_high = eval_window['High'].max()
    day_low = eval_window['Low'].min()
    touched_pdh_anytime = day_high >= pdh
    touched_pdl_anytime = day_low <= pdl
    
    setups = []
    
    # --- BULLISH ---
    bull_sweeps = eval_window[eval_window['Low'] <= pdl]
    if not bull_sweeps.empty:
        if not (strict_pdh_filter and touched_pdh_anytime):
            # Isolate the chronologically FIRST sweep of the day
            sweep_idx = bull_sweeps.index[0]
            sweep_low = eval_window.loc[sweep_idx, 'Low']
            
            pre_df = df.loc[:sweep_idx].iloc[-40:-1] 
            if len(pre_df) >= 3:
                shs = [pre_df['High'].iloc[i] for i in range(1, len(pre_df)-1) if pre_df['High'].iloc[i] > pre_df['High'].iloc[i-1] and pre_df['High'].iloc[i] > pre_df['High'].iloc[i+1]]
                if shs:
                    break_level = shs[-1]
                    if len(shs) > 1 and abs(shs[-2] - break_level) / break_level < 0.0015:
                        break_level = max(break_level, shs[-2])
                    
                    # MSS Breakout must happen TODAY
                    post_sweep = eval_window.loc[sweep_idx:]
                    bo_cands = post_sweep[post_sweep['Close'] > break_level]
                    
                    if not bo_cands.empty:
                        bo_idx = bo_cands.index[0]
                        sweep_pos = eval_window.index.get_loc(sweep_idx)
                        bo_pos = eval_window.index.get_loc(bo_idx)
                        mss_count = bo_pos - sweep_pos
                        
                        if 0 < mss_count <= mss_limit:
                            # Swing High must form TODAY
                            post_bo = eval_window.loc[bo_idx:]
                            swing_high_val = None
                            swing_high_idx = None
                            confirmation_idx = None
                            
                            for i in range(1, len(post_bo)-1):
                                if post_bo['High'].iloc[i] > post_bo['High'].iloc[i-1] and post_bo['High'].iloc[i] > post_bo['High'].iloc[i+1]:
                                    swing_high_val = post_bo['High'].iloc[i]
                                    swing_high_idx = post_bo.index[i]
                                    confirmation_idx = post_bo.index[i+1] 
                                    break
                                    
                            if swing_high_val is not None:
                                eq_50 = (sweep_low + swing_high_val) / 2
                                rally_leg = eval_window.loc[sweep_idx:swing_high_idx]
                                
                                entry_zone = find_entry_zone(rally_leg, sweep_idx, bo_idx, eq_50, "Bullish")
                                
                                if entry_zone:
                                    # Entry Zone must remain untouched TODAY
                                    post_confirmation = eval_window.loc[confirmation_idx:]
                                    touched = False
                                    if len(post_confirmation) > 1:
                                        if post_confirmation['Low'].iloc[1:].min() <= entry_zone['top']:
                                            touched = True
                                            
                                    if not touched and cmp > entry_zone['top']:
                                        setups.append({
                                            "Direction": "Bullish", "Date": bo_idx.strftime('%Y-%m-%d'),
                                            "Time": bo_idx.strftime('%H:%M'), "Symbol": ticker.replace('.NS',''),
                                            "Stage": f"MSS c{mss_count}", "HTF Level (₹)": round(pdl, 2),
                                            "MSS Break Level (₹)": round(break_level, 2), 
                                            "Entry Zone": f"{entry_zone['type']} (±2%)", 
                                            "Entry Limit (₹)": round(entry_zone['top'], 2),
                                            "CMP (₹)": round(cmp, 2),
                                            "Gap (%)": round(((cmp - entry_zone['top']) / cmp) * 100, 2)
                                        })

    # --- BEARISH ---
    bear_sweeps = eval_window[eval_window['High'] >= pdh]
    if not bear_sweeps.empty:
        if not (strict_pdh_filter and touched_pdl_anytime):
            # Isolate the chronologically FIRST sweep of the day
            sweep_idx = bear_sweeps.index[0]
            sweep_high = eval_window.loc[sweep_idx, 'High']
            
            pre_df = df.loc[:sweep_idx].iloc[-40:-1] 
            if len(pre_df) >= 3:
                sls = [pre_df['Low'].iloc[i] for i in range(1, len(pre_df)-1) if pre_df['Low'].iloc[i] < pre_df['Low'].iloc[i-1] and pre_df['Low'].iloc[i] < pre_df['Low'].iloc[i+1]]
                if sls:
                    break_level = sls[-1]
                    if len(sls) > 1 and abs(sls[-2] - break_level) / break_level < 0.0015:
                        break_level = min(break_level, sls[-2])
                    
                    # MSS Breakout must happen TODAY
                    post_sweep = eval_window.loc[sweep_idx:]
                    bo_cands = post_sweep[post_sweep['Close'] < break_level]
                    
                    if not bo_cands.empty:
                        bo_idx = bo_cands.index[0]
                        sweep_pos = eval_window.index.get_loc(sweep_idx)
                        bo_pos = eval_window.index.get_loc(bo_idx)
                        mss_count = bo_pos - sweep_pos
                        
                        if 0 < mss_count <= mss_limit:
                            # Swing Low must form TODAY
                            post_bo = eval_window.loc[bo_idx:]
                            swing_low_val = None
                            swing_low_idx = None
                            confirmation_idx = None
                            
                            for i in range(1, len(post_bo)-1):
                                if post_bo['Low'].iloc[i] < post_bo['Low'].iloc[i-1] and post_bo['Low'].iloc[i] < post_bo['Low'].iloc[i+1]:
                                    swing_low_val = post_bo['Low'].iloc[i]
                                    swing_low_idx = post_bo.index[i]
                                    confirmation_idx = post_bo.index[i+1]
                                    break
                                    
                            if swing_low_val is not None:
                                eq_50 = (sweep_high + swing_low_val) / 2
                                rally_leg = eval_window.loc[sweep_idx:swing_low_idx]
                                
                                entry_zone = find_entry_zone(rally_leg, sweep_idx, bo_idx, eq_50, "Bearish")
                                
                                if entry_zone:
                                    # Entry Zone must remain untouched TODAY
                                    post_confirmation = eval_window.loc[confirmation_idx:]
                                    touched = False
                                    if len(post_confirmation) > 1:
                                        if post_confirmation['High'].iloc[1:].max() >= entry_zone['bot']:
                                            touched = True
                                            
                                    if not touched and cmp < entry_zone['bot']:
                                        setups.append({
                                            "Direction": "Bearish", "Date": bo_idx.strftime('%Y-%m-%d'),
                                            "Time": bo_idx.strftime('%H:%M'), "Symbol": ticker.replace('.NS',''),
                                            "Stage": f"MSS c{mss_count}", "HTF Level (₹)": round(pdh, 2),
                                            "MSS Break Level (₹)": round(break_level, 2), 
                                            "Entry Zone": f"{entry_zone['type']} (±2%)", 
                                            "Entry Limit (₹)": round(entry_zone['bot'], 2),
                                            "CMP (₹)": round(cmp, 2),
                                            "Gap (%)": round(((entry_zone['bot'] - cmp) / cmp) * 100, 2)
                                        })
    return setups

def find_15m_ict_setup(ticker, mss_limit, strict_pdh_filter):
    try:
        t = yf.Ticker(ticker)
        df = t.history(period="60d", interval="15m", auto_adjust=False)
        if df.empty or len(df) < 200: return None
            
        df.index = df.index.tz_convert('Asia/Kolkata').tz_localize(None) if df.index.tz is not None else df.index.tz_localize(None)
        df = df.dropna(subset=['Close', 'High', 'Low'])
        
        try: cmp = float(t.fast_info.last_price)
        except: cmp = float(df['Close'].iloc[-1])
        if pd.isna(cmp) or cmp <= 60: return None
            
        if cmp > df['High'].iloc[-1]: df.loc[df.index[-1], 'High'] = cmp
        if cmp < df['Low'].iloc[-1]: df.loc[df.index[-1], 'Low'] = cmp
        df.loc[df.index[-1], 'Close'] = cmp
        
        daily_df = df.resample('D').agg({'High':'max', 'Low':'min', 'Close':'last'}).dropna()
        if len(daily_df) < 10: return None
            
        all_setups = []
        for eval_day in daily_df.index[-5:]:
            day_start = eval_day.replace(hour=0, minute=0, second=0)
            day_end = day_start + pd.Timedelta(days=1)
            all_setups.extend(process_setup_logic(df, daily_df, eval_day, day_start, day_end, ticker, cmp, mss_limit, strict_pdh_filter))
                
        return all_setups if all_setups else None
    except Exception:
        return None

@st.cache_data(ttl=300, show_spinner=False)
def run_market_scan(tickers, mss_limit, strict_pdh_filter):
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        futures = [executor.submit(find_15m_ict_setup, tick, mss_limit, strict_pdh_filter) for tick in tickers]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res: results.extend(res)
    return results

def plot_interactive_chart(setup):
    ticker = setup['Symbol'] + ".NS"
    t = yf.Ticker(ticker)
    df = t.history(period="4d", interval="15m")
    if df.index.tz is not None: df.index = df.index.tz_convert('Asia/Kolkata').tz_localize(None)
    
    fig = go.Figure(data=[go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
        increasing_line_color='#26a69a', decreasing_line_color='#ef5350'
    )])
    
    pool_color = "#ef5350" if setup['Direction'] == 'Bullish' else "#26a69a"
    fig.add_hline(y=setup['HTF Level (₹)'], line_dash="dash", line_color=pool_color, annotation_text=" HTF Sweep ", annotation_position="bottom right", annotation_bgcolor=pool_color)
    fig.add_hline(y=setup['MSS Break Level (₹)'], line_dash="dot", line_color="#ff9800", annotation_text=" MSS Break ", annotation_position="top left", annotation_bgcolor="#ff9800")
    fig.add_hline(y=setup['Entry Limit (₹)'], line_dash="dash", line_color="#4fc3f7", annotation_text=f" Limit Entry ({setup['Entry Zone']}) ", annotation_position="bottom right", annotation_bgcolor="#4fc3f7")
    
    fig.update_layout(title=f"{setup['Symbol']} | {setup['Direction']} | {setup['Stage']}", yaxis_title="Price (₹)", xaxis_rangeslider_visible=False, template="plotly_dark", height=500, margin=dict(l=20, r=20, t=50, b=20))
    fig.update_xaxes(rangebreaks=[dict(bounds=["15:30", "09:15"]), dict(bounds=["sat", "mon"])])
    return fig

# --- STREAMLIT UI ---
st.title("⚡ ICT Intraday Precision Scanner")

with st.sidebar:
    st.header("⚙️ Algorithm Settings")
    mss_limit = st.number_input("Max Candles for MSS Breakout", min_value=3, max_value=20, value=10, step=1)
    strict_pdh_filter = st.radio("Strict PDH/PDL No-Touch Filter", options=["On (Discard if touched)", "Off (Allow opposite touch)"])
    strict_bool = True if "On" in strict_pdh_filter else False

now_str = datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S IST")
st.markdown(f"**Market Data Current As Of:** `{now_str}`")

if st.button("🚀 Fetch Live Market Data & Scan", type="primary"):
    with st.spinner(f"Scanning Nifty 500 (MSS ≤ {mss_limit} candles | PDH Filter: {strict_bool})..."):
        tickers = get_nifty500_symbols()
        st.session_state['raw_data'] = run_market_scan(tickers, mss_limit, strict_bool)
        st.session_state['valid_dates'] = get_trading_days(5)

if 'raw_data' in st.session_state:
    df_all = pd.DataFrame(st.session_state['raw_data'])
    valid_dates = reversed(st.session_state['valid_dates'])
    
    col1, col2 = st.columns(2)
    with col1: sel_date = st.selectbox("Select Date", valid_dates)
    with col2:
        times = ["View Full Day"] + [f"{h:02d}:{m:02d}" for h in range(9, 16) for m in (0, 15, 30, 45) if not (h==9 and m==0) and not (h==15 and m>30)]
        sel_time = st.selectbox("Simulated Screener Time", times)

    if not df_all.empty:
        df_filtered = df_all[df_all['Date'] == sel_date]
        if sel_time != "View Full Day": df_filtered = df_filtered[df_filtered['Time'] <= sel_time]
        df_bull = df_filtered[df_filtered['Direction'] == 'Bullish'].sort_values('Gap (%)')
        df_bear = df_filtered[df_filtered['Direction'] == 'Bearish'].sort_values('Gap (%)')
    else:
        df_bull, df_bear = pd.DataFrame(), pd.DataFrame()

    t1, t2 = st.tabs(["🟢 Bullish Setups (Long)", "🔴 Bearish Setups (Short)"])
    with t1:
        if df_bull.empty: st.info(f"No strictly compliant PDL sweeps found on {sel_date} by {sel_time}.")
        else: st.dataframe(df_bull.drop(columns=['Direction', 'Date']), use_container_width=True, hide_index=True)
    with t2:
        if df_bear.empty: st.info(f"No strictly compliant PDH sweeps found on {sel_date} by {sel_time}.")
        else: st.dataframe(df_bear.drop(columns=['Direction', 'Date']), use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("📈 Visualize Setup")
    if not df_filtered.empty:
        setup_options = {f"{row['Symbol']} ({row['Direction']} - {row['Stage']} @ {row['Time']})": row.to_dict() for _, row in df_filtered.iterrows()}
        selected_key = st.selectbox("Select a stock to render its chart:", list(setup_options.keys()))
        if selected_key:
            with st.spinner(f"Loading live chart for {setup_options[selected_key]['Symbol']}..."):
                st.plotly_chart(plot_interactive_chart(setup_options[selected_key]), use_container_width=True)
