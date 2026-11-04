import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import io
import concurrent.futures
import time
import os
import pickle
import gc
from datetime import datetime, date, time as dtime
import warnings
import logging

warnings.filterwarnings('ignore')
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

st.set_page_config(page_title="GTF MIT & WIT Demand Zone Scanner", layout="wide")

CACHE_DIR_DAILY = "/tmp/gtf_daily_cache"
CACHE_DIR_1H = "/tmp/gtf_1h_cache"
os.makedirs(CACHE_DIR_DAILY, exist_ok=True)
os.makedirs(CACHE_DIR_1H, exist_ok=True)

# -------------------------------------------------------------
# 1. STOCK UNIVERSE LOADERS
# -------------------------------------------------------------
@st.cache_data(ttl=86400)
def get_nifty50_symbols():
    url = "https://niftyindices.com/IndexConstituent/ind_nifty50list.csv"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        df = pd.read_csv(io.StringIO(res.text))
        return [str(s).strip() + '.NS' for s in df['Symbol']]
    except Exception:
        return ['RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'ICICIBANK.NS', 'INFY.NS', 'SBIN.NS', 'BHARTIARTL.NS']

@st.cache_data(ttl=86400)
def get_nifty500_symbols():
    url = "https://niftyindices.com/IndexConstituent/ind_nifty500list.csv"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        df = pd.read_csv(io.StringIO(res.text))
        return [str(s).strip() + '.NS' for s in df['Symbol']]
    except Exception:
        return get_nifty50_symbols()

@st.cache_data(ttl=86400)
def get_all_nse_symbols():
    url = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        df = pd.read_csv(io.StringIO(response.text))
        df.columns = df.columns.str.strip()
        df = df[df['SERIES'] == 'EQ']
        return [str(symbol).strip() + '.NS' for symbol in df['SYMBOL']]
    except Exception:
        return get_nifty500_symbols()

# -------------------------------------------------------------
# 2. DATA LOADERS (DAILY & 1-HOUR CACHING)
# -------------------------------------------------------------
def load_daily_data(ticker, force_refresh=False):
    safe_ticker = ticker.replace('.NS', '').replace('^', '').replace('&', '_')
    filepath = os.path.join(CACHE_DIR_DAILY, f"{safe_ticker}.pkl")
    
    if not force_refresh and os.path.exists(filepath):
        try:
            with open(filepath, 'rb') as f:
                df = pickle.load(f)
            if df is not None and not df.empty and len(df) >= 60:
                return ticker, df
        except Exception:
            pass
            
    for attempt in range(2):
        try:
            t = yf.Ticker(ticker)
            df = t.history(period="3y", interval="1d", auto_adjust=False)
            if df is not None and not df.empty and len(df) >= 60:
                df.index = df.index.tz_localize(None)
                with open(filepath, 'wb') as f:
                    pickle.dump(df, f)
                return ticker, df
        except Exception:
            time.sleep(0.5 + attempt)
        time.sleep(0.04)
        
    return ticker, None

def load_1h_data(ticker, force_refresh=False):
    safe_ticker = ticker.replace('.NS', '').replace('^', '').replace('&', '_')
    filepath = os.path.join(CACHE_DIR_1H, f"{safe_ticker}.pkl")
    
    if not force_refresh and os.path.exists(filepath):
        try:
            with open(filepath, 'rb') as f:
                df = pickle.load(f)
            if df is not None and not df.empty and len(df) >= 100:
                return ticker, df
        except Exception:
            pass
            
    for attempt in range(2):
        try:
            t = yf.Ticker(ticker)
            df = t.history(period="730d", interval="1h", auto_adjust=False)
            if df is not None and not df.empty and len(df) >= 100:
                df.index = df.index.tz_localize(None)
                with open(filepath, 'wb') as f:
                    pickle.dump(df, f)
                return ticker, df
        except Exception:
            time.sleep(0.5 + attempt)
        time.sleep(0.04)
        
    return ticker, None

# -------------------------------------------------------------
# 3. MIT STRATEGY ENGINE (DAILY LTF, WEEKLY ITF, MONTHLY HTF)
# -------------------------------------------------------------
def analyze_mit_trade(ticker, df_d, target_year, target_month, risk_per_trade=2000, 
                      apply_max_sl=True, filter_high_curve=True, require_bullish_eq=True):
    try:
        cmp = float(df_d['Close'].iloc[-1])
        if cmp < 100:
            return None

        # Build Weekly (ITF) and Monthly (HTF) from Daily
        df_w = df_d.resample('W-FRI').agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).dropna()
        
        df_m = df_d.resample('ME').agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).dropna()

        df_w['EMA20'] = df_w['Close'].ewm(span=20, adjust=False).mean()

        # Daily Candle Classifications
        df_d['Range'] = (df_d['High'] - df_d['Low']).replace(0, np.nan)
        df_d['Body'] = abs(df_d['Close'] - df_d['Open'])
        df_d['Body_Ratio'] = df_d['Body'] / df_d['Range']
        df_d['isLegIn'] = df_d['Body_Ratio'] > 0.55
        df_d['isBase'] = df_d['Body_Ratio'] < 0.45
        df_d['isBullish'] = df_d['Close'] > df_d['Open']
        df_d['isLegOut'] = df_d['isBullish'] & (df_d['Body_Ratio'] > 0.55)

        results = []
        n = len(df_d)
        max_hold_days = 25  # Swing horizon for MIT (~1 month)

        for i in range(3, n - 1):
            if not df_d['isLegOut'].iloc[i]:
                continue

            is_1base = df_d['isBase'].iloc[i-1] and df_d['isLegIn'].iloc[i-2]
            is_2base = False
            if i >= 4:
                is_2base = df_d['isBase'].iloc[i-1] and df_d['isBase'].iloc[i-2] and df_d['isLegIn'].iloc[i-3]

            if not (is_1base or is_2base):
                continue

            if is_1base:
                base_high = df_d['High'].iloc[i-1]
                proximal = max(df_d['Open'].iloc[i-1], df_d['Close'].iloc[i-1])
                distal = df_d['Low'].iloc[i-1]
            else:
                base_high = max(df_d['High'].iloc[i-1], df_d['High'].iloc[i-2])
                proximal = max(df_d['Open'].iloc[i-1], df_d['Close'].iloc[i-1], df_d['Open'].iloc[i-2], df_d['Close'].iloc[i-2])
                distal = min(df_d['Low'].iloc[i-1], df_d['Low'].iloc[i-2])

            if df_d['Close'].iloc[i] < (base_high * 1.005):
                continue

            # Departure Rally
            curr = i
            while curr + 1 < n and df_d['isLegOut'].iloc[curr + 1]:
                curr += 1
            last_legout_idx = curr
            pct_move = ((df_d['Close'].iloc[last_legout_idx] - proximal) / proximal) * 100
            if pct_move < 6.0:
                continue

            raw_sl_pct = (proximal - distal) / proximal
            if apply_max_sl and raw_sl_pct > 0.02:
                proximal = distal / 0.98

            sl_points = proximal - distal
            if sl_points <= 0:
                continue

            # Strict 1:2 Risk to Reward Target
            target_price = proximal + (2 * sl_points)
            qty = int(risk_per_trade / sl_points) if sl_points > 0 else 0

            # Forward Retest Scan
            is_tested = False
            is_invalidated = False
            entry_idx = None

            for j in range(last_legout_idx + 1, n):
                day_low = df_d['Low'].iloc[j]
                day_close = df_d['Close'].iloc[j]

                if not is_tested:
                    if day_close < distal:
                        is_invalidated = True
                        break
                    if day_low <= (proximal * 1.0025):
                        is_tested = True
                        entry_idx = j
                        break

            if is_tested and not is_invalidated and entry_idx is not None:
                entry_dt = df_d.index[entry_idx]

                if entry_dt.year == target_year and entry_dt.month == target_month:
                    
                    # 1. HTF Curve Analysis (Monthly 12-month range)
                    m_slice = df_m[df_m.index <= entry_dt].iloc[-12:]
                    if len(m_slice) >= 4:
                        m_high = m_slice['High'].max()
                        m_low = m_slice['Low'].min()
                        curve_pos = (proximal - m_low) / (m_high - m_low) if (m_high - m_low) > 0 else 0.5
                    else:
                        curve_pos = 0.5

                    # 2. ITF Trend Analysis (Weekly 20 EMA)
                    w_slice = df_w[df_w.index <= entry_dt]
                    weekly_bullish = False
                    if len(w_slice) >= 2:
                        weekly_bullish = w_slice['Close'].iloc[-1] >= (w_slice['EMA20'].iloc[-1] * 0.97)

                    curve_label = "Low on Curve" if curve_pos <= 0.40 else ("Equilibrium" if curve_pos <= 0.65 else "High on Curve")
                    trend_label = "Weekly Bullish" if weekly_bullish else "Weekly Neutral/Bearish"

                    # --- STRICT GTF CURVE & TREND FILTERS ---
                    if filter_high_curve and "High" in curve_label:
                        continue  # Rule 1: Strictly reject buying when High on the Curve!
                    
                    if require_bullish_eq and "Equilibrium" in curve_label and not weekly_bullish:
                        continue  # Rule 2: Equilibrium only allowed with confirmed Bullish Trend!

                    # 3. Trade Outcome Evaluation
                    outcome = "Pending"
                    exit_date = "Open"
                    pnl_rs = 0.0

                    for k in range(entry_idx, min(entry_idx + max_hold_days + 1, n)):
                        k_low = df_d['Low'].iloc[k]
                        k_high = df_d['High'].iloc[k]
                        k_close = df_d['Close'].iloc[k]
                        days_held = k - entry_idx

                        if k_low < distal:
                            outcome = "Loss (-1R)"
                            exit_date = df_d.index[k].strftime('%Y-%m-%d')
                            pnl_rs = -(qty * sl_points)
                            break

                        target_hit = (k_close >= target_price) if (k == entry_idx) else (k_high >= target_price)
                        if target_hit:
                            outcome = "Win (1:2 RR)"
                            exit_date = df_d.index[k].strftime('%Y-%m-%d')
                            pnl_rs = qty * (target_price - proximal)
                            break

                        if days_held >= max_hold_days:
                            outcome = "Time Exit (Win)" if k_close >= proximal else "Time Exit (Loss)"
                            exit_date = df_d.index[k].strftime('%Y-%m-%d')
                            pnl_rs = qty * (k_close - proximal)
                            break

                    results.append({
                        "Stock Symbol": ticker.replace('.NS', ''),
                        "Trade Type": "MIT",
                        "Timeframes": "HTF: M | ITF: W | LTF: 1D",
                        "Entry Date": entry_dt.strftime('%Y-%m-%d'),
                        "Exit Date": exit_date,
                        "Entry (₹)": round(proximal, 2),
                        "SL (₹)": round(distal, 2),
                        "Target (1:2) (₹)": round(target_price, 2),
                        "SL %": round((sl_points / proximal) * 100, 2),
                        "Qty": qty,
                        "Curve Position": curve_label,
                        "Trend Status": trend_label,
                        "Outcome": outcome,
                        "P&L (₹)": round(pnl_rs, 2)
                    })

        return results if results else None
    except Exception:
        return None

