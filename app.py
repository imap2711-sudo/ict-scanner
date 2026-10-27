import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import io
import concurrent.futures
from datetime import datetime, timedelta
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
    df = ref.history(period="60d", interval="1d")
    if df.index.tz is not None:
        df.index = df.index.tz_convert('Asia/Kolkata').tz_localize(None)
    return df.index[-limit:].strftime('%Y-%m-%d').tolist()

def process_setup_logic(df, daily_df, eval_day, day_start, day_end, ticker, cmp, mode="live"):
    hist_daily = daily_df.loc[daily_df.index < day_start]
    if hist_daily.empty: return []
        
    pdh = hist_daily['High'].iloc[-1]
    pdl = hist_daily['Low'].iloc[-1]
    
    bullish_levels = [(pdl, "PDL")]
    bearish_levels = [(pdh, "PDH")]
            
    eval_window = df.loc[(df.index >= day_start) & (df.index < day_end)]
    if eval_window.empty: return []
        
    setups = []
    df_index_list = df.index.tolist()
    
    # --- BULLISH ---
    bull_found = False
    for sweep_idx in eval_window.index:
        if bull_found: break
        sweep_low = df.loc[sweep_idx, 'Low']
        
        swept_level = next(((px, name) for px, name in bullish_levels if sweep_low < px), None)
        if not swept_level: continue
        
        pre_df = df.loc[:sweep_idx].iloc[-40:-1] 
        if len(pre_df) < 3: continue
            
        shs = [pre_df['High'].iloc[i] for i in range(1, len(pre_df)-1) if pre_df['High'].iloc[i] > pre_df['High'].iloc[i-1] and pre_df['High'].iloc[i] > pre_df['High'].iloc[i+1]]
        if not shs: continue
        break_level = shs[-1]
        if len(shs) > 1 and abs(shs[-2] - break_level) / break_level < 0.0015:
            break_level = max(break_level, shs[-2])
        
        post_df = eval_window.loc[sweep_idx:]
        bo_cands = post_df[post_df['Close'] > break_level]
        if bo_cands.empty: continue
            
        bo_idx = bo_cands.index[0]
        if (df_index_list.index(bo_idx) - df_index_list.index(sweep_idx)) > 5: continue 
            
        leg = df.loc[sweep_idx:bo_idx]
        if leg['High'].max() >= pdh: continue
            
        if not any(leg['Low'].iloc[i+2] > leg['High'].iloc[i] for i in range(len(leg)-2)): continue
        
        disp_high = leg['High'].max()
        eq_50 = (sweep_low + disp_high) / 2
        
        if mode == "live":
            post_high = df.loc[leg['High'].idxmax():]
            if len(post_high) > 1 and post_high['Low'].iloc[1:].min() <= eq_50: continue
            if cmp <= eq_50: continue
            
            setups.append({
                "Direction": "Bullish", "Date": bo_idx.strftime('%Y-%m-%d'), "Breakout Time (15m Close)": bo_idx.strftime('%H:%M'),
                "Symbol": ticker.replace('.NS',''), "HTF Pool": swept_level[1], "HTF Level (₹)": round(swept_level[0], 2),
                "MSS Break Level (₹)": round(break_level, 2), "Anchor (₹)": round(sweep_low, 2),
                "Displacement (₹)": round(disp_high, 2), "Entry 50% (₹)": round(eq_50, 2),
                "CMP (₹)": round(cmp, 2), "Gap (%)": round(((cmp - eq_50) / cmp) * 100, 2)
            })
        else:
            setups.append({
                "Direction": "Bullish", "Breakout_Idx": bo_idx, "Symbol": ticker.replace('.NS',''),
                "Anchor": sweep_low, "Displacement_Peak": disp_high, "Entry_50": eq_50
            })
        bull_found = True

    # --- BEARISH ---
    bear_found = False
    for sweep_idx in eval_window.index:
        if bear_found: break
        sweep_high = df.loc[sweep_idx, 'High']
        
        swept_level = next(((px, name) for px, name in bearish_levels if sweep_high > px), None)
        if not swept_level: continue
        
        pre_df = df.loc[:sweep_idx].iloc[-40:-1] 
        if len(pre_df) < 3: continue
            
        sls = [pre_df['Low'].iloc[i] for i in range(1, len(pre_df)-1) if pre_df['Low'].iloc[i] < pre_df['Low'].iloc[i-1] and pre_df['Low'].iloc[i] < pre_df['Low'].iloc[i+1]]
        if not sls: continue
        break_level = sls[-1]
        if len(sls) > 1 and abs(sls[-2] - break_level) / break_level < 0.0015:
            break_level = min(break_level, sls[-2])
        
        post_df = eval_window.loc[sweep_idx:]
        bo_cands = post_df[post_df['Close'] < break_level]
        if bo_cands.empty: continue
            
        bo_idx = bo_cands.index[0]
        if (df_index_list.index(bo_idx) - df_index_list.index(sweep_idx)) > 5: continue 
            
        leg = df.loc[sweep_idx:bo_idx]
        if leg['Low'].min() <= pdl: continue
            
        if not any(leg['High'].iloc[i+2] < leg['Low'].iloc[i] for i in range(len(leg)-2)): continue
        
        disp_low = leg['Low'].min()
        eq_50 = (sweep_high + disp_low) / 2
        
        if mode == "live":
            post_low = df.loc[leg['Low'].idxmin():]
            if len(post_low) > 1 and post_low['High'].iloc[1:].max() >= eq_50: continue
            if cmp >= eq_50: continue
            
            setups.append({
                "Direction": "Bearish", "Date": bo_idx.strftime('%Y-%m-%d'), "Breakout Time (15m Close)": bo_idx.strftime('%H:%M'),
                "Symbol": ticker.replace('.NS',''), "HTF Pool": swept_level[1], "HTF Level (₹)": round(swept_level[0], 2),
                "MSS Break Level (₹)": round(break_level, 2), "Anchor (₹)": round(sweep_high, 2),
                "Displacement (₹)": round(disp_low, 2), "Entry 50% (₹)": round(eq_50, 2),
                "CMP (₹)": round(cmp, 2), "Gap (%)": round(((eq_50 - cmp) / cmp) * 100, 2)
            })
        else:
            setups.append({
                "Direction": "Bearish", "Breakout_Idx": bo_idx, "Symbol": ticker.replace('.NS',''),
                "Anchor": sweep_high, "Displacement_Peak": disp_low, "Entry_50": eq_50
            })
        bear_found = True
        
    return setups

