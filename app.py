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
    try:
        loc = df.index.get_loc(current_idx)
        for i in range(loc - 1, 1, -1):
            if direction == 'high':
                if df['High'].iloc[i] > df['High'].iloc[i-1] and df['High'].iloc[i] > df['High'].iloc[i+1]:
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
    try:
        loc = df.index.get_loc(mss_idx)
        for i in range(loc, len(df)-1):
            if direction == 'high':
                if df['High'].iloc[i] > df['High'].iloc[i-1] and df['High'].iloc[i] > df['High'].iloc[i+1]:
                    return df.index[i], df['High'].iloc[i], df.index[i+1]
            else:
                if df['Low'].iloc[i] < df['Low'].iloc[i-1] and df['Low'].iloc[i] < df['Low'].iloc[i+1]:
                    return df.index[i], df['Low'].iloc[i], df.index[i+1]
        return None, None, None
    except:
        return None, None, None

def evaluate_setup(df, htf_high, htf_low, mss_limit, scan_state, eval_start, eval_end, strict_opposite, is_daily=False):
    setups = []
    df_index = df.index.tolist()
    cmp = df['Close'].iloc[-1]
    
    window_df = df.loc[(df.index >= eval_start) & (df.index <= eval_end)]
    if window_df.empty: return setups
    
    time_fmt = '%Y-%m-%d' if is_daily else '%Y-%m-%d %H:%M'

    # --- BULLISH LOGIC ---
    bull_sweeps = window_df[window_df['Low'] <= htf_low]
    if not bull_sweeps.empty:
        sweep_idx = bull_sweeps.index[0] 
        sweep_pos = df_index.index(sweep_idx) 
        sweep_low = df.loc[sweep_idx, 'Low']
        
        post_sweep_df = window_df.loc[sweep_idx:]
        
        if not strict_opposite or post_sweep_df['High'].max() < htf_high:
            sh_idx, sh_val = get_recent_swing(df, sweep_idx, 'high')
            if sh_idx:
                mss_cands = post_sweep_df[post_sweep_df['Close'] > sh_val]
                if not mss_cands.empty:
                    mss_idx = mss_cands.index[0]
                    mss_pos = df_index.index(mss_idx)
                    mss_count = mss_pos - sweep_pos
                    
                    if 0 < mss_count <= mss_limit:
                        post_sh_idx, post_sh_val, confirm_idx = get_post_mss_swing(df, mss_idx, 'high')
                        
                        setup_data = {
                            "Direction": "Bullish",
                            "Stock name": None, 
                            "CMP": round(cmp, 2),
                            "Liq. Sweep time": sweep_idx.strftime(time_fmt),
                            "MSS time": mss_idx.strftime(time_fmt),
                            "MSS candles": mss_count,
                            "MSS price": round(sh_val, 2),
                            "50% distance": "N/A"
                        }
                        
                        if not post_sh_idx:
                            if scan_state == "1":
                                setups.append(setup_data)
                        else:
                            eq_50 = (sweep_low + post_sh_val) / 2
                            gap_pct = round(((cmp - eq_50)/cmp)*100, 2)
                            setup_data["50% distance"] = f"{gap_pct}%"
                            
                            confirm_pos = df_index.index(confirm_idx)
                            tracking_df = df.iloc[confirm_pos:]
                            touched_50 = not tracking_df[tracking_df['Low'] <= eq_50].empty
                            
                            if not touched_50 and scan_state == "2":
                                setups.append(setup_data)
                                
                            elif touched_50 and scan_state == "3":
                                entry_idx = tracking_df[tracking_df['Low'] <= eq_50].index[0]
                                forward_df = df.loc[entry_idx:]
                                is_active = True
                                for idx, row in forward_df.iterrows():
                                    if row['Low'] <= sweep_low or row['High'] >= post_sh_val:
                                        is_active = False # Hit SL or Target
                                        break
                                if is_active:
                                    setup_data["50% distance"] = "Touched (Active)"
                                    setups.append(setup_data)
                                    
                            elif touched_50 and scan_state == "4":
                                entry_idx = tracking_df[tracking_df['Low'] <= eq_50].index[0]
                                forward_df = df.loc[entry_idx:]
                                outcome, highest_seen = "Still Open", eq_50
                                for idx, row in forward_df.iterrows():
                                    if row['High'] > highest_seen: highest_seen = row['High']
                                    if row['Low'] <= sweep_low:
                                        outcome = "SL Hit"
                                        break
                                    elif row['High'] >= post_sh_val:
                                        outcome = "Target Hit"
                                        break
                                setup_data["Max Move (%)"] = f"{round(((highest_seen - eq_50) / eq_50) * 100, 2)}%"
                                setup_data["Outcome"] = outcome
                                setups.append(setup_data)

    # --- BEARISH LOGIC ---
    bear_sweeps = window_df[window_df['High'] >= htf_high]
    if not bear_sweeps.empty:
        sweep_idx = bear_sweeps.index[0] 
        sweep_pos = df_index.index(sweep_idx)
        sweep_high = df.loc[sweep_idx, 'High']
        
        post_sweep_df = window_df.loc[sweep_idx:]
        
        if not strict_opposite or post_sweep_df['Low'].min() > htf_low:
            sl_idx, sl_val = get_recent_swing(df, sweep_idx, 'low')
            if sl_idx:
                mss_cands = post_sweep_df[post_sweep_df['Close'] < sl_val]
                if not mss_cands.empty:
                    mss_idx = mss_cands.index[0]
                    mss_pos = df_index.index(mss_idx)
                    mss_count = mss_pos - sweep_pos
                    
                    if 0 < mss_count <= mss_limit:
                        post_sl_idx, post_sl_val, confirm_idx = get_post_mss_swing(df, mss_idx, 'low')
                        
                        setup_data = {
                            "Direction": "Bearish",
                            "Stock name": None,
                            "CMP": round(cmp, 2),
                            "Liq. Sweep time": sweep_idx.strftime(time_fmt),
                            "MSS time": mss_idx.strftime(time_fmt),
                            "MSS candles": mss_count,
                            "MSS price": round(sl_val, 2),
                            "50% distance": "N/A"
                        }
                        
                        if not post_sl_idx:
                            if scan_state == "1":
                                setups.append(setup_data)
                        else:
                            eq_50 = (sweep_high + post_sl_val) / 2
                            gap_pct = round(((eq_50 - cmp)/cmp)*100, 2)
                            setup_data["50% distance"] = f"{gap_pct}%"
                            
                            confirm_pos = df_index.index(confirm_idx)
                            tracking_df = df.iloc[confirm_pos:]
                            touched_50 = not tracking_df[tracking_df['High'] >= eq_50].empty
                            
                            if not touched_50 and scan_state == "2":
                                setups.append(setup_data)
                                
                            elif touched_50 and scan_state == "3":
                                entry_idx = tracking_df[tracking_df['High'] >= eq_50].index[0]
                                forward_df = df.loc[entry_idx:]
                                is_active = True
                                for idx, row in forward_df.iterrows():
                                    if row['High'] >= sweep_high or row['Low'] <= post_sl_val:
                                        is_active = False # Hit SL or Target
                                        break
                                if is_active:
                                    setup_data["50% distance"] = "Touched (Active)"
                                    setups.append(setup_data)
                                    
                            elif touched_50 and scan_state == "4":
                                entry_idx = tracking_df[tracking_df['High'] >= eq_50].index[0]
                                forward_df = df.loc[entry_idx:]
                                outcome, lowest_seen = "Still Open", eq_50
                                for idx, row in forward_df.iterrows():
                                    if row['Low'] < lowest_seen: lowest_seen = row['Low']
                                    if row['High'] >= sweep_high:
                                        outcome = "SL Hit"
                                        break
                                    elif row['Low'] <= post_sl_val:
                                        outcome = "Target Hit"
                                        break
                                setup_data["Max Move (%)"] = f"{round(((eq_50 - lowest_seen) / eq_50) * 100, 2)}%"
                                setup_data["Outcome"] = outcome
                                setups.append(setup_data)
    return setups