# -------------------------------------------------------------
# 4. WIT STRATEGY ENGINE (1-HOUR LTF, DAILY ITF, WEEKLY HTF)
# -------------------------------------------------------------
def analyze_wit_trade(ticker, df_d, df_1h, target_year, target_month, risk_per_trade=2000, 
                      apply_max_sl=True, filter_high_curve=True, require_bullish_eq=True, only_after_10am=True):
    try:
        cmp = float(df_d['Close'].iloc[-1])
        if cmp < 100 or df_1h is None or df_1h.empty:
            return None

        # Build Weekly (HTF) from Daily
        df_w = df_d.resample('W-FRI').agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).dropna()

        # Daily (ITF) 20 EMA
        df_d['EMA20'] = df_d['Close'].ewm(span=20, adjust=False).mean()

        # 1-Hour (LTF) Candle Classifications
        df_1h['Range'] = (df_1h['High'] - df_1h['Low']).replace(0, np.nan)
        df_1h['Body'] = abs(df_1h['Close'] - df_1h['Open'])
        df_1h['Body_Ratio'] = df_1h['Body'] / df_1h['Range']
        df_1h['isLegIn'] = df_1h['Body_Ratio'] > 0.55
        df_1h['isBase'] = df_1h['Body_Ratio'] < 0.45
        df_1h['isBullish'] = df_1h['Close'] > df_1h['Open']
        df_1h['isLegOut'] = df_1h['isBullish'] & (df_1h['Body_Ratio'] > 0.55)

        results = []
        n = len(df_1h)
        max_hourly_bars = 42  # ~6 trading days (7 bars/day * 6)

        for i in range(3, n - 1):
            if not df_1h['isLegOut'].iloc[i]:
                continue

            is_1base = df_1h['isBase'].iloc[i-1] and df_1h['isLegIn'].iloc[i-2]
            is_2base = False
            if i >= 4:
                is_2base = df_1h['isBase'].iloc[i-1] and df_1h['isBase'].iloc[i-2] and df_1h['isLegIn'].iloc[i-3]

            if not (is_1base or is_2base):
                continue

            if is_1base:
                base_high = df_1h['High'].iloc[i-1]
                proximal = max(df_1h['Open'].iloc[i-1], df_1h['Close'].iloc[i-1])
                distal = df_1h['Low'].iloc[i-1]
            else:
                base_high = max(df_1h['High'].iloc[i-1], df_1h['High'].iloc[i-2])
                proximal = max(df_1h['Open'].iloc[i-1], df_1h['Close'].iloc[i-1], df_1h['Open'].iloc[i-2], df_1h['Close'].iloc[i-2])
                distal = min(df_1h['Low'].iloc[i-1], df_1h['Low'].iloc[i-2])

            if df_1h['Close'].iloc[i] < (base_high * 1.0025):
                continue

            # Departure move on 1-hour chart (>= 3.5%)
            curr = i
            while curr + 1 < n and df_1h['isLegOut'].iloc[curr + 1]:
                curr += 1
            last_legout_idx = curr
            pct_move = ((df_1h['Close'].iloc[last_legout_idx] - proximal) / proximal) * 100
            if pct_move < 3.5:
                continue

            raw_sl_pct = (proximal - distal) / proximal
            if apply_max_sl and raw_sl_pct > 0.02:
                proximal = distal / 0.98

            sl_points = proximal - distal
            if sl_points <= 0:
                continue

            # Strict 1:2 Target
            target_price = proximal + (2 * sl_points)
            qty = int(risk_per_trade / sl_points) if sl_points > 0 else 0

            # Forward Retest Scan on 1-Hour Bars
            is_tested = False
            is_invalidated = False
            entry_idx = None

            for j in range(last_legout_idx + 1, n):
                bar_low = df_1h['Low'].iloc[j]
                bar_close = df_1h['Close'].iloc[j]
                bar_time = df_1h.index[j].time()

                if not is_tested:
                    if bar_close < distal:
                        is_invalidated = True
                        break
                    if bar_low <= (proximal * 1.0025):
                        if only_after_10am and bar_time < dtime(10, 0):
                            is_invalidated = True
                            break
                        is_tested = True
                        entry_idx = j
                        break

            if is_tested and not is_invalidated and entry_idx is not None:
                entry_dt = df_1h.index[entry_idx]

                if entry_dt.year == target_year and entry_dt.month == target_month:
                    
                    # 1. HTF Curve Analysis (Weekly 26-week range)
                    w_slice = df_w[df_w.index <= entry_dt].iloc[-26:]
                    if len(w_slice) >= 4:
                        w_high = w_slice['High'].max()
                        w_low = w_slice['Low'].min()
                        curve_pos = (proximal - w_low) / (w_high - w_low) if (w_high - w_low) > 0 else 0.5
                    else:
                        curve_pos = 0.5

                    # 2. ITF Trend Analysis (Daily 20 EMA)
                    d_slice = df_d[df_d.index <= entry_dt]
                    daily_bullish = False
                    if len(d_slice) >= 2:
                        daily_bullish = d_slice['Close'].iloc[-1] >= (d_slice['EMA20'].iloc[-1] * 0.98)

                    curve_label = "Low on Weekly" if curve_pos <= 0.40 else ("Equilibrium" if curve_pos <= 0.65 else "High on Weekly")
                    trend_label = "Daily Bullish" if daily_bullish else "Daily Neutral/Bearish"

                    # --- STRICT GTF CURVE & TREND FILTERS ---
                    if filter_high_curve and "High" in curve_label:
                        continue  # Rule 1: Strictly reject buying when High on Weekly Curve!
                    
                    if require_bullish_eq and "Equilibrium" in curve_label and not daily_bullish:
                        continue  # Rule 2: Equilibrium only allowed with confirmed Bullish Trend!

                    # 3. Trade Outcome Evaluation on Hourly Bars
                    outcome = "Pending"
                    exit_date = "Open"
                    pnl_rs = 0.0

                    for k in range(entry_idx, min(entry_idx + max_hourly_bars + 1, n)):
                        k_low = df_1h['Low'].iloc[k]
                        k_high = df_1h['High'].iloc[k]
                        k_close = df_1h['Close'].iloc[k]
                        bars_held = k - entry_idx

                        if k_low < distal:
                            outcome = "Loss (-1R)"
                            exit_date = df_1h.index[k].strftime('%Y-%m-%d %H:%M')
                            pnl_rs = -(qty * sl_points)
                            break

                        if k_high >= target_price:
                            outcome = "Win (1:2 RR)"
                            exit_date = df_1h.index[k].strftime('%Y-%m-%d %H:%M')
                            pnl_rs = qty * (target_price - proximal)
                            break

                        if bars_held >= max_hourly_bars:
                            outcome = "Time Exit (Win)" if k_close >= proximal else "Time Exit (Loss)"
                            exit_date = df_1h.index[k].strftime('%Y-%m-%d %H:%M')
                            pnl_rs = qty * (k_close - proximal)
                            break

                    results.append({
                        "Stock Symbol": ticker.replace('.NS', ''),
                        "Trade Type": "WIT",
                        "Timeframes": "HTF: W | ITF: 1D | LTF: 1H",
                        "Entry Date": entry_dt.strftime('%Y-%m-%d %H:%M'),
                        "Exit Date": exit_date,
                        "Entry (₹)": round(proximal, 2),
                        "SL (₹)": round(distal, 2),
                        "Target (1:2) (₹)": round(target_price, 2),
                        "SL %": round((sl_points / proximal) * 100, 2),
                        "Qty": qty,
                        "Curve Position": curve_label,
                        "Trend Status": trend_label,
                        "Outcome": outcome,
                        "P&L (₹)": round(pnl_rs, 2)
                    })

        return results if results else None
    except Exception:
        return None

