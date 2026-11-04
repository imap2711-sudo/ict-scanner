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
from datetime import datetime, date, timedelta
import warnings
import logging

warnings.filterwarnings('ignore')
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

st.set_page_config(page_title="NSE Demand Zone Scanner", layout="wide")

CACHE_DIR = "/tmp/nse_pickle_cache"
CACHE_DIR_1H = "/tmp/nse_1h_cache"
os.makedirs(CACHE_DIR, exist_ok=True)
os.makedirs(CACHE_DIR_1H, exist_ok=True)

@st.cache_data(ttl=86400)
def get_live_nifty500_symbols():
    url = "https://niftyindices.com/IndexConstituent/ind_nifty500list.csv"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        response = requests.get(url, headers=headers, timeout=10)
        df = pd.read_csv(io.StringIO(response.text))
        return [str(symbol).strip() + '.NS' for symbol in df['Symbol']]
    except Exception:
        return []

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
        return []

def load_daily_ticker(ticker, force_refresh=False):
    safe_ticker = ticker.replace('.NS', '').replace('^', '').replace('&', '_')
    filepath = os.path.join(CACHE_DIR, f"{safe_ticker}.pkl")
    
    if not force_refresh and os.path.exists(filepath):
        try:
            with open(filepath, 'rb') as f:
                df = pickle.load(f)
            if df is not None and not df.empty and len(df) >= 20:
                return ticker, df, "cached"
        except Exception:
            pass
            
    for attempt in range(2):
        try:
            t = yf.Ticker(ticker)
            df = t.history(period="730d", interval="1d", auto_adjust=False)
            if df is not None and not df.empty and len(df) >= 20:
                df.index = df.index.tz_localize(None)
                with open(filepath, 'wb') as f:
                    pickle.dump(df, f)
                return ticker, df, "downloaded"
        except Exception:
            time.sleep(1 + attempt)
        time.sleep(0.05)
        
    return ticker, None, "failed"

def fetch_hourly_data(ticker, start_date_str):
    safe_ticker = ticker.replace('.NS', '').replace('^', '').replace('&', '_')
    filepath = os.path.join(CACHE_DIR_1H, f"{safe_ticker}_{start_date_str}.pkl")
    
    if os.path.exists(filepath):
        try:
            with open(filepath, 'rb') as f:
                return pickle.load(f)
        except Exception:
            pass
            
    try:
        t = yf.Ticker(ticker)
        df_1h = t.history(start=start_date_str, interval="1h", auto_adjust=False)
        if df_1h is not None and not df_1h.empty:
            df_1h.index = df_1h.index.tz_localize(None)
            with open(filepath, 'wb') as f:
                pickle.dump(df_1h, f)
            return df_1h
    except Exception:
        pass
    return None

def evaluate_with_1h_candles(ticker, entry_date, proximal, distal, target, qty, sl_points, max_hold_days):
    start_str = entry_date.strftime('%Y-%m-%d')
    df_1h = fetch_hourly_data(ticker, start_str)
    
    if df_1h is None or df_1h.empty:
        return "Win", qty * (target - proximal), entry_date.strftime('%Y-%m-%d')
        
    in_trade = False
    entry_bar_idx = None
    max_hourly_bars = (max_hold_days * 7) if (max_hold_days is not None and max_hold_days > 0) else None
    
    for idx, (timestamp, bar) in enumerate(df_1h.iterrows()):
        bar_low = bar['Low']
        bar_high = bar['High']
        bar_close = bar['Close']
        
        # Step 1: Detect exact entry hour
        if not in_trade:
            if bar_low <= (proximal * 1.0025):
                in_trade = True
                entry_bar_idx = idx
                
                if bar_low < distal:
                    return "Loss", -(qty * sl_points), timestamp.strftime('%Y-%m-%d %H:%M')
                if bar_high >= target and bar_close >= target:
                    return "Win", qty * (target - proximal), timestamp.strftime('%Y-%m-%d %H:%M')
            continue
            
        # Step 2: Track hourly bars after entry
        if in_trade:
            bars_held = idx - entry_bar_idx
            
            # Stop loss check
            if bar_low < distal:
                return "Loss", -(qty * sl_points), timestamp.strftime('%Y-%m-%d %H:%M')
                
            # Target check (2R breach)
            if bar_high >= target:
                return "Win", qty * (target - proximal), timestamp.strftime('%Y-%m-%d %H:%M')
                
            # Time exit check
            if max_hourly_bars is not None and bars_held >= max_hourly_bars:
                pnl = qty * (bar_close - proximal)
                outcome = "Time Exit (Win)" if bar_close >= proximal else "Time Exit (Loss)"
                return outcome, pnl, timestamp.strftime('%Y-%m-%d %H:%M')
                
    return "Pending", 0.0, "Open"

