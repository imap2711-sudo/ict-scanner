import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import io
import warnings
import logging
import concurrent.futures
from datetime import datetime, timedelta

warnings.filterwarnings('ignore')
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

st.set_page_config(page_title="ICT Liquidity Screener", layout="wide")

@st.cache_data(ttl=3600)
def get_nifty500_symbols():
    url = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5"
    }
    
    for attempt in range(3):
        try:
            response = requests.get(url, headers=headers, timeout=20)
            if response.status_code == 200:
                df = pd.read_csv(io.StringIO(response.text))
                return [str(symbol).strip() + '.NS' for symbol in df['Symbol']]
        except Exception:
            continue
            
    return [
        'RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'ICICIBANK.NS', 'BHARTIARTL.NS', 'SBIN.NS', 
        'INFY.NS', 'LICI.NS', 'ITC.NS', 'HINDUNILVR.NS', 'LT.NS', 'BAJFINANCE.NS', 
        'HCLTECH.NS', 'MARUTI.NS', 'SUNPHARMA.NS', 'TATAMOTORS.NS', 'TATASTEEL.NS', 
        'ONGC.NS', 'KOTAKBANK.NS', 'NTPC.NS', 'AXISBANK.NS', 'POWERGRID.NS', 'TITAN.NS', 
        'M&M.NS', 'BAJAJFINSV.NS', 'ASIANPAINT.NS', 'ADANIENT.NS', 'ADANIPORTS.NS', 
        'WIPRO.NS', 'COALINDIA.NS', 'NESTLEIND.NS', 'GRASIM.NS', 'TECHM.NS', 'HINDALCO.NS'
    ]

def check_ema20_rounded_bottom(ema_series, lookback=20):
    """
    Upgraded function to force a smooth, circular Titan-style bottom
    and strictly reject abrupt GPIL-style V-shape kinks.
    """
    if len(ema_series) < lookback: return False
    recent_ema = ema_series.iloc[-lookback:].values
    
    # First derivative (rate of change)
    roc1 = np.diff(recent_ema)
    # Second derivative (rate of rate of change - acceleration)
    roc2 = np.diff(roc1)
    
    min_idx = np.argmin(recent_ema)
    
    # Trough must be roughly in the middle to form a proper 'U'
    if min_idx < 4 or min_idx > lookback - 4: return False
    
    # 1. Slope Check
    falling_before = np.mean(roc1[:min_idx-1]) < 0
    rising_after = np.mean(roc1[min_idx+1:]) > 0
    if not (falling_before and rising_after): return False
    
    # 2. Smooth Circularity Check (Reject V-Shapes)
    # At the bottom (trough), the rate of change should be near zero (flattening out)
    trough_roc = np.mean(np.abs(roc1[max(0, min_idx-2):min_idx+2]))
    overall_roc = np.mean(np.abs(roc1))
    
    # If the speed of change at the trough is equal to or faster than the overall speed, it's a V-shape spike.
    if trough_roc > overall_roc * 0.7: return False
    
    # 3. Convexity (Acceleration should be generally positive and smooth)
    if np.mean(roc2) <= 0: return False
    
    return True

