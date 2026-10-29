import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import io
import concurrent.futures
from datetime import datetime, timedelta
import pytz
import numpy as np

st.set_page_config(page_title="Ultimate ICT Precision Scanner", layout="wide", page_icon="⚡")
ist = pytz.timezone('Asia/Kolkata')

@st.cache_data(ttl=86400)
def get_nifty500_symbols():
    url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
    }
    try:
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=headers, timeout=10)
        response = session.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            df = pd.read_csv(io.StringIO(response.text))
            return [str(symbol).strip() + '.NS' for symbol in df['Symbol']]
    except Exception as e:
        pass
    st.sidebar.error("⚠️ NSE Website blocked the Nifty 500 download. Showing Top 10 fallback stocks.")
    return ['RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'ICICIBANK.NS', 'INFY.NS', 'ITC.NS', 'SBIN.NS', 'BHARTIARTL.NS', 'BAJFINANCE.NS', 'KOTAKBANK.NS']

@st.cache_data(ttl=3600)
def get_valid_trading_dates():
    try:
        df = yf.Ticker('^NSEI').history(period="60d", interval="1d")
        if not df.empty:
            return [d.date() for d in df.index]
    except Exception:
        pass
    today = datetime.now(ist).date()
    dates = []
    for i in range(60):
        d = today - timedelta(days=i)
        if d.weekday() < 5:
            dates.append(d)
    return dates[::-1]

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

def get_dynamic_entry(df, sweep_idx, peak_idx, direction, anchor, peak):
    leg_df = df.loc[sweep_idx:peak_idx]
    range_size = abs(peak - anchor)
    
    if direction == 'Bullish':
        eq_50 = anchor + range_size * 0.5
        fib_618 = peak - range_size * 0.618
        
        fvg_tops = []
        for i in range(len(leg_df)-2):
            if leg_df['Low'].iloc[i+2] > leg_df['High'].iloc[i]:
                fvg_top = leg_df['Low'].iloc[i+2]
                if fvg_top <= eq_50:
                    fvg_tops.append(fvg_top)
                    
        if fvg_tops:
            return max(fvg_tops), "Discount FVG"
        else:
            return fib_618, "61.8% Fib"
            
    else:
        eq_50 = anchor - range_size * 0.5
        fib_618 = peak + range_size * 0.618
        
        fvg_bottoms = []
        for i in range(len(leg_df)-2):
            if leg_df['High'].iloc[i+2] < leg_df['Low'].iloc[i]:
                fvg_bot = leg_df['High'].iloc[i+2]
                if fvg_bot >= eq_50:
                    fvg_bottoms.append(fvg_bot)
                    
        if fvg_bottoms:
            return min(fvg_bottoms), "Premium FVG"
        else:
            return fib_618, "61.8% Fib"

def calculate_floating_pnl(direction, cmp, entry, stop_loss, risk_amt):
    risk_dist = abs(entry - stop_loss)
    if risk_dist == 0: return 0.0
    qty = risk_amt / risk_dist
    if direction == 'Bullish':
        return round(qty * (cmp - entry), 2)
    else:
        return round(qty * (entry - cmp), 2)

def evaluate_setup(df, htf_high, htf_low, mss_limit, scan_state, eval_start, eval_end, strict_opposite, entry_method, target_method, is_daily=False):
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
                            "MSS price (Breaker)": round(sh_val, 2),
                            "Entry Distance": "N/A"
                        }
                        
                        if not post_sh_idx:
                            if scan_state == "1":
                                setups.append(setup_data)
                        else:
                            if entry_method == "Breaker Block (Shallow Pullback)":
                                entry_price = sh_val
                                entry_type = "Breaker Block"
                                breaker_low = df.loc[sh_idx, 'Low']
                                active_sl = breaker_low * 0.99
                            else:
                                entry_price, entry_type = get_dynamic_entry(df, sweep_idx, post_sh_idx, 'Bullish', sweep_low, post_sh_val)
                                active_sl = sweep_low
                                
                            risk_dist = abs(entry_price - active_sl)
                            
                            if target_method == "Fixed 1:2 Risk-to-Reward":
                                active_target = entry_price + (2 * risk_dist)
                            else:
                                active_target = post_sh_val
                                
                            gap_pct = round(((cmp - entry_price)/cmp)*100, 2)
                            
                            setup_data.update({
                                "Entry Type": entry_type,
                                "Entry Level": round(entry_price, 2),
                                "Stop Loss": round(active_sl, 2),
                                "Target": round(active_target, 2),
                                "Entry Distance": f"{gap_pct}%"
                            })
                            
                            confirm_pos = df_index.index(confirm_idx)
                            tracking_df = df.iloc[confirm_pos:]
                            touched_entry = not tracking_df[tracking_df['Low'] <= entry_price].empty
                            
                            if not touched_entry and scan_state == "2":
                                setups.append(setup_data)
                                
                            elif touched_entry and scan_state == "3":
                                entry_idx = tracking_df[tracking_df['Low'] <= entry_price].index[0]
                                forward_df = df.loc[entry_idx:]
                                is_active = True
                                for idx, row in forward_df.iterrows():
                                    if row['Low'] <= active_sl or row['High'] >= active_target:
                                        is_active = False
                                        break
                                if is_active:
                                    setup_data["Entry Distance"] = "Touched (Active)"
                                    setup_data["Floating P&L (₹)"] = calculate_floating_pnl("Bullish", cmp, entry_price, active_sl, 1000)
                                    setups.append(setup_data)
                                    
                            elif touched_entry and scan_state == "4":
                                entry_idx = tracking_df[tracking_df['Low'] <= entry_price].index[0]
                                forward_df = df.loc[entry_idx:]
                                outcome, highest_seen = "Still Open", entry_price
                                for idx, row in forward_df.iterrows():
                                    if row['High'] > highest_seen: highest_seen = row['High']
                                    if row['Low'] <= active_sl:
                                        outcome = "SL Hit"
                                        break
                                    elif row['High'] >= active_target:
                                        outcome = "Target Hit"
                                        break
                                setup_data["Max Move (%)"] = f"{round(((highest_seen - entry_price) / entry_price) * 100, 2)}%"
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
                            "MSS price (Breaker)": round(sl_val, 2),
                            "Entry Distance": "N/A"
                        }
                        
                        if not post_sl_idx:
                            if scan_state == "1":
                                setups.append(setup_data)
                        else:
                            if entry_method == "Breaker Block (Shallow Pullback)":
                                entry_price = sl_val
                                entry_type = "Breaker Block"
                                breaker_high = df.loc[sl_idx, 'High']
                                active_sl = breaker_high * 1.01
                            else:
                                entry_price, entry_type = get_dynamic_entry(df, sweep_idx, post_sl_idx, 'Bearish', sweep_high, post_sl_val)
                                active_sl = sweep_high
                                
                            risk_dist = abs(entry_price - active_sl)
                            
                            if target_method == "Fixed 1:2 Risk-to-Reward":
                                active_target = entry_price - (2 * risk_dist)
                            else:
                                active_target = post_sl_val
                                
                            gap_pct = round(((entry_price - cmp)/cmp)*100, 2)
                            
                            setup_data.update({
                                "Entry Type": entry_type,
                                "Entry Level": round(entry_price, 2),
                                "Stop Loss": round(active_sl, 2),
                                "Target": round(active_target, 2),
                                "Entry Distance": f"{gap_pct}%"
                            })
                            
                            confirm_pos = df_index.index(confirm_idx)
                            tracking_df = df.iloc[confirm_pos:]
                            touched_entry = not tracking_df[tracking_df['High'] >= entry_price].empty
                            
                            if not touched_entry and scan_state == "2":
                                setups.append(setup_data)
                                
                            elif touched_entry and scan_state == "3":
                                entry_idx = tracking_df[tracking_df['High'] >= entry_price].index[0]
                                forward_df = df.loc[entry_idx:]
                                is_active = True
                                for idx, row in forward_df.iterrows():
                                    if row['High'] >= active_sl or row['Low'] <= active_target:
                                        is_active = False
                                        break
                                if is_active:
                                    setup_data["Entry Distance"] = "Touched (Active)"
                                    setup_data["Floating P&L (₹)"] = calculate_floating_pnl("Bearish", cmp, entry_price, active_sl, 1000)
                                    setups.append(setup_data)
                                    
                            elif touched_entry and scan_state == "4":
                                entry_idx = tracking_df[tracking_df['High'] >= entry_price].index[0]
                                forward_df = df.loc[entry_idx:]
                                outcome, lowest_seen = "Still Open", entry_price
                                for idx, row in forward_df.iterrows():
                                    if row['Low'] < lowest_seen: lowest_seen = row['Low']
                                    if row['High'] >= active_sl:
                                        outcome = "SL Hit"
                                        break
                                    elif row['Low'] <= active_target:
                                        outcome = "Target Hit"
                                        break
                                setup_data["Max Move (%)"] = f"{round(((entry_price - lowest_seen) / entry_price) * 100, 2)}%"
                                setup_data["Outcome"] = outcome
                                setups.append(setup_data)
    return setups