def analyze_ticker(ticker, df, mode, start_date=None, end_date=None, risk_amount=1000, 
                   max_hold_days=None, apply_max_sl=True, apply_min_sl=False, 
                   use_1h_precision=True, apply_compression=True, max_compression_ratio=0.75):
    try:
        cmp = float(df['Close'].iloc[-1])
        if pd.isna(cmp) or cmp <= 100: 
            return None

        df['Range'] = (df['High'] - df['Low']).replace(0, np.nan)
        df['Body'] = abs(df['Close'] - df['Open'])
        df['Body_Ratio'] = df['Body'] / df['Range']

        df['isLegIn'] = df['Body_Ratio'] > 0.65
        df['isBase'] = df['Body_Ratio'] < 0.40
        df['isBullish'] = df['Close'] > df['Open']
        df['isLegOutCandle'] = df['isBullish'] & (df['Body_Ratio'] > 0.65)

        results = []
        n = len(df)

        for i in range(3, n - 1):
            if not df['isLegOutCandle'].iloc[i]: 
                continue
                
            is_1base = df['isBase'].iloc[i-1] and df['isLegIn'].iloc[i-2]
            is_2base = False
            if i >= 4:
                is_2base = df['isBase'].iloc[i-1] and df['isBase'].iloc[i-2] and df['isLegIn'].iloc[i-3]
            
            if not (is_1base or is_2base): 
                continue
                
            first_legout_range = df['Range'].iloc[i]
            first_legout_close = df['Close'].iloc[i]
            base_close = df['Close'].iloc[i-1] 
            
            if is_1base:
                legin_range = df['Range'].iloc[i-2]
                base_high = df['High'].iloc[i-1]
                proximal_line = max(df['Open'].iloc[i-1], df['Close'].iloc[i-1])
                distal_line = df['Low'].iloc[i-1]
                base_date = df.index[i-1].strftime('%Y-%m-%d')
            else:
                legin_range = df['Range'].iloc[i-3]
                base_high = max(df['High'].iloc[i-1], df['High'].iloc[i-2])
                proximal_line = max(df['Open'].iloc[i-1], df['Close'].iloc[i-1], df['Open'].iloc[i-2], df['Close'].iloc[i-2])
                distal_line = min(df['Low'].iloc[i-1], df['Low'].iloc[i-2])
                base_date = f"{df.index[i-2].strftime('%Y-%m-%d')} to {df.index[i-1].strftime('%Y-%m-%d')}"
            
            if legin_range < 0.5 * first_legout_range: 
                continue
            if first_legout_close < (base_high * 1.01): 
                continue
            
            current_idx = i
            total_legouts = 1
            pause_used = False
            
            while current_idx + 1 < n:
                if df['isLegOutCandle'].iloc[current_idx + 1]:
                    current_idx += 1
                    total_legouts += 1
                elif not pause_used and df['isBase'].iloc[current_idx + 1] and current_idx + 2 < n and df['isLegOutCandle'].iloc[current_idx + 2]:
                    current_idx += 2
                    total_legouts += 1
                    pause_used = True
                else:
                    break
                
            last_legout_idx = current_idx
            move_end_price = df['Close'].iloc[last_legout_idx]
            pct_move = ((move_end_price - base_close) / base_close) * 100
            
            if pct_move < 7.0: 
                continue
            
            sl_pct = (proximal_line - distal_line) / proximal_line
            if apply_max_sl and sl_pct > 0.02:
                proximal_line = distal_line / 0.98
                sl_pct = 0.02
                
            if apply_min_sl and sl_pct < 0.015:
                continue
                
            sl_points = proximal_line - distal_line
            if sl_points <= 0:
                continue
                
            target_price = proximal_line + (2 * sl_points)
            qty = int(risk_amount / sl_points) if risk_amount else 0

            is_invalidated = False
            is_tested = False
            entry_idx = None
            
            for j in range(last_legout_idx + 1, n):
                day_low = df['Low'].iloc[j]
                day_close = df['Close'].iloc[j]
                
                if not is_tested:
                    if day_close < distal_line:
                        is_invalidated = True
                        break 
                    if day_low <= (proximal_line * 1.0025):
                        is_tested = True
                        entry_idx = j
                        break
            
            # --- PULLBACK COMPRESSION CALCULATION ---
            legout_indices = list(range(i, last_legout_idx + 1))
            avg_legout_range = df['Range'].iloc[legout_indices].mean()
            
            if mode == "Historical Backtest":
                if is_tested and not is_invalidated and entry_idx is not None:
                    entry_date = df.index[entry_idx].date()
                    if start_date <= entry_date <= end_date:
                        pullback_indices = list(range(last_legout_idx + 1, entry_idx + 1))
                        avg_pullback_range = df['Range'].iloc[pullback_indices].mean()
                        max_pullback_range = df['Range'].iloc[pullback_indices].max()
                        
                        compression_ratio = avg_pullback_range / avg_legout_range if avg_legout_range > 0 else 1.0
                        
                        # Apply Compression Filter if toggled ON
                        if apply_compression:
                            is_compressed = compression_ratio <= max_compression_ratio
                            no_supply_spike = max_pullback_range <= (first_legout_range * 1.10)
                            is_gradual = len(pullback_indices) >= len(legout_indices)
                            if not (is_compressed and no_supply_spike and is_gradual):
                                continue

                        if use_1h_precision:
                            outcome, pnl_rs, exit_date_str = evaluate_with_1h_candles(
                                ticker, entry_date, proximal_line, distal_line, target_price, qty, sl_points, max_hold_days
                            )
                        else:
                            outcome, pnl_rs, exit_date_str = "Pending", 0.0, "N/A"

                        results.append({
                            "Stock Symbol": ticker.replace('.NS', ''),
                            "Entry Date": entry_date.strftime('%Y-%m-%d'),
                            "Exit Timestamp": exit_date_str,
                            "Entry (₹)": round(proximal_line, 2),
                            "SL (₹)": round(distal_line, 2),
                            "Target (₹)": round(target_price, 2),
                            "Qty": qty,
                            "Compression Ratio": round(compression_ratio, 2),
                            "P&L (₹)": round(pnl_rs, 2),
                            "Outcome": outcome
                        })
            
            elif mode == "Live Scan (Same Day)":
                if is_invalidated or is_tested: 
                    continue
                if cmp <= (proximal_line * 1.0025): 
                    continue
                
                pullback_indices = list(range(last_legout_idx + 1, n))
                if pullback_indices:
                    avg_pullback_range = df['Range'].iloc[pullback_indices].mean()
                    max_pullback_range = df['Range'].iloc[pullback_indices].max()
                    compression_ratio = avg_pullback_range / avg_legout_range if avg_legout_range > 0 else 1.0
                else:
                    compression_ratio = 0.0
                
                # Filter live candidates on ongoing pullback
                if apply_compression and pullback_indices:
                    is_compressed = compression_ratio <= max_compression_ratio
                    no_supply_spike = max_pullback_range <= (first_legout_range * 1.10)
                    if not (is_compressed and no_supply_spike):
                        continue
                    
                distance_pct = ((cmp - proximal_line) / cmp) * 100
                results.append({
                    "Stock Symbol": ticker.replace('.NS', ''),
                    "CMP (₹)": round(cmp, 2),
                    "Base date": base_date,
                    "Proximal": round(proximal_line, 2),
                    "Distal": round(distal_line, 2),
                    "Compression Ratio": round(compression_ratio, 2) if pullback_indices else "N/A",
                    "Legout candles": f"{total_legouts} (incl. pause)" if pause_used else str(total_legouts),
                    "Legout % move": round(pct_move, 2),
                    "Required fall %": round(distance_pct, 2)
                })
            
        return results if results else None
    except Exception:
        return None