# ==========================================
# TAB 1: DAILY HTF SETUP
# ==========================================
def find_ict_htf_setups(ticker):
    try:
        t = yf.Ticker(ticker)
        df = t.history(period="2y", interval="1d", auto_adjust=False)
        if df.empty or len(df) < 100: return None
        try: cmp = float(t.fast_info.last_price)
        except Exception: cmp = float(df['Close'].iloc[-1])
        if pd.isna(cmp) or cmp <= 60: return None

        current_month_period = df.index[-1].to_period('M')
        previous_month_period = current_month_period - 1
        eval_window = df.iloc[-30:]
        hist_df = df.iloc[:-30]
        levels = []
        
        prev_month_data = df[df.index.to_period('M') == previous_month_period]
        if not prev_month_data.empty:
            levels.append((prev_month_data['Low'].min(), prev_month_data['Low'].idxmin(), 'Last Month Low (PML)'))
            
        weekly_df = hist_df.resample('W-FRI').agg({'Low':'min'}).dropna()
        for i in range(1, len(weekly_df)-1):
            if weekly_df['Low'].iloc[i] < weekly_df['Low'].iloc[i-1] and weekly_df['Low'].iloc[i] < weekly_df['Low'].iloc[i+1]:
                week_data = hist_df.loc[weekly_df.index[i] - pd.Timedelta(days=6):weekly_df.index[i]]
                if not week_data.empty:
                    levels.append((weekly_df['Low'].iloc[i], week_data['Low'].idxmin(), 'Weekly Swing Low (WSL)'))
                    
        monthly_df = hist_df.resample('ME').agg({'Low':'min'}).dropna()
        for i in range(1, len(monthly_df)-1):
            if monthly_df['Low'].iloc[i] < monthly_df['Low'].iloc[i-1] and monthly_df['Low'].iloc[i] < monthly_df['Low'].iloc[i+1]:
                month_data = hist_df.loc[monthly_df.index[i].replace(day=1):monthly_df.index[i]]
                if not month_data.empty:
                    levels.append((monthly_df['Low'].iloc[i], month_data['Low'].idxmin(), 'Monthly Swing Low (MSL)'))

        fresh_levels = []
        for price, date, ltype in levels:
            if ltype != 'Last Month Low (PML)' and date < hist_df.index[-1]:
                subsequent_data = hist_df.loc[date + pd.Timedelta(days=1):]
                if not subsequent_data.empty and subsequent_data['Low'].min() < price: continue 
            fresh_levels.append((price, date, ltype))
            
        if not fresh_levels: return None
        
        sweep_occurred, swept_level_details, first_sweep_day = False, None, None
        for price, date, ltype in fresh_levels:
            sweep_candidates = eval_window[eval_window['Low'] < price]
            if not sweep_candidates.empty:
                temp_first_sweep = sweep_candidates.index[0]
                if ltype == 'Last Month Low (PML)' and temp_first_sweep.to_period('M') != current_month_period: continue
                if temp_first_sweep <= date: continue
                sweep_occurred, first_sweep_day, swept_level_details = True, temp_first_sweep, (price, date, ltype)
                break 
                
        if not sweep_occurred: return None
        
        sweep_low_price = eval_window['Low'].min()
        pre_sweep_data = df.loc[:first_sweep_day].iloc[-30:-1]
        
        swing_highs_info = []
        for i in range(1, len(pre_sweep_data)-1):
            if pre_sweep_data['High'].iloc[i] > pre_sweep_data['High'].iloc[i-1] and pre_sweep_data['High'].iloc[i] > pre_sweep_data['High'].iloc[i+1]:
                swing_highs_info.append({'price': pre_sweep_data['High'].iloc[i], 'time': pre_sweep_data.index[i]})
        
        if not swing_highs_info: return None
        
        nearest_pre_sweep_high = None
        for sh in reversed(swing_highs_info):
            subsequent_data = pre_sweep_data.loc[sh['time']:].iloc[1:]
            if subsequent_data.empty or subsequent_data['High'].max() < sh['price']:
                nearest_pre_sweep_high = sh['price']
                break
                
        if nearest_pre_sweep_high is None: return None
        
        post_sweep_data = df.loc[first_sweep_day:]
        breakout_days = post_sweep_data[post_sweep_data['Close'] > nearest_pre_sweep_high]
        if breakout_days.empty: return None 
            
        trading_days_to_mss = df.index.get_loc(breakout_days.index[0]) - df.index.get_loc(first_sweep_day)
        if trading_days_to_mss > 10: return None
            
        displacement_high = post_sweep_data['High'].max()
        dealing_range_50_level = sweep_low_price + (displacement_high - sweep_low_price) * 0.5
        
        post_high_data = post_sweep_data.loc[post_sweep_data['High'].idxmax():]
        if not post_high_data.empty and post_high_data['Low'].min() <= dealing_range_50_level: return None 
        if cmp <= dealing_range_50_level: return None
            
        return {
            "Stock Symbol": ticker.replace('.NS', ''),
            "Swept Liquidity": swept_level_details[2],
            "Level Price (₹)": round(swept_level_details[0], 2),
            "Sweep Low (₹)": round(sweep_low_price, 2),
            "Prior Swing High (₹)": round(nearest_pre_sweep_high, 2),
            "Days to MSS": trading_days_to_mss,
            "Displacement High (₹)": round(displacement_high, 2),
            "Untested 50% Eq. (₹)": round(dealing_range_50_level, 2),
            "Live CMP (₹)": round(cmp, 2),
            "Distance to Entry (%)": round(((cmp - dealing_range_50_level) / cmp) * 100, 2)
        }
    except Exception:
        return None

