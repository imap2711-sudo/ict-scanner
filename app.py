import streamlit as st
import pandas as pd
import numpy as np
import requests
import io
import warnings
import logging
import concurrent.futures
from datetime import datetime, timedelta
from dhanhq import dhanhq

warnings.filterwarnings('ignore')

st.set_page_config(page_title="ICT Doji Resting Screener", layout="wide")

FALLBACK_TICKERS = [
    'RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'ICICIBANK.NS', 'BHARTIARTL.NS', 'SBIN.NS', 
    'INFY.NS', 'LICI.NS', 'ITC.NS', 'HINDUNILVR.NS', 'LT.NS', 'BAJFINANCE.NS', 
    'HCLTECH.NS', 'MARUTI.NS', 'SUNPHARMA.NS', 'TATAMOTORS.NS', 'TATASTEEL.NS', 
    'ONGC.NS', 'KOTAKBANK.NS', 'NTPC.NS', 'AXISBANK.NS', 'POWERGRID.NS', 'TITAN.NS'
]

# ==========================================
# UNIVERSE FETCHING
# ==========================================
def fetch_nse_csv(url):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            df = pd.read_csv(io.StringIO(res.text))
            col = 'Symbol' if 'Symbol' in df.columns else 'SYMBOL'
            return [str(s).strip() + '.NS' for s in df[col]]
    except: pass
    return []

@st.cache_data(ttl=86400)
def get_nifty200_symbols():
    res = fetch_nse_csv("https://nsearchives.nseindia.com/content/indices/ind_nifty200list.csv")
    return res if res else FALLBACK_TICKERS

@st.cache_data(ttl=86400)
def get_nifty500_symbols():
    res = fetch_nse_csv("https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv")
    return res if res else FALLBACK_TICKERS

@st.cache_data(ttl=86400)
def get_all_nse_symbols():
    res = fetch_nse_csv("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv")
    return res if res else FALLBACK_TICKERS

# ==========================================
# DHANHQ DATA FETCHING
# ==========================================
def fetch_dhan_data(clean_symbol, client_id, access_token):
    try:
        dhan = dhanhq(client_id, access_token)
        
        from_date_str = (datetime.today() - timedelta(days=1095)).strftime('%Y-%m-%d')
        to_date_str = datetime.today().strftime('%Y-%m-%d')
        
        # CRITICAL FIX: The historical_daily_data API strictly expects the text symbol ('RELIANCE'), 
        # not the numeric security ID used in intraday APIs.
        historical_data = dhan.historical_daily_data(
            symbol=clean_symbol, 
            exchange_segment='NSE_EQ',
            instrument_type='EQUITY',
            expiry_code=0, 
            from_date=from_date_str,
            to_date=to_date_str
        )
        
        if historical_data.get('status') == 'success':
            df = pd.DataFrame(historical_data['data'])
            if df.empty: return pd.DataFrame()
            
            if pd.api.types.is_numeric_dtype(df['start_Time']):
                if df['start_Time'].iloc[0] > 1e11: df['start_Time'] = pd.to_datetime(df['start_Time'], unit='ms')
                else: df['start_Time'] = pd.to_datetime(df['start_Time'], unit='s')
            else:
                df['start_Time'] = pd.to_datetime(df['start_Time'])
                
            if df['start_Time'].dt.tz is not None:
                df['start_Time'] = df['start_Time'].dt.tz_localize(None)
                
            df.set_index('start_Time', inplace=True)
            df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low', 'close': 'Close', 'volume': 'Volume'}, inplace=True)
            df.sort_index(inplace=True)
            return df
        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

# ==========================================
# CURVATURE MATH
# ==========================================
def check_ema20_rounded_bottom(ema_series, lookback=20):
    if len(ema_series) < lookback: return False
    recent_ema = ema_series.iloc[-lookback:].values
    min_idx = np.argmin(recent_ema)
    
    if min_idx < 4 or min_idx > lookback - 4: return False
    
    ema_start = recent_ema[0]
    ema_end = recent_ema[-1]
    ema_trough = recent_ema[min_idx]
    if ema_start <= ema_trough or ema_end <= ema_trough: return False
    
    trough_vals = recent_ema[max(0, min_idx-2):min(lookback, min_idx+3)]
    trough_range = np.max(trough_vals) - np.min(trough_vals)
    total_depth = max(ema_start, ema_end) - ema_trough
    
    if total_depth == 0: return False
    if trough_range > total_depth * 0.5: return False 
    return True