def find_15m_ict_setup(ticker):
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
            all_setups.extend(process_setup_logic(df, daily_df, eval_day, day_start, day_end, ticker, cmp, mode="live"))
                
        return all_setups if all_setups else None
    except Exception:
        return None

def run_historical_backtest(ticker, target_date_str):
    try:
        t = yf.Ticker(ticker)
        df = t.history(period="60d", interval="15m", auto_adjust=False)
        if df.empty: return None
            
        df.index = df.index.tz_convert('Asia/Kolkata').tz_localize(None) if df.index.tz is not None else df.index.tz_localize(None)
        df = df.dropna(subset=['Close', 'High', 'Low'])
        
        daily_df = df.resample('D').agg({'High':'max', 'Low':'min', 'Close':'last'}).dropna()
        
        target_date = pd.to_datetime(target_date_str).replace(hour=0, minute=0, second=0)
        if target_date not in daily_df.index: return None
            
        day_start = target_date
        day_end = day_start + pd.Timedelta(days=1)
        
        # 1. Identify Setup
        setups = process_setup_logic(df, daily_df, target_date, day_start, day_end, ticker, 0, mode="backtest")
        if not setups: return None
        
        results = []
        for s in setups:
            bo_idx = s['Breakout_Idx']
            
            # 2. Determine Entry Window (Same day + Next trading day)
            future_daily = daily_df.loc[daily_df.index > target_date]
            if future_daily.empty:
                entry_limit = day_end + pd.Timedelta(hours=15) 
            else:
                next_day_start = future_daily.index[0]
                entry_limit = next_day_start + pd.Timedelta(days=1)
            
            entry_window = df.loc[(df.index > bo_idx) & (df.index < entry_limit)]
            entered = False
            entry_idx = None
            
            # 3. Check for Entry
            if s['Direction'] == 'Bullish':
                for idx, row in entry_window.iterrows():
                    if row['Low'] <= s['Entry_50']:
                        entered = True
                        entry_idx = idx
                        break
            else:
                for idx, row in entry_window.iterrows():
                    if row['High'] >= s['Entry_50']:
                        entered = True
                        entry_idx = idx
                        break
                        
            if not entered:
                results.append({**s, "Triggered": False, "Max_Move_Pct": 0, "Outcome": "Missed Entry"})
                continue
                
            # 4. Forward Track (SL vs Target & Max Excursion)
            forward_df = df.loc[df.index > entry_idx]
            max_move_pct = 0
            outcome = "Open / End of Data"
            
            if s['Direction'] == 'Bullish':
                highest_seen = s['Entry_50']
                for idx, row in forward_df.iterrows():
                    if row['High'] > highest_seen: highest_seen = row['High']
                    if row['Low'] <= s['Anchor']:
                        outcome = "SL Hit"
                        break
                    if row['High'] >= s['Displacement_Peak']:
                        outcome = "Target Hit"
                        break
                max_move_pct = ((highest_seen - s['Entry_50']) / s['Entry_50']) * 100
            else:
                lowest_seen = s['Entry_50']
                for idx, row in forward_df.iterrows():
                    if row['Low'] < lowest_seen: lowest_seen = row['Low']
                    if row['High'] >= s['Anchor']:
                        outcome = "SL Hit"
                        break
                    if row['Low'] <= s['Displacement_Peak']:
                        outcome = "Target Hit"
                        break
                max_move_pct = ((s['Entry_50'] - lowest_seen) / s['Entry_50']) * 100
                
            results.append({
                "Symbol": s['Symbol'], "Direction": s['Direction'], "Triggered": True,
                "Outcome": outcome, "Max Move (%)": round(max_move_pct, 2)
            })
            
        return results if results else None
    except Exception:
        return None

