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
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
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
    st.sidebar.error("⚠️ NSE Website blocked download. Showing Top 10 fallback stocks.")
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
    return [today - timedelta(days=i) for i in range(60) if (today - timedelta(days=i)).weekday() < 5][::-1]

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

def calculate_floating_pnl(direction, cmp, entry, stop_loss, risk_amt):
    risk_dist = abs(entry - stop_loss)
    if risk_dist == 0: return 0.0
    qty = risk_amt / risk_dist
    return round(qty * (cmp - entry), 2) if direction == 'Bullish' else round(qty * (entry - cmp), 2)

# --- 15M SUPPLY/DEMAND ZONE GENERATOR ---
def find_sd_zone(df_15m, sweep_time, mss_time, mss_price, direction):
    """Identifies Base + Leg-out candles between sweep and MSS line"""
    try:
        leg_df = df_15m.loc[sweep_time:mss_time]
        if len(leg_df) < 2: return None, None, 0
        
        # Calculate body vs range for each candle
        leg_df = leg_df.copy()
        leg_df['Body'] = abs(leg_df['Open'] - leg_df['Close'])
        leg_df['Range'] = leg_df['High'] - leg_df['Low']
        leg_df['Is_Base'] = (leg_df['Body'] / leg_df['Range'].replace(0, 0.001)) < 0.5
        
        base_candles = leg_df[leg_df['Is_Base']]
        if base_candles.empty:
            # Fallback to the absolute origin candle if no clear base is formed
            base_candles = leg_df.iloc[0:1]
            
        if direction == 'Bullish':
            distal = base_candles['Low'].min()
            proximal = base_candles['High'].max()
            
            # Count Leg-out: large green candles crossing the MSS
            post_base = leg_df.loc[base_candles.index[-1]:]
            legout_count = len(post_base[(post_base['Close'] > post_base['Open']) & (~post_base['Is_Base'])])
            
        else:
            distal = base_candles['High'].max()
            proximal = base_candles['Low'].min()
            
            post_base = leg_df.loc[base_candles.index[-1]:]
            legout_count = len(post_base[(post_base['Close'] < post_base['Open']) & (~post_base['Is_Base'])])
            
        return proximal, distal, legout_count
    except:
        return None, None, 0

