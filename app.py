import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import io
import concurrent.futures
from datetime import datetime, timedelta
import datetime as dt
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

def evaluate_setup(df, htf_high, htf_low, mss_limit, scan_state, eval_start, eval_end, strict_opposite, is_daily=False):
    setups = []
    df_index = df.index.tolist()
    cmp = df['Close'].iloc[-1]
    
    window_df = df.loc[(df.index >= eval_start) & (df.index <= eval_end)]
    if window_df.empty: return setups
    
    time_fmt = '%Y-%m-%d' if is_daily else '%Y-%m-%d %H:%M'
    cutoff_time = dt.time(13, 0)
    exit_time = dt.time(15, 15)

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
                            "Entry Distance": "N/A"
                        }
                        
                        if not post_sh_idx:
                            if scan_state == "1":
                                setups.append(setup_data)
                        else:
                            entry_price, entry_type = get_dynamic_entry(df, sweep_idx, post_sh_idx, 'Bullish', sweep_low, post_sh_val)
                            gap_pct = round(((cmp - entry_price)/cmp)*100, 2)
                            
                            setup_data.update({
                                "Entry Type": entry_type,
                                "Entry Level": round(entry_price, 2),
                                "Stop Loss": round(sweep_low, 2),
                                "Target": round(post_sh_val, 2),
                                "Entry Distance": f"{gap_pct}%"
                            })
                            
                            confirm_pos = df_index.index(confirm_idx)
                            tracking_df = df.iloc[confirm_pos:]
                            
                            # Intraday 1 PM Entry Time Constraint
                            touched_entry = False
                            entry_idx = None
                            touch_mask = tracking_df['Low'] <= entry_price
                            
                            if not touch_mask.empty and touch_mask.any():
                                entry_idx = tracking_df[touch_mask].index[0]
                                if is_daily or (entry_idx.date() == sweep_idx.date() and entry_idx.time() <= cutoff_time):
                                    touched_entry = True
                            
                            if not touched_entry and scan_state == "2":
                                # Reject if past 1 PM today
                                if is_daily or df.index[-1].time() <= cutoff_time:
                                    setups.append(setup_data)
                                
                            elif touched_entry and scan_state in ["3", "4"]:
                                forward_df = df.loc[entry_idx:]
                                is_active = True
                                outcome = "Still Open"
                                highest_seen = entry_price
                                exit_price = cmp
                                
                                for idx, row in forward_df.iterrows():
                                    if row['High'] > highest_seen: highest_seen = row['High']
                                    
                                    if row['Low'] <= sweep_low:
                                        is_active = False
                                        outcome = "SL Hit"
                                        exit_price = sweep_low
                                        break
                                    elif row['High'] >= post_sh_val:
                                        is_active = False
                                        outcome = "Target Hit"
                                        exit_price = post_sh_val
                                        break
                                        
                                    # Hard 3:15 PM EOD Exit Constraint
                                    if not is_daily and (idx.time() >= exit_time or idx.date() > entry_idx.date()):
                                        is_active = False
                                        outcome = "Time Exit"
                                        exit_price = row['Close'] if idx.date() == entry_idx.date() else row['Open']
                                        break
                                        
                                if scan_state == "3" and is_active:
                                    setup_data["Entry Distance"] = "Touched (Active)"
                                    setup_data["Floating P&L (₹)"] = calculate_floating_pnl("Bullish", cmp, entry_price, sweep_low, 1000)
                                    setups.append(setup_data)
                                    
                            elif touched_entry and scan_state == "4":
                                setup_data["Max Move (%)"] = f"{round(((highest_seen - entry_price) / entry_price) * 100, 2)}%"
                                setup_data["Outcome"] = outcome
                                setup_data["Exit Price"] = exit_price
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
                            "Entry Distance": "N/A"
                        }
                        
                        if not post_sl_idx:
                            if scan_state == "1":
                                setups.append(setup_data)
                        else:
                            entry_price, entry_type = get_dynamic_entry(df, sweep_idx, post_sl_idx, 'Bearish', sweep_high, post_sl_val)
                            gap_pct = round(((entry_price - cmp)/cmp)*100, 2)
                            
                            setup_data.update({
                                "Entry Type": entry_type,
                                "Entry Level": round(entry_price, 2),
                                "Stop Loss": round(sweep_high, 2),
                                "Target": round(post_sl_val, 2),
                                "Entry Distance": f"{gap_pct}%"
                            })
                            
                            confirm_pos = df_index.index(confirm_idx)
                            tracking_df = df.iloc[confirm_pos:]
                            
                            # Intraday 1 PM Entry Time Constraint
                            touched_entry = False
                            entry_idx = None
                            touch_mask = tracking_df['High'] >= entry_price
                            
                            if not touch_mask.empty and touch_mask.any():
                                entry_idx = tracking_df[touch_mask].index[0]
                                if is_daily or (entry_idx.date() == sweep_idx.date() and entry_idx.time() <= cutoff_time):
                                    touched_entry = True
                            
                            if not touched_entry and scan_state == "2":
                                if is_daily or df.index[-1].time() <= cutoff_time:
                                    setups.append(setup_data)
                                
                            elif touched_entry and scan_state in ["3", "4"]:
                                forward_df = df.loc[entry_idx:]
                                is_active = True
                                outcome = "Still Open"
                                lowest_seen = entry_price
                                exit_price = cmp
                                
                                for idx, row in forward_df.iterrows():
                                    if row['Low'] < lowest_seen: lowest_seen = row['Low']
                                    
                                    if row['High'] >= sweep_high:
                                        is_active = False
                                        outcome = "SL Hit"
                                        exit_price = sweep_high
                                        break
                                    elif row['Low'] <= post_sl_val:
                                        is_active = False
                                        outcome = "Target Hit"
                                        exit_price = post_sl_val
                                        break
                                        
                                    # Hard 3:15 PM EOD Exit Constraint
                                    if not is_daily and (idx.time() >= exit_time or idx.date() > entry_idx.date()):
                                        is_active = False
                                        outcome = "Time Exit"
                                        exit_price = row['Close'] if idx.date() == entry_idx.date() else row['Open']
                                        break
                                        
                                if scan_state == "3" and is_active:
                                    setup_data["Entry Distance"] = "Touched (Active)"
                                    setup_data["Floating P&L (₹)"] = calculate_floating_pnl("Bearish", cmp, entry_price, sweep_high, 1000)
                                    setups.append(setup_data)
                                    
                            elif touched_entry and scan_state == "4":
                                setup_data["Max Move (%)"] = f"{round(((entry_price - lowest_seen) / entry_price) * 100, 2)}%"
                                setup_data["Outcome"] = outcome
                                setup_data["Exit Price"] = exit_price
                                setups.append(setup_data)
    return setups