def scan_ticker(ticker, timeframe, mss_limit, scan_state, start_date_str, end_date_str, strict_opposite, entry_method, target_method):
    try:
        t = yf.Ticker(ticker)
        start_date = pd.to_datetime(start_date_str).replace(hour=0, minute=0, second=0)
        end_date = pd.to_datetime(end_date_str).replace(hour=23, minute=59, second=59)
        
        if timeframe in ["75 Minute", "125 Minute"]:
            daily_htf = t.history(period="1y", interval="1d", auto_adjust=False)
            df_5m = t.history(period="60d", interval="5m", auto_adjust=False)
            
            if df_5m.empty or daily_htf.empty: return None
            
            # Resample 5m to 75m or 125m exactly matching NSE hours (375 mins/day)
            chunk_size = 15 if timeframe == "75 Minute" else 25
            resampled = []
            for date, group in df_5m.groupby(df_5m.index.date):
                for i in range(0, len(group), chunk_size):
                    chunk = group.iloc[i:i+chunk_size]
                    if len(chunk) > 0:
                        resampled.append({
                            'Datetime': chunk.index[-1],
                            'Open': chunk['Open'].iloc[0],
                            'High': chunk['High'].max(),
                            'Low': chunk['Low'].min(),
                            'Close': chunk['Close'].iloc[-1],
                        })
                        
            df = pd.DataFrame(resampled).set_index('Datetime')
            df.index = df.index.tz_convert('Asia/Kolkata').tz_localize(None) if df.index.tz else df.index.tz_localize(None)
            daily_htf.index = daily_htf.index.tz_localize(None)
            
            # Create Weekly HTF for Previous Week High/Low sweeps
            weekly_hist = daily_htf.resample('W-MON', closed='left', label='left').agg({'High':'max', 'Low':'min'}).dropna()
            
            if scan_state != "4":
                current_monday = start_date - pd.Timedelta(days=start_date.weekday())
                past_htf = weekly_hist.loc[weekly_hist.index < current_monday]
                if len(past_htf) < 1: return None
                
                pwl, pwh = past_htf['Low'].iloc[-1], past_htf['High'].iloc[-1]
                week_end = current_monday + pd.Timedelta(days=6, hours=23, minutes=59)
                
                res = evaluate_setup(df, pwh, pwl, mss_limit, scan_state, current_monday, week_end, strict_opposite, entry_method, target_method, is_daily=False)
                
            else:
                start_monday = start_date - pd.Timedelta(days=start_date.weekday())
                weeks = pd.date_range(start=start_monday, end=end_date, freq='W-MON')
                if start_monday not in weeks:
                    weeks = weeks.insert(0, start_monday)
                    
                res = []
                for w_start in weeks:
                    past_htf = weekly_hist.loc[weekly_hist.index < w_start]
                    if past_htf.empty: continue
                    pwl, pwh = past_htf['Low'].iloc[-1], past_htf['High'].iloc[-1]
                    w_end = w_start + pd.Timedelta(days=6, hours=23, minutes=59)
                    
                    r_week = evaluate_setup(df, pwh, pwl, mss_limit, scan_state, w_start, w_end, strict_opposite, entry_method, target_method, is_daily=False)
                    if r_week: res.extend(r_week)
                    
        elif timeframe == "15 Minute":
            daily_htf = t.history(period="1y", interval="1d", auto_adjust=False)
            df = t.history(period="60d", interval="15m", auto_adjust=False)
            
            if df.empty or daily_htf.empty: return None
            df.index = df.index.tz_convert('Asia/Kolkata').tz_localize(None) if df.index.tz else df.index.tz_localize(None)
            daily_htf.index = daily_htf.index.tz_localize(None)
            
            available_dates = pd.Series(df.index.date).drop_duplicates().apply(lambda x: pd.to_datetime(x))
            
            if scan_state != "4":
                if start_date not in available_dates.values:
                    start_date = available_dates.iloc[-1] 
                
                past_htf = daily_htf.loc[daily_htf.index < start_date]
                if len(past_htf) < 1: return None
                
                pdl_today, pdh_today = past_htf['Low'].iloc[-1], past_htf['High'].iloc[-1]
                day_end = start_date + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
                
                res = evaluate_setup(df, pdh_today, pdl_today, mss_limit, scan_state, start_date, day_end, strict_opposite, entry_method, target_method, is_daily=False)
                
            else: 
                days_in_range = available_dates[(available_dates >= start_date) & (available_dates <= end_date)]
                res = []
                for d in days_in_range:
                    past_htf = daily_htf.loc[daily_htf.index < d]
                    if len(past_htf) < 1: continue
                    
                    pdl_today, pdh_today = past_htf['Low'].iloc[-1], past_htf['High'].iloc[-1]
                    day_end = d + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
                    
                    r_today = evaluate_setup(df, pdh_today, pdl_today, mss_limit, scan_state, d, day_end, strict_opposite, entry_method, target_method, is_daily=False)
                    if r_today: res.extend(r_today)
                
        else: 
            df = t.history(period="2y", interval="1d", auto_adjust=False)
            if df.empty: return None
            df.index = df.index.tz_localize(None)
            monthly_hist = df.resample('ME').agg({'High':'max', 'Low':'min'}).dropna()
            
            if scan_state != "4":
                target_month_start = start_date.replace(day=1)
                target_month_end = target_month_start + pd.offsets.MonthEnd(0)
                
                hist_df = monthly_hist.loc[monthly_hist.index < target_month_start]
                if hist_df.empty: return None
                pml, pmh = hist_df['Low'].iloc[-1], hist_df['High'].iloc[-1]
                
                res = evaluate_setup(df, pmh, pml, mss_limit, scan_state, target_month_start, target_month_end, strict_opposite, entry_method, target_method, is_daily=True)
            else:
                months_in_range = pd.date_range(start=start_date.replace(day=1), end=end_date, freq='MS')
                res = []
                for m_start in months_in_range:
                    m_end = m_start + pd.offsets.MonthEnd(0)
                    hist_df = monthly_hist.loc[monthly_hist.index < m_start]
                    if hist_df.empty: continue
                    pml, pmh = hist_df['Low'].iloc[-1], hist_df['High'].iloc[-1]
                    
                    r_month = evaluate_setup(df, pmh, pml, mss_limit, scan_state, m_start, m_end, strict_opposite, entry_method, target_method, is_daily=True)
                    if r_month: res.extend(r_month)

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
    timeframe = st.selectbox("Execution Timeframe", ["15 Minute", "75 Minute", "125 Minute", "Daily"])
    
    scan_state = st.selectbox(
        "Select Market State", 
        [
            "1. MSS done (Swing high not yet formed)", 
            "2. Awaiting entry (Price has not touched Entry Level)", 
            "3. Trade open (Price has touched Entry, SL/Target not hit)", 
            "4. Previous reports (Date Range Backtest Mode)"
        ]
    )
    state_code = scan_state.split(".")[0]
    
    entry_method = st.selectbox(
        "Entry Trigger Logic",
        ["Dynamic Discount (FVG / 61.8%)", "Breaker Block (Shallow Pullback)"],
        help="Dynamic Discount targets standard 50%-61.8% equilibrium. Breaker Block uses the fractured structural swing for high-momentum shallow retests."
    )
    
    target_method = st.selectbox(
        "Target Strategy",
        ["Structural Anchor (Momentum Peak)", "Fixed 1:2 Risk-to-Reward"],
        help="Structural Anchor maps the TP to the original Post-MSS swing. 1:2 RR sets an exact multiplier based on your Stop Loss distance."
    )
    
    mss_options = list(range(1, 16)) if timeframe == "Daily" else list(range(1, 11))
    mss_limit = st.selectbox("Max Displacement Candles for MSS", mss_options, index=6)
    
    strict_opposite = st.checkbox("Reject if Opposite Liquidity Touched", value=False)
    
    st.divider()
    if state_code == "4":
        st.subheader("Backtest Date Range")
        today = pd.to_datetime(datetime.now(ist).date())
        
        if timeframe in ["15 Minute", "75 Minute", "125 Minute"]:
            st.caption(f"Note: {timeframe} historical data is restricted to the last 60 trading days.")
            valid_dates = get_valid_trading_dates()
            valid_dates_rev = list(reversed(valid_dates))
            
            if valid_dates_rev:
                from_date_str = st.selectbox("From Date", valid_dates_rev, index=len(valid_dates_rev)-1, format_func=lambda x: x.strftime('%d %b %Y'))
                to_date_str = st.selectbox("To Date", valid_dates_rev, index=0, format_func=lambda x: x.strftime('%d %b %Y'))
                start_date = pd.to_datetime(from_date_str)
                end_date = pd.to_datetime(to_date_str)
            else:
                st.error("Failed to load trading calendar.")
                start_date, end_date = today, today
        else:
            month_opts = [(today - pd.DateOffset(months=i)).strftime('%Y-%m-01') for i in range(24)]
            from_month_str = st.selectbox("From Month", reversed(month_opts), format_func=lambda x: pd.to_datetime(x).strftime('%B %Y'))
            to_month_str = st.selectbox("To Month", month_opts, format_func=lambda x: pd.to_datetime(x).strftime('%B %Y'))
            start_date = pd.to_datetime(from_month_str)
            end_date = pd.to_datetime(to_month_str) + pd.offsets.MonthEnd(0)
        
        risk_per_trade = st.number_input("Risk per Trade (₹)", min_value=100, value=1000, step=100)
    else:
        start_date = pd.to_datetime(datetime.now(ist).date())
        end_date = start_date