@st.cache_data(ttl=300, show_spinner=False)
def run_market_scan(tickers):
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        for res in executor.map(find_15m_ict_setup, tickers):
            if res: results.extend(res)
    return results

@st.cache_data(ttl=3600, show_spinner=False)
def execute_backtest(tickers, target_date):
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        futures = [executor.submit(run_historical_backtest, tick, target_date) for tick in tickers]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res: results.extend(res)
    return pd.DataFrame(results) if results else pd.DataFrame()

def plot_interactive_chart(setup):
    ticker = setup['Symbol'] + ".NS"
    t = yf.Ticker(ticker)
    df = t.history(period="4d", interval="15m")
    if df.index.tz is not None: df.index = df.index.tz_convert('Asia/Kolkata').tz_localize(None)
    
    fig = go.Figure(data=[go.Candlestick(
        x=df.index, open=df['Open'], high=df['High'], low=df['Low'], close=df['Close'],
        increasing_line_color='#26a69a', decreasing_line_color='#ef5350'
    )])
    fig.add_hline(y=setup['HTF Level (₹)'], line_dash="dash", line_color="#ef5350", annotation_text=f" Swept {setup['HTF Pool']} ", annotation_position="bottom right", annotation_bgcolor="#ef5350")
    fig.add_hline(y=setup['MSS Break Level (₹)'], line_dash="dot", line_color="#ff9800", annotation_text=" MSS Break ", annotation_position="top left", annotation_bgcolor="#ff9800")
    fig.add_hline(y=setup['Entry 50% (₹)'], line_dash="dash", line_color="#26a69a", annotation_text=" 50% Entry ", annotation_position="bottom right", annotation_bgcolor="#26a69a")
    fig.update_layout(title=f"{setup['Symbol']} | {setup['Direction']} | Breakout @ {setup['Breakout Time (15m Close)']}", yaxis_title="Price (₹)", xaxis_rangeslider_visible=False, template="plotly_dark", height=500, margin=dict(l=20, r=20, t=50, b=20))
    fig.update_xaxes(rangebreaks=[dict(bounds=["15:30", "09:15"]), dict(bounds=["sat", "mon"])])
    return fig


