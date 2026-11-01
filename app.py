import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import concurrent.futures
from datetime import datetime, timedelta
import pytz
import os
import shutil

# --- PAGE SETUP ---
st.set_page_config(page_title="ICT Precision Scanner", layout="wide", page_icon="⚡")
ist = pytz.timezone('Asia/Kolkata')

# ---------------------------------------------------------
# SMART CACHE DIRECTORY SETUP
# ---------------------------------------------------------
CACHE_DIR = "nifty500_data_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

custom_css = """
<style>
    .stApp { background-color: #0B1121; color: #E2E8F0; }
    h1, h2, h3, p, label, .stMetric label { color: #E2E8F0 !important; font-family: 'Inter', sans-serif !important; }
    [data-testid="stDataFrame"] { background-color: #0F172A; border-radius: 8px; }
    div[data-testid="metric-container"] { background-color: #1E293B; border: 1px solid #334155; padding: 15px; border-radius: 8px; }
    div[data-baseweb="tab-list"] { gap: 10px; }
    div[data-baseweb="tab"] { background-color: #1E293B; border-radius: 8px !important; padding: 10px 20px !important; border: 1px solid #334155; color: white !important; font-weight: 600; margin: 0 !important; }
    div[data-baseweb="tab"][aria-selected="true"]:nth-child(1) { background-color: #10B981 !important; border-color: #059669 !important; }
    div[data-baseweb="tab"][aria-selected="true"]:nth-child(2) { background-color: #EF4444 !important; border-color: #DC2626 !important; }
</style>
"""
st.markdown(custom_css, unsafe_allow_html=True)

