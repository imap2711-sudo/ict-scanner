import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import io
import concurrent.futures
import time
from datetime import datetime, date
import warnings
import logging

warnings.filterwarnings('ignore')
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

st.set_page_config(page_title="NSE Demand Zone Scanner & Intraday Precision Backtester", layout="wide")

@st.cache_data(ttl=86400)
def get_live_nifty500_symbols():
    url = "https://niftyindices.com/IndexConstituent/ind_nifty500list.csv"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        df = pd.read_csv(io.StringIO(response.text))
        latest_tickers = [str(symbol).strip() + '.NS' for symbol in df['Symbol']]
        return latest_tickers
    except Exception:
        return []

@st.cache_data(ttl=86400)
def get_all_nse_symbols():
    url = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        df = pd.read_csv(io.StringIO(response.text))
        df.columns = df.columns.str.strip()
        df = df[df['SERIES'] == 'EQ']
        latest_tickers = [str(symbol).strip() + '.NS' for symbol in df['SYMBOL']]
        return latest_tickers
    except Exception:
        return []

def fetch_with_retry(ticker, period, interval, retries=3):
    for attempt in range(retries):
        try:
            t = yf.Ticker(ticker)
            df = t.history(period=period, interval=interval, auto_adjust=False)
            if not df.empty:
                return t, df
        except Exception:
            time.sleep(1 + attempt)
        time.sleep(0.2) # Gentle pacing to prevent 429 rate limit blocks
    return None, None