# ==========================================
# TAB 2: 15-MIN INTRADAY SETUP
# ==========================================
def find_ict_15m_intraday_setups(ticker):
    try:
        t = yf.Ticker(ticker)
        df = t.history(period="5d", interval="15m", auto_adjust=False)
        if df.empty or len(df) < 20: return None
        cmp = float(df['Close'].iloc[-1])
        if pd.isna(cmp) or cmp <= 60: return None
        
        unique_dates = pd.Series(df.index.date).unique()
        if len(unique_dates) < 2: return None
        
        yesterday_date = unique_dates[-2]
        today_date = unique_dates[-1]
        
        yesterday_data = df[df.index.date == yesterday_date]
        today_data = df[df.index.date == today_date]
        if yesterday_data.empty or today_data.empty: return None
        
        pdl = yesterday_data['Low'].min()
        sweep_candidates = today_data[today_data['Low'] < pdl]
        if sweep_candidates.empty: return None
        
        absolute_sweep_time = today_data['Low'].idxmin()
        sweep_low_price = today_data['Low'].min()
        
        pre_sweep_data = df.loc[:absolute_sweep_time].iloc[:-1]
        if len(pre_sweep_data) < 5: return None
        
        swing_highs_info = []
        for i in range(2, len(pre_sweep_data)-2):
            if (pre_sweep_data['High'].iloc[i] > pre_sweep_data['High'].iloc[i-1] and 
                pre_sweep_data['High'].iloc[i] > pre_sweep_data['High'].iloc[i-2] and 
                pre_sweep_data['High'].iloc[i] > pre_sweep_data['High'].iloc[i+1] and 
                pre_sweep_data['High'].iloc[i] > pre_sweep_data['High'].iloc[i+2]):
                
                swing_highs_info.append({'price': pre_sweep_data['High'].iloc[i], 'time': pre_sweep_data.index[i]})
                
        if not swing_highs_info: return None
        
        valid_pre_sweep_high = None
        for sh in reversed(swing_highs_info):
            subsequent_data = pre_sweep_data.loc[sh['time']:].iloc[1:] 
            if subsequent_data.empty or subsequent_data['High'].max() < sh['price']:
                valid_pre_sweep_high = sh['price']
                break
                
        if valid_pre_sweep_high is None: return None
        
        post_sweep_data = df.loc[absolute_sweep_time:]
        breakout_candles = post_sweep_data[post_sweep_data['Close'] > valid_pre_sweep_high]
        if breakout_candles.empty: return None
        
        displacement_high = post_sweep_data['High'].max()
        displacement_high_time = post_sweep_data['High'].idxmax()
        eq_50_level = sweep_low_price + (displacement_high - sweep_low_price) * 0.5
        
        post_high_data = post_sweep_data.loc[displacement_high_time:]
        if not post_high_data.empty and post_high_data['Low'].min() <= eq_50_level: return None
        if cmp <= eq_50_level: return None
        
        return {
            "Stock Symbol": ticker.replace('.NS', ''),
            "PDL Swept (₹)": round(pdl, 2),
            "15m Sweep Low (₹)": round(sweep_low_price, 2),
            "15m Pre-Sweep High (₹)": round(valid_pre_sweep_high, 2),
            "15m Displacement High (₹)": round(displacement_high, 2),
            "15m Entry 50% Eq (₹)": round(eq_50_level, 2),
            "Live CMP (₹)": round(cmp, 2),
            "Distance to Entry (%)": round(((cmp - eq_50_level) / cmp) * 100, 2)
        }
    except Exception:
        return None