# --- STREAMLIT UI ---
st.title("NSE Daily Demand Zone Scanner")
st.markdown("Multi-timeframe engine: Daily zone detection with **1-hour candle execution** and **pullback compression filtering**.")

st.sidebar.header("Scan Parameters")

universe = st.sidebar.selectbox(
    "Select Stock Universe:",
    ("Nifty 500", "All NSE Equities (Price > ₹100)"),
    index=0
)

mode = st.sidebar.radio("Select Mode:", ("Historical Backtest", "Live Scan (Same Day)"))

st.sidebar.markdown("---")
st.sidebar.write("**Execution Engine:**")
use_1h_precision = st.sidebar.checkbox("Use 1-Hour Intraday Precision", value=True, help="Chronologically tracks 1-hour candles post-entry to accurately detect target breaches.")
force_refresh = st.sidebar.checkbox("Force Redownload Fresh Data", value=False)

st.sidebar.markdown("---")
st.sidebar.write("**Quality & Compression Controls:**")
apply_compression = st.sidebar.toggle("Enforce Pullback Compression Filter", value=True, help="Only accepts trades where the price approaches the zone in small candles relative to the legout rally.")
max_compression_ratio = st.sidebar.slider(
    "Max Pullback Compression Ratio:",
    min_value=0.40,
    max_value=1.00,
    value=0.75,
    step=0.05,
    help="0.75 means pullback candles must be at least 25% smaller on average than departure candles. Lower = stricter quality."
)

