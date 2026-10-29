import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import io
import concurrent.futures
from datetime import datetime
import pytz

st.set_page_config(page_title="ICT 15m Scanner (Advanced)", layout="wide", page_icon="⚡")
ist = pytz.timezone('Asia/Kolkata')

@st.cache_data(ttl=3600)
def get_nifty500_symbols():
    url = "https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv"
    headers = {"User-Agent": "Mozilla/5.0"}
    for _ in range(3):
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                df = pd.read_csv(io.StringIO(response.text))
                return [str(symbol).strip() + '.NS' for symbol in df['Symbol']]
        except Exception:
            pass
    return ['RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'ICICIBANK.NS', 'INFY.NS', 'ITC.NS', 'SBIN.NS', 'LT.NS']

def process_setup_logic(df, daily_df, day_start, ticker, cmp):
    hist_daily = daily_df.loc[daily_df.index < day_start]
    if hist_daily.empty: return []
        
    pdh = hist_daily['High'].iloc[-1]
    pdl = hist_daily['Low'].iloc[-1]
            
    today_df = df.loc[df.index >= day_start]
    if today_df.empty: return []
    
    setups = []
    df_index_list = today_df.index.tolist()
    
    # Check absolute daily extremes to ensure opposite boundary is NOT touched
    day_high = today_df['High'].max()
    day_low = today_df['Low'].min()
    
    # ==========================
    # BULLISH SETUP (PDL Sweep)
    # ==========================
    # Condition: If it swept PDL, it MUST NOT have touched PDH today.
    bull_sweeps = today_df[today_df['Low'] <= pdl]
    if not bull_sweeps.empty and day_high < pdh: 
        sweep_idx = bull_sweeps.index[0]
        sweep_pos = df_index_list.index(sweep_idx)
        sweep_low = today_df.loc[sweep_idx, 'Low']
        
        hist_df = df.loc[:sweep_idx].iloc[-40:-1]
        if len(hist_df) >= 3:
            shs = [hist_df['High'].iloc[i] for i in range(1, len(hist_df)-1) 
                   if hist_df['High'].iloc[i] > hist_df['High'].iloc[i-1] and hist_df['High'].iloc[i] > hist_df['High'].iloc[i+1]]
            
            if shs:
                recent_swing_high = shs[-1]
                
                # MSS check (max 6 candles)
                post_sweep = today_df.iloc[sweep_pos+1 : sweep_pos+7] 
                mss_cands = post_sweep[post_sweep['Close'] > recent_swing_high]
                
                if not mss_cands.empty:
                    mss_idx = mss_cands.index[0]
                    mss_pos = df_index_list.index(mss_idx)
                    
                    leg_df = today_df.iloc[sweep_pos : mss_pos+2]
                    leg_high = leg_df['High'].max()
                    leg_high_pos = df_index_list.index(leg_df['High'].idxmax())
                    
                    eq_50 = (sweep_low + leg_high) / 2
                    
                    post_leg_df = today_df.iloc[leg_high_pos+1:]
                    touched_50 = False
                    if not post_leg_df.empty:
                        if post_leg_df['Low'].min() <= eq_50:
                            touched_50 = True
                    
                    category = "Already Touched 50%" if touched_50 else "MSS Done (Untouched)"
                    
                    setups.append({
                        "Direction": "Bullish",
                        "Category": category,
                        "Symbol": ticker.replace('.NS', ''),
                        "Time of Sweep": sweep_idx.strftime('%H:%M'),
                        "Time of MSS": mss_idx.strftime('%H:%M'),
                        "PDL Swept (₹)": round(pdl, 2),
                        "Sweep Low (₹)": round(sweep_low, 2),
                        "Leg High (₹)": round(leg_high, 2),
                        "50% Level (₹)": round(eq_50, 2),
                        "Live Price (₹)": round(cmp, 2),
                        "Distance from 50% (%)": round(((cmp - eq_50) / cmp) * 100, 2)
                    })

    # ==========================
    # BEARISH SETUP (PDH Sweep)
    # ==========================
    # Condition: If it swept PDH, it MUST NOT have touched PDL today.
    bear_sweeps = today_df[today_df['High'] >= pdh]
    if not bear_sweeps.empty and day_low > pdl: 
        sweep_idx = bear_sweeps.index[0]
        sweep_pos = df_index_list.index(sweep_idx)
        sweep_high = today_df.loc[sweep_idx, 'High']
        
        hist_df = df.loc[:sweep_idx].iloc[-40:-1]
        if len(hist_df) >= 3:
            sls = [hist_df['Low'].iloc[i] for i in range(1, len(hist_df)-1) 
                   if hist_df['Low'].iloc[i] < hist_df['Low'].iloc[i-1] and hist_df['Low'].iloc[i] < hist_df['Low'].iloc[i+1]]
            
            if sls:
                recent_swing_low = sls[-1]
                
                # MSS check (max 6 candles)
                post_sweep = today_df.iloc[sweep_pos+1 : sweep_pos+7] 
                mss_cands = post_sweep[post_sweep['Close'] < recent_swing_low]
                
                if not mss_cands.empty:
                    mss_idx = mss_cands.index[0]
                    mss_pos = df_index_list.index(mss_idx)
                    
                    leg_df = today_df.iloc[sweep_pos : mss_pos+2]
                    leg_low = leg_df['Low'].min()
                    leg_low_pos = df_index_list.index(leg_df['Low'].idxmin())
                    
                    eq_50 = (sweep_high + leg_low) / 2
                    
                    post_leg_df = today_df.iloc[leg_low_pos+1:]
                    touched_50 = False
                    if not post_leg_df.empty:
                        if post_leg_df['High'].max() >= eq_50:
                            touched_50 = True
                    
                    category = "Already Touched 50%" if touched_50 else "MSS Done (Untouched)"
                    
                    setups.append({
                        "Direction": "Bearish",
                        "Category": category,
                        "Symbol": ticker.replace('.NS', ''),
                        "Time of Sweep": sweep_idx.strftime('%H:%M'),
                        "Time of MSS": mss_idx.strftime('%H:%M'),
                        "PDH Swept (₹)": round(pdh, 2),
                        "Sweep High (₹)": round(sweep_high, 2),
                        "Leg Low (₹)": round(leg_low, 2),
                        "50% Level (₹)": round(eq_50, 2),
                        "Live Price (₹)": round(cmp, 2),
                        "Distance from 50% (%)": round(((eq_50 - cmp) / cmp) * 100, 2)
                    })
                        
    return setups

def scan_ticker(ticker):
    try:
        t = yf.Ticker(ticker)
        df = t.history(period="10d", interval="15m", auto_adjust=False)
        if df.empty or len(df) < 50: return None
            
        if df.index.tz is not None:
            df.index = df.index.tz_convert('Asia/Kolkata').tz_localize(None)
        else:
            df.index = df.index.tz_localize(None)
            
        df = df.dropna(subset=['Close', 'High', 'Low'])
        
        try: cmp = float(t.fast_info.last_price)
        except: cmp = float(df['Close'].iloc[-1])
            
        if pd.isna(cmp) or cmp <= 60: return None
            
        if cmp > df['High'].iloc[-1]: df.loc[df.index[-1], 'High'] = cmp
        if cmp < df['Low'].iloc[-1]: df.loc[df.index[-1], 'Low'] = cmp
        df.loc[df.index[-1], 'Close'] = cmp
        
        daily_df = df.resample('D').agg({'High':'max', 'Low':'min', 'Close':'last'}).dropna()
        if len(daily_df) < 2: return None
            
        today_start = daily_df.index[-1].replace(hour=0, minute=0, second=0)
        
        return process_setup_logic(df, daily_df, today_start, ticker, cmp)
    except:
        return None

@st.cache_data(ttl=180, show_spinner=False)
def run_full_scan():
    tickers = get_nifty500_symbols()
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = [executor.submit(scan_ticker, tick) for tick in tickers]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                results.extend(res)
    return results

# --- STREAMLIT UI ---
st.title("🎯 Nifty 500 ICT 15m Precision Scanner")
st.markdown("**Strict Rules:** First Sweep -> No Opposite Touch -> MSS in 6 Candles -> Sub-categorized by 50% Touch.")
now_str = datetime.now(ist).strftime("%Y-%m-%d %H:%M:%S IST")
st.markdown(f"**Last Scanned:** `{now_str}`")

if st.button("🚀 Fetch Live Market Data & Scan", type="primary"):
    with st.spinner("Scanning 500 stocks with updated logic. Please wait..."):
        st.session_state['scan_results'] = run_full_scan()

if 'scan_results' in st.session_state:
    all_data = st.session_state['scan_results']
    
    if not all_data:
        st.warning("No stocks matched these strict conditions right now.")
    else:
        df_all = pd.DataFrame(all_data)
        
        # Bullish Data
        df_bull = df_all[df_all['Direction'] == 'Bullish']
        df_bull_untouched = df_bull[df_bull['Category'] == 'MSS Done (Untouched)'].sort_values('Distance from 50% (%)')
        df_bull_touched = df_bull[df_bull['Category'] == 'Already Touched 50%'].sort_values('Distance from 50% (%)')
        
        # Bearish Data
        df_bear = df_all[df_all['Direction'] == 'Bearish']
        df_bear_untouched = df_bear[df_bear['Category'] == 'MSS Done (Untouched)'].sort_values('Distance from 50% (%)')
        df_bear_touched = df_bear[df_bear['Category'] == 'Already Touched 50%'].sort_values('Distance from 50% (%)')
        
        main_tab1, main_tab2 = st.tabs(["🟢 Bullish Setups", "🔴 Bearish Setups"])
        
        with main_tab1:
            bull_sub1, bull_sub2 = st.tabs(["MSS Done (Untouched 50%)", "Already Touched 50%"])
            with bull_sub1:
                if df_bull_untouched.empty: st.info("No untouched Bullish setups.")
                else: st.dataframe(df_bull_untouched.drop(columns=['Direction', 'Category']), use_container_width=True, hide_index=True)
            with bull_sub2:
                if df_bull_touched.empty: st.info("No Bullish setups have touched 50% yet.")
                else: st.dataframe(df_bull_touched.drop(columns=['Direction', 'Category']), use_container_width=True, hide_index=True)
                
        with main_tab2:
            bear_sub1, bear_sub2 = st.tabs(["MSS Done (Untouched 50%)", "Already Touched 50%"])
            with bear_sub1:
                if df_bear_untouched.empty: st.info("No untouched Bearish setups.")
                else: st.dataframe(df_bear_untouched.drop(columns=['Direction', 'Category']), use_container_width=True, hide_index=True)
            with bear_sub2:
                if df_bear_touched.empty: st.info("No Bearish setups have touched 50% yet.")
                else: st.dataframe(df_bear_touched.drop(columns=['Direction', 'Category']), use_container_width=True, hide_index=True)
else:
    st.info("👆 Click the button above to run the scan for today's market data.")