def scan_ticker(ticker, timeframe, mss_limit, scan_state, target_date_str, strict_opposite):
    try:
        t = yf.Ticker(ticker)
        target_date = pd.to_datetime(target_date_str).replace(hour=0, minute=0, second=0)
        
        if timeframe == "15 Minute":
            df = t.history(period="60d", interval="15m", auto_adjust=False)
            if df.empty: return None
            df.index = df.index.tz_convert('Asia/Kolkata').tz_localize(None) if df.index.tz else df.index.tz_localize(None)
            
            daily_df = df.resample('D').agg({'High':'max', 'Low':'min'}).dropna()
            
            # Normal Scanning (States 1, 2, 3)
            if scan_state != "4":
                if target_date not in daily_df.index: return None
                past_days = daily_df.loc[daily_df.index < target_date]
                if len(past_days) < 2: return None
                
                t_minus_1 = past_days.index[-1]
                pdl_today, pdh_today = past_days['Low'].iloc[-1], past_days['High'].iloc[-1]
                pdl_yest, pdh_yest = past_days['Low'].iloc[-2], past_days['High'].iloc[-2]
                
                day_end = target_date + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
                
                res_today = evaluate_setup(df, pdh_today, pdl_today, mss_limit, scan_state, target_date, day_end, strict_opposite, is_daily=False)
                eval_start_yest = t_minus_1 + pd.Timedelta(hours=12)
                res_yest = evaluate_setup(df, pdh_yest, pdl_yest, mss_limit, scan_state, eval_start_yest, day_end, strict_opposite, is_daily=False)
                
                valid_res_yest = [r for r in (res_yest or []) if pd.to_datetime(r["Liq. Sweep time"]) < target_date]
                res = (res_today or []) + valid_res_yest

            # Backtest Scanning (State 4) - Loops through the selected month
            else:
                month_start = target_date.replace(day=1)
                month_end = month_start + pd.offsets.MonthEnd(0)
                days_in_month = daily_df.loc[(daily_df.index >= month_start) & (daily_df.index <= month_end)].index
                
                all_res = []
                for d in days_in_month:
                    past_days = daily_df.loc[daily_df.index < d]
                    if len(past_days) < 2: continue
                    t_minus_1 = past_days.index[-1]
                    pdl_today, pdh_today = past_days['Low'].iloc[-1], past_days['High'].iloc[-1]
                    pdl_yest, pdh_yest = past_days['Low'].iloc[-2], past_days['High'].iloc[-2]
                    day_end = d + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
                    
                    r_today = evaluate_setup(df, pdh_today, pdl_today, mss_limit, scan_state, d, day_end, strict_opposite, is_daily=False)
                    e_start_yest = t_minus_1 + pd.Timedelta(hours=12)
                    r_yest = evaluate_setup(df, pdh_yest, pdl_yest, mss_limit, scan_state, e_start_yest, day_end, strict_opposite, is_daily=False)
                    
                    v_res_yest = [r for r in (r_yest or []) if pd.to_datetime(r["Liq. Sweep time"]) < d]
                    if r_today: all_res.extend(r_today)
                    all_res.extend(v_res_yest)
                res = all_res
                
        else: # Daily Timeframe
            df = t.history(period="2y", interval="1d", auto_adjust=False)
            if df.empty: return None
            df.index = df.index.tz_localize(None)
            
            target_month_start = target_date.replace(day=1)
            hist_df = df.loc[df.index < target_month_start]
            if hist_df.empty: return None
            
            monthly_hist = hist_df.resample('ME').agg({'High':'max', 'Low':'min'}).dropna()
            if monthly_hist.empty: return None
            
            pml, pmh = monthly_hist['Low'].iloc[-1], monthly_hist['High'].iloc[-1]
            target_month_end = target_date + pd.offsets.MonthEnd(0)
            
            res = evaluate_setup(df, pmh, pml, mss_limit, scan_state, target_month_start, target_month_end, strict_opposite, is_daily=True)

        if res:
            for r in res: r['Stock name'] = ticker.replace('.NS', '')
            return res
        return None
    except:
        return None