def analyze_ticker(ticker, mode, start_date=None, end_date=None, risk_amount=None, max_hold_days=None, apply_max_sl=True, apply_min_sl=False, is_intraday_mode=False):
    try:
        interval = "15m" if is_intraday_mode else "1d"
        period_str = "60d" if is_intraday_mode else "10y"
        
        t, df = fetch_with_retry(ticker, period_str, interval)
        if df is None or len(df) < 5: 
            return None
            
        df.index = df.index.tz_localize(None)

        try: cmp = float(t.fast_info.last_price)
        except: cmp = float(df['Close'].iloc[-1])

        if pd.isna(cmp) or cmp <= 100: 
            return None

        _, df_daily = fetch_with_retry(ticker, "10y", "1d")
        if df_daily is None or len(df_daily) < 5: return None
        df_daily.index = df_daily.index.tz_localize(None)

        cutoff_date = df_daily.index[-1] - pd.DateOffset(years=3)

        df_daily['Range'] = df_daily['High'] - df_daily['Low']
        df_daily['Body'] = abs(df_daily['Close'] - df_daily['Open'])
        df_daily['Range'] = df_daily['Range'].replace(0, np.nan)
        df_daily['Body_Ratio'] = df_daily['Body'] / df_daily['Range']

        df_daily['isLegIn'] = df_daily['Body_Ratio'] > 0.65
        df_daily['isBase'] = df_daily['Body_Ratio'] < 0.40
        df_daily['isBullish'] = df_daily['Close'] > df_daily['Open']
        df_daily['isLegOutCandle'] = df_daily['isBullish'] & (df_daily['Body_Ratio'] > 0.65)

        results = []
        
        for i in range(3, len(df_daily)):
            if not df_daily['isLegOutCandle'].iloc[i]: continue
                
            is_1base = df_daily['isBase'].iloc[i-1] and df_daily['isLegIn'].iloc[i-2]
            is_2base = False
            if i >= 4:
                is_2base = df_daily['isBase'].iloc[i-1] and df_daily['isBase'].iloc[i-2] and df_daily['isLegIn'].iloc[i-3]
            
            if not (is_1base or is_2base): continue
            
            zone_formation_date = df_daily.index[i-1]
            if zone_formation_date < cutoff_date: continue
                
            first_legout_range = df_daily['Range'].iloc[i]
            first_legout_close = df_daily['Close'].iloc[i]
            base_close = df_daily['Close'].iloc[i-1] 
            
            if is_1base:
                legin_range = df_daily['Range'].iloc[i-2]
                base_high = df_daily['High'].iloc[i-1]
                proximal_line = max(df_daily['Open'].iloc[i-1], df_daily['Close'].iloc[i-1])
                distal_line = df_daily['Low'].iloc[i-1]
                base_date = df_daily.index[i-1].strftime('%Y-%m-%d')
            else:
                legin_range = df_daily['Range'].iloc[i-3]
                base_high = max(df_daily['High'].iloc[i-1], df_daily['High'].iloc[i-2])
                proximal_line = max(df_daily['Open'].iloc[i-1], df_daily['Close'].iloc[i-1], df_daily['Open'].iloc[i-2], df_daily['Close'].iloc[i-2])
                distal_line = min(df_daily['Low'].iloc[i-1], df_daily['Low'].iloc[i-2])
                base_date = f"{df_daily.index[i-2].strftime('%Y-%m-%d')} to {df_daily.index[i-1].strftime('%Y-%m-%d')}"
            
            if legin_range < 0.5 * first_legout_range: continue
            if first_legout_close < (base_high * 1.01): continue
            
            current_idx = i
            total_legouts = 1
            pause_used = False
            
            while current_idx + 1 < len(df_daily):
                if df_daily['isLegOutCandle'].iloc[current_idx + 1]:
                    current_idx += 1
                    total_legouts += 1
                elif not pause_used and df_daily['isBase'].iloc[current_idx + 1] and current_idx + 2 < len(df_daily) and df_daily['isLegOutCandle'].iloc[current_idx + 2]:
                    current_idx += 2
                    total_legouts += 1
                    pause_used = True
                else:
                    break
                
            last_legout_idx = current_idx
            move_end_price = df_daily['Close'].iloc[last_legout_idx]
            pct_move = ((move_end_price - base_close) / base_close) * 100
            
            if pct_move < 7.0: continue
            
            sl_pct = (proximal_line - distal_line) / proximal_line
            if apply_max_sl and sl_pct > 0.02:
                proximal_line = distal_line / 0.98
                sl_pct = 0.02
                
            if apply_min_sl and sl_pct < 0.015:
                continue
                
            sl_points = proximal_line - distal_line
            target_price = proximal_line + (2 * sl_points)
            
            qty = 0
            if risk_amount and sl_points > 0:
                qty = int(risk_amount / sl_points)
                
            if is_intraday_mode:
                sub_df = df[(df.index.date >= start_date) & (df.index.date <= end_date)]
                if sub_df.empty: continue
                
                zone_tested = False
                entry_timestamp = None
                exit_timestamp = None
                outcome = "Pending"
                pnl_rs = 0.0
                
                for idx, row in sub_df.iterrows():
                    if not zone_tested:
                        if row['Low'] <= (proximal_line * 1.0025):
                            zone_tested = True
                            entry_timestamp = idx
                            
                            trade_bars = sub_df.loc[idx:]
                            for b_idx, b_row in trade_bars.iterrows():
                                if b_row['Low'] < distal_line:
                                    outcome = "Loss"
                                    pnl_rs = -(qty * sl_points) if risk_amount else 0.0
                                    exit_timestamp = b_idx
                                    break
                                elif b_row['High'] >= target_price:
                                    outcome = "Win"
                                    pnl_rs = (qty * (target_price - proximal_line)) if risk_amount else 0.0
                                    exit_timestamp = b_idx
                                    break
                            break
                
                if zone_tested and outcome != "Pending":
                    results.append({
                        "Stock Symbol": ticker.replace('.NS', ''),
                        "Entry Date": entry_timestamp.strftime('%Y-%m-%d'),
                        "Entry Time": entry_timestamp.strftime('%H:%M:%S'),
                        "Exit Date": exit_timestamp.strftime('%Y-%m-%d') if exit_timestamp else "N/A",
                        "Entry (₹)": round(proximal_line, 2),
                        "SL (₹)": round(distal_line, 2),
                        "Target (₹)": round(target_price, 2),
                        "Qty": qty,
                        "P&L (₹)": round(pnl_rs, 2),
                        "Outcome": outcome
                    })
            else:
                is_invalidated = False
                is_tested = False
                entry_idx = None
                outcome = "Pending"
                exit_date = None
                pnl_rs = 0.0
                
                for j in range(last_legout_idx + 1, len(df_daily)):
                    day_low = df_daily['Low'].iloc[j]
                    day_high = df_daily['High'].iloc[j]
                    day_close = df_daily['Close'].iloc[j]
                    
                    if not is_tested:
                        if day_close < distal_line:
                            is_invalidated = True
                            break 
                        if day_low <= (proximal_line * 1.0025):
                            is_tested = True
                            entry_idx = j
                            if mode == "Live Scan (Same Day)": break
                    
                    if is_tested and mode == "Historical Backtest":
                        days_in_trade = j - entry_idx
                        if day_low < distal_line: 
                            outcome = "Loss"
                            pnl_rs = -(qty * sl_points) if risk_amount else 0.0
                            exit_date = df_daily.index[j].date()
                            break
                        elif day_high >= target_price: 
                            outcome = "Win"
                            pnl_rs = (qty * (target_price - proximal_line)) if risk_amount else 0.0
                            exit_date = df_daily.index[j].date()
                            break
                        elif max_hold_days is not None and days_in_trade >= max_hold_days:
                            outcome = "Time Exit (Win)" if day_close >= proximal_line else "Time Exit (Loss)"
                            pnl_rs = (qty * (day_close - proximal_line)) if risk_amount else 0.0
                            exit_date = df_daily.index[j].date()
                            break
                
                if mode == "Historical Backtest" and is_tested and not is_invalidated:
                    entry_date = df_daily.index[entry_idx].date()
                    if start_date <= entry_date <= end_date:
                        results.append({
                            "Stock Symbol": ticker.replace('.NS', ''),
                            "Entry Date": entry_date.strftime('%Y-%m-%d'),
                            "Entry Time": "09:15:00 AM",
                            "Exit Date": exit_date.strftime('%Y-%m-%d') if exit_date else "N/A",
                            "Entry (₹)": round(proximal_line, 2),
                            "SL (₹)": round(distal_line, 2),
                            "Target (₹)": round(target_price, 2),
                            "Qty": qty,
                            "P&L (₹)": round(pnl_rs, 2),
                            "Outcome": outcome
                        })
            
        return results if results else None
    except Exception:
        return None