@st.cache_data(ttl=86400, show_spinner=False)
def get_nifty500_symbols():
    nifty500_csv = "360ONE,3MINDIA,ABB,ACC,AIAENG,APLAPOLLO,AUBANK,AARTIDRUGS,AARTIIND,AAVAS,ABBOTINDIA,ADANIENT,ADANIGREEN,ADANIPORTS,ADANIPOWER,ATGL,AWL,ABCAPITAL,ABFRL,AEGISCHEM,AETHER,AFFLE,AJANTPHARM,APLLTD,ALKEM,ALKYLAMINE,ALLCARGO,AMARAJABAT,AMBER,AMBUJACEM,ANANDAMATH,ANGELONE,ANURAS,APARINDS,APOLLOHOSP,APOLLOTYRE,APTUS,ASAHIINDIA,ASHOKLEY,ASIANPAINT,ASTERDM,ASTRAL,ATUL,AUROPHARMA,AVANTIFEED,DMART,AXISBANK,BEML,BSE,BAJAJ-AUTO,BAJAJFINSV,BAJFINANCE,BAJAJHLDNG,BALAMINES,BALKRISIND,BALRAMCHIN,BANDHANBNK,BANKBARODA,BANKINDIA,MAHABANK,BATAINDIA,BAYERCROP,BERGEPAINT,BDL,BEL,BHARATFORG,BHEL,BPCL,BHARTIARTL,BIOCON,BOSCHLTD,BRIGADE,BRITANNIA,MAPMYINDIA,CCL,CESC,CGPOWER,CAMS,CANFINHOME,CANBK,CAPLIPOINT,CARBORUNIV,CASTROLIND,CEATLTD,CENTRALBK,CDSL,CENTURYPLY,CENTURYTEX,CERA,CHALET,CHAMBLFERT,CHEMPLASTS,CHENNPETRO,CHOLAFIN,CHOLAHLDNG,CIPLA,CLEAN,COALINDIA,COCHINSHIP,COFORGE,COLPAL,CONCOR,COROMANDEL,CRAFTSMAN,CREDITACC,CROMPTON,CUB,CUMMINSIND,CYIENT,DCMSHRIRAM,DLF,DABUR,DALBHARAT,DEEPAKNTR,DELHIVERY,DEVYANI,DIVISLAB,DIXON,LALPATHLAB,DRREDDY,EIDPARRY,EIHOTEL,EPL,EASEMYTRIP,EICHERMOT,ELECON,ELGIEQUIP,EMAMILTD,ENDURANCE,ENGINERSIN,EQUITASBNK,ERIS,ESCORTS,EXIDEIND,FDC,NYKAA,FEDERALBNK,FACT,FINEORG,FINCABLES,FINPIPE,FSL,FORTIS,GRINFRA,GAIL,GMMPFAUDLR,GMRINFRA,GALAXYSURF,GARFIBRES,GICRE,GLAXO,GLENMARK,MEDANTA,GODFRYPHLP,GODREJAGRO,GODREJCP,GODREJIND,GODREJPROP,GRASIM,GESHIP,GRINDWELL,GUJGASLTD,GNFC,GSFC,GSPL,HAVELLS,HEG,HEGAM,HCLTECH,HDFCAMC,HDFCBANK,HDFCLIFE,HFCL,HAL,HINDALCO,HINDCOPPER,HINDPETRO,HINDUNILVR,HINDZINC,HONAUT,HSCL,HUDCO,ITC,IDBI,IDFCFIRSTB,IFBIND,IIFL,IRB,IRCON,ITI,INDIACEM,INDIAMART,INDIANB,IEX,INDHOTEL,IOC,IOB,IRCTC,IRFC,INDIGOPNTS,IGL,INDUSINDBK,NAUKRI,INFIBEAM,INFY,INOXWIND,INTELLECT,INDIGO,IPCALAB,JBCHEPHARM,JKCEMENT,JKLAKSHMI,JKPAPER,JKTYRE,JMFINANCIL,JSWENERGY,JSWSTEEL,JAICORPLTD,J&KBANK,JINDALSTEL,JINDALPHOT,JIOFIN,JUBILANT,JUBLFOOD,JUBLINGREA,JUBLPHARMA,KPRMILL,KEI,KNRCON,KPITTECH,KRBL,KSB,KAJARIACER,KALYANKJIL,KANSAINER,KARURVYSYA,KAYNES,KEC,KFINTECH,KOTAKBANK,KIMS,L&TFH,LTTS,LICHSGFIN,LTIM,LT,LATENTVIEW,LAURUSLABS,LEMONTREE,LICI,LINDEINDIA,LUPIN,MRF,MTARTECH,MACPOWER,LODHA,MGL,M&MFIN,M&M,MAHSEAMLES,MARICO,MARUTI,MASTEK,MAXHEALTH,MAXFIN,MAZDOCK,MEDPLUS,METROBRAND,METROPOLIS,MINDACORP,UNOINDA,MOTILALOFS,MPHASIS,MCX,MUTHOOTFIN,NATCOPHARM,NBCC,NCC,NHPC,NLCINDIA,NMDC,NOCIL,NTPC,OBEROIRLTY,ONGC,OIL,OLECTRA,PAYTM,OFSS,POLICYBKR,PCBL,PIIND,PNBHOUSING,PNCINFRA,PVRINOX,PAGEIND,PATANJALI,PERSISTENT,PETRONET,PFIZER,PHOENIXLTD,PIDILITIND,PEL,PPLPHARMA,POLYMED,POLYCAB,POONAWALLA,PFC,POWERGRID,PRAJIND,PRESTIGE,PRINCEPIPE,PRSMJOHNSN,PGHL,PNB,QUESS,RBLBANK,RECLTD,RHIM,RITES,RADICO,RVNL,RAILTEL,RAIN,RAMCOCEM,RATNAMANI,RAYMOND,REDINGTON,RELAXO,RELIANCE,RBA,ROUTE,SJVN,SKFINDIA,SRF,MOTHERSON,SANOFI,SAPPHIRE,SAREGAMA,SCHAEFFLER,SCHNEIDER,CIGNITITEC,SEQUENT,SHARDACROP,SHAREINDIA,SCI,SHREECEM,SHRIRAMFIN,SHYAMMETL,SIEMENS,SOBHA,SOLARINDS,SONACOMS,STARHEALTH,SBI,SAIL,SBM,STLTECH,STARCEMENT,SUDARSCHEM,SUMICHEM,SPARC,SUNPHARMA,SUNTV,SUNDARMFIN,SUNDRMFAST,SUNTECK,SUPREMEIND,SUVENPHAR,SUZLON,SWANENERGY,SYMPHONY,SYNGENE,TCIEXP,TCNSBRANDS,TCS,TATACHEM,TATACOMM,TATACONSUM,TATAELXSI,TATAINVEST,TATAMOTORS,TATAPOWER,TATASTEEL,TTML,TEAMLEASE,TECHM,TEJASNET,THERMAX,TIDEWATER,TIMKEN,TITAN,TORNTPHARM,TORNTPOWER,TRENT,TRIDENT,TRIVENI,TRIVENITQ,TUBEINVEST,UCOBANK,UPL,UTIAMC,UJJIVANSFB,ULTRACEMCO,UNIONBANK,UBL,MCDOWELL-N,VGUARD,VMART,VIPIND,VAIBHAVGBL,VTL,VARROC,VBL,VEDL,VENKEYS,VIJAYA,VINATIORGA,IDEA,VOLTAS,WELCORP,WELENT,WHIRLPOOL,WIPRO,YESBANK,ZFCVINDIA,ZEEL,ZENSARTECH,ZOMATO,ZYDUSLIFE"
    return [s.strip() + ".NS" for s in nifty500_csv.split(",")]