# --- ADVANCED MULTI-TIMEFRAME EVALUATOR ---
def evaluate_mtf_setup(df_15m, df_75m, htf_high, htf_low, mss_limit, scan_state, eval_start, eval_end, strict_opposite, target_method):
    setups = []
    df_15m_index = df_15m.index.tolist()
    cmp = df_15m['Close'].iloc[-1]
    
    # Filter working window
    window_75m = df_75m.loc[(df_75m.index >= eval_start) & (df_75m.index <= eval_end)]
    if window_75m.empty: return setups
    
    time_fmt = '%Y-%m-%d %H:%M'

    # --- BULLISH LOGIC ---
    bull_sweeps = window_75m[window_75m['Low'] <= htf_low]
    if not bull_sweeps.empty:
        sweep_idx_75m = bull_sweeps.index[0]
        sweep_low = window_75m.loc[sweep_idx_75m, 'Low']
        post_sweep_75m = window_75m.loc[sweep_idx_75m:]
        
        if not strict_opposite or post_sweep_75m['High'].max() < htf_high:
            # 1. Find 75m MSS Swing
            sh_idx_75m, sh_val_75m = get_recent_swing(df_75m, sweep_idx_75m, 'high') 
            
            if sh_idx_75m:
                # 2. Check for 75m Close Above MSS Line
                mss_cands = post_sweep_75m[post_sweep_75m['Close'] > sh_val_75m]
                
                if not mss_cands.empty:
                    mss_idx_75m = mss_cands.index[0]
                    
                    # 3. Drop to 15m to find the precise base and legout near MSS
                    # We map 75m indexes to the closest 15m equivalent
                    proximal, distal, legout_count = find_sd_zone(df_15m, sweep_idx_75m, mss_idx_75m, sh_val_75m, 'Bullish')
                    
                    if proximal and distal:
                        # 4. Target Mapping (15m Swing High)
                        target_idx, target_val, _ = get_post_mss_swing(df_15m, mss_idx_75m, 'high')
                        
                        if target_val:
                            entry_price = proximal
                            active_sl = distal * 0.999 # Distal line SL
                            risk_dist = abs(entry_price - active_sl)
                            active_target = entry_price + (2 * risk_dist) if target_method == "Fixed 1:2 Risk-to-Reward" else target_val
                            gap_pct = round(((cmp - entry_price)/cmp)*100, 2)
                            
                            setup_data = {
                                "Direction": "Bullish",
                                "Stock name": None, 
                                "CMP": round(cmp, 2),
                                "Sweep Time (75m)": sweep_idx_75m.strftime(time_fmt),
                                "MSS Line (75m)": round(sh_val_75m, 2),
                                "15m Leg-out Candles": legout_count,
                                "Entry Level (Proximal)": round(entry_price, 2),
                                "Stop Loss (Distal)": round(active_sl, 2),
                                "Target (15m Swing)": round(active_target, 2),
                                "Entry Distance": f"{gap_pct}%"
                            }
                            
                            # Forward Tracking
                            tracking_df = df_15m.loc[mss_idx_75m:]
                            touched_entry = not tracking_df[tracking_df['Low'] <= entry_price].empty
                            
                            if not touched_entry and scan_state == "2":
                                setups.append(setup_data)
                                
                            elif touched_entry and scan_state == "3":
                                entry_idx = tracking_df[tracking_df['Low'] <= entry_price].index[0]
                                forward_df = df_15m.loc[entry_idx:]
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
                                forward_df = df_15m.loc[entry_idx:]
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
    bear_sweeps = window_75m[window_75m['High'] >= htf_high]
    if not bear_sweeps.empty:
        sweep_idx_75m = bear_sweeps.index[0]
        sweep_high = window_75m.loc[sweep_idx_75m, 'High']
        post_sweep_75m = window_75m.loc[sweep_idx_75m:]
        
        if not strict_opposite or post_sweep_75m['Low'].min() > htf_low:
            sh_idx_75m, sl_val_75m = get_recent_swing(df_75m, sweep_idx_75m, 'low') 
            
            if sh_idx_75m:
                mss_cands = post_sweep_75m[post_sweep_75m['Close'] < sl_val_75m]
                
                if not mss_cands.empty:
                    mss_idx_75m = mss_cands.index[0]
                    
                    proximal, distal, legout_count = find_sd_zone(df_15m, sweep_idx_75m, mss_idx_75m, sl_val_75m, 'Bearish')
                    
                    if proximal and distal:
                        target_idx, target_val, _ = get_post_mss_swing(df_15m, mss_idx_75m, 'low')
                        
                        if target_val:
                            entry_price = proximal
                            active_sl = distal * 1.001 
                            risk_dist = abs(entry_price - active_sl)
                            active_target = entry_price - (2 * risk_dist) if target_method == "Fixed 1:2 Risk-to-Reward" else target_val
                            gap_pct = round(((entry_price - cmp)/cmp)*100, 2)
                            
                            setup_data = {
                                "Direction": "Bearish",
                                "Stock name": None, 
                                "CMP": round(cmp, 2),
                                "Sweep Time (75m)": sweep_idx_75m.strftime(time_fmt),
                                "MSS Line (75m)": round(sl_val_75m, 2),
                                "15m Leg-out Candles": legout_count,
                                "Entry Level (Proximal)": round(entry_price, 2),
                                "Stop Loss (Distal)": round(active_sl, 2),
                                "Target (15m Swing)": round(active_target, 2),
                                "Entry Distance": f"{gap_pct}%"
                            }
                            
                            tracking_df = df_15m.loc[mss_idx_75m:]
                            touched_entry = not tracking_df[tracking_df['High'] >= entry_price].empty
                            
                            if not touched_entry and scan_state == "2":
                                setups.append(setup_data)
                                
                            elif touched_entry and scan_state == "3":
                                entry_idx = tracking_df[tracking_df['High'] >= entry_price].index[0]
                                forward_df = df_15m.loc[entry_idx:]
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
                                forward_df = df_15m.loc[entry_idx:]
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


def scan_ticker(ticker, sweep_type, mss_limit, scan_state, start_date_str, end_date_str, strict_opposite, target_method):
    try:
        t = yf.Ticker(ticker)
        start_date = pd.to_datetime(start_date_str).replace(hour=0, minute=0, second=0)
        end_date = pd.to_datetime(end_date_str).replace(hour=23, minute=59, second=59)
        
        # 1. Fetch multi-timeframe base data
        df_15m = t.history(period="60d", interval="15m", auto_adjust=False)
        daily_htf = t.history(period="2y", interval="1d", auto_adjust=False)
        
        if df_15m.empty or daily_htf.empty: return None
        df_15m.index = df_15m.index.tz_convert('Asia/Kolkata').tz_localize(None) if df_15m.index.tz else df_15m.index.tz_localize(None)
        daily_htf.index = daily_htf.index.tz_localize(None)
        
        # 2. Resample 15m to exact 75m Indian Market chunks
        resampled_75m = []
        for date, group in df_15m.groupby(df_15m.index.date):
            for i in range(0, len(group), 5): # 5 candles of 15m = 75m
                chunk = group.iloc[i:i+5]
                if len(chunk) > 0:
                    resampled_75m.append({
                        'Datetime': chunk.index[-1],
                        'Open': chunk['Open'].iloc[0], 'High': chunk['High'].max(),
                        'Low': chunk['Low'].min(), 'Close': chunk['Close'].iloc[-1],
                    })
        df_75m = pd.DataFrame(resampled_75m).set_index('Datetime')
        
        # 3. Create Weekly HTF
        weekly_hist = daily_htf.resample('W-MON', closed='left', label='left').agg({'High':'max', 'Low':'min'}).dropna()
        
        available_dates = pd.Series(df_15m.index.date).drop_duplicates().apply(lambda x: pd.to_datetime(x))
        days_in_range = available_dates[(available_dates >= start_date) & (available_dates <= end_date)]
        
        res = []
        for d in days_in_range:
            # Resolve the Liquidity Level based on user dropdown
            if sweep_type == "Previous Week Candle":
                current_monday = d - pd.Timedelta(days=d.weekday())
                past_htf = weekly_hist.loc[weekly_hist.index < current_monday]
                if len(past_htf) < 1: continue
                pwl, pwh = past_htf['Low'].iloc[-1], past_htf['High'].iloc[-1]
                
            elif sweep_type == "Weekly Swing High/Low":
                current_monday = d - pd.Timedelta(days=d.weekday())
                past_htf = weekly_hist.loc[weekly_hist.index < current_monday]
                if len(past_htf) < 2: continue
                # Search for latest weekly swing
                _, pwh = get_recent_swing(weekly_hist, current_monday, 'high')
                _, pwl = get_recent_swing(weekly_hist, current_monday, 'low')
                if not pwh or not pwl: continue
                
            day_end = d + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
            
            # Execute Advanced Multi-Timeframe logic
            r_today = evaluate_mtf_setup(df_15m, df_75m, pwh, pwl, mss_limit, scan_state, d, day_end, strict_opposite, target_method)
            if r_today: res.extend(r_today)

        if res:
            for r in res: r['Stock name'] = ticker.replace('.NS', '')
            return res
        return None
    except:
        return None