# --- STREAMLIT UI ---
st.title("NSE Demand Zone Scanner & Intraday Precision Backtester")
st.markdown("Fully rate-limited robust scanner across the entire NSE universe.")

st.sidebar.header("Scan Parameters")

universe = st.sidebar.selectbox(
    "Select Stock Universe:",
    ("Nifty 500", "All NSE Equities (Price > ₹100)")
)

mode = st.sidebar.radio("Select Mode:", ("Live Scan (Same Day)", "Historical Backtest"))

is_intraday_mode = False
if mode == "Historical Backtest":
    st.sidebar.markdown("---")
    is_intraday_mode = st.sidebar.toggle(
        "Use 15-Min Exact Timestamp Mode", 
        value=False, 
        help="Enables exact minute execution timestamps. Restricted to the last 60 days."
    )

st.sidebar.markdown("---")
st.sidebar.write("**Stop Loss Controls:**")
apply_max_sl = st.sidebar.toggle("Enforce Max 2% SL Shift", value=True)
apply_min_sl = st.sidebar.toggle("Enforce Min 1.5% SL Filter", value=False)

start_date, end_date = None, None
risk_per_trade = None
max_hold_days = None

if mode == "Historical Backtest":
    st.sidebar.markdown("---")
    st.sidebar.write("**Backtest Settings:**")
    
    risk_per_trade = st.sidebar.number_input(
        "Risk Per Trade (₹)", 
        min_value=100, 
        max_value=100000, 
        value=1000, 
        step=500
    )
    
    time_exit_mapping = {
        "No Time Limit": None,
        "Same Day Exit (Intraday)": 0,
        "1 Trading Day (Next Day)": 1,
        "2 Trading Days (Day After Tomorrow)": 2,
        "3 Trading Days": 3,
        "5 Trading Days (1 Week)": 5
    }
    
    max_hold_days = time_exit_mapping[st.sidebar.selectbox("Max Hold Duration:", list(time_exit_mapping.keys()), index=2)]
    
    st.sidebar.markdown("---")
    st.sidebar.write("**Select Trade Entry Window:**")
    
    max_days_back = 60 if is_intraday_mode else 1800
    default_days = 30 if is_intraday_mode else 180
    
    date_range = st.sidebar.date_input(
        "Date Range", 
        value=(date.today() - pd.DateOffset(days=default_days), date.today()),
        min_value=date.today() - pd.DateOffset(days=max_days_back),
        max_value=date.today()
    )
    
    if len(date_range) == 2:
        start_date, end_date = date_range
    else:
        start_date, end_date = date_range[0], date_range[0]

if st.sidebar.button("Run Scan"):
    tickers = get_live_nifty500_symbols() if universe == "Nifty 500" else get_all_nse_symbols()
    
    if not tickers:
        st.error("Failed to fetch stock list.")
    else:
        all_results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # Max workers reduced to 10 to ensure safe rate pacing for ~2300 stocks
        with st.spinner(f"Executing {mode} across {len(tickers)} equities (Rate-Limited & Paced)..."):
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = {executor.submit(analyze_ticker, t, mode, start_date, end_date, risk_per_trade, max_hold_days, apply_max_sl, apply_min_sl, is_intraday_mode): t for t in tickers}
                
                for i, future in enumerate(concurrent.futures.as_completed(futures)):
                    res = future.result()
                    if res:
                        for z in res: all_results.append(z)
                            
                    if i % 25 == 0 or i == len(tickers) - 1:
                        progress_bar.progress((i + 1) / len(tickers))
                        status_text.text(f"Processed {i + 1} / {len(tickers)} equities...")

        status_text.text("Scan complete!")
        
        if all_results:
            df_res = pd.DataFrame(all_results)
            if mode == "Historical Backtest":
                df_res = df_res.sort_values(by=["Entry Date", "Entry Time"], ascending=False).reset_index(drop=True)
                
                total_closed = len(df_res[df_res["Outcome"] != "Pending"])
                wins = len(df_res[df_res["Outcome"].str.contains("Win", na=False)])
                losses = len(df_res[df_res["Outcome"].str.contains("Loss", na=False)])
                win_rate = (wins / total_closed * 100) if total_closed > 0 else 0
                total_profit = df_res["P&L (₹)"].sum()
                
                st.markdown("### Backtest Performance Dashboard")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Win Rate", f"{win_rate:.1f}%")
                c2.metric("Total Net P&L", f"₹ {total_profit:,.2f}")
                c3.metric("Trades Triggered", len(df_res))
                c4.metric("Mode", "15-Min Intraday" if is_intraday_mode else "Daily")
                
                st.dataframe(df_res, use_container_width=True, height=500)
            else:
                st.dataframe(df_res, use_container_width=True, height=500)
        else:
            st.warning("No demand zones matched your criteria for the selected parameters.")