if st.button("🚀 Execute Master Scan", type="primary"):
    if state_code == "4" and start_date > end_date:
        st.error("Error: 'From Date' must be earlier than or equal to 'To Date'.")
    else:
        with st.spinner(f"Scanning Nifty 500 | {timeframe} | State: {state_code}..."):
            tickers = get_nifty500_symbols()
            results = []
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
                futures = [executor.submit(scan_ticker, tick, timeframe, mss_limit, state_code, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'), strict_opposite, entry_method, target_method) for tick in tickers]
                for f in concurrent.futures.as_completed(futures):
                    res = f.result()
                    if res: results.extend(res)
                    
            if not results:
                st.warning("No stocks matched these criteria. (Try unchecking 'Reject if Opposite Liquidity Touched' or expanding the date range).")
            else:
                df_all = pd.DataFrame(results)
                
                if state_code == "4":
                    def calculate_pnl(row):
                        risk = risk_per_trade
                        risk_dist = abs(row['Entry Level'] - row['Stop Loss'])
                        if risk_dist == 0: return 0
                        qty = risk / risk_dist
                        reward_dist = abs(row['Target'] - row['Entry Level'])
                        reward_ratio = reward_dist / risk_dist
                        
                        if row['Outcome'] == 'Target Hit':
                            return risk * reward_ratio
                        elif row['Outcome'] == 'SL Hit':
                            return -risk
                        else: 
                            if row['Direction'] == 'Bullish':
                                return qty * (row['CMP'] - row['Entry Level'])
                            else:
                                return qty * (row['Entry Level'] - row['CMP'])
                                
                    df_all['Trade P&L (₹)'] = df_all.apply(calculate_pnl, axis=1).round(2)
                
                df_bull = df_all[df_all['Direction'] == 'Bullish']
                df_bear = df_all[df_all['Direction'] == 'Bearish']
                
                tab1, tab2 = st.tabs(["🟢 Bullish Setups", "🔴 Bearish Setups"])
                
                def render_tab_content(df, title):
                    if df.empty:
                        st.info(f"No {title} Setups.")
                    else:
                        if state_code == "4":
                            total_pnl = df['Trade P&L (₹)'].sum()
                            wins = len(df[df['Outcome'] == 'Target Hit'])
                            losses = len(df[df['Outcome'] == 'SL Hit'])
                            open_t = len(df[df['Outcome'] == 'Still Open'])
                            win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
                            
                            st.subheader(f"📊 {title} Backtest Results (Risk: ₹{risk_per_trade}/trade)")
                            c1, c2, c3, c4 = st.columns(4)
                            c1.metric("Total Range P&L", f"₹ {total_pnl:,.2f}")
                            c2.metric("Win Rate (Closed)", f"{win_rate:.1f}%")
                            c3.metric("Closed Trades", f"{wins}W / {losses}L")
                            c4.metric("Open Floating Trades", open_t)
                            st.divider()
                            
                        st.dataframe(df.drop(columns=['Direction']), use_container_width=True, hide_index=True)

                with tab1:
                    render_tab_content(df_bull, "Bullish")
                    
                with tab2:
                    render_tab_content(df_bear, "Bearish")