# -------------------------------------------------------------
# 5. STREAMLIT INTERFACE
# -------------------------------------------------------------
st.title("GTF Demand Zone Backtester (MIT & WIT)")
st.markdown("Automated Multiple Timeframe Analysis (MTFA) with strict GTF institutional rules and **1:2 Risk-Reward**.")

st.sidebar.header("Strategy Settings")

# 1. Trade Type Selector
trade_type = st.sidebar.selectbox(
    "Select Trade Type:",
    (
        "MIT (Monthly Income Trade - Daily Execution)", 
        "WIT (Weekly Income Trade - 1-Hour LTF Execution)"
    ),
    index=0
)

# 2. Month Selector Dropdown
month_options = {
    "October 2026": (2026, 10),
    "September 2026": (2026, 9),
    "August 2026": (2026, 8),
    "July 2026": (2026, 7),
    "June 2026": (2026, 6),
    "May 2026": (2026, 5),
    "April 2026": (2026, 4),
    "March 2026": (2026, 3),
    "February 2026": (2026, 2),
    "January 2026": (2026, 1),
    "December 2025": (2025, 12),
    "November 2025": (2025, 11),
    "October 2025": (2025, 10)
}

selected_month_name = st.sidebar.selectbox(
    "Select Backtest Month:",
    list(month_options.keys()),
    index=0
)
target_year, target_month = month_options[selected_month_name]

