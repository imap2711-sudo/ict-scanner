import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import io
import concurrent.futures
from datetime import datetime, timedelta
import pytz

st.set_page_config(page_title="Ultimate ICT Precision Scanner", layout="wide", page_icon="⚡")
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

def get_recent_swing(df, current_idx, direction='high'):
    """Finds the most recent untested swing point strictly prior to the sweep."""
    try:
        loc = df.index.get_loc(current_idx)
        for i in range(loc - 1, 1, -1):
            if direction == 'high':
                if df['High'].iloc[i] > df['High'].iloc[i-1] and df['High'].iloc[i] > df['High'].iloc[i+1]:
                    # Ensure it remained untested between its formation and the sweep
                    if df['High'].iloc[i:loc].max() <= df['High'].iloc[i]:
                        return df.index[i], df['High'].iloc[i]
            else:
                if df['Low'].iloc[i] < df['Low'].iloc[i-1] and df['Low'].iloc[i] < df['Low'].iloc[i+1]:
                    if df['Low'].iloc[i:loc].min() >= df['Low'].iloc[i]:
                        return df.index[i], df['Low'].iloc[i]
        return None, None
    except:
        return None, None

def get_post_mss_swing(df, mss_idx, direction='high'):
    """Finds the first swing point formed AFTER the MSS breakout is completed."""
    try:
        loc = df.index.get_loc(mss_idx)
        for i in range(loc, len(df)-1):
            if direction == 'high':
                if df['High'].iloc[i] > df['High'].iloc[i-1] and df['High'].iloc[i] > df['High'].iloc[i+1]:
                    return df.index[i], df['High'].iloc[i], df.index[i+1] # Returns the right-shoulder confirmation candle
            else:
                if df['Low'].iloc[i] < df['Low'].iloc[i-1] and df['Low'].iloc[i] < df['Low'].iloc[i+1]:
                    return df.index[i], df['Low'].iloc[i], df.index[i+1]
        return None, None, None
    except:
        return None, None, None