st.sidebar.markdown("---")
st.sidebar.write("**Stop Loss Controls:**")
apply_max_sl = st.sidebar.toggle("Enforce Max 2% SL Shift", value=True)
apply_min_sl = st.sidebar.toggle("Enforce Min 1.5% SL Filter", value=False)

start_date, end_date = None, None
risk_per_trade = None
max_hold_days = None

min_allowed_date = date.today() - timedelta(days=725)

if mode == "Historical Backtest":
    st.sidebar.markdown("---")
    st.sidebar.write("**Backtest Settings:**")
    
    risk_per_trade = st.sidebar.number_input("Risk Per Trade (₹)", min_value=100, max_value=100000, value=1000, step=500)
    
    time_exit_mapping = {
        "No Time Limit": None,
        "Same Day Exit (Intraday)": 0,
        "1 Trading Day (Next Day)": 1,
        "2 Trading Days (Day After Tomorrow)": 2,
        "3 Trading Days": 3,
        "5 Trading Days (1 Week)": 5,
        "10 Trading Days (2 Weeks)": 10
    }
    
    max_hold_days = time_exit_mapping[st.sidebar.selectbox("Max Hold Duration:", list(time_exit_mapping.keys()), index=3)]
    
    st.sidebar.markdown("---")
    st.sidebar.write("**Select Trade Entry Window (730 Days Max for 1H):**")
    
    date_range = st.sidebar.date_input(
        "Date Range", 
        value=(min_allowed_date, date.today()),
        min_value=min_allowed_date,
        max_value=date.today()
    )
    
    if len(date_range) == 2:
        start_date, end_date = date_range
    else:
        start_date, end_date = date_range[0], date_range[0]

