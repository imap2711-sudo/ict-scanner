import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import io
import warnings
import logging
import concurrent.futures

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
        'WIPRO.NS', 'COALINDIA.NS', 'NESTLEIND.NS', 'GRASIM.NS', 'TECHM.NS', 'HINDALCO.NS', 
        'JSWSTEEL.NS', 'CIPLA.NS', 'SBILIFE.NS', 'DRREDDY.NS', 'EICHERMOT.NS', 'APOLLOHOSP.NS', 
        'BRITANNIA.NS', 'HDFCLIFE.NS', 'TATACHEM.NS', 'INDUSINDBK.NS', 'TATACONSUM.NS', 
        'HEROMOTOCO.NS', 'DIVISLAB.NS', 'BPCL.NS', 'UPL.NS'
    ]

def find_ict_liquidity_setups(ticker):
    try:
        t = yf.Ticker(ticker)
        df = t.history(period="2y", interval="1d", auto_adjust=False)
        
        if df.empty or len(df) < 100: 
            return None
            
        try:
            cmp = float(t.fast_info.last_price)
        except Exception:
            try:
                cmp = float(t.info.get('currentPrice', df['Close'].iloc[-1]))
            except Exception:
                cmp = float(df['Close'].iloc[-1])
                
        if pd.isna(cmp) or cmp <= 60: 
            return None

        current_month_period = df.index[-1].to_period('M')
        previous_month_period = current_month_period - 1

        eval_window = df.iloc[-30:]
        hist_df = df.iloc[:-30]
        
        levels = []
        
        prev_month_data = df[df.index.to_period('M') == previous_month_period]
        if not prev_month_data.empty:
            pml_price = prev_month_data['Low'].min()
            pml_date = prev_month_data['Low'].idxmin()
            levels.append((pml_price, pml_date, 'Last Month Low (PML)'))
            
        weekly_df = hist_df.resample('W-FRI').agg({'Low':'min'}).dropna()
        for i in range(1, len(weekly_df)-1):
            if weekly_df['Low'].iloc[i] < weekly_df['Low'].iloc[i-1] and weekly_df['Low'].iloc[i] < weekly_df['Low'].iloc[i+1]:
                w_low = weekly_df['Low'].iloc[i]
                week_start = weekly_df.index[i] - pd.Timedelta(days=6)
                week_end = weekly_df.index[i]
                week_data = hist_df.loc[week_start:week_end]
                if not week_data.empty:
                    low_date = week_data['Low'].idxmin()
                    levels.append((w_low, low_date, 'Weekly Swing Low (WSL)'))
                    
        monthly_df = hist_df.resample('ME').agg({'Low':'min'}).dropna()
        for i in range(1, len(monthly_df)-1):
            if monthly_df['Low'].iloc[i] < monthly_df['Low'].iloc[i-1] and monthly_df['Low'].iloc[i] < monthly_df['Low'].iloc[i+1]:
                m_low = monthly_df['Low'].iloc[i]
                month_start = monthly_df.index[i].replace(day=1)
                month_end = monthly_df.index[i]
                month_data = hist_df.loc[month_start:month_end]
                if not month_data.empty:
                    low_date = month_data['Low'].idxmin()
                    levels.append((m_low, low_date, 'Monthly Swing Low (MSL)'))

        fresh_levels = []
        for price, date, ltype in levels:
            if ltype != 'Last Month Low (PML)': 
                if date < hist_df.index[-1]:
                    subsequent_data = hist_df.loc[date + pd.Timedelta(days=1):]
                    if not subsequent_data.empty and subsequent_data['Low'].min() < price:
                        continue 
            fresh_levels.append((price, date, ltype))
            
        if not fresh_levels: 
            return None
        
        sweep_occurred = False
        swept_level_details = None
        first_sweep_day = None
        
        for price, date, ltype in fresh_levels:
            sweep_candidates = eval_window[eval_window['Low'] < price]
            if not sweep_candidates.empty:
                temp_first_sweep = sweep_candidates.index[0]
                
                if ltype == 'Last Month Low (PML)':
                    if temp_first_sweep.to_period('M') != current_month_period:
                        continue
                
                if temp_first_sweep <= date:
                    continue
                    
                sweep_occurred = True
                first_sweep_day = temp_first_sweep
                swept_level_details = (price, date, ltype)
                break 
                
        if not sweep_occurred: 
            return None
        
        sweep_low_price = eval_window['Low'].min()
        
        pre_sweep_data = df.loc[:first_sweep_day].iloc[-30:-1]
        if pre_sweep_data.empty: 
            return None
        
        swing_highs = []
        for i in range(1, len(pre_sweep_data)-1):
            if pre_sweep_data['High'].iloc[i] > pre_sweep_data['High'].iloc[i-1] and pre_sweep_data['High'].iloc[i] > pre_sweep_data['High'].iloc[i+1]:
                swing_highs.append(pre_sweep_data['High'].iloc[i])
                
        if not swing_highs:
            return None
        nearest_pre_sweep_high = swing_highs[-1]
        
        post_sweep_data = df.loc[first_sweep_day:]
        breakout_days = post_sweep_data[post_sweep_data['Close'] > nearest_pre_sweep_high]
        
        if breakout_days.empty:
            return None 
            
        first_breakout_day = breakout_days.index[0]
        
        first_sweep_idx_pos = df.index.get_loc(first_sweep_day)
        first_breakout_idx_pos = df.index.get_loc(first_breakout_day)
        trading_days_to_mss = first_breakout_idx_pos - first_sweep_idx_pos
        
        if trading_days_to_mss > 10:
            return None
            
        displacement_high_idx = post_sweep_data['High'].idxmax()
        displacement_high = post_sweep_data['High'].max()
        dealing_range_50_level = sweep_low_price + (displacement_high - sweep_low_price) * 0.5
        
        post_high_data = post_sweep_data.loc[displacement_high_idx:]
        if not post_high_data.empty:
            if post_high_data['Low'].min() <= dealing_range_50_level:
                return None 
                
        if cmp <= dealing_range_50_level:
            return None
            
        distance_to_eq_pct = ((cmp - dealing_range_50_level) / cmp) * 100
            
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
            "Distance to 50% Eq. (%)": round(distance_to_eq_pct, 2)
        }
        
    except Exception:
        return None