# ---------------------------------------------------------
# SMART RAM + DISK CACHE FUNCTION
# ---------------------------------------------------------
@st.cache_data(ttl=900, show_spinner=False)
def fetch_market_data(ticker, period, interval):
    file_path = os.path.join(CACHE_DIR, f"{ticker}_{interval}.csv")
    t = yf.Ticker(ticker)
    
    if os.path.exists(file_path):
        try:
            # Use UTC to guarantee safe cross-timezone file age comparison
            file_mod_time = datetime.fromtimestamp(os.path.getmtime(file_path), tz=pytz.UTC)
            now = datetime.now(pytz.UTC)
            
            local_df = pd.read_csv(file_path, index_col=0, parse_dates=True)
            if not local_df.empty:
                is_stale = False
                if interval == '15m' and (now - file_mod_time) > timedelta(minutes=15):
                    is_stale = True
                elif interval == '1d' and (now - file_mod_time) > timedelta(hours=24):
                    is_stale = True
                    
                if is_stale:
                    fetch_period = "5d" if interval == "15m" else "1mo"
                    recent_df = t.history(period=fetch_period, interval=interval, auto_adjust=False)
                    
                    if not recent_df.empty:
                        recent_df.index = recent_df.index.tz_convert('Asia/Kolkata').tz_localize(None) if recent_df.index.tz else recent_df.index.tz_localize(None)
                        combined = pd.concat([local_df, recent_df])
                        combined = combined[~combined.index.duplicated(keep='last')].sort_index()
                        
                        # Strict memory trimming
                        if interval == '15m':
                            sixty_days_ago = combined.index[-1] - pd.Timedelta(days=60)
                            combined = combined[combined.index >= sixty_days_ago]
                            
                        combined.to_csv(file_path)
                        return combined
                    else:
                        # Override modification timestamp so it stops pinging Yahoo on closed weekends
                        os.utime(file_path, None) 
                        return local_df
                else:
                    return local_df
        except Exception:
            pass 
            
    df = t.history(period=period, interval=interval, auto_adjust=False)
    if not df.empty:
        df.index = df.index.tz_convert('Asia/Kolkata').tz_localize(None) if df.index.tz else df.index.tz_localize(None)
        df.to_csv(file_path)
    return df

def get_nearest_untested_75m_swing(df_75m, sweep_idx, direction='high'):
    closest_75m_time = df_75m.index.asof(sweep_idx)
    if pd.isna(closest_75m_time): return None, None
    loc = df_75m.index.get_loc(closest_75m_time)
    
    for i in range(loc - 1, 0, -1):
        if direction == 'high':
            if df_75m['High'].iloc[i] > df_75m['High'].iloc[i-1] and df_75m['High'].iloc[i] > df_75m['High'].iloc[i+1]:
                if df_75m['Close'].iloc[i:loc].max() < df_75m['High'].iloc[i]:
                    return df_75m.index[i], df_75m['High'].iloc[i]
        else:
            if df_75m['Low'].iloc[i] < df_75m['Low'].iloc[i-1] and df_75m['Low'].iloc[i] < df_75m['Low'].iloc[i+1]:
                if df_75m['Close'].iloc[i:loc].min() > df_75m['Low'].iloc[i]:
                    return df_75m.index[i], df_75m['Low'].iloc[i]
                    
    for i in range(loc + 1, len(df_75m)-1):
        if direction == 'high':
            if df_75m['High'].iloc[i] > df_75m['High'].iloc[i-1] and df_75m['High'].iloc[i] > df_75m['High'].iloc[i+1]:
                return df_75m.index[i], df_75m['High'].iloc[i]
        else:
            if df_75m['Low'].iloc[i] < df_75m['Low'].iloc[i-1] and df_75m['Low'].iloc[i] < df_75m['Low'].iloc[i+1]:
                return df_75m.index[i], df_75m['Low'].iloc[i]
    return None, None

