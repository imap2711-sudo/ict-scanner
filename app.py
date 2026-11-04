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
from datetime import datetime, date
import warnings
import logging

warnings.filterwarnings('ignore')
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

st.set_page_config(page_title="GTF MIT & WIT Demand Zone Scanner", layout="wide")

CACHE_DIR = "/tmp/gtf_titz_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

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

# -------------------------------------------------------------
# 2. DATA FETCHER & RESAMPLER (DAILY -> WEEKLY & MONTHLY)
# -------------------------------------------------------------
def fetch_stock_data(ticker, force_refresh=False):
    safe_ticker = ticker.replace('.NS', '').replace('^', '').replace('&', '_')
    filepath = os.path.join(CACHE_DIR, f"{safe_ticker}.pkl")

    if not force_refresh and os.path.exists(filepath):
        try:
            with open(filepath, 'rb') as f:
                df_d = pickle.load(f)
            if df_d is not None and not df_d.empty and len(df_d) >= 60:
                return ticker, df_d
        except Exception:
            pass

    for attempt in range(2):
        try:
            t = yf.Ticker(ticker)
            df_d = t.history(period="3y", interval="1d", auto_adjust=False)
            if df_d is not None and not df_d.empty and len(df_d) >= 60:
                df_d.index = df_d.index.tz_localize(None)
                with open(filepath, 'wb') as f:
                    pickle.dump(df_d, f)
                return ticker, df_d
        except Exception:
            time.sleep(0.5 + attempt)
        time.sleep(0.04)

    return ticker, None