if st.sidebar.button("Run Scan"):
    tickers = get_live_nifty500_symbols() if universe == "Nifty 500" else get_all_nse_symbols()
    
    if not tickers:
        st.error("Failed to fetch stock list from NSE.")
    else:
        all_results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        with st.spinner(f"Analyzing {len(tickers)} equities with compression & 1-hour verification..."):
            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
                future_to_ticker = {executor.submit(load_daily_ticker, t, force_refresh): t for t in tickers}
                
                completed = 0
                for future in concurrent.futures.as_completed(future_to_ticker):
                    completed += 1
                    ticker, df_stock, status = future.result()
                    
                    if df_stock is not None:
                        res = analyze_ticker(
                            ticker, df_stock, mode, start_date, end_date, 
                            risk_per_trade, max_hold_days, apply_max_sl, apply_min_sl, 
                            use_1h_precision, apply_compression, max_compression_ratio
                        )
                        if res:
                            for item in res:
                                all_results.append(item)
                        del df_stock
                    
                    if completed % 25 == 0 or completed == len(tickers):
                        gc.collect()
                        progress_bar.progress(completed / len(tickers))
                        status_text.text(f"Processed {completed} / {len(tickers)} equities...")

        status_text.text("Scan complete!")

        if all_results:
            df_res = pd.DataFrame(all_results)
            if mode == "Historical Backtest":
                df_res = df_res.sort_values(by="Entry Date", ascending=False).reset_index(drop=True)
                
                total_closed = len(df_res[df_res["Outcome"] != "Pending"])
                wins = len(df_res[df_res["Outcome"].str.contains("Win", na=False)])
                losses = len(df_res[df_res["Outcome"].str.contains("Loss", na=False)])
                pending = len(df_res[df_res["Outcome"] == "Pending"])
                win_rate = (wins / total_closed * 100) if total_closed > 0 else 0
                total_profit = df_res["P&L (₹)"].sum()
                
                st.markdown("### Backtest Performance Dashboard")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Win Rate", f"{win_rate:.1f}%")
                c2.metric("Total Net P&L", f"₹ {total_profit:,.2f}", delta=f"{'Profit' if total_profit > 0 else 'Loss'}")
                c3.metric("Trades Triggered", len(df_res))
                c4.metric("Pending/Open", pending)
                
                def style_outcome(val):
                    if pd.isna(val): return ''
                    if 'Win' in val: return 'color: green'
                    if 'Loss' in val: return 'color: red'
                    return 'color: gray'
                
                st.dataframe(
                    df_res.style.map(style_outcome, subset=['Outcome']).format({
                        "Entry (₹)": "{:.2f}",
                        "SL (₹)": "{:.2f}",
                        "Target (₹)": "{:.2f}",
                        "Compression Ratio": "{:.2f}",
                        "P&L (₹)": "{:.2f}"
                    }),
                    use_container_width=True, 
                    height=500
                )
            else:
                df_res = df_res.sort_values(by="Required fall %").reset_index(drop=True)
                st.markdown(f"### Active Untested Zones ({universe})")
                st.dataframe(df_res, use_container_width=True, height=500)
                
            csv = df_res.to_csv(index=False).encode('utf-8')
            file_label = "Compression_Backtest" if mode == "Historical Backtest" else "Live_Compressed_Zones"
            st.download_button(
                label="📥 Download Data CSV",
                data=csv,
                file_name=f"{file_label}_{universe.replace(' ', '_')}.csv",
                mime="text/csv",
            )
        else:
            st.warning("No demand zones matched your criteria for the selected parameters.")
