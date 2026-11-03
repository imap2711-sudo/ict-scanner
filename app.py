import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import io
import concurrent.futures
from datetime import datetime, date
import warnings
import logging

warnings.filterwarnings('ignore')
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

st.set_page_config(page_title="Nifty 500 DZ Scanner", layout="wide")

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

def analyze_ticker(ticker, mode, start_date=None, end_date=None):
    try:
        t = yf.Ticker(ticker)
        # Always fetch max data so we can accurately track forward-looking price action for backtesting
        df = t.history(period="10y", interval="1d", auto_adjust=False)
        
        if df.empty or len(df) < 5: 
            return None
            
        df.index = df.index.tz_localize(None)

        try: cmp = float(t.fast_info.last_price)
        except: cmp = float(df['Close'].iloc[-1])

        if pd.isna(cmp) or cmp <= 60: 
            return None

        # 3-Year Cutoff based on today
        cutoff_date = df.index[-1] - pd.DateOffset(years=3)

        df['Range'] = df['High'] - df['Low']
        df['Body'] = abs(df['Close'] - df['Open'])
        df['Range'] = df['Range'].replace(0, np.nan)
        df['Body_Ratio'] = df['Body'] / df['Range']

        df['isLegIn'] = df['Body_Ratio'] > 0.65
        df['isBase'] = df['Body_Ratio'] < 0.40
        df['isBullish'] = df['Close'] > df['Open']
        df['isLegOutCandle'] = df['isBullish'] & (df['Body_Ratio'] > 0.65)

        results = []
        
        for i in range(3, len(df)):
            if not df['isLegOutCandle'].iloc[i]: continue
                
            is_1base = df['isBase'].iloc[i-1] and df['isLegIn'].iloc[i-2]
            is_2base = False
            if i >= 4:
                is_2base = df['isBase'].iloc[i-1] and df['isBase'].iloc[i-2] and df['isLegIn'].iloc[i-3]
            
            if not (is_1base or is_2base): continue
            
            zone_formation_date = df.index[i-1]
            if zone_formation_date < cutoff_date: continue
                
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
            
            if legin_range < 0.5 * first_legout_range: continue
            if first_legout_close < (base_high * 1.01): continue
            
            current_idx = i
            total_legouts = 1
            pause_used = False
            
            while current_idx + 1 < len(df):
                if df['isLegOutCandle'].iloc[current_idx + 1]:
                    current_idx += 1
                    total_legouts += 1
                elif not pause_used and df['isBase'].iloc[current_idx + 1] and current_idx + 2 < len(df) and df['isLegOutCandle'].iloc[current_idx + 2]:
                    current_idx += 2
                    total_legouts += 1
                    pause_used = True
                else:
                    break
                
            last_legout_idx = current_idx
            
            move_end_price = df['Close'].iloc[last_legout_idx]
            pct_move = ((move_end_price - base_close) / base_close) * 100
            
            if pct_move < 7.0: continue
            
            # Risk Management Mathematics (1:2 RR)
            risk_pct = ((proximal_line - distal_line) / proximal_line) * 100
            target_price = proximal_line + 2 * (proximal_line - distal_line)
                
            # Forward Price Simulation
            is_invalidated = False
            is_tested = False
            entry_idx = None
            outcome = "Pending"
            exit_date = None
            
            for j in range(last_legout_idx + 1, len(df)):
                day_low = df['Low'].iloc[j]
                day_high = df['High'].iloc[j]
                day_close = df['Close'].iloc[j]
                
                # Check for Entry or Invalidation
                if not is_tested:
                    if day_close < distal_line:
                        is_invalidated = True
                        break # Destroyed before entry
                    if day_low <= (proximal_line * 1.0025):
                        is_tested = True
                        entry_idx = j
                        if mode == "Live Scan (Same Day)":
                            break # In live mode, we drop tested zones immediately
                
                # Post-Entry Simulation (Backtest Only)
                if is_tested and mode == "Historical Backtest":
                    if day_low < distal_line: # SL Hit
                        outcome = "Loss"
                        exit_date = df.index[j].date()
                        break
                    elif day_high >= target_price: # TP Hit
                        outcome = "Win"
                        exit_date = df.index[j].date()
                        break
            
            # MODE 1: LIVE SCAN RETURN
            if mode == "Live Scan (Same Day)":
                if is_invalidated or is_tested: continue
                # Catch live daily tick test
                try:
                    if float(t.fast_info.day_low) <= (proximal_line * 1.0025): continue
                except:
                    if cmp <= (proximal_line * 1.0025): continue
                    
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
            
            # MODE 2: BACKTEST RETURN
            elif mode == "Historical Backtest":
                if is_tested and not is_invalidated:
                    entry_date = df.index[entry_idx].date()
                    # Only register the trade if it triggered inside the selected date range
                    if start_date <= entry_date <= end_date:
                        results.append({
                            "Stock Symbol": ticker.replace('.NS', ''),
                            "Base Date": base_date,
                            "Entry Date": entry_date.strftime('%Y-%m-%d'),
                            "Exit Date": exit_date.strftime('%Y-%m-%d') if exit_date else "N/A",
                            "Proximal (Entry)": round(proximal_line, 2),
                            "Distal (SL)": round(distal_line, 2),
                            "Target (1:2)": round(target_price, 2),
                            "Risk (%)": round(risk_pct, 2),
                            "Outcome": outcome
                        })
            
        return results if results else None
    except Exception:
        return None