def scan_ticker(ticker, timeframe, mss_limit, scan_state, start_date_str, end_date_str, strict_opposite):
    try:
        t = yf.Ticker(ticker)
        start_date = pd.to_datetime(start_date_str).replace(hour=0, minute=0, second=0)
        end_date = pd.to_datetime(end_date_str).replace(hour=23, minute=59, second=59)
        
        if timeframe == "15 Minute":
            df = t.history(period="60d", interval="15m", auto_adjust=False)
            if df.empty: return None
            df.index = df.index.tz_convert('Asia/Kolkata').tz_localize(None) if df.index.tz else df.index.tz_localize(None)
            
            # PERFECT MATCH: Create daily data explicitly from the exact 15m dataset
            daily_df = df.resample('D').agg({'High':'max', 'Low':'min'}).dropna()
            
            if scan_state != "4":
                if start_date not in daily_df.index: 
                    start_date = daily_df.index[-1] # Fallback to most recent day if today has no data yet
                
                past_days = daily_df.loc[daily_df.index < start_date]
                if len(past_days) < 1: return None
                
                pdl_today, pdh_today = past_days['Low'].iloc[-1], past_days['High'].iloc[-1]
                day_end = start_date + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
                
                res_today = evaluate_setup(df, pdh_today, pdl_today, mss_limit, scan_state, start_date, day_end, strict_opposite, is_daily=False)
                res = res_today or []

            else: 
                days_in_range = daily_df.loc[(daily_df.index >= start_date) & (daily_df.index <= end_date)].index
                all_res = []
                for d in days_in_range:
                    past_days = daily_df.loc[daily_df.index < d]
                    if len(past_days) < 1: continue
                    
                    pdl_today, pdh_today = past_days['Low'].iloc[-1], past_days['High'].iloc[-1]
                    day_end = d + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
                    
                    r_today = evaluate_setup(df, pdh_today, pdl_today, mss_limit, scan_state, d, day_end, strict_opposite, is_daily=False)
                    if r_today: all_res.extend(r_today)
                res = all_res
                
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
                
                res = evaluate_setup(df, pmh, pml, mss_limit, scan_state, target_month_start, target_month_end, strict_opposite, is_daily=True)
            else:
                months_in_range = pd.date_range(start=start_date.replace(day=1), end=end_date, freq='MS')
                all_res = []
                for m_start in months_in_range:
                    m_end = m_start + pd.offsets.MonthEnd(0)
                    hist_df = monthly_hist.loc[monthly_hist.index < m_start]
                    if hist_df.empty: continue
                    pml, pmh = hist_df['Low'].iloc[-1], hist_df['High'].iloc[-1]
                    
                    r_month = evaluate_setup(df, pmh, pml, mss_limit, scan_state, m_start, m_end, strict_opposite, is_daily=True)
                    if r_month: all_res.extend(r_month)
                res = all_res

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
            "2. Awaiting entry (Price has not yet touched FVG/61%)", 
            "3. Trade open (Price has touched Entry, SL/Target not hit)", 
            "4. Previous reports (Date Range Backtest Mode)"
        ]
    )
    state_code = scan_state.split(".")[0]
    
    mss_options = list(range(1, 16)) if timeframe == "Daily" else list(range(1, 11))
    mss_limit = st.selectbox("Max Displacement Candles for MSS", mss_options, index=6)
    
    strict_opposite = st.checkbox("Reject if Opposite Liquidity Touched", value=False)
    
    st.divider()
    if state_code == "4":
        st.subheader("Backtest Date Range")
        today = pd.to_datetime(datetime.now(ist).date())
        
        if timeframe == "15 Minute":
            st.caption("Note: 15-minute historical data is restricted to the last 60 days by the data provider.")
            
            min_date = (today - pd.Timedelta(days=59)).date()
            max_date = today.date()
            
            # Default to scanning the last 7 days automatically for better UX
            default_start = max(min_date, (today - pd.Timedelta(days=7)).date())
            
            start_date_input = st.date_input("From Date", default_start, min_value=min_date, max_value=max_date)
            end_date_input = st.date_input("To Date", max_date, min_value=min_date, max_value=max_date)
            
            start_date = pd.to_datetime(start_date_input)
            end_date = pd.to_datetime(end_date_input)
            
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
        st.error("Error: 'From Date/Month' must be earlier than or equal to 'To Date/Month'.")
    else:
        with st.spinner(f"Scanning Nifty 500 | {timeframe} | State: {state_code}..."):
            tickers = get_nifty500_symbols()
            results = []
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
                futures = [executor.submit(scan_ticker, tick, timeframe, mss_limit, state_code, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'), strict_opposite) for tick in tickers]
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
                        elif row['Outcome'] == 'Time Exit':
                            if row['Direction'] == 'Bullish':
                                return qty * (row['Exit Price'] - row['Entry Level'])
                            else:
                                return qty * (row['Entry Level'] - row['Exit Price'])
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
                            
                            closed_trades = df[df['Outcome'] != 'Still Open']
                            wins = len(closed_trades[closed_trades['Trade P&L (₹)'] > 0])
                            losses = len(closed_trades[closed_trades['Trade P&L (₹)'] <= 0])
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