def get_nearest_15m_target_swing(df_15m, activation_idx, direction='high'):
    try:
        loc = df_15m.index.get_loc(activation_idx)
        for i in range(loc + 1, len(df_15m)-1):
            if direction == 'high':
                if df_15m['High'].iloc[i] > df_15m['High'].iloc[i-1] and df_15m['High'].iloc[i] > df_15m['High'].iloc[i+1]:
                    return df_15m['High'].iloc[i]
            else:
                if df_15m['Low'].iloc[i] < df_15m['Low'].iloc[i-1] and df_15m['Low'].iloc[i] < df_15m['Low'].iloc[i+1]:
                    return df_15m['Low'].iloc[i]
        return None
    except: return None

def find_sd_zone(df_15m, sweep_time, activation_time, mss_price, direction, zone_method):
    try:
        leg_df = df_15m.loc[sweep_time:activation_time].copy()
        if len(leg_df) < 3: return None, None
        
        leg_df['Body'] = abs(leg_df['Open'] - leg_df['Close'])
        leg_df['Range'] = leg_df['High'] - leg_df['Low']
        leg_df['Is_Base'] = (leg_df['Body'] / leg_df['Range'].replace(0, 0.001)) <= 0.5
        
        base_candles = leg_df[leg_df['Is_Base']].copy()
        if base_candles.empty: return None, None
        
        base_candles['Dist_to_MSS'] = abs(((base_candles['High'] + base_candles['Low']) / 2) - mss_price)
        closest_base_idx = base_candles['Dist_to_MSS'].idxmin()
        
        leg_df['Block'] = (~leg_df['Is_Base']).cumsum()
        target_block = leg_df.loc[closest_base_idx, 'Block']
        zone_candles = leg_df[(leg_df['Is_Base']) & (leg_df['Block'] == target_block)]
        
        if zone_candles.empty: return None, None
        
        if zone_method == "Strict (Base + Leg-Out)":
            last_base_idx = zone_candles.index[-1]
            post_base = leg_df.loc[last_base_idx:]
            if len(post_base) > 1:
                post_base = post_base.iloc[1:]
            else:
                return None, None
            
            if direction == 'Bullish':
                valid_legout = post_base[(post_base['Close'] > post_base['Open']) & (~post_base['Is_Base'])]
            else:
                valid_legout = post_base[(post_base['Close'] < post_base['Open']) & (~post_base['Is_Base'])]
                
            if valid_legout.empty: return None, None
        
        if direction == 'Bullish':
            return zone_candles['High'].max(), zone_candles['Low'].min()
        else:
            return zone_candles['Low'].min(), zone_candles['High'].max()
    except: return None, None

