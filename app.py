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

def analyze_ticker(ticker, end_date=None):
    try:
        t = yf.Ticker(ticker)
        # Fetch 10 years to ensure 3-year lookback is available even for 5-year old backtests
        df = t.history(period="10y", interval="1d", auto_adjust=False)
        
        if df.empty: 
            return None
            
        df.index = df.index.tz_localize(None)

        if end_date:
            # Backtest Mode: Truncate data up to the selected date
            end_date_parsed = pd.to_datetime(end_date)
            df = df.loc[:end_date_parsed]
            if len(df) < 5: return None
            cmp = float(df['Close'].iloc[-1])
        else:
            # Live Mode
            try: cmp = float(t.fast_info.last_price)
            except: cmp = float(df['Close'].iloc[-1])

        if pd.isna(cmp) or cmp <= 60: 
            return None

        # 3-Year Cutoff from the evaluation date
        cutoff_date = df.index[-1] - pd.DateOffset(years=3)

        df['Range'] = df['High'] - df['Low']
        df['Body'] = abs(df['Close'] - df['Open'])
        df['Range'] = df['Range'].replace(0, np.nan)
        df['Body_Ratio'] = df['Body'] / df['Range']

        df['isLegIn'] = df['Body_Ratio'] > 0.65
        df['isBase'] = df['Body_Ratio'] < 0.40
        df['isBullish'] = df['Close'] > df['Open']
        df['isLegOutCandle'] = df['isBullish'] & (df['Body_Ratio'] > 0.65)

        surviving_zones = []
        
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
                
            # STRICT 0.25% BUFFER UNTESTED CHECK
            is_invalidated = False
            is_tested = False
            
            if i + 1 < len(df):
                subsequent_df = df.iloc[i + 1:]
                if (subsequent_df['Close'] < distal_line).any():
                    is_invalidated = True
                elif (subsequent_df['Low'] <= (proximal_line * 1.0025)).any():
                    is_tested = True
            
            if not end_date:
                try:
                    live_low = float(t.fast_info.day_low)
                    if live_low <= (proximal_line * 1.0025): is_tested = True
                except:
                    if cmp <= (proximal_line * 1.0025): is_tested = True
                    
            if is_invalidated or is_tested: continue
                
            distance_pct = ((cmp - proximal_line) / cmp) * 100
            
            zone_data = {
                "Stock Symbol": ticker.replace('.NS', ''),
                "CMP (₹)": round(cmp, 2),
                "Base date": base_date,
                "Proximal": round(proximal_line, 2),
                "Distal": round(distal_line, 2),
                "Legout candles": f"{total_legouts} (incl. pause)" if pause_used else str(total_legouts),
                "Legout % move": round(pct_move, 2),
                "Required fall %": round(distance_pct, 2)
            }
            
            surviving_zones.append(zone_data)
            
        if surviving_zones:
            surviving_zones.sort(key=lambda x: x['Required fall %'])
            return surviving_zones[:2] 
            
        return None
    except Exception:
        return None

# --- STREAMLIT UI ---
st.title("Nifty 500 Daily Demand Zone Scanner")
st.markdown("Institutional Drop-Base-Rally & Rally-Base-Rally structural scanner.")

st.sidebar.header("Scan Parameters")
mode = st.sidebar.radio("Select Mode:", ("Live Scan (Same Day)", "Historical Backtest"))

target_date = None
if mode == "Historical Backtest":
    max_past_date = date.today() - pd.DateOffset(years=5)
    target_date = st.sidebar.date_input(
        "Select Backtest Date (End Date)", 
        value=date.today() - pd.DateOffset(days=30),
        min_value=max_past_date.date(),
        max_value=date.today()
    )

if st.sidebar.button("Run Scan"):
    tickers = get_live_nifty500_symbols()
    
    if not tickers:
        st.error("Failed to fetch Nifty 500 list from NSE. Please try again.")
    else:
        results = []
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        with st.spinner("Executing multithreaded scan across Nifty 500..."):
            # Multithreading to speed up Streamlit execution
            with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
                futures = {executor.submit(analyze_ticker, t, target_date): t for t in tickers}
                
                for i, future in enumerate(concurrent.futures.as_completed(futures)):
                    res = future.result()
                    if res:
                        for z in res:
                            results.append(z)
                            
                    # Update progress UI
                    if i % 10 == 0 or i == len(tickers) - 1:
                        progress_bar.progress((i + 1) / len(tickers))
                        status_text.text(f"Processed {i + 1} / {len(tickers)} equities...")

        status_text.text(f"Scan complete! {len(results)} zones identified.")
        
        if results:
            df_res = pd.DataFrame(results)
            df_res = df_res.sort_values(by="Required fall %").reset_index(drop=True)
            
            # Format UI Display
            st.dataframe(
                df_res.style.format({
                    "CMP (₹)": "{:.2f}",
                    "Proximal": "{:.2f}",
                    "Distal": "{:.2f}",
                    "Legout % move": "{:.2f}%",
                    "Required fall %": "{:.2f}%"
                }), 
                use_container_width=True,
                height=600
            )
            
            # CSV Download
            csv = df_res.to_csv(index=False).encode('utf-8')
            file_prefix = "Live" if mode == "Live Scan (Same Day)" else f"Backtest_{target_date}"
            st.download_button(
                label="📥 Download Data as CSV",
                data=csv,
                file_name=f"{file_prefix}_Demand_Zones.csv",
                mime="text/csv",
            )
        else:
            st.warning("No active demand zones matched your criteria for the selected period.")