# ==========================================
# TAB 3 & 4: EMA 20 RESTING SETUP (LIVE & BACKTEST)
# ==========================================
def find_ema20_resting_setups(ticker):
    try:
        t = yf.Ticker(ticker)
        df = t.history(period="1y", interval="1d", auto_adjust=False)
        if df.empty or len(df) < 50: return None
        try: cmp = float(t.fast_info.last_price)
        except Exception: cmp = float(df['Close'].iloc[-1])
        if pd.isna(cmp) or cmp <= 60: return None

        df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
        if not check_ema20_rounded_bottom(df['EMA20']): return None

        current_month_period = df.index[-1].to_period('M')
        previous_month_period = current_month_period - 1
        
        prev_month_data = df[df.index.to_period('M') == previous_month_period]
        if prev_month_data.empty: return None
        pml = prev_month_data['Low'].min()
        
        curr_month_data = df[df.index.to_period('M') == current_month_period]
        sweep_candidates = curr_month_data[curr_month_data['Low'] < pml]
        if sweep_candidates.empty: return None
        
        absolute_sweep_day = sweep_candidates['Low'].idxmin()
        post_sweep_data = df.loc[absolute_sweep_day:]
        breakout_days = post_sweep_data[post_sweep_data['Close'] > post_sweep_data['EMA20']]
        if breakout_days.empty: return None
        
        current_ema20 = df['EMA20'].iloc[-1]
        if cmp < current_ema20: return None 
        buffer_zone_ceiling = current_ema20 * 1.015
        if cmp > buffer_zone_ceiling: return None 
        
        return {
            "Stock Symbol": ticker.replace('.NS', ''),
            "PML Swept (₹)": round(pml, 2),
            "Current EMA20 (₹)": round(current_ema20, 2),
            "Live CMP (₹)": round(cmp, 2),
            "Distance to EMA20 (%)": round(((cmp - current_ema20) / current_ema20) * 100, 2)
        }
    except Exception:
        return None

def backtest_ema20_setups(ticker, target_year, target_month):
    try:
        t = yf.Ticker(ticker)
        df = t.history(period="2y", interval="1d", auto_adjust=False)
        if df.empty or len(df) < 50: return []
        df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
        target_dates = df[(df.index.year == target_year) & (df.index.month == target_month)].index
        valid_setups = []
        for current_day in target_dates:
            idx = df.index.get_loc(current_day)
            if idx < 30: continue
            cmp_on_day = df['Close'].iloc[idx]
            if pd.isna(cmp_on_day) or cmp_on_day <= 60: continue
            
            current_period = current_day.to_period('M')
            prev_month_data = df[df.index.to_period('M') == current_period - 1]
            if prev_month_data.empty: continue
            pml = prev_month_data['Low'].min()
            
            curr_month_so_far = df[(df.index.to_period('M') == current_period) & (df.index <= current_day)]
            sweep_candidates = curr_month_so_far[curr_month_so_far['Low'] < pml]
            if sweep_candidates.empty: continue
            
            if not check_ema20_rounded_bottom(df['EMA20'].iloc[idx-20:idx+1]): continue
            
            post_sweep_data = df.loc[sweep_candidates['Low'].idxmin():current_day]
            if post_sweep_data[post_sweep_data['Close'] > post_sweep_data['EMA20']].empty: continue
            
            current_ema20 = df['EMA20'].iloc[idx]
            if cmp_on_day < current_ema20 or cmp_on_day > current_ema20 * 1.015: continue 
            
            valid_setups.append({
                "Stock Symbol": ticker.replace('.NS', ''),
                "Trigger Date": current_day.strftime('%Y-%m-%d'),
                "PML Swept (₹)": round(pml, 2),
                "EMA20 Level (₹)": round(current_ema20, 2),
                "Closing Price (₹)": round(cmp_on_day, 2)
            })
        return valid_setups
    except Exception:
        return []