def simulate_intraday_execution(df_15m, activation_idx, entry_price, active_sl, active_target, qty, direction):
    post_activation_df = df_15m.loc[activation_idx:]
    if len(post_activation_df) <= 1: return None
    tracking_df = post_activation_df.iloc[1:]
    
    if direction == 'Bullish': touched = tracking_df[tracking_df['Low'] <= entry_price]
    else: touched = tracking_df[tracking_df['High'] >= entry_price]
    
    if touched.empty: return {"Entry Date": "-", "Outcome": "No Entry", "P&L (₹)": 0.0, "Exit Price": "-"}
    
    entry_time = touched.index[0]
    open_px = df_15m.loc[entry_time, 'Open']
    
    if direction == 'Bullish' and open_px < active_sl: return {"Entry Date": "-", "Outcome": "Gap SL Void", "P&L (₹)": 0.0, "Exit Price": "-"}
    if direction == 'Bearish' and open_px > active_sl: return {"Entry Date": "-", "Outcome": "Gap SL Void", "P&L (₹)": 0.0, "Exit Price": "-"}
    
    actual_entry = round(open_px if open_px < entry_price else entry_price, 2) if direction == 'Bullish' else round(open_px if open_px > entry_price else entry_price, 2)
    end_of_day = entry_time.replace(hour=23, minute=59, second=59)
    day_df = df_15m.loc[entry_time:end_of_day]
    
    outcome = "Time Square Off"
    exit_price = day_df['Close'].iloc[-1]
    
    for idx, row in day_df.iterrows():
        if direction == 'Bullish':
            if row['Low'] <= active_sl: outcome, exit_price = "SL Hit", active_sl; break
            elif row['High'] >= active_target: outcome, exit_price = "Target Hit", active_target; break
        else:
            if row['High'] >= active_sl: outcome, exit_price = "SL Hit", active_sl; break
            elif row['Low'] <= active_target: outcome, exit_price = "Target Hit", active_target; break
            
    is_today = entry_time.date() == datetime.now(ist).date()
    current_time = datetime.now(ist)
    if is_today and (current_time.hour < 15 or (current_time.hour == 15 and current_time.minute < 30)):
        if outcome == "Time Square Off":
            outcome = "Running (Live)"
            
    pnl = round(qty * (exit_price - actual_entry), 2) if direction == 'Bullish' else round(qty * (actual_entry - exit_price), 2)
    
    return {
        "Entry Date": entry_time.strftime('%Y-%m-%d %H:%M'),
        "Outcome": outcome,
        "Exit Price": round(exit_price, 2),
        "P&L (₹)": pnl
    }