def check_ema20_rounded_top(ema_series, lookback=20):
    if len(ema_series) < lookback: return False
    recent_ema = ema_series.iloc[-lookback:].values
    max_idx = np.argmax(recent_ema)
    
    if max_idx < 4 or max_idx > lookback - 4: return False
    
    ema_start = recent_ema[0]
    ema_end = recent_ema[-1]
    ema_peak = recent_ema[max_idx]
    if ema_start >= ema_peak or ema_end >= ema_peak: return False
    
    peak_vals = recent_ema[max(0, max_idx-2):min(lookback, max_idx+3)]
    peak_range = np.max(peak_vals) - np.min(peak_vals)
    total_height = ema_peak - min(ema_start, ema_end)
    
    if total_height == 0: return False
    if peak_range > total_height * 0.5: return False 
    return True

# ==========================================
# ENGINE: BULLISH LOGIC
# ==========================================
def evaluate_bullish_day(ticker, df, idx, current_day):
    if not check_ema20_rounded_bottom(df['EMA20'].iloc[max(0, idx-20):idx+1]): return None
    
    curr_month = current_day.to_period('M')
    pml = (df[df.index.to_period('M') == curr_month - 1]['Low'].min(), 'PML') if not df[df.index.to_period('M') == curr_month - 1].empty else None
    curr_quarter = current_day.to_period('Q')
    pql = (df[df.index.to_period('Q') == curr_quarter - 1]['Low'].min(), 'PQL') if not df[df.index.to_period('Q') == curr_quarter - 1].empty else None
    
    curr_half = 1 if current_day.month <= 6 else 2
    prev_half_year = current_day.year - 1 if curr_half == 1 else current_day.year
    prev_half = 2 if curr_half == 1 else 1
    prev_half_data = df[(df.index.year == prev_half_year) & 
                        (((df.index.month >= 1) & (df.index.month <= 6) & (prev_half == 1)) | 
                         ((df.index.month >= 7) & (df.index.month <= 12) & (prev_half == 2)))]
    phl = (prev_half_data['Low'].min(), 'PHL') if not prev_half_data.empty else None
    
    htf_levels = [l for l in [pml, pql, phl] if l is not None]
    
    eval_window = df.iloc[idx-40:idx+1]
    sweep_occurred, swept_name, absolute_sweep_day, swept_price = False, "", None, np.inf
    
    for price, name in htf_levels:
        sweep_cands = eval_window[eval_window['Low'] < price]
        if not sweep_cands.empty:
            if price < swept_price:
                sweep_occurred = True
                swept_name = name
                swept_price = price
                absolute_sweep_day = sweep_cands['Low'].idxmin()
                
    if not sweep_occurred: return None
    sweep_idx = df.index.get_loc(absolute_sweep_day)
    
    if sweep_idx < 40: return None
    ema_40_pre = df['EMA20'].iloc[sweep_idx - 40]
    ema_20_pre = df['EMA20'].iloc[sweep_idx - 20]
    ema_sweep = df['EMA20'].iloc[sweep_idx]
    if not (ema_40_pre > ema_20_pre > ema_sweep): return None
    
    pre_sweep_df = df.iloc[max(0, sweep_idx-60):sweep_idx]
    if len(pre_sweep_df) < 5: return None
    
    swing_highs = []
    for i in range(1, len(pre_sweep_df)-1):
        if pre_sweep_df['High'].iloc[i] > pre_sweep_df['High'].iloc[i-1] and pre_sweep_df['High'].iloc[i] > pre_sweep_df['High'].iloc[i+1]:
            swing_highs.append({'price': pre_sweep_df['High'].iloc[i], 'time': pre_sweep_df.index[i]})
    
    nearest_untested_high = None
    for sh in reversed(swing_highs):
        interim = pre_sweep_df.loc[sh['time']:].iloc[1:]
        if interim.empty or interim['High'].max() < sh['price']:
            nearest_untested_high = sh['price']
            break
            
    if not nearest_untested_high: return None
    
    post_sweep_df = df.iloc[sweep_idx:idx+1]
    if post_sweep_df[post_sweep_df['Close'] > nearest_untested_high].empty: return None
    
    closes_above_ema = post_sweep_df[post_sweep_df['Close'] > post_sweep_df['EMA20']]
    if closes_above_ema.empty: return None
    first_breakout_idx = df.index.get_loc(closes_above_ema.index[0])
    
    pre_touch_window = df.iloc[max(0, first_breakout_idx - 30):first_breakout_idx]
    if len(pre_touch_window[pre_touch_window['High'] >= pre_touch_window['EMA20']]) > 5: return None
    
    recent_window = df.iloc[max(first_breakout_idx, idx-5):idx+1]
    doji_count = 0
    for i in range(len(recent_window)):
        r = recent_window.iloc[i]
        c_idx = df.index.get_loc(recent_window.index[i])
        ema_val = df['EMA20'].iloc[c_idx]
        body = abs(r['Open'] - r['Close'])
        rng = r['High'] - r['Low']
        if (rng > 0) and (body <= rng * 0.35) and (r['Close'] > ema_val): doji_count += 1
            
    if doji_count < 1: return None
    
    row = df.iloc[idx]
    ema_val = df['EMA20'].iloc[idx]
    if row['Close'] <= ema_val: return None 
    
    distance_to_ema = ((row['Low'] - ema_val) / ema_val) * 100
    if distance_to_ema < -1.0 or distance_to_ema > 2.0: return None
    
    return {
        "Stock Symbol": ticker.replace('.NS', ''),
        "Trigger Date": current_day.strftime('%Y-%m-%d'),
        "HTF Swept": swept_name,
        "Pre-Sweep High (₹)": round(nearest_untested_high, 2),
        "EMA20 Rest (₹)": round(ema_val, 2),
        "Close (₹)": round(row['Close'], 2)
    }