# --- STREAMLIT UI ---
st.title("🎯 Ultimate ICT Precision Scanner")

with st.sidebar:
    st.header("⚙️ Scanner Configurations")
    timeframe = st.selectbox("Execution Timeframe", ["15 Minute", "Daily"])
    
    scan_state = st.selectbox(
        "Select Market State", 
        [
            "1. MSS done (Swing high not yet formed)", 
            "2. Awaiting entry (Price has not yet touched 50% line)", 
            "3. Trade open (Price has touched 50% line, SL/Target not hit)", 
            "4. Previous reports (Monthly Backtest Mode)"
        ]
    )
    state_code = scan_state.split(".")[0]
    
    mss_options = list(range(1, 16)) if timeframe == "Daily" else list(range(1, 11))
    mss_limit = st.selectbox("Max Displacement Candles for MSS", mss_options, index=6)
    
    strict_opposite = st.checkbox("Reject if Opposite Liquidity Touched", value=False, help="Uncheck this to allow 'Outside Days/Months' (e.g., sweeps PDL/PML then rallies through PDH/PMH). Leave checked for strict rejection.")
    
    st.divider()
    if state_code == "4":
        st.subheader("Backtest Settings")
        today = pd.Timestamp.today()
        month_opts = [(today - pd.DateOffset(months=i)).strftime('%Y-%m-01') for i in (range(2) if timeframe == "15 Minute" else range(24))]
        sel_month_str = st.selectbox("Select Backtest Month", month_opts, format_func=lambda x: pd.to_datetime(x).strftime('%B %Y'))
        target_date = pd.to_datetime(sel_month_str)
    else:
        target_date = datetime.today()

if st.button("🚀 Execute Master Scan", type="primary"):
    with st.spinner(f"Scanning Nifty 500 | {timeframe} | State: {state_code}..."):
        tickers = get_nifty500_symbols()
        results = []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
            futures = [executor.submit(scan_ticker, tick, timeframe, mss_limit, state_code, target_date.strftime('%Y-%m-%d'), strict_opposite) for tick in tickers]
            for f in concurrent.futures.as_completed(futures):
                res = f.result()
                if res: results.extend(res)
                
        if not results:
            st.warning("No stocks matched these criteria for the selected state.")
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