def evaluate_ticker(ticker, start_date_val, end_date_val, risk_amt, zone_method, app_mode):
    raw_setups = []
    
    internal_start = start_date_val - timedelta(days=10) if app_mode == "Today's Live Trades" else start_date_val - timedelta(days=15)
    
    df_15m = fetch_market_data(ticker, "60d", "15m")
    daily_htf = fetch_market_data(ticker, "1y", "1d")
    if df_15m.empty or daily_htf.empty: return []
    
    resampled = [{'Datetime': chunk.index[0], 'Open': chunk['Open'].iloc[0], 'High': chunk['High'].max(), 'Low': chunk['Low'].min(), 'Close': chunk['Close'].iloc[-1]} for date, group in df_15m.groupby(df_15m.index.date) for i in range(0, len(group), 5) if len(chunk := group.iloc[i:i+5]) > 0]
    df_75m = pd.DataFrame(resampled).set_index('Datetime')
    weekly_hist = daily_htf.resample('W-MON', closed='left', label='left').agg({'High':'max', 'Low':'min'}).dropna()
    available_dates = pd.Series(df_15m.index.date).drop_duplicates().apply(pd.to_datetime)
    scan_days = available_dates[(available_dates >= pd.to_datetime(internal_start)) & (available_dates <= pd.to_datetime(end_date_val))]
    
    for d in scan_days:
        current_monday = d - pd.Timedelta(days=d.weekday())
        current_monday = current_monday.replace(hour=0, minute=0, second=0)
        past_weekly = weekly_hist.loc[weekly_hist.index < current_monday]
        if past_weekly.empty: continue
        
        pwl, pwh = past_weekly['Low'].iloc[-1], past_weekly['High'].iloc[-1]
        day_15m = df_15m.loc[d.strftime('%Y-%m-%d')]
        if day_15m.empty: continue
        
        for sweep_idx, sweep_row in day_15m.iterrows():
            if sweep_row['Low'] <= pwl:
                sh_idx_75m, sh_val_75m = get_nearest_untested_75m_swing(df_75m, sweep_idx, 'high')
                if not sh_idx_75m: continue
                
                post_sweep_15m = df_15m.loc[sweep_idx:]
                activation_points = (post_sweep_15m['Close'] > sh_val_75m).astype(int).rolling(window=3).sum()
                activation_points = activation_points[activation_points == 3]
                
                if not activation_points.empty:
                    activation_idx = activation_points.index[0]
                    if len(np.unique(df_15m.loc[sweep_idx:activation_idx].index.date)) <= 2:
                        proximal, distal = find_sd_zone(df_15m, sweep_idx, activation_idx, sh_val_75m, 'Bullish', zone_method)
                        if proximal and distal:
                            target_val = get_nearest_15m_target_swing(df_15m, activation_idx, 'high')
                            if target_val:
                                entry_price, active_sl, active_target = round(proximal, 2), round(distal * 0.999, 2), round(target_val, 2)
                                risk_dist, target_dist = round(abs(entry_price - active_sl), 2), round(abs(active_target - entry_price), 2)
                                
                                if risk_dist > 0 and target_dist >= risk_dist:
                                    qty = int(risk_amt / risk_dist)
                                    if qty > 0:
                                        setup = {"Stock": ticker.replace('.NS',''), "Type": "Bullish", "Sweep Time": sweep_idx, "Activation Time": activation_idx, "MSS Line": sh_val_75m, "Entry": entry_price, "SL": active_sl, "Target": active_target, "Target RR": f"1:{round(target_dist / risk_dist, 1)}", "Qty": qty}
                                        raw_setups.append(setup)
                                        break 

            elif sweep_row['High'] >= pwh:
                sl_idx_75m, sl_val_75m = get_nearest_untested_75m_swing(df_75m, sweep_idx, 'low')
                if not sl_idx_75m: continue
                
                post_sweep_15m = df_15m.loc[sweep_idx:]
                activation_points = (post_sweep_15m['Close'] < sl_val_75m).astype(int).rolling(window=3).sum()
                activation_points = activation_points[activation_points == 3]
                
                if not activation_points.empty:
                    activation_idx = activation_points.index[0]
                    if len(np.unique(df_15m.loc[sweep_idx:activation_idx].index.date)) <= 2:
                        proximal, distal = find_sd_zone(df_15m, sweep_idx, activation_idx, sl_val_75m, 'Bearish', zone_method)
                        if proximal and distal:
                            target_val = get_nearest_15m_target_swing(df_15m, activation_idx, 'low')
                            if target_val:
                                entry_price, active_sl, active_target = round(proximal, 2), round(distal * 1.001, 2), round(target_val, 2)
                                risk_dist, target_dist = round(abs(entry_price - active_sl), 2), round(abs(entry_price - active_target), 2)
                                
                                if risk_dist > 0 and target_dist >= risk_dist:
                                    qty = int(risk_amt / risk_dist)
                                    if qty > 0:
                                        setup = {"Stock": ticker.replace('.NS',''), "Type": "Bearish", "Sweep Time": sweep_idx, "Activation Time": activation_idx, "MSS Line": sl_val_75m, "Entry": entry_price, "SL": active_sl, "Target": active_target, "Target RR": f"1:{round(target_dist / risk_dist, 1)}", "Qty": qty}
                                        raw_setups.append(setup)
                                        break
                                        
    deduped_setups = {}
    for s in raw_setups:
        key = (s['Stock'], s['Type'], s['Activation Time'])
        if key not in deduped_setups or s['Sweep Time'] > deduped_setups[key]['Sweep Time']:
            deduped_setups[key] = s
            
    final_setups = []
    today_str = datetime.now(ist).strftime('%Y-%m-%d')
    
    for s in deduped_setups.values():
        exec_data = simulate_intraday_execution(df_15m, s['Activation Time'], s['Entry'], s['SL'], s['Target'], s['Qty'], s['Type'])
        if not exec_data: continue
        
        s.update(exec_data)
        s['Sweep Time'] = s['Sweep Time'].strftime('%Y-%m-%d %H:%M')
        s['Activation Time'] = s['Activation Time'].strftime('%Y-%m-%d %H:%M')
        
        entry_date_str = exec_data.get("Entry Date", "-")
        outcome = exec_data.get("Outcome", "")
        
        if app_mode == "Today's Live Trades":
            if entry_date_str.startswith(today_str):
                final_setups.append(s)
            elif outcome == "No Entry" and s['Activation Time'].startswith(today_str):
                s["Outcome"] = "Pending Entry"
                final_setups.append(s)
        
        elif app_mode == "Backtester":
            if entry_date_str != "-" and outcome != "Gap SL Void":
                try:
                    entry_date_obj = datetime.strptime(entry_date_str, '%Y-%m-%d %H:%M').date()
                    if start_date_val <= entry_date_obj <= end_date_val:
                        final_setups.append(s)
                except ValueError:
                    pass
                    
    return final_setups