# ==========================================
# ENGINE: BEARISH LOGIC
# ==========================================
def evaluate_bearish_day(ticker, df, idx, current_day):
    if not check_ema20_rounded_top(df['EMA20'].iloc[max(0, idx-20):idx+1]): return None
    
    curr_month = current_day.to_period('M')
    pmh = (df[df.index.to_period('M') == curr_month - 1]['High'].max(), 'PMH') if not df[df.index.to_period('M') == curr_month - 1].empty else None
    curr_quarter = current_day.to_period('Q')
    pqh = (df[df.index.to_period('Q') == curr_quarter - 1]['High'].max(), 'PQH') if not df[df.index.to_period('Q') == curr_quarter - 1].empty else None
    
    curr_half = 1 if current_day.month <= 6 else 2
    prev_half_year = current_day.year - 1 if curr_half == 1 else current_day.year
    prev_half = 2 if curr_half == 1 else 1
    prev_half_data = df[(df.index.year == prev_half_year) & 
                        (((df.index.month >= 1) & (df.index.month <= 6) & (prev_half == 1)) | 
                         ((df.index.month >= 7) & (df.index.month <= 12) & (prev_half == 2)))]
    phh = (prev_half_data['High'].max(), 'PHH') if not prev_half_data.empty else None
    
    htf_levels = [l for l in [pmh, pqh, phh] if l is not None]
    
    eval_window = df.iloc[idx-40:idx+1]
    sweep_occurred, swept_name, absolute_sweep_day, swept_price = False, "", None, -np.inf
    
    for price, name in htf_levels:
        sweep_cands = eval_window[eval_window['High'] > price]
        if not sweep_cands.empty:
            if price > swept_price:
                sweep_occurred = True
                swept_name = name
                swept_price = price
                absolute_sweep_day = sweep_cands['High'].idxmax()
                
    if not sweep_occurred: return None
    sweep_idx = df.index.get_loc(absolute_sweep_day)
    
    if sweep_idx < 40: return None
    ema_40_pre = df['EMA20'].iloc[sweep_idx - 40]
    ema_20_pre = df['EMA20'].iloc[sweep_idx - 20]
    ema_sweep = df['EMA20'].iloc[sweep_idx]
    if not (ema_40_pre < ema_20_pre < ema_sweep): return None
    
    pre_sweep_df = df.iloc[max(0, sweep_idx-60):sweep_idx]
    if len(pre_sweep_df) < 5: return None
    
    swing_lows = []
    for i in range(1, len(pre_sweep_df)-1):
        if pre_sweep_df['Low'].iloc[i] < pre_sweep_df['Low'].iloc[i-1] and pre_sweep_df['Low'].iloc[i] < pre_sweep_df['Low'].iloc[i+1]:
            swing_lows.append({'price': pre_sweep_df['Low'].iloc[i], 'time': pre_sweep_df.index[i]})
    
    nearest_untested_low = None
    for sl in reversed(swing_lows):
        interim = pre_sweep_df.loc[sl['time']:].iloc[1:]
        if interim.empty or interim['Low'].min() > sl['price']:
            nearest_untested_low = sl['price']
            break
            
    if not nearest_untested_low: return None
    
    post_sweep_df = df.iloc[sweep_idx:idx+1]
    if post_sweep_df[post_sweep_df['Close'] < nearest_untested_low].empty: return None
    
    closes_below_ema = post_sweep_df[post_sweep_df['Close'] < post_sweep_df['EMA20']]
    if closes_below_ema.empty: return None
    first_breakout_idx = df.index.get_loc(closes_below_ema.index[0])
    
    pre_touch_window = df.iloc[max(0, first_breakout_idx - 30):first_breakout_idx]
    if len(pre_touch_window[pre_touch_window['Low'] <= pre_touch_window['EMA20']]) > 5: return None
    
    recent_window = df.iloc[max(first_breakout_idx, idx-5):idx+1]
    doji_count = 0
    for i in range(len(recent_window)):
        r = recent_window.iloc[i]
        c_idx = df.index.get_loc(recent_window.index[i])
        ema_val = df['EMA20'].iloc[c_idx]
        body = abs(r['Open'] - r['Close'])
        rng = r['High'] - r['Low']
        if (rng > 0) and (body <= rng * 0.35) and (r['Close'] < ema_val): doji_count += 1
            
    if doji_count < 1: return None
    
    row = df.iloc[idx]
    ema_val = df['EMA20'].iloc[idx]
    if row['Close'] >= ema_val: return None 
    
    distance_to_ema = ((ema_val - row['High']) / ema_val) * 100
    if distance_to_ema < -1.0 or distance_to_ema > 2.0: return None
    
    return {
        "Stock Symbol": ticker.replace('.NS', ''),
        "Trigger Date": current_day.strftime('%Y-%m-%d'),
        "HTF Swept": swept_name,
        "Pre-Sweep Low (₹)": round(nearest_untested_low, 2),
        "EMA20 Rest (₹)": round(ema_val, 2),
        "Close (₹)": round(row['Close'], 2)
    }

