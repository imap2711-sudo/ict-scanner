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

st.set_page_config(page_title="NSE Daily Demand Zone Scanner", layout="wide")

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

def fetch_stock_history(ticker):
    try:
        t = yf.Ticker(ticker)
        # Fetches 10 years of data to support 2017 onwards
        df = t.history(period="10y", interval="1d", auto_adjust=False)
        if df is not None and not df.empty and len(df) >= 20:
            df.index = df.index.tz_localize(None)
            return ticker, df
    except Exception:
        pass
    return ticker, None

def analyze_ticker(ticker, df, mode, start_date=None, end_date=None, risk_amount=1000, max_hold_days=None, apply_max_sl=True, apply_min_sl=False):
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
            
            # Legout Continuation Chain
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
            
            # Stop Loss Rules
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

            # Forward Test of this isolated zone
            is_invalidated = False
            is_tested = False
            entry_idx = None
            outcome = "Pending"
            exit_date = None
            pnl_rs = 0.0
            
            for j in range(last_legout_idx + 1, n):
                day_low = df['Low'].iloc[j]
                day_high = df['High'].iloc[j]
                day_close = df['Close'].iloc[j]
                
                if not is_tested:
                    if day_close < distal_line:
                        is_invalidated = True
                        break 
                    if day_low <= (proximal_line * 1.0025):
                        is_tested = True
                        entry_idx = j
                        if mode == "Live Scan (Same Day)": 
                            break
                
                if is_tested and mode == "Historical Backtest":
                    days_in_trade = j - entry_idx
                    if day_low < distal_line: 
                        outcome = "Loss"
                        pnl_rs = -(qty * sl_points)
                        exit_date = df.index[j].date()
                        break
                    elif day_high >= target_price: 
                        outcome = "Win"
                        pnl_rs = (qty * (target_price - proximal_line))
                        exit_date = df.index[j].date()
                        break
                    elif max_hold_days is not None and days_in_trade >= max_hold_days:
                        outcome = "Time Exit (Win)" if day_close >= proximal_line else "Time Exit (Loss)"
                        pnl_rs = (qty * (day_close - proximal_line))
                        exit_date = df.index[j].date()
                        break
            
            if mode == "Live Scan (Same Day)":
                if is_invalidated or is_tested: 
                    continue
                if cmp <= (proximal_line * 1.0025): 
                    continue
                    
                distance_pct = ((cmp - proximal_line) / cmp) * 100
                results.append({
                    "Stock Symbol": ticker.replace('.NS', ''),
                    "CMP (₹)": round(cmp, 2),
                    "Base date": base_date,
                    "Proximal": round(proximal_line, 2),
                    "Distal": round(distal_line, 2),
                    "Legout candles": f"{total_legouts} (incl. pause)" if pause_used else str(total_legouts),
                    "Legout % move": round(pct_move, 2),
                    "Required fall %": round(distance_pct, 2)
                })
            
            elif mode == "Historical Backtest":
                if is_tested and not is_invalidated and entry_idx is not None:
                    entry_date = df.index[entry_idx].date()
                    if start_date <= entry_date <= end_date:
                        results.append({
                            "Stock Symbol": ticker.replace('.NS', ''),
                            "Entry Date": entry_date.strftime('%Y-%m-%d'),
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
st.title("NSE Daily Demand Zone Scanner")
st.markdown("Automated 1:2 RR institutional zone scanner with time-based exits and complete universe support.")

st.sidebar.header("Scan Parameters")

universe = st.sidebar.selectbox(
    "Select Stock Universe:",
    ("All NSE Equities (Price > ₹100)", "Nifty 500"),
    index=0
)

mode = st.sidebar.radio("Select Mode:", ("Historical Backtest", "Live Scan (Same Day)"))

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
        "5 Trading Days (1 Week)": 5,
        "10 Trading Days (2 Weeks)": 10
    }
    
    max_hold_days = time_exit_mapping[st.sidebar.selectbox("Max Hold Duration:", list(time_exit_mapping.keys()), index=0)]
    
    st.sidebar.markdown("---")
    st.sidebar.write("**Select Trade Entry Window:**")
    
    date_range = st.sidebar.date_input(
        "Date Range", 
        value=(date(2017, 1, 1), date.today()),
        min_value=date(2017, 1, 1),
        max_value=date.today()
    )
    
    if len(date_range) == 2:
        start_date, end_date = date_range
    else:
        start_date, end_date = date_range[0], date_range[0]

if st.sidebar.button("Run Scan"):
    tickers = get_all_nse_symbols() if universe == "All NSE Equities (Price > ₹100)" else get_live_nifty500_symbols()
    
    if not tickers:
        st.error("Failed to fetch stock list from NSE.")
    else:
        all_results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        with st.spinner(f"Scanning {len(tickers)} equities..."):
            with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
                future_to_ticker = {executor.submit(fetch_stock_history, t): t for t in tickers}
                
                completed = 0
                for future in concurrent.futures.as_completed(future_to_ticker):
                    completed += 1
                    ticker, df_stock = future.result()
                    
                    if df_stock is not None:
                        res = analyze_ticker(ticker, df_stock, mode, start_date, end_date, risk_per_trade, max_hold_days, apply_max_sl, apply_min_sl)
                        if res:
                            for item in res:
                                all_results.append(item)
                    
                    if completed % 50 == 0 or completed == len(tickers):
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
            file_prefix = "Live" if mode == "Live Scan (Same Day)" else f"Backtest_{start_date}_to_{end_date}"
            st.download_button(
                label="📥 Download Data as CSV",
                data=csv,
                file_name=f"{file_prefix}_{universe.replace(' ', '_')}_Demand_Zones.csv",
                mime="text/csv",
            )
        else:
            st.warning("No demand zones matched your criteria for the selected parameters.")