# --- UI EXECUTION ---
st.title("⚡ Weekly ICT Sweep & MTF Screener")
st.write("Strictly executing the 7-Rule framework with Smart Local RAM Caching.")

if st.button("🗑️ Clear Local Data Cache", type="secondary"):
    if os.path.exists(CACHE_DIR):
        shutil.rmtree(CACHE_DIR)
        os.makedirs(CACHE_DIR)
    st.cache_data.clear()
    st.success("Cache cleared! The next scan will download fresh historical data.")

app_mode = st.radio("Operating Mode", ["Today's Live Trades", "Backtester"], horizontal=True)

if app_mode == "Backtester":
    c1, c2, c3, c4 = st.columns(4)
    today = datetime.now(ist).date()
    with c1: start_date = st.date_input("Entry Start Date", today - timedelta(days=5))
    with c2: end_date = st.date_input("Entry End Date", today)
    with c3: risk_amt = st.number_input("Risk Per Trade (₹)", value=1000, step=100)
    with c4: zone_method = st.selectbox("Zone Identification", ["Standard (Base Only)", "Strict (Base + Leg-Out)"])
else:
    c1, c2 = st.columns(2)
    today = datetime.now(ist).date()
    start_date, end_date = today, today
    with c1: risk_amt = st.number_input("Risk Per Trade (₹)", value=1000, step=100)
    with c2: zone_method = st.selectbox("Zone Identification", ["Standard (Base Only)", "Strict (Base + Leg-Out)"])

if st.button("🚀 Execute Scan", type="primary"):
    with st.spinner(f"Scanning Nifty 500 across {app_mode}..."):
        tickers = get_nifty500_symbols()
        all_setups = []
        progress_bar = st.progress(0)
        
        # Reduced max_workers to 10 to bypass Python GIL CPU choking
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = {executor.submit(evaluate_ticker, t, start_date, end_date, risk_amt, zone_method, app_mode): t for t in tickers}
            completed = 0
            for f in concurrent.futures.as_completed(futures):
                res = f.result()
                if res: all_setups.extend(res)
                completed += 1
                progress_bar.progress(completed / len(tickers))
                
        progress_bar.empty()
        
        if all_setups:
            df = pd.DataFrame(all_setups)
            cols_order = ["Stock", "Type", "Sweep Time", "Activation Time", "MSS Line", "Entry Date", "Entry", "SL", "Target", "Target RR", "Qty", "Outcome", "Exit Price", "P&L (₹)"]
            
            df_bull = df[df['Type'] == 'Bullish'].copy()
            df_bear = df[df['Type'] == 'Bearish'].copy()
            
            if not df_bull.empty: df_bull = df_bull[[c for c in cols_order if c in df_bull.columns]]
            if not df_bear.empty: df_bear = df_bear[[c for c in cols_order if c in df_bear.columns]]
            
            tab1, tab2 = st.tabs(["🟢 Bullish Setups", "🔴 Bearish Setups"])
            
            def render_tab(df_sub):
                if df_sub.empty:
                    st.info("No triggered trades in this category.")
                    return
                    
                completed_trades = df_sub[df_sub['Outcome'].isin(["Target Hit", "SL Hit", "Time Square Off", "Running (Live)"])]
                wins = len(completed_trades[completed_trades['P&L (₹)'] > 0])
                total = len(completed_trades)
                win_rate = (wins / total) * 100 if total > 0 else 0
                total_pnl = completed_trades['P&L (₹)'].sum()
                
                m1, m2, m3 = st.columns(3)
                m1.metric("Active / Completed Trades", total)
                m2.metric("Win Rate", f"{win_rate:.1f}%")
                m3.metric("Net Profit / Loss", f"₹ {total_pnl:,.2f}")
                
                st.dataframe(df_sub, use_container_width=True, hide_index=True)
                
            with tab1: render_tab(df_bull)
            with tab2: render_tab(df_bear)
        else:
            st.warning("No setups met all conditions for the selected mode.")