# ==========================================
# WRAPPER FUNCTIONS
# ==========================================
def scan_live_setups(ticker, clean_symbol, setup_type, client_id, access_token):
    df = fetch_dhan_data(clean_symbol, client_id, access_token)
    if df.empty: return "API_FAIL" 
    if len(df) < 200: return None
    
    cmp = df['Close'].iloc[-1]
    if pd.isna(cmp) or cmp < 100: return None
    
    df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
    idx = len(df) - 1
    
    if setup_type == "Bullish": return evaluate_bullish_day(ticker, df, idx, df.index[idx])
    else: return evaluate_bearish_day(ticker, df, idx, df.index[idx])

def backtest_setups(ticker, clean_symbol, start_date, end_date, setup_type, client_id, access_token):
    df = fetch_dhan_data(clean_symbol, client_id, access_token)
    if df.empty: return "API_FAIL"
    if len(df) < 200: return []
    
    df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
    target_dates = df[(df.index.date >= start_date) & (df.index.date <= end_date)].index
    valid_setups = []
    
    for current_day in target_dates:
        idx = df.index.get_loc(current_day)
        if idx < 130: continue
        
        cmp = df['Close'].iloc[idx]
        if pd.isna(cmp) or cmp < 100: continue
        
        if setup_type == "Bullish": res = evaluate_bullish_day(ticker, df, idx, current_day)
        else: res = evaluate_bearish_day(ticker, df, idx, current_day)
            
        if res: valid_setups.append(res)
        
    return valid_setups

# ==============================
# STREAMLIT UI
# ==============================
st.title("ICT Doji Resting Screener (DhanHQ)")
st.markdown("Macro Trend -> Untested HTF Sweep -> Daily MSS -> Flag -> Pinpoint Curvature Doji Rest")

# Sidebar Configuration
st.sidebar.header("Dhan API Configuration")
st.sidebar.markdown("Enter your broker keys to fetch institutional-grade tick data directly from NSE.")
CLIENT_ID = st.sidebar.text_input("Dhan Client ID", type="password")
ACCESS_TOKEN = st.sidebar.text_input("Dhan Access Token", type="password")