# ==========================================
# TAB 5: STRICT EMA 20 (DATE RANGE BACKTEST)
# ==========================================
def backtest_strict_ema20_date_range(ticker, start_date, end_date):
    try:
        t = yf.Ticker(ticker)
        df = t.history(period="2y", interval="1d", auto_adjust=False)
        if df.empty or len(df) < 50: return []
        
        df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
        
        target_dates = df[(df.index.date >= start_date) & (df.index.date <= end_date)].index
        valid_setups = []
        
        for current_day in target_dates:
            idx = df.index.get_loc(current_day)
            if idx < 30: continue
            
            cmp_on_day = float(df['Close'].iloc[idx])
            if pd.isna(cmp_on_day) or cmp_on_day <= 60: continue
            
            target_period = current_day.to_period('M')
            prev_month_data = df[df.index.to_period('M') == target_period - 1]
            if prev_month_data.empty: continue
            pml = prev_month_data['Low'].min()
            
            curr_month_so_far = df[(df.index.to_period('M') == target_period) & (df.index <= current_day)]
            sweep_candidates = curr_month_so_far[curr_month_so_far['Low'] < pml]
            if sweep_candidates.empty: continue
            
            absolute_sweep_day = sweep_candidates['Low'].idxmin()
            sweep_idx = df.index.get_loc(absolute_sweep_day)
            
            if sweep_idx < 5: continue
            ema_pre_sweep_start = df['EMA20'].iloc[sweep_idx - 5]
            ema_at_sweep = df['EMA20'].iloc[sweep_idx]
            if ema_at_sweep >= ema_pre_sweep_start: continue
            
            post_sweep_data = df.iloc[sweep_idx:idx+1]
            touches = post_sweep_data[post_sweep_data['High'] >= post_sweep_data['EMA20']]
            if touches.empty: continue
            
            first_touch_date = touches.index[0]
            first_touch_idx = df.index.get_loc(first_touch_date)
            
            window_start = max(0, first_touch_idx - 15)
            pre_touch_window = df.iloc[window_start:first_touch_idx]
            touch_count = len(pre_touch_window[pre_touch_window['High'] >= pre_touch_window['EMA20']])
            
            if touch_count > 2: continue
            
            target_ema = df['EMA20'].iloc[idx]
            if cmp_on_day < target_ema: continue
            buffer_zone_ceiling = target_ema * 1.015
            if cmp_on_day > buffer_zone_ceiling: continue
            
            distance_to_ema = ((cmp_on_day - target_ema) / target_ema) * 100
            
            valid_setups.append({
                "Stock Symbol": ticker.replace('.NS', ''),
                "Trigger Date": current_day.strftime('%Y-%m-%d'),
                "PML Swept (₹)": round(pml, 2),
                "First Touch Date": first_touch_date.strftime('%Y-%m-%d'),
                "Pre-Touch Hits (15d)": touch_count,
                "EMA20 Level (₹)": round(target_ema, 2),
                "Closing Price (₹)": round(cmp_on_day, 2),
                "Distance to EMA20 (%)": round(distance_to_ema, 2)
            })
            
        return valid_setups
    except Exception:
        return []

# ==========================================
# TAB 6 & 7: EXPANDING DIVERGENCE SETUP & BACKTESTER
# ==========================================
def find_expanding_divergence_setup(ticker):
    try:
        t = yf.Ticker(ticker)
        df = t.history(period="2y", interval="1d", auto_adjust=False)
        if df.empty or len(df) < 130: return None
        
        try: cmp = float(t.fast_info.last_price)
        except Exception: cmp = float(df['Close'].iloc[-1])
        if pd.isna(cmp) or cmp <= 60: return None
        
        df['EMA20'] = df['Close'].ewm(span=20, adjust=False).mean()
        current_date = df.index[-1]
        
        curr_month = current_date.to_period('M')
        prev_month_data = df[df.index.to_period('M') == curr_month - 1]
        pml = prev_month_data['Low'].min() if not prev_month_data.empty else np.nan
        
        curr_quarter = current_date.to_period('Q')
        prev_quarter_data = df[df.index.to_period('Q') == curr_quarter - 1]
        pql = prev_quarter_data['Low'].min() if not prev_quarter_data.empty else np.nan
        
        curr_half = 1 if current_date.month <= 6 else 2
        prev_half_year = current_date.year - 1 if curr_half == 1 else current_date.year
        prev_half = 2 if curr_half == 1 else 1
        
        prev_half_data = df[(df.index.year == prev_half_year) &