# --- STREAMLIT UI ---
st.title("🎯 Ultimate ICT Advanced Multi-Timeframe Scanner")
st.caption("Engine: Weekly Liquidity → 75m MSS Confirmation → 15m S/D Base Entry")

with st.sidebar:
    st.header("⚙️ Scanner Configurations")
    
    sweep_type = st.selectbox(
        "HTF Liquidity Sweep Level",
        ["Previous Week Candle", "Weekly Swing High/Low"],
        help="Defines what major structural level needs to be swept before hunting for the 75m MSS."
    )
    
    scan_state = st.selectbox(
        "Select Market State", 
        [
            "1. MSS done (Swing high not yet formed)", 
            "2. Awaiting entry (Price has not touched Proximal Line)", 
            "3. Trade open (Price touched Zone, Active)", 
            "4. Previous reports (Date Range Backtest Mode)"
        ]
    )
    state_code = scan_state.split(".")[0]
    
    target_method = st.selectbox(
        "Target Strategy",
        ["Recent Untested 15m Swing", "Fixed 1:2 Risk-to-Reward"]
    )
    
    mss_limit = st.selectbox("Max 75m Displacement Candles for MSS", list(range(1, 11)), index=6)
    strict_opposite = st.checkbox("Reject if Opposite Liquidity Touched", value=False)
    
    st.divider()
    if state_code == "4":
        st.subheader("Backtest Date Range")
        today = pd.to_datetime(datetime.now(ist).date())
        
        st.caption("Note: 15m base data restricted to the last 60 trading days.")
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
        
        risk_per_trade = st.number_input("Risk per Trade (₹)", min_value=100, value=1000, step=100)
    else:
        start_date = pd.to_datetime(datetime.now(ist).date())
        end_date = start_date

if st.button("🚀 Execute MTF Master Scan", type="primary"):
    if state_code == "4" and start_date > end_date:
        st.error("Error: 'From Date' must be earlier than or equal to 'To Date'.")
    else:
        with st.spinner(f"Scanning Nifty 500 | Multi-Timeframe Engine | State: {state_code}..."):
            tickers = get_nifty500_symbols()
            results = []
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
                futures = [executor.submit(scan_ticker, tick, sweep_type, mss_limit, state_code, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'), strict_opposite, target_method) for tick in tickers]
                for f in concurrent.futures.as_completed(futures):
                    res = f.result()
                    if res: results.extend(res)
                    
            if not results:
                st.warning("No stocks matched these highly specific MTF criteria.")
            else:
                df_all = pd.DataFrame(results)
                
                if state_code == "4":
                    def calculate_pnl(row):
                        risk = risk_per_trade
                        risk_dist = abs(row['Entry Level (Proximal)'] - row['Stop Loss (Distal)'])
                        if risk_dist == 0: return 0
                        qty = risk / risk_dist
                        reward_dist = abs(row['Target (15m Swing)'] - row['Entry Level (Proximal)'])
                        reward_ratio = reward_dist / risk_dist
                        
                        if row['Outcome'] == 'Target Hit': return risk * reward_ratio
                        elif row['Outcome'] == 'SL Hit': return -risk
                        else: 
                            if row['Direction'] == 'Bullish': return qty * (row['CMP'] - row['Entry Level (Proximal)'])
                            else: return qty * (row['Entry Level (Proximal)'] - row['CMP'])
                                
                    df_all['Trade P&L (₹)'] = df_all.apply(calculate_pnl, axis=1).round(2)
                
                df_bull = df_all[df_all['Direction'] == 'Bullish']
                df_bear = df_all[df_all['Direction'] == 'Bearish']
                
                tab1, tab2 = st.tabs(["🟢 Bullish MTF Setups", "🔴 Bearish MTF Setups"])
                
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