# -------------------------------------------------------------
# 3. MIT & WIT STRATEGY EVALUATION
# -------------------------------------------------------------
def analyze_gtf_trade(ticker, df_d, trade_type, target_year, target_month, risk_per_trade=2000, apply_max_sl=True):
    try:
        cmp = float(df_d['Close'].iloc[-1])
        if cmp < 100:
            return None

        # Build Weekly (ITF) and Monthly (HTF) bars directly from Daily
        df_w = df_d.resample('W-FRI').agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).dropna()
        
        df_m = df_d.resample('ME').agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).dropna()

        # Indicators for Trend (20 EMA)
        df_d['EMA20'] = df_d['Close'].ewm(span=20, adjust=False).mean()
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

        # Max holding duration by trade type
        max_hold_days = 25 if "MIT" in trade_type else 8

        # Scan for DBR zones
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

            first_legout_close = df_d['Close'].iloc[i]
            if first_legout_close < (base_high * 1.005):
                continue

            # Check Departure Rally
            curr = i
            while curr + 1 < n and df_d['isLegOut'].iloc[curr + 1]:
                curr += 1
            last_legout_idx = curr
            pct_move = ((df_d['Close'].iloc[last_legout_idx] - proximal) / proximal) * 100
            
            # Minimum departure move: 5% for WIT, 6.5% for MIT
            min_move = 6.5 if "MIT" in trade_type else 5.0
            if pct_move < min_move:
                continue

            # Stop loss calculation (Optional max 2% cap shift)
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

            # Check if entry falls into the selected month and year
            if is_tested and not is_invalidated and entry_idx is not None:
                entry_dt = df_d.index[entry_idx]

                if entry_dt.year == target_year and entry_dt.month == target_month:
                    
                    # --- HTF & ITF VALIDATION ---
                    if "MIT" in trade_type:
                        # MIT HTF: Monthly Curve (past 12 months)
                        m_slice = df_m[df_m.index <= entry_dt].iloc[-12:]
                        if len(m_slice) >= 4:
                            m_high = m_slice['High'].max()
                            m_low = m_slice['Low'].min()
                            curve_pos = (proximal - m_low) / (m_high - m_low) if (m_high - m_low) > 0 else 0.5
                        else:
                            curve_pos = 0.5

                        # MIT ITF: Weekly Trend (Weekly 20 EMA)
                        w_slice = df_w[df_w.index <= entry_dt]
                        weekly_trend_ok = True
                        if len(w_slice) >= 2:
                            weekly_trend_ok = w_slice['Close'].iloc[-1] >= (w_slice['EMA20'].iloc[-1] * 0.96)

                        curve_label = "Low on Curve" if curve_pos <= 0.40 else ("Equilibrium" if curve_pos <= 0.65 else "High on Curve")
                        trend_label = "Weekly Bullish" if weekly_trend_ok else "Weekly Neutral"

                    else:
                        # WIT HTF: Weekly Curve (past 26 weeks)
                        w_slice = df_w[df_w.index <= entry_dt].iloc[-26:]
                        if len(w_slice) >= 4:
                            w_high = w_slice['High'].max()
                            w_low = w_slice['Low'].min()
                            curve_pos = (proximal - w_low) / (w_high - w_low) if (w_high - w_low) > 0 else 0.5
                        else:
                            curve_pos = 0.5

                        # WIT ITF: Daily Trend (Daily 20 EMA)
                        daily_trend_ok = df_d['Close'].iloc[entry_idx] >= (df_d['EMA20'].iloc[entry_idx] * 0.97)
                        curve_label = "Low on Weekly" if curve_pos <= 0.45 else ("Equilibrium" if curve_pos <= 0.70 else "High on Weekly")
                        trend_label = "Daily Bullish" if daily_trend_ok else "Daily Neutral"

                    # --- TRADE OUTCOME EVALUATION ---
                    outcome = "Pending"
                    exit_date = "Open"
                    pnl_rs = 0.0

                    for k in range(entry_idx, min(entry_idx + max_hold_days + 1, n)):
                        k_low = df_d['Low'].iloc[k]
                        k_high = df_d['High'].iloc[k]
                        k_close = df_d['Close'].iloc[k]
                        days_held = k - entry_idx

                        # 1. Stop loss hit (-1R)
                        if k_low < distal:
                            outcome = "Loss (-1R)"
                            exit_date = df_d.index[k].strftime('%Y-%m-%d')
                            pnl_rs = -(qty * sl_points)
                            break

                        # 2. Strict 1:2 Target hit (+2R)
                        # On entry day, require Close >= Target or on subsequent day High >= Target
                        target_hit = (k_close >= target_price) if (k == entry_idx) else (k_high >= target_price)
                        if target_hit:
                            outcome = "Win (1:2 RR)"
                            exit_date = df_d.index[k].strftime('%Y-%m-%d')
                            pnl_rs = qty * (target_price - proximal)
                            break

                        # 3. Time exit
                        if days_held >= max_hold_days:
                            if k_close >= proximal:
                                outcome = "Time Exit (Win)"
                            else:
                                outcome = "Time Exit (Loss)"
                            exit_date = df_d.index[k].strftime('%Y-%m-%d')
                            pnl_rs = qty * (k_close - proximal)
                            break

                    results.append({
                        "Stock Symbol": ticker.replace('.NS', ''),
                        "Trade Type": "MIT" if "MIT" in trade_type else "WIT",
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
# 4. STREAMLIT INTERFACE
# -------------------------------------------------------------
st.title("GTF Demand Zone Backtester (MIT & WIT)")
st.markdown("Automated Multiple Timeframe Analysis (MTFA) backtesting engine with strict **1:2 Risk-Reward**.")

st.sidebar.header("Strategy Settings")

# 1. Trade Type Dropdown
trade_type = st.sidebar.selectbox(
    "Select Trade Type:",
    ("MIT (Monthly Income Trade - Daily Execution)", "WIT (Weekly Income Trade - Fast Swing)"),
    index=0
)

# 2. Month Selection Dropdown
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
    index=0  # Defaults to October 2026
)
target_year, target_month = month_options[selected_month_name]

# Universe Selection
universe = st.sidebar.selectbox("Select Stock Universe:", ("Nifty 500", "Nifty 50 (Fast Verification)"), index=0)

st.sidebar.markdown("---")
risk_per_trade = st.sidebar.number_input("Risk Per Trade (₹):", min_value=500, max_value=50000, value=2000, step=500)
apply_max_sl = st.sidebar.toggle("Enforce Max 2% SL Shift", value=True)
force_refresh = st.sidebar.checkbox("Force Redownload Fresh Data", value=False)

# Run Scan
if st.sidebar.button("Run Scan", type="primary"):
    tickers = get_nifty500_symbols() if universe == "Nifty 500" else get_nifty50_symbols()
    
    all_trades = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    with st.spinner(f"Scanning {len(tickers)} stocks for {selected_month_name} ({trade_type[:3]})..."):
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            future_to_ticker = {executor.submit(fetch_stock_data, t, force_refresh): t for t in tickers}
            
            completed = 0
            for future in concurrent.futures.as_completed(future_to_ticker):
                completed += 1
                ticker, df_stock = future.result()
                
                if df_stock is not None:
                    res = analyze_gtf_trade(ticker, df_stock, trade_type, target_year, target_month, risk_per_trade, apply_max_sl)
                    if res:
                        all_trades.extend(res)
                    del df_stock
                
                if completed % 25 == 0 or completed == len(tickers):
                    gc.collect()
                    progress_bar.progress(completed / len(tickers))
                    status_text.text(f"Processed {completed}/{len(tickers)} stocks... (Found {len(all_trades)} trades so far)")

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

        # Style outcome column
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
            file_name=f"{trade_type[:3]}_{selected_month_name.replace(' ', '_')}_Results.csv",
            mime="text/csv"
        )
    else:
        st.warning(f"No {trade_type[:3]} setups matched in {selected_month_name}. Try switching between MIT and WIT or checking an adjacent month.")