def evaluate_setup(df, htf_high, htf_low, mss_limit, scan_state, eval_start, eval_end):
    setups = []
    df_index = df.index.tolist()
    cmp = df['Close'].iloc[-1]
    
    # Restrict the sweep search to the exact evaluation window (Today or This Month)
    window_df = df.loc[(df.index >= eval_start) & (df.index <= eval_end)]
    if window_df.empty: return setups
    
    # -----------------------
    # BULLISH LOGIC
    # -----------------------
    bull_sweeps = window_df[window_df['Low'] <= htf_low]
    if not bull_sweeps.empty:
        sweep_idx = bull_sweeps.index[0] 
        sweep_pos = df_index.index(sweep_idx) # Count candles using the full dataframe index
        sweep_low = df.loc[sweep_idx, 'Low']
        
        # Rule: Must not touch opposite liquidity (HTF High) AFTER sweep inside the evaluation window
        post_sweep_df = window_df.loc[sweep_idx:]
        if post_sweep_df['High'].max() < htf_high:
            
            # Find Untested Swing High Prior to Sweep (Searches the full un-truncated history)
            sh_idx, sh_val = get_recent_swing(df, sweep_idx, 'high')
            if sh_idx:
                mss_cands = post_sweep_df[post_sweep_df['Close'] > sh_val]
                if not mss_cands.empty:
                    mss_idx = mss_cands.index[0]
                    mss_pos = df_index.index(mss_idx)
                    
                    if (mss_pos - sweep_pos) <= mss_limit:
                        post_sh_idx, post_sh_val, confirm_idx = get_post_mss_swing(df, mss_idx, 'high')
                        
                        setup_data = {
                            "Direction": "Bullish",
                            "Sweep Time": sweep_idx.strftime('%Y-%m-%d %H:%M'),
                            "HTF Low Swept": round(htf_low, 2),
                            "MSS Break Time": mss_idx.strftime('%Y-%m-%d %H:%M'),
                            "Broken Swing High": round(sh_val, 2),
                        }
                        
                        # State 1: MSS Done
                        if not post_sh_idx:
                            if scan_state == "1":
                                setups.append({**setup_data, "Status": "MSS Done, Building Leg"})
                        
                        else:
                            eq_50 = (sweep_low + post_sh_val) / 2
                            setup_data.update({
                                "Momentum Peak": round(post_sh_val, 2),
                                "50% Entry Level": round(eq_50, 2),
                            })
                            
                            confirm_pos = df_index.index(confirm_idx)
                            tracking_df = df.iloc[confirm_pos:]
                            touched_50 = not tracking_df[tracking_df['Low'] <= eq_50].empty
                            
                            # State 2: Awaiting Entry
                            if not touched_50 and scan_state == "2":
                                setups.append({**setup_data, "Status": "Awaiting Entry", "Live CMP": round(cmp, 2), "Gap to 50%": round(((cmp - eq_50)/cmp)*100, 2)})
                                
                            # State 3: Trade Open
                            elif touched_50 and scan_state == "3":
                                setups.append({**setup_data, "Status": "Trade Open", "Live CMP": round(cmp, 2)})
                                
                            # State 4: Previous Reports (Backtest Mode)
                            elif touched_50 and scan_state == "4":
                                entry_idx = tracking_df[tracking_df['Low'] <= eq_50].index[0]
                                forward_df = df.loc[entry_idx:]
                                
                                outcome = "Open"
                                highest_seen = eq_50
                                
                                for idx, row in forward_df.iterrows():
                                    if row['High'] > highest_seen: highest_seen = row['High']
                                    
                                    if row['Low'] <= sweep_low:
                                        outcome = "SL Hit"
                                        break
                                    elif row['High'] >= post_sh_val:
                                        outcome = "Target Hit (Successful)"
                                        break
                                
                                max_move = ((highest_seen - eq_50) / eq_50) * 100
                                setups.append({**setup_data, "Outcome": outcome, "Max Favorable Move (%)": round(max_move, 2)})

    # -----------------------
    # BEARISH LOGIC
    # -----------------------
    bear_sweeps = window_df[window_df['High'] >= htf_high]
    if not bear_sweeps.empty:
        sweep_idx = bear_sweeps.index[0] 
        sweep_pos = df_index.index(sweep_idx)
        sweep_high = df.loc[sweep_idx, 'High']
        
        post_sweep_df = window_df.loc[sweep_idx:]
        if post_sweep_df['Low'].min() > htf_low:
            
            sl_idx, sl_val = get_recent_swing(df, sweep_idx, 'low')
            if sl_idx:
                mss_cands = post_sweep_df[post_sweep_df['Close'] < sl_val]
                if not mss_cands.empty:
                    mss_idx = mss_cands.index[0]
                    mss_pos = df_index.index(mss_idx)
                    
                    if (mss_pos - sweep_pos) <= mss_limit:
                        post_sl_idx, post_sl_val, confirm_idx = get_post_mss_swing(df, mss_idx, 'low')
                        
                        setup_data = {
                            "Direction": "Bearish",
                            "Sweep Time": sweep_idx.strftime('%Y-%m-%d %H:%M'),
                            "HTF High Swept": round(htf_high, 2),
                            "MSS Break Time": mss_idx.strftime('%Y-%m-%d %H:%M'),
                            "Broken Swing Low": round(sl_val, 2),
                        }
                        
                        if not post_sl_idx:
                            if scan_state == "1":
                                setups.append({**setup_data, "Status": "MSS Done, Building Leg"})
                        else:
                            eq_50 = (sweep_high + post_sl_val) / 2
                            setup_data.update({
                                "Momentum Trough": round(post_sl_val, 2),
                                "50% Entry Level": round(eq_50, 2),
                            })
                            
                            confirm_pos = df_index.index(confirm_idx)
                            tracking_df = df.iloc[confirm_pos:]
                            touched_50 = not tracking_df[tracking_df['High'] >= eq_50].empty
                            
                            if not touched_50 and scan_state == "2":
                                setups.append({**setup_data, "Status": "Awaiting Entry", "Live CMP": round(cmp, 2), "Gap to 50%": round(((eq_50 - cmp)/cmp)*100, 2)})
                                
                            elif touched_50 and scan_state == "3":
                                setups.append({**setup_data, "Status": "Trade Open", "Live CMP": round(cmp, 2)})
                                
                            elif touched_50 and scan_state == "4":
                                entry_idx = tracking_df[tracking_df['High'] >= eq_50].index[0]
                                forward_df = df.loc[entry_idx:]
                                
                                outcome = "Open"
                                lowest_seen = eq_50
                                
                                for idx, row in forward_df.iterrows():
                                    if row['Low'] < lowest_seen: lowest_seen = row['Low']
                                    
                                    if row['High'] >= sweep_high:
                                        outcome = "SL Hit"
                                        break
                                    elif row['Low'] <= post_sl_val:
                                        outcome = "Target Hit (Successful)"
                                        break
                                
                                max_move = ((eq_50 - lowest_seen) / eq_50) * 100
                                setups.append({**setup_data, "Outcome": outcome, "Max Favorable Move (%)": round(max_move, 2)})

    return setups