# --- STREAMLIT UI ---
st.title("Nifty 500 Daily Demand Zone Scanner")
st.markdown("Institutional structural scanner with full 1:2 RR backtesting capabilities.")

st.sidebar.header("Scan Parameters")
mode = st.sidebar.radio("Select Mode:", ("Live Scan (Same Day)", "Historical Backtest"))

start_date, end_date = None, None
if mode == "Historical Backtest":
    st.sidebar.markdown("---")
    st.sidebar.write("**Select Trade Entry Window:**")
    st.sidebar.caption("The engine will evaluate any setups that triggered an entry within this specific date range.")
    
    date_range = st.sidebar.date_input(
        "Date Range", 
        value=(date.today() - pd.DateOffset(days=90), date.today()),
        max_value=date.today()
    )
    
    if len(date_range) == 2:
        start_date, end_date = date_range
    else:
        start_date, end_date = date_range[0], date_range[0]

if st.sidebar.button("Run Scan"):
    tickers = get_live_nifty500_symbols()
    
    if not tickers:
        st.error("Failed to fetch Nifty 500 list from NSE. Please try again.")
    else:
        all_results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        with st.spinner(f"Executing {mode} across Nifty 500..."):
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                futures = {executor.submit(analyze_ticker, t, mode, start_date, end_date): t for t in tickers}
                
                for i, future in enumerate(concurrent.futures.as_completed(futures)):
                    res = future.result()
                    if res:
                        for z in res:
                            all_results.append(z)
                            
                    if i % 10 == 0 or i == len(tickers) - 1:
                        progress_bar.progress((i + 1) / len(tickers))
                        status_text.text(f"Processed {i + 1} / {len(tickers)} equities...")

        status_text.text("Scan complete!")
        
        if all_results:
            df_res = pd.DataFrame(all_results)
            
            if mode == "Historical Backtest":
                df_res = df_res.sort_values(by="Entry Date", ascending=False).reset_index(drop=True)
                
                # --- BACKTEST METRICS DASHBOARD ---
                total_trades = len(df_res)
                wins = len(df_res[df_res["Outcome"] == "Win"])
                losses = len(df_res[df_res["Outcome"] == "Loss"])
                pending = len(df_res[df_res["Outcome"] == "Pending"])
                avg_risk = df_res["Risk (%)"].mean()
                
                st.markdown("### Backtest Performance (1:2 RR)")
                col1, col2, col3, col4, col5 = st.columns(5)
                col1.metric("Setups Triggered", total_trades)
                col2.metric("Successful", wins)
                col3.metric("Failed (SL Hit)", losses)
                col4.metric("Pending", pending)
                col5.metric("Avg. Risk / Trade", f"{avg_risk:.2f}%")
                
                st.dataframe(
                    df_res.style.map(lambda x: 'color: green' if x == 'Win' else ('color: red' if x == 'Loss' else 'color: gray'), subset=['Outcome']),
                    use_container_width=True,
                    height=500
                )
            else:
                df_res = df_res.sort_values(by="Required fall %").reset_index(drop=True)
                st.markdown("### Active Untested Zones")
                st.dataframe(df_res, use_container_width=True, height=500)
            
            # CSV Download
            csv = df_res.to_csv(index=False).encode('utf-8')
            file_prefix = "Live" if mode == "Live Scan (Same Day)" else f"Backtest_{start_date}_to_{end_date}"
            st.download_button(
                label="📥 Download Data as CSV",
                data=csv,
                file_name=f"{file_prefix}_Demand_Zones.csv",
                mime="text/csv",
            )
        else:
            st.warning("No demand zones matched your criteria for the selected parameters.")
