import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import io
import concurrent.futures
from datetime import datetime
import pytz

st.set_page_config(page_title="Ultimate ICT Precision Scanner (Daily Engine)", layout="wide", page_icon="⚡")
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
                    
        if fvg_tops: return max(fvg_tops), "Discount FVG"
        else: return fib_618, "61.8% Fib"
            
    else:
        eq_50 = anchor - range_size * 0.5
        fib_618 = peak + range_size * 0.618
        
        fvg_bottoms = []
        for i in range(len(leg_df)-2):
            if leg_df['High'].iloc[i+2] < leg_df['Low'].iloc[i]:
                fvg_bot = leg_df['High'].iloc[i+2]
                if fvg_bot >= eq_50:
                    fvg_bottoms.append(fvg_bot)
                    
        if fvg_bottoms: return min(fvg_bottoms), "Premium FVG"
        else: return fib_618, "61.8% Fib"

def evaluate_setup(df, htf_high, htf_low, mss_limit, scan_state, eval_start, eval_end, strict_opposite, target_pref, monthly_sh_val, monthly_sl_val):
    setups = []
    df_index = df.index.tolist()
    cmp = df['Close'].iloc[-1]
    
    window_df = df.loc[(df.index >= eval_start) & (df.index <= eval_end)]
    if window_df.empty: return setups
    
    time_fmt = '%Y-%m-%d'

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
                            # Target Resolution
                            target_price = post_sh_val
                            target_label = "Daily Anchor"
                            if target_pref == "Monthly Untested Swing" and monthly_sh_val:
                                if monthly_sh_val > post_sh_val:
                                    target_price = monthly_sh_val
                                    target_label = "Monthly Swing"

                            entry_price, entry_type = get_dynamic_entry(df, sweep_idx, post_sh_idx, 'Bullish', sweep_low, post_sh_val)
                            gap_pct = round(((cmp - entry_price)/cmp)*100, 2)
                            
                            setup_data.update({
                                "Target Type": target_label,
                                "Entry Type": entry_type,
                                "Entry Level": round(entry_price, 2),
                                "Stop Loss": round(sweep_low, 2),
                                "Target": round(target_price, 2),
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
                                    if row['Low'] <= sweep_low or row['High'] >= target_price:
                                        is_active = False
                                        break
                                if is_active:
                                    setup_data["Entry Distance"] = "Touched (Active)"
                                    setups.append(setup_data)
                                    
                            elif touched_entry and scan_state == "4":
                                entry_idx = tracking_df[tracking_df['Low'] <= entry_price].index[0]
                                forward_df = df.loc[entry_idx:]
                                outcome, highest_seen = "Still Open", entry_price
                                for idx, row in forward_df.iterrows():
                                    if row['High'] > highest_seen: highest_seen = row['High']
                                    if row['Low'] <= sweep_low:
                                        outcome = "SL Hit"
                                        break
                                    elif row['High'] >= target_price:
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
                            "MSS price": round(sl_val, 2),
                            "Entry Distance": "N/A"
                        }
                        
                        if not post_sl_idx:
                            if scan_state == "1":
                                setups.append(setup_data)
                        else:
                            # Target Resolution
                            target_price = post_sl_val
                            target_label = "Daily Anchor"
                            if target_pref == "Monthly Untested Swing" and monthly_sl_val:
                                if monthly_sl_val < post_sl_val:
                                    target_price = monthly_sl_val
                                    target_label = "Monthly Swing"

                            entry_price, entry_type = get_dynamic_entry(df, sweep_idx, post_sl_idx, 'Bearish', sweep_high, post_sl_val)
                            gap_pct = round(((entry_price - cmp)/cmp)*100, 2)
                            
                            setup_data.update({
                                "Target Type": target_label,
                                "Entry Type": entry_type,
                                "Entry Level": round(entry_price, 2),
                                "Stop Loss": round(sweep_high, 2),
                                "Target": round(target_price, 2),
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
                                    if row['High'] >= sweep_high or row['Low'] <= target_price:
                                        is_active = False
                                        break
                                if is_active:
                                    setup_data["Entry Distance"] = "Touched (Active)"
                                    setups.append(setup_data)
                                    
                            elif touched_entry and scan_state == "4":
                                entry_idx = tracking_df[tracking_df['High'] >= entry_price].index[0]
                                forward_df = df.loc[entry_idx:]
                                outcome, lowest_seen = "Still Open", entry_price
                                for idx, row in forward_df.iterrows():
                                    if row['Low'] < lowest_seen: lowest_seen = row['Low']
                                    if row['High'] >= sweep_high:
                                        outcome = "SL Hit"
                                        break
                                    elif row['Low'] <= target_price:
                                        outcome = "Target Hit"
                                        break
                                setup_data["Max Move (%)"] = f"{round(((entry_price - lowest_seen) / entry_price) * 100, 2)}%"
                                setup_data["Outcome"] = outcome
                                setups.append(setup_data)
    return setups

def scan_ticker(ticker, mss_limit, scan_state, start_date_str, end_date_str, strict_opposite, target_pref):
    try:
        t = yf.Ticker(ticker)
        start_date = pd.to_datetime(start_date_str).replace(hour=0, minute=0, second=0)
        end_date = pd.to_datetime(end_date_str).replace(hour=23, minute=59, second=59)
        
        # Deep 5 Year Pull for Pristine Monthly Fractals
        df = t.history(period="5y", interval="1d", auto_adjust=False)
        if df.empty: return None
        df.index = df.index.tz_localize(None)
        
        monthly_hist = df.resample('ME').agg({'High':'max', 'Low':'min'}).dropna()
        if monthly_hist.empty: return None
        
        if scan_state != "4":
            target_month_start = start_date.replace(day=1)
            target_month_end = target_month_start + pd.offsets.MonthEnd(0)
            
            hist_df = monthly_hist.loc[monthly_hist.index < target_month_start]
            if len(hist_df) < 2: return None
            pml, pmh = hist_df['Low'].iloc[-1], hist_df['High'].iloc[-1]
            m_idx = hist_df.index[-1]
            
            monthly_sh_idx, monthly_sh_val = get_recent_swing(monthly_hist, m_idx, 'high')
            monthly_sl_idx, monthly_sl_val = get_recent_swing(monthly_hist, m_idx, 'low')
            
            res = evaluate_setup(df, pmh, pml, mss_limit, scan_state, target_month_start, target_month_end, strict_opposite, target_pref, monthly_sh_val, monthly_sl_val)
        else:
            months_in_range = pd.date_range(start=start_date.replace(day=1), end=end_date, freq='MS')
            all_res = []
            for m_start in months_in_range:
                m_end = m_start + pd.offsets.MonthEnd(0)
                hist_df = monthly_hist.loc[monthly_hist.index < m_start]
                if len(hist_df) < 2: continue
                
                pml, pmh = hist_df['Low'].iloc[-1], hist_df['High'].iloc[-1]
                m_idx = hist_df.index[-1]
                
                monthly_sh_idx, monthly_sh_val = get_recent_swing(monthly_hist, m_idx, 'high')
                monthly_sl_idx, monthly_sl_val = get_recent_swing(monthly_hist, m_idx, 'low')
                
                r_month = evaluate_setup(df, pmh, pml, mss_limit, scan_state, m_start, m_end, strict_opposite, target_pref, monthly_sh_val, monthly_sl_val)
                if r_month: all_res.extend(r_month)
            res = all_res

        if res:
            for r in res: r['Stock name'] = ticker.replace('.NS', '')
            return res
        return None
    except:
        return None

# --- STREAMLIT UI ---
st.title("🎯 Ultimate ICT Precision Scanner (Daily Only)")

with st.sidebar:
    st.header("⚙️ Scanner Configurations")
    
    scan_state = st.selectbox(
        "Select Market State", 
        [
            "1. MSS done (Swing high not yet formed)", 
            "2. Awaiting entry (Price has not yet touched FVG/61%)", 
            "3. Trade open (Price has touched Entry, SL/Target not hit)", 
            "4. Previous reports (Monthly Backtest Mode)"
        ]
    )
    state_code = scan_state.split(".")[0]
    
    target_pref = st.selectbox(
        "Target Level Selection", 
        ["Daily Anchor Swing (Momentum Peak)", "Monthly Untested Swing"]
    )
    
    mss_limit = st.selectbox("Max Displacement Candles for MSS", list(range(1, 16)), index=6)
    strict_opposite = st.checkbox("Reject if Opposite Liquidity Touched", value=False)
    
    st.divider()
    if state_code == "4":
        st.subheader("Backtest Date Range")
        today = pd.Timestamp.today()
        month_opts = [(today - pd.DateOffset(months=i)).strftime('%Y-%m-01') for i in range(36)]
        
        from_month_str = st.selectbox("From Month", reversed(month_opts), format_func=lambda x: pd.to_datetime(x).strftime('%B %Y'))
        to_month_str = st.selectbox("To Month", month_opts, format_func=lambda x: pd.to_datetime(x).strftime('%B %Y'))
        
        start_date = pd.to_datetime(from_month_str)
        end_date = pd.to_datetime(to_month_str) + pd.offsets.MonthEnd(0)
        
        risk_per_trade = st.number_input("Risk per Trade (₹)", min_value=100, value=1000, step=100)
    else:
        start_date = datetime.today()
        end_date = start_date

if st.button("🚀 Execute Master Scan", type="primary"):
    if state_code == "4" and start_date > end_date:
        st.error("Error: 'From Month' must be earlier than or equal to 'To Month'.")
    else:
        with st.spinner(f"Scanning Nifty 500 | Daily Timeframe | State: {state_code}..."):
            tickers = get_nifty500_symbols()
            results = []
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
                futures = [executor.submit(scan_ticker, tick, mss_limit, state_code, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'), strict_opposite, target_pref) for tick in tickers]
                for f in concurrent.futures.as_completed(futures):
                    res = f.result()
                    if res: results.extend(res)
                    
            if not results:
                st.warning("No stocks matched these criteria for the selected parameters.")
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
                            if row['Direction'] == 'Bullish': return qty * (row['CMP'] - row['Entry Level'])
                            else: return qty * (row['Entry Level'] - row['CMP'])
                                
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

                with tab1: render_tab_content(df_bull, "Bullish")
                with tab2: render_tab_content(df_bear, "Bearish")