# Universe Selection
universe = st.sidebar.selectbox("Select Stock Universe:", ("Nifty 500", "Nifty 50 (Fast Verification)"), index=0)

st.sidebar.markdown("---")
st.sidebar.write("**GTF Location & Trend Filters:**")
filter_high_curve = st.sidebar.toggle("Filter Out 'High on Curve' Setups", value=True, help="Strictly prohibits buying in demand zones when price is High on the Curve near HTF supply.")
require_bullish_eq = st.sidebar.toggle("Require Bullish Trend for Equilibrium", value=True, help="Only permits taking Equilibrium setups if the Intermediate Timeframe trend is confirmed Bullish.")

st.sidebar.markdown("---")
st.sidebar.write("**Execution Controls:**")
only_after_10am = st.sidebar.toggle("Only Allow Entry After 10:00 AM (for WIT)", value=True, help="Avoids taking entries triggered during the opening 45-min volatility (9:15–10:00 AM).")
apply_max_sl = st.sidebar.toggle("Enforce Max 2% SL Shift", value=True)
risk_per_trade = st.sidebar.number_input("Risk Per Trade (₹):", min_value=500, max_value=50000, value=2000, step=500)
force_refresh = st.sidebar.checkbox("Force Redownload Fresh Data", value=False)

# Run Scan Button
if st.sidebar.button("Run Scan", type="primary"):
    tickers = get_nifty500_symbols() if universe == "Nifty 500" else get_nifty50_symbols()
    
    all_trades = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    is_wit = "WIT" in trade_type
    tf_label = "1-Hour LTF" if is_wit else "Daily LTF"
    
    with st.spinner(f"Scanning {len(tickers)} stocks for {selected_month_name} ({trade_type[:3]} using {tf_label})..."):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            if is_wit:
                # WIT requires Daily + 1-Hour data
                future_to_ticker = {
                    executor.submit(
                        lambda t: (t, load_daily_data(t, force_refresh)[1], load_1h_data(t, force_refresh)[1])
                    ): t for t in tickers
                }
            else:
                # MIT requires Daily data (resampled to Weekly & Monthly)
                future_to_ticker = {
                    executor.submit(load_daily_data, t, force_refresh): t for t in tickers
                }
            
            completed = 0
            for future in concurrent.futures.as_completed(future_to_ticker):
                completed += 1
                res_tuple = future.result()
                
                if is_wit:
                    ticker, df_daily, df_hourly = res_tuple
                    if df_daily is not None and df_hourly is not None:
                        res = analyze_wit_trade(
                            ticker, df_daily, df_hourly, target_year, target_month, risk_per_trade,
                            apply_max_sl, filter_high_curve, require_bullish_eq, only_after_10am
                        )
                        if res:
                            all_trades.extend(res)
                        del df_daily, df_hourly
                else:
                    ticker, df_daily = res_tuple
                    if df_daily is not None:
                        res = analyze_mit_trade(
                            ticker, df_daily, target_year, target_month, risk_per_trade,
                            apply_max_sl, filter_high_curve, require_bullish_eq
                        )
                        if res:
                            all_trades.extend(res)
                        del df_daily
                
                if completed % 25 == 0 or completed == len(tickers):
                    gc.collect()
                    progress_bar.progress(completed / len(tickers))
                    status_text.text(f"Processed {completed}/{len(tickers)} stocks... (Found {len(all_trades)} valid setups)")

    status_text.text("Scan complete!")

    if all_trades:
        df_res = pd.DataFrame(all_trades)
        df_res = df_res.sort_values(by="Entry Date", ascending=True).reset_index(drop=True)

        total_trades = len(df_res)
        wins = len(df_res[df_res["Outcome"].str.contains("Win", na=False)])
        losses = len(df_res[df_res["Outcome"].str.contains("Loss", na=False)])
        pending = len(df_res[df_res["Outcome"] == "Pending"])
        closed = wins + losses
        win_rate = (wins / closed * 100) if closed > 0 else 0
        total_pnl = df_res["P&L (₹)"].sum()

        st.markdown(f"### Performance Dashboard — {selected_month_name} ({trade_type[:3]})")
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Win Rate", f"{win_rate:.1f}%")
        c2.metric("Total Net P&L", f"₹ {total_pnl:,.2f}", delta=f"{'Profit' if total_pnl >= 0 else 'Loss'}")
        c3.metric("Trades Triggered", total_trades)
        c4.metric("Wins (1:2 RR)", wins)
        c5.metric("Losses (-1R)", losses)

        def highlight_outcome(val):
            if 'Win' in str(val):
                return 'color: #00E676; font-weight: bold;'
            elif 'Loss' in str(val):
                return 'color: #FF5252; font-weight: bold;'
            return 'color: #B0BEC5;'

        st.markdown("#### Detailed Trade Log")
        st.dataframe(
            df_res.style.map(highlight_outcome, subset=['Outcome']).format({
                "Entry (₹)": "{:.2f}",
                "SL (₹)": "{:.2f}",
                "Target (1:2) (₹)": "{:.2f}",
                "SL %": "{:.2f}%",
                "P&L (₹)": "{:,.2f}"
            }),
            use_container_width=True,
            height=500
        )

        csv = df_res.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download Trade Results as CSV",
            data=csv,
            file_name=f"{trade_type[:3]}_{selected_month_name.replace(' ', '_')}_Clean_Results.csv",
            mime="text/csv"
        )
    else:
        st.warning(f"No {trade_type[:3]} setups matched all strict institutional filters in {selected_month_name}. Try selecting another month or testing Nifty 50.")