st.title("ICT Liquidity Sweep & MSS Screener (Nifty 500)")
st.markdown("Identifies 100% fresh Higher Timeframe Liquidity Sweeps leading to a Market Structure Shift (MSS) within 10 days, pulling back toward an untested 50% Discount Level.")

if st.button("Run Screener"):
    with st.spinner("Fetching Nifty 500 Universe..."):
        tickers = get_nifty500_symbols()
        
    progress_text = "Scanning Equities..."
    my_bar = st.progress(0, text=progress_text)
    
    active_setups = []
    total_tickers = len(tickers)
    
    # ThreadPoolExecutor is used to bypass the 10-minute Colab loop and fetch yfinance data concurrently
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(find_ict_liquidity_setups, t): t for t in tickers}
        for i, future in enumerate(concurrent.futures.as_completed(futures)):
            result = future.result()
            if result:
                active_setups.append(result)
            
            progress = (i + 1) / total_tickers
            my_bar.progress(progress, text=f"Scanned {i+1}/{total_tickers} stocks...")
            
    my_bar.empty()
    
    if active_setups:
        active_setups.sort(key=lambda x: x['Distance to 50% Eq. (%)'])
        df_final = pd.DataFrame(active_setups)
        
        st.success(f"Found {len(df_final)} active setups!")
        st.dataframe(df_final, use_container_width=True)
        
        csv = df_final.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="Download Results as CSV",
            data=csv,
            file_name="ICT_Fresh_50_Retracements.csv",
            mime="text/csv",
        )
    else:
        st.warning("No stocks matched these strict ICT conditions today.")