# --- STREAMLIT UI ---
st.title("⚡ ICT Intraday Precision Scanner")
now_str = datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S IST")
st.markdown(f"**Market Data Current As Of:** `{now_str}`")

tab_live, tab_hist = st.tabs(["🟢 Live Market Scanner (Last 5 Days)", "📊 Historical Backtester (60 Days)"])

with tab_live:
    if st.button("🚀 Fetch Live Market Data & Scan", type="primary", key="live_btn"):
        with st.spinner("Scanning Nifty 500 for strict PDL / PDH Sweeps..."):
            tickers = get_nifty500_symbols()
            st.session_state['raw_data'] = run_market_scan(tickers)
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
            if sel_time != "View Full Day": df_filtered = df_filtered[df_filtered['Breakout Time (15m Close)'] <= sel_time]
            df_bull = df_filtered[df_filtered['Direction'] == 'Bullish'].sort_values('Gap (%)')
            df_bear = df_filtered[df_filtered['Direction'] == 'Bearish'].sort_values('Gap (%)')
        else:
            df_bull, df_bear = pd.DataFrame(), pd.DataFrame()

        t1, t2 = st.tabs(["Bullish Setups (Long)", "Bearish Setups (Short)"])
        with t1:
            if df_bull.empty: st.info(f"No setups found on {sel_date} by {sel_time}.")
            else: st.dataframe(df_bull.drop(columns=['Direction', 'Date']), use_container_width=True, hide_index=True)
        with t2:
            if df_bear.empty: st.info(f"No setups found on {sel_date} by {sel_time}.")
            else: st.dataframe(df_bear.drop(columns=['Direction', 'Date']), use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("📈 Visualize Setup")
        if not df_filtered.empty:
            setup_options = {f"{row['Symbol']} ({row['Direction']} @ {row['Breakout Time (15m Close)']})": row.to_dict() for _, row in df_filtered.iterrows()}
            selected_key = st.selectbox("Select a stock to render its chart:", list(setup_options.keys()))
            if selected_key:
                with st.spinner(f"Loading live chart for {setup_options[selected_key]['Symbol']}..."):
                    st.plotly_chart(plot_interactive_chart(setup_options[selected_key]), use_container_width=True)

with tab_hist:
    st.markdown("Select any trading date in the last **60 days** to backtest T+1 entry and stop-loss metrics.")
    all_60_days = reversed(get_trading_days(60))
    hist_date = st.selectbox("Select Backtest Date", all_60_days, key="hist_date")
    
    if st.button(f"🔍 Run Backtest for {hist_date}"):
        with st.spinner(f"Executing deep historical scan for {hist_date}..."):
            tickers = get_nifty500_symbols()
            res_df = execute_backtest(tickers, hist_date)
            
            if res_df.empty:
                st.warning(f"No valid PDL/PDH ICT setups formed on {hist_date}.")
            else:
                total_setups = len(res_df)
                triggered = len(res_df[res_df['Triggered'] == True])
                sl_hits = len(res_df[res_df['Outcome'] == 'SL Hit'])
                target_hits = len(res_df[res_df['Outcome'] == 'Target Hit'])
                avg_move = res_df[res_df['Triggered'] == True]['Max Move (%)'].mean()
                
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Total Setups Identified", total_setups)
                c2.metric("Entered (Touched 50%)", triggered)
                c3.metric("Failed (Hit SL before Target)", sl_hits)
                c4.metric("Avg Max Favorable Excursion", f"{avg_move:.2f}%" if pd.notna(avg_move) else "0%")
                
                st.dataframe(res_df, use_container_width=True, hide_index=True)