st.sidebar.divider()
universe_option = st.sidebar.selectbox("Select Stock Universe", ["Nifty 200", "Nifty 500", "All NSE Stocks (> ₹100)"])

if not CLIENT_ID or not ACCESS_TOKEN:
    st.info("👈 Please enter your Dhan API Client ID and Access Token in the sidebar to run scans.")
    st.stop()

bullish_tab, bearish_tab = st.tabs(["Bullish Setups (Sweep Low)", "Bearish Setups (Sweep High)"])

def execute_scan(setup_type, mode, start_date=None, end_date=None):
    with st.spinner(f"Fetching {universe_option} via Dhan API and scanning..."):
        if universe_option == "Nifty 200": tickers = get_nifty200_symbols()
        elif universe_option == "Nifty 500": tickers = get_nifty500_symbols()
        else: tickers = get_all_nse_symbols()
            
        my_bar = st.progress(0)
        results = []
        api_fails = 0
        
        # Throttled to 5 workers to prevent API Rate Limiting from DhanHQ
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = {}
            for t in tickers:
                clean_sym = t.replace('.NS', '')  # Just passes 'RELIANCE', exactly as Dhan historical endpoint requires
                if mode == "live":
                    futures[executor.submit(scan_live_setups, t, clean_sym, setup_type, CLIENT_ID, ACCESS_TOKEN)] = t
                else:
                    futures[executor.submit(backtest_setups, t, clean_sym, start_date, end_date, setup_type, CLIENT_ID, ACCESS_TOKEN)] = t
                    
            for i, future in enumerate(concurrent.futures.as_completed(futures)):
                res = future.result()
                if res == "API_FAIL": 
                    api_fails += 1
                elif res: 
                    if mode == "live": results.append(res)
                    else: results.extend(res)
                my_bar.progress((i + 1) / len(futures))
                
        my_bar.empty()
        
        # Diagnostics Catch
        if api_fails > len(futures) * 0.9:
            st.error(f"🚨 **Dhan API Connection Failed:** {api_fails} requests returned empty data. Check your Client ID, Token, and ensure you have an active Data API plan.")
            return

        if results:
            if mode == "backtest": results.sort(key=lambda x: x['Trigger Date'])
            df_res = pd.DataFrame(results)
            st.success(f"Found {len(df_res)} {setup_type} Setups!")
            st.dataframe(df_res, use_container_width=True)
            
            if mode == "backtest":
                csv = df_res.to_csv(index=False).encode('utf-8')
                st.download_button(label=f"Download Backtest Data", data=csv, file_name=f"{setup_type}_Backtest.csv", mime="text/csv")
        else:
            st.warning(f"No {setup_type} setups found in the specified criteria.")

with bullish_tab:
    st.markdown("Identifies a sustained **Macro Downtrend**, an **untested HTF low sweep**, daily **MSS**, a breakout above a **rounded EMA 20 bottom**, and a flag pulling back to print at least one **Doji resting precisely ON the EMA**.")
    if st.button("Run Live Bullish Screener"): execute_scan("Bullish", "live")
        
    st.divider()
    st.markdown("#### Backtest Custom Date Range (Bullish)")
    col1, col2 = st.columns(2)
    with col1: start_b = st.date_input("From Date (Bullish)", datetime.today() - timedelta(days=30))
    with col2: end_b = st.date_input("To Date (Bullish)", datetime.today())
    if st.button("Run Bullish Backtester"): execute_scan("Bullish", "backtest", start_b, end_b)

with bearish_tab:
    st.markdown("Identifies a sustained **Macro Uptrend**, an **untested HTF high sweep**, daily **MSS (Downside)**, a drop below a **rounded EMA 20 top**, and a rally flag printing at least one **Doji resting tightly BENEATH the EMA**.")
    if st.button("Run Live Bearish Screener"): execute_scan("Bearish", "live")
        
    st.divider()
    st.markdown("#### Backtest Custom Date Range (Bearish)")
    col3, col4 = st.columns(2)
    with col3: start_br = st.date_input("From Date (Bearish)", datetime.today() - timedelta(days=30))
    with col4: end_br = st.date_input("To Date (Bearish)", datetime.today())
    if st.button("Run Bearish Backtester"): execute_scan("Bearish", "backtest", start_br, end_br)