def scan_ticker(ticker, timeframe, mss_limit, scan_state, target_date_str):
    try:
        t = yf.Ticker(ticker)
        
        if timeframe == "15 Minute":
            df = t.history(period="60d", interval="15m", auto_adjust=False)
            if df.empty: return None
            df.index = df.index.tz_convert('Asia/Kolkata').tz_localize(None) if df.index.tz else df.index.tz_localize(None)
            
            daily_df = df.resample('D').agg({'High':'max', 'Low':'min'}).dropna()
            target_date = pd.to_datetime(target_date_str).replace(hour=0, minute=0, second=0)
            
            if target_date not in daily_df.index: return None
            
            hist_daily = daily_df.loc[daily_df.index < target_date]
            if hist_daily.empty: return None
            
            pdl, pdh = hist_daily['Low'].iloc[-1], hist_daily['High'].iloc[-1]
            day_end = target_date + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
            
            # Passes full df for fractal searches, but isolates sweep window to exactly target_date
            res = evaluate_setup(df, pdh, pdl, mss_limit, scan_state, target_date, day_end)
            
        else: # Daily Timeframe
            df = t.history(period="2y", interval="1d", auto_adjust=False)
            if df.empty: return None
            df.index = df.index.tz_localize(None)
            
            monthly_df = df.resample('M').agg({'High':'max', 'Low':'min'}).dropna()
            target_date = pd.to_datetime(target_date_str)
            target_month_end = target_date + pd.offsets.MonthEnd(0)
            
            hist_monthly = monthly_df.loc[monthly_df.index < target_month_end]
            if hist_monthly.empty: return None
            
            pml, pmh = hist_monthly['Low'].iloc[-1], hist_monthly['High'].iloc[-1]
            target_month_start = target_date.replace(day=1)
            
            # Passes full df for cross-month fractal searches, but isolates sweep window to target month
            res = evaluate_setup(df, pmh, pml, mss_limit, scan_state, target_month_start, target_month_end)

        if res:
            for r in res: r['Symbol'] = ticker.replace('.NS', '')
            return res
        return None
    except:
        return None

# --- STREAMLIT UI ---
st.title("🎯 Ultimate ICT Precision Scanner")
st.markdown("Scans strictly for Untested Prior Swing Breaks, 50% Pullbacks, and No Opposite Touch Invalidation.")

with st.sidebar:
    st.header("⚙️ Scanner Configurations")
    timeframe = st.selectbox("Execution Timeframe", ["15 Minute", "Daily"])
    
    scan_state = st.selectbox(
        "Select Market State", 
        [
            "1. MSS done (Swing high not yet formed)", 
            "2. Awaiting entry (Price has not yet touched 50% line)", 
            "3. Trade open (Price has touched 50% line)", 
            "4. Previous reports (Backtest Mode)"
        ]
    )
    state_code = scan_state.split(".")[0]
    
    mss_limit = st.selectbox("Max Displacement Candles for MSS", list(range(1, 11)), index=6)
    
    st.divider()
    if state_code == "4":
        st.subheader("Backtest Settings")
        target_date = st.date_input("Select Historical Date", datetime.today() - timedelta(days=1))
    else:
        target_date = datetime.today()

if st.button("🚀 Execute Master Scan", type="primary"):
    with st.spinner(f"Scanning Nifty 500 | {timeframe} | State: {state_code}..."):
        tickers = get_nifty500_symbols()
        results = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
            futures = [executor.submit(scan_ticker, tick, timeframe, mss_limit, state_code, target_date.strftime('%Y-%m-%d')) for tick in tickers]
            for f in concurrent.futures.as_completed(futures):
                res = f.result()
                if res: results.extend(res)
                
        if not results:
            st.warning("No stocks matched these ultra-strict criteria for the selected date and state.")
        else:
            df_all = pd.DataFrame(results)
            df_bull = df_all[df_all['Direction'] == 'Bullish']
            df_bear = df_all[df_all['Direction'] == 'Bearish']
            
            tab1, tab2 = st.tabs(["🟢 Bullish Setups", "🔴 Bearish Setups"])
            
            with tab1:
                if df_bull.empty: st.info("No Bullish Setups.")
                else: st.dataframe(df_bull.drop(columns=['Direction']), use_container_width=True, hide_index=True)
                
            with tab2:
                if df_bear.empty: st.info("No Bearish Setups.")
                else: st.dataframe(df_bear.drop(columns=['Direction']), use_container_width=True, hide_index=True)
