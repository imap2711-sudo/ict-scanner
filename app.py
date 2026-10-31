import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import io
import concurrent.futures
from datetime import datetime, timedelta
import pytz
import numpy as np
import os
import shutil
import streamlit.components.v1 as components

# --- PAGE SETUP & CUSTOM CSS ---
st.set_page_config(page_title="ICT Precision Scanner", layout="centered", page_icon="⚡")
ist = pytz.timezone('Asia/Kolkata')

def keep_screen_awake():
    components.html(
        """
        <script>
        let wakeLock = null;
        const requestWakeLock = async () => {
          try { wakeLock = await navigator.wakeLock.request('screen'); }
          catch (err) { console.log(`${err.name}, ${err.message}`); }
        };
        requestWakeLock();
        document.addEventListener('visibilitychange', async () => {
          if (wakeLock !== null && document.visibilityState === 'visible') requestWakeLock();
        });
        </script>
        """,
        height=0, width=0
    )

for key in ['scan_run', 'scan_results', 'current_start', 'current_end', 'current_state_code', 'current_risk']:
    if key not in st.session_state:
        st.session_state[key] = False if key == 'scan_run' else None

custom_css = """
<style>
    .stApp { background-color: #0B1121; color: #E2E8F0; }
    h1, h2, h3, p, label { color: #E2E8F0 !important; font-family: 'Inter', sans-serif !important; }
    #MainMenu {visibility: hidden;} footer {visibility: hidden;} header {visibility: hidden;}
    div[data-testid="stVerticalBlock"] > div[style*="flex-direction: column;"] > div[data-testid="stVerticalBlock"] { background-color: #161E2E; padding: 20px; border-radius: 12px; border: 1px solid #1E293B; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); }
    .stSelectbox div[data-baseweb="select"] > div, .stNumberInput input, .stDateInput input { background-color: #0F172A !important; color: white !important; border: 1px solid #334155 !important; border-radius: 8px !important; }
    .stSlider div[data-baseweb="slider"] div[data-testid="stTickBar"] > div { background-color: #10B981 !important; }
    button[kind="primary"] { background-color: #EF4444 !important; color: white !important; font-weight: 600 !important; border-radius: 8px !important; border: none !important; padding: 10px !important; width: 100%; }
    button[kind="primary"]:hover { background-color: #DC2626 !important; }
    button[kind="secondary"] { background-color: #3B82F6 !important; color: white !important; border-radius: 8px !important; border: none !important; font-weight: 500 !important; }
    button[kind="secondary"]:hover { background-color: #2563EB !important; }
    div[data-baseweb="tab-list"] { gap: 10px; background-color: transparent; }
    div[data-baseweb="tab"] { background-color: #1E293B; border-radius: 8px !important; padding: 10px 20px !important; border: 1px solid #334155; color: white !important; font-weight: 600; margin: 0 !important; flex: 1; justify-content: center; }
    div[data-baseweb="tab"][aria-selected="true"]:nth-child(1) { background-color: #10B981 !important; border-color: #059669 !important; }
    div[data-baseweb="tab"][aria-selected="true"]:nth-child(2) { background-color: #EF4444 !important; border-color: #DC2626 !important; }
    [data-testid="stDataFrame"] { background-color: #0F172A; border-radius: 8px; }
</style>
"""
st.markdown(custom_css, unsafe_allow_html=True)

CACHE_DIR = "nifty500_data_cache"
os.makedirs(CACHE_DIR, exist_ok=True)

@st.cache_data(ttl=86400)
def get_nifty500_symbols():
    nifty500_csv = "360ONE,3MINDIA,ABB,ACC,AIAENG,APLAPOLLO,AUBANK,AARTIDRUGS,AARTIIND,AAVAS,ABBOTINDIA,ADANIENT,ADANIGREEN,ADANIPORTS,ADANIPOWER,ATGL,AWL,ABCAPITAL,ABFRL,AEGISCHEM,AETHER,AFFLE,AJANTPHARM,APLLTD,ALKEM,ALKYLAMINE,ALLCARGO,AMARAJABAT,AMBER,AMBUJACEM,ANANDAMATH,ANGELONE,ANURAS,APARINDS,APOLLOHOSP,APOLLOTYRE,APTUS,ASAHIINDIA,ASHOKLEY,ASIANPAINT,ASTERDM,ASTRAL,ATUL,AUROPHARMA,AVANTIFEED,DMART,AXISBANK,BEML,BSE,BAJAJ-AUTO,BAJAJFINSV,BAJFINANCE,BAJAJHLDNG,BALAMINES,BALKRISIND,BALRAMCHIN,BANDHANBNK,BANKBARODA,BANKINDIA,MAHABANK,BATAINDIA,BAYERCROP,BERGEPAINT,BDL,BEL,BHARATFORG,BHEL,BPCL,BHARTIARTL,BIOCON,BOSCHLTD,BRIGADE,BRITANNIA,MAPMYINDIA,CCL,CESC,CGPOWER,CAMS,CANFINHOME,CANBK,CAPLIPOINT,CARBORUNIV,CASTROLIND,CEATLTD,CENTRALBK,CDSL,CENTURYPLY,CENTURYTEX,CERA,CHALET,CHAMBLFERT,CHEMPLASTS,CHENNPETRO,CHOLAFIN,CHOLAHLDNG,CIPLA,CLEAN,COALINDIA,COCHINSHIP,COFORGE,COLPAL,CONCOR,COROMANDEL,CRAFTSMAN,CREDITACC,CROMPTON,CUB,CUMMINSIND,CYIENT,DCMSHRIRAM,DLF,DABUR,DALBHARAT,DEEPAKNTR,DELHIVERY,DEVYANI,DIVISLAB,DIXON,LALPATHLAB,DRREDDY,EIDPARRY,EIHOTEL,EPL,EASEMYTRIP,EICHERMOT,ELECON,ELGIEQUIP,EMAMILTD,ENDURANCE,ENGINERSIN,EQUITASBNK,ERIS,ESCORTS,EXIDEIND,FDC,NYKAA,FEDERALBNK,FACT,FINEORG,FINCABLES,FINPIPE,FSL,FORTIS,GRINFRA,GAIL,GMMPFAUDLR,GMRINFRA,GALAXYSURF,GARFIBRES,GICRE,GLAXO,GLENMARK,MEDANTA,GODFRYPHLP,GODREJAGRO,GODREJCP,GODREJIND,GODREJPROP,GRASIM,GESHIP,GRINDWELL,GUJGASLTD,GNFC,GSFC,GSPL,HAVELLS,HEG,HEGAM,HCLTECH,HDFCAMC,HDFCBANK,HDFCLIFE,HFCL,HAL,HINDALCO,HINDCOPPER,HINDPETRO,HINDUNILVR,HINDZINC,HONAUT,HSCL,HUDCO,ITC,IDBI,IDFCFIRSTB,IFBIND,IIFL,IRB,IRCON,ITI,INDIACEM,INDIAMART,INDIANB,IEX,INDHOTEL,IOC,IOB,IRCTC,IRFC,INDIGOPNTS,IGL,INDUSINDBK,NAUKRI,INFIBEAM,INFY,INOXWIND,INTELLECT,INDIGO,IPCALAB,JBCHEPHARM,JKCEMENT,JKLAKSHMI,JKPAPER,JKTYRE,JMFINANCIL,JSWENERGY,JSWSTEEL,JAICORPLTD,J&KBANK,JINDALSTEL,JINDALPHOT,JIOFIN,JUBILANT,JUBLFOOD,JUBLINGREA,JUBLPHARMA,KPRMILL,KEI,KNRCON,KPITTECH,KRBL,KSB,KAJARIACER,KALYANKJIL,KANSAINER,KARURVYSYA,KAYNES,KEC,KFINTECH,KOTAKBANK,KIMS,L&TFH,LTTS,LICHSGFIN,LTIM,LT,LATENTVIEW,LAURUSLABS,LEMONTREE,LICI,LINDEINDIA,LUPIN,MRF,MTARTECH,MACPOWER,LODHA,MGL,M&MFIN,M&M,MAHSEAMLES,MARICO,MARUTI,MASTEK,MAXHEALTH,MAXFIN,MAZDOCK,MEDPLUS,METROBRAND,METROPOLIS,MINDACORP,UNOINDA,MOTILALOFS,MPHASIS,MCX,MUTHOOTFIN,NATCOPHARM,NBCC,NCC,NHPC,NLCINDIA,NMDC,NOCIL,NTPC,OBEROIRLTY,ONGC,OIL,OLECTRA,PAYTM,OFSS,POLICYBKR,PCBL,PIIND,PNBHOUSING,PNCINFRA,PVRINOX,PAGEIND,PATANJALI,PERSISTENT,PETRONET,PFIZER,PHOENIXLTD,PIDILITIND,PEL,PPLPHARMA,POLYMED,POLYCAB,POONAWALLA,PFC,POWERGRID,PRAJIND,PRESTIGE,PRINCEPIPE,PRSMJOHNSN,PGHL,PNB,QUESS,RBLBANK,RECLTD,RHIM,RITES,RADICO,RVNL,RAILTEL,RAIN,RAMCOCEM,RATNAMANI,RAYMOND,REDINGTON,RELAXO,RELIANCE,RBA,ROUTE,SJVN,SKFINDIA,SRF,MOTHERSON,SANOFI,SAPPHIRE,SAREGAMA,SCHAEFFLER,SCHNEIDER,CIGNITITEC,SEQUENT,SHARDACROP,SHAREINDIA,SCI,SHREECEM,SHRIRAMFIN,SHYAMMETL,SIEMENS,SOBHA,SOLARINDS,SONACOMS,STARHEALTH,SBI,SAIL,SBM,STLTECH,STARCEMENT,SUDARSCHEM,SUMICHEM,SPARC,SUNPHARMA,SUNTV,SUNDARMFIN,SUNDRMFAST,SUNTECK,SUPREMEIND,SUVENPHAR,SUZLON,SWANENERGY,SYMPHONY,SYNGENE,TCIEXP,TCNSBRANDS,TCS,TATACHEM,TATACOMM,TATACONSUM,TATAELXSI,TATAINVEST,TATAMOTORS,TATAPOWER,TATASTEEL,TTML,TEAMLEASE,TECHM,TEJASNET,THERMAX,TIDEWATER,TIMKEN,TITAN,TORNTPHARM,TORNTPOWER,TRENT,TRIDENT,TRIVENI,TRIVENITQ,TUBEINVEST,UCOBANK,UPL,UTIAMC,UJJIVANSFB,ULTRACEMCO,UNIONBANK,UBL,MCDOWELL-N,VGUARD,VMART,VIPIND,VAIBHAVGBL,VTL,VARROC,VBL,VEDL,VENKEYS,VIJAYA,VINATIORGA,IDEA,VOLTAS,WELCORP,WELENT,WHIRLPOOL,WIPRO,YESBANK,ZFCVINDIA,ZEEL,ZENSARTECH,ZOMATO,ZYDUSLIFE"
    return [s.strip() + ".NS" for s in nifty500_csv.split(",")]

@st.cache_data(ttl=3600)
def get_valid_trading_dates():
    try:
        df = yf.Ticker('^NSEI').history(period="60d", interval="1d")
        if not df.empty: return [d.date() for d in df.index]
    except: pass
    today = datetime.now(ist).date()
    return [today - timedelta(days=i) for i in range(60) if (today - timedelta(days=i)).weekday() < 5][::-1]

def fetch_market_data(ticker, period, interval):
    file_path = os.path.join(CACHE_DIR, f"{ticker}_{interval}.csv")
    t = yf.Ticker(ticker)
    if os.path.exists(file_path):
        try:
            local_df = pd.read_csv(file_path, index_col=0, parse_dates=True)
            if not local_df.empty:
                last_date = local_df.index[-1]
                now = datetime.now().replace(tzinfo=None)
                if interval == '15m' and (now - last_date) > timedelta(minutes=15):
                    recent_df = t.history(period="5d", interval="15m", auto_adjust=False)
                    if not recent_df.empty:
                        recent_df.index = recent_df.index.tz_convert('Asia/Kolkata').tz_localize(None) if recent_df.index.tz else recent_df.index.tz_localize(None)
                        combined = pd.concat([local_df, recent_df])
                        combined = combined[~combined.index.duplicated(keep='last')].sort_index()
                        sixty_days_ago = combined.index[-1] - pd.Timedelta(days=60)
                        combined = combined[combined.index >= sixty_days_ago]
                        combined.to_csv(file_path)
                        return combined
                elif interval == '1d' and (now - last_date) > timedelta(hours=24):
                    recent_df = t.history(period="1mo", interval="1d", auto_adjust=False)
                    if not recent_df.empty:
                        recent_df.index = recent_df.index.tz_localize(None)
                        combined = pd.concat([local_df, recent_df])
                        combined = combined[~combined.index.duplicated(keep='last')].sort_index()
                        combined.to_csv(file_path)
                        return combined
                return local_df
        except: pass 
    df = t.history(period=period, interval=interval, auto_adjust=False)
    if not df.empty:
        if interval == '15m': df.index = df.index.tz_convert('Asia/Kolkata').tz_localize(None) if df.index.tz else df.index.tz_localize(None)
        else: df.index = df.index.tz_localize(None)
        df.to_csv(file_path)
    return df

def get_recent_swing(df, current_idx, direction='high'):
    try:
        loc = df.index.get_loc(current_idx)
        for i in range(loc - 1, 1, -1):
            if direction == 'high':
                if df['High'].iloc[i] > df['High'].iloc[i-1] and df['High'].iloc[i] > df['High'].iloc[i+1]:
                    if df['High'].iloc[i:loc].max() <= df['High'].iloc[i]: return df.index[i], df['High'].iloc[i]
            else:
                if df['Low'].iloc[i] < df['Low'].iloc[i-1] and df['Low'].iloc[i] < df['Low'].iloc[i+1]:
                    if df['Low'].iloc[i:loc].min() >= df['Low'].iloc[i]: return df.index[i], df['Low'].iloc[i]
        return None, None
    except: return None, None

def get_post_mss_swing(df, mss_idx, direction='high'):
    try:
        loc = df.index.get_loc(mss_idx)
        for i in range(loc, len(df)-1):
            if direction == 'high':
                if df['High'].iloc[i] > df['High'].iloc[i-1] and df['High'].iloc[i] > df['High'].iloc[i+1]: return df.index[i], df['High'].iloc[i], df.index[i+1]
            else:
                if df['Low'].iloc[i] < df['Low'].iloc[i-1] and df['Low'].iloc[i] < df['Low'].iloc[i+1]: return df.index[i], df['Low'].iloc[i], df.index[i+1]
        return None, None, None
    except: return None, None, None

def calculate_floating_pnl(direction, cmp, entry, stop_loss, risk_amt):
    risk_dist = abs(entry - stop_loss)
    if risk_dist == 0: return 0.0
    qty = int(risk_amt / risk_dist)
    return round(qty * (cmp - entry), 2) if direction == 'Bullish' else round(qty * (entry - cmp), 2)

def find_sd_zone(df_15m, sweep_time, mss_time, mss_price, direction):
    try:
        leg_df = df_15m.loc[sweep_time:mss_time]
        if len(leg_df) < 2: return None, None, 0
        leg_df = leg_df.copy()
        leg_df['Body'] = abs(leg_df['Open'] - leg_df['Close'])
        leg_df['Range'] = leg_df['High'] - leg_df['Low']
        leg_df['Is_Base'] = (leg_df['Body'] / leg_df['Range'].replace(0, 0.001)) < 0.5
        base_candles = leg_df[leg_df['Is_Base']].copy()
        if base_candles.empty: return None, None, 0
        
        base_candles['Dist_to_MSS'] = abs(((base_candles['High'] + base_candles['Low']) / 2) - mss_price)
        closest_base_idx = base_candles['Dist_to_MSS'].idxmin()
        leg_df['Block'] = (~leg_df['Is_Base']).cumsum()
        target_block = leg_df.loc[closest_base_idx, 'Block']
        zone_candles = leg_df[(leg_df['Is_Base']) & (leg_df['Block'] == target_block)]
        if zone_candles.empty: return None, None, 0
        
        last_base_idx = zone_candles.index[-1]
        post_base = leg_df.loc[last_base_idx:]
        if len(post_base) > 1: post_base = post_base.iloc[1:]
        else: return None, None, 0
            
        if direction == 'Bullish':
            distal = zone_candles['Low'].min()
            proximal = zone_candles['High'].max()
            legout_count = len(post_base[(post_base['Close'] > post_base['Open']) & (~post_base['Is_Base'])])
        else:
            distal = zone_candles['High'].max()
            proximal = zone_candles['Low'].min()
            legout_count = len(post_base[(post_base['Close'] < post_base['Open']) & (~post_base['Is_Base'])])
            
        if not (1 <= legout_count <= 3): return None, None, 0
        return proximal, distal, legout_count
    except: return None, None, 0

def evaluate_mtf_weekly_setup(ticker, df_15m, df_75m, daily_htf, weekly_hist, mss_limit, scan_state, d, strict_opposite, target_method, target_entry_start=None, target_entry_end=None):
    setups = []
    if d not in daily_htf.index: return setups
    cmp = df_15m['Close'].iloc[-1]
    
    current_monday = d - pd.Timedelta(days=d.weekday())
    current_monday = current_monday.replace(hour=0, minute=0, second=0)
    past_weekly = weekly_hist.loc[weekly_hist.index < current_monday]
    if past_weekly.empty: return setups
    
    pwl, pwh = past_weekly['Low'].iloc[-1], past_weekly['High'].iloc[-1]
    if not pwh or not pwl: return setups
    time_fmt = '%Y-%m-%d %H:%M'
    df_15m_index = df_15m.index.tolist()
    
    # Bullish Sequence (Previous Weekly Low)
    future_75m = df_75m.loc[d.strftime('%Y-%m-%d'):]
    if not future_75m.empty:
        bull_sweeps = future_75m[future_75m['Low'] <= pwl]
        if not bull_sweeps.empty:
            sweep_idx_75m = bull_sweeps.index[0]
            if sweep_idx_75m.date() == d.date():
                post_sweep_75m = future_75m.loc[sweep_idx_75m:]
                if not strict_opposite or post_sweep_75m['High'].max() < pwh:
                    sh_idx_75m, sh_val_75m = get_recent_swing(df_75m, sweep_idx_75m, 'high')
                    if sh_idx_75m:
                        mss_cands = post_sweep_75m[post_sweep_75m['Close'] > sh_val_75m]
                        if not mss_cands.empty:
                            mss_idx_75m = mss_cands.index[0]
                            proximal, distal, legout_count = find_sd_zone(df_15m, sweep_idx_75m, mss_idx_75m, sh_val_75m, 'Bullish')
                            
                            if proximal and distal and 1 <= legout_count <= 3:
                                _, target_val, _ = get_post_mss_swing(df_15m, mss_idx_75m, 'high')
                                if target_val:
                                    entry_price = proximal
                                    active_sl = distal * 0.999
                                    risk_dist = abs(entry_price - active_sl)
                                    if risk_dist > 0:
                                        active_target = entry_price + (2 * risk_dist) if target_method == "Fixed 1:2 Risk-to-Reward" else target_val
                                        if active_target > entry_price and active_sl < entry_price:
                                            actual_rr = (active_target - entry_price) / risk_dist
                                            if target_method == "Fixed 1:2 Risk-to-Reward" or actual_rr >= 1.0:
                                                setup_data = {"Direction": "Bullish", "Stock name": ticker, "CMP": round(cmp, 2), "Base Start (Sweep)": sweep_idx_75m.strftime(time_fmt), "Base End (MSS)": mss_idx_75m.strftime(time_fmt), "MSS Line (75m/125m)": round(sh_val_75m, 2), "15m Leg-out Candles": legout_count, "Entry Type": "15m S/D Base", "Entry": round(entry_price, 2), "SL": round(active_sl, 2), "Target": round(active_target, 2), "Target RR": f"1:{round(actual_rr, 1)}", "Entry Distance": f"{round(((cmp - entry_price)/cmp)*100, 2)}%", "Entry Time": "Pending"}
                                                
                                                start_tracking_idx = df_15m_index.index(mss_idx_75m)
                                                if start_tracking_idx + 1 < len(df_15m_index):
                                                    tracking_df = df_15m.iloc[start_tracking_idx + 1:]
                                                    touched_entry_df = tracking_df[tracking_df['Low'] <= entry_price]
                                                    
                                                    # State 1: MSS completed, Entry awaited
                                                    if touched_entry_df.empty and scan_state == "1": setups.append(setup_data)
                                                    elif not touched_entry_df.empty:
                                                        entry_idx = touched_entry_df.index[0]
                                                        setup_data["Entry Time"] = entry_idx.strftime('%Y-%m-%d %H:%M')
                                                        
                                                        # State 2: Running trades
                                                        if scan_state == "2" and entry_idx.date() == target_entry_end.date():
                                                            end_of_day = entry_idx.replace(hour=23, minute=59, second=59) if isinstance(entry_idx, pd.Timestamp) else entry_idx
                                                            entry_day_df = df_15m.loc[entry_idx : end_of_day]
                                                            if not any((row['Low'] <= active_sl or row['High'] >= active_target) for _, row in entry_day_df.iterrows()):
                                                                setup_data.update({"Entry Distance": "Touched (Active)", "Profit/Loss (₹)": calculate_floating_pnl("Bullish", cmp, entry_price, active_sl, 1000)})
                                                                setups.append(setup_data)
                                                        
                                                        # State 3: Backtester
                                                        elif scan_state == "3":
                                                            if target_entry_start <= entry_idx <= target_entry_end:
                                                                end_of_day = entry_idx.replace(hour=23, minute=59, second=59) if isinstance(entry_idx, pd.Timestamp) else entry_idx
                                                                entry_day_df = df_15m.loc[entry_idx:end_of_day]
                                                                outcome, exit_price, highest_seen = "Time Square Off", entry_day_df['Close'].iloc[-1], entry_price
                                                                for idx, row in entry_day_df.iterrows():
                                                                    highest_seen = max(highest_seen, row['High'])
                                                                    if row['Low'] <= active_sl: outcome, exit_price = "SL Hit", active_sl; break
                                                                    elif row['High'] >= active_target: outcome, exit_price = "Target Hit", active_target; break
                                                                setup_data.update({"Max Move (%)": f"{round(((highest_seen - entry_price) / entry_price) * 100, 2)}%", "Outcome": outcome, "Exit Price": round(exit_price, 2)})
                                                                setups.append(setup_data)

    # Bearish Sequence (Previous Weekly High)
    if not future_75m.empty:
        bear_sweeps = future_75m[future_75m['High'] >= pwh]
        if not bear_sweeps.empty:
            sweep_idx_75m = bear_sweeps.index[0]
            if sweep_idx_75m.date() == d.date():
                post_sweep_75m = future_75m.loc[sweep_idx_75m:]
                if not strict_opposite or post_sweep_75m['Low'].min() > pwl:
                    sh_idx_75m, sl_val_75m = get_recent_swing(df_75m, sweep_idx_75m, 'low')
                    if sh_idx_75m:
                        mss_cands = post_sweep_75m[post_sweep_75m['Close'] < sl_val_75m]
                        if not mss_cands.empty:
                            mss_idx_75m = mss_cands.index[0]
                            proximal, distal, legout_count = find_sd_zone(df_15m, sweep_idx_75m, mss_idx_75m, sl_val_75m, 'Bearish')
                            
                            if proximal and distal and 1 <= legout_count <= 3:
                                _, target_val, _ = get_post_mss_swing(df_15m, mss_idx_75m, 'low')
                                if target_val:
                                    entry_price = proximal
                                    active_sl = distal * 1.001
                                    risk_dist = abs(entry_price - active_sl)
                                    if risk_dist > 0:
                                        active_target = entry_price - (2 * risk_dist) if target_method == "Fixed 1:2 Risk-to-Reward" else target_val
                                        if active_target < entry_price and active_sl > entry_price:
                                            actual_rr = (entry_price - active_target) / risk_dist
                                            if target_method == "Fixed 1:2 Risk-to-Reward" or actual_rr >= 1.0:
                                                setup_data = {"Direction": "Bearish", "Stock name": ticker, "CMP": round(cmp, 2), "Base Start (Sweep)": sweep_idx_75m.strftime(time_fmt), "Base End (MSS)": mss_idx_75m.strftime(time_fmt), "MSS Line (75m/125m)": round(sl_val_75m, 2), "15m Leg-out Candles": legout_count, "Entry Type": "15m S/D Base", "Entry": round(entry_price, 2), "SL": round(active_sl, 2), "Target": round(active_target, 2), "Target RR": f"1:{round(actual_rr, 1)}", "Entry Distance": f"{round(((entry_price - cmp)/cmp)*100, 2)}%", "Entry Time": "Pending"}
                                                
                                                start_tracking_idx = df_15m_index.index(mss_idx_75m)
                                                if start_tracking_idx + 1 < len(df_15m_index):
                                                    tracking_df = df_15m.iloc[start_tracking_idx + 1:]
                                                    touched_entry_df = tracking_df[tracking_df['High'] >= entry_price]
                                                    
                                                    # State 1: MSS completed, Entry awaited
                                                    if touched_entry_df.empty and scan_state == "1": setups.append(setup_data)
                                                    elif not touched_entry_df.empty:
                                                        entry_idx = touched_entry_df.index[0]
                                                        setup_data["Entry Time"] = entry_idx.strftime('%Y-%m-%d %H:%M')
                                                        
                                                        # State 2: Running trades
                                                        if scan_state == "2" and entry_idx.date() == target_entry_end.date():
                                                            end_of_day = entry_idx.replace(hour=23, minute=59, second=59) if isinstance(entry_idx, pd.Timestamp) else entry_idx
                                                            entry_day_df = df_15m.loc[entry_idx : end_of_day]
                                                            if not any((row['High'] >= active_sl or row['Low'] <= active_target) for _, row in entry_day_df.iterrows()):
                                                                setup_data.update({"Entry Distance": "Touched (Active)", "Profit/Loss (₹)": calculate_floating_pnl("Bearish", cmp, entry_price, active_sl, 1000)})
                                                                setups.append(setup_data)
                                                        
                                                        # State 3: Backtester
                                                        elif scan_state == "3":
                                                            if target_entry_start <= entry_idx <= target_entry_end:
                                                                end_of_day = entry_idx.replace(hour=23, minute=59, second=59) if isinstance(entry_idx, pd.Timestamp) else entry_idx
                                                                entry_day_df = df_15m.loc[entry_idx:end_of_day]
                                                                outcome, exit_price, lowest_seen = "Time Square Off", entry_day_df['Close'].iloc[-1], entry_price
                                                                for idx, row in entry_day_df.iterrows():
                                                                    lowest_seen = min(lowest_seen, row['Low'])
                                                                    if row['High'] >= active_sl: outcome, exit_price = "SL Hit", active_sl; break
                                                                    elif row['Low'] <= active_target: outcome, exit_price = "Target Hit", active_target; break
                                                                setup_data.update({"Max Move (%)": f"{round(((entry_price - lowest_seen) / entry_price) * 100, 2)}%", "Outcome": outcome, "Exit Price": round(exit_price, 2)})
                                                                setups.append(setup_data)
    return setups

def scan_ticker(ticker, mss_limit, scan_state, start_date_str, end_date_str, strict_opposite, target_method):
    try:
        target_entry_start = pd.to_datetime(start_date_str).replace(hour=0, minute=0, second=0)
        target_entry_end = pd.to_datetime(end_date_str).replace(hour=23, minute=59, second=59)
        res = []
        
        df_15m = fetch_market_data(ticker, "60d", "15m")
        daily_htf = fetch_market_data(ticker, "2y", "1d")
        if df_15m.empty or daily_htf.empty: return None
        
        resampled = [{'Datetime': chunk.index[-1], 'Open': chunk['Open'].iloc[0], 'High': chunk['High'].max(), 'Low': chunk['Low'].min(), 'Close': chunk['Close'].iloc[-1]} for date, group in df_15m.groupby(df_15m.index.date) for i in range(0, len(group), 5) if len(chunk := group.iloc[i:i+5]) > 0]
        df_htf = pd.DataFrame(resampled).set_index('Datetime')
        weekly_hist = daily_htf.resample('W-MON', closed='left', label='left').agg({'High':'max', 'Low':'min'}).dropna()
        available_dates = pd.Series(df_15m.index.date).drop_duplicates().apply(pd.to_datetime)
        
        expanded_start = target_entry_start - pd.Timedelta(days=15) if scan_state != "3" else target_entry_start - pd.Timedelta(days=60)
        expanded_days = available_dates[(available_dates >= expanded_start) & (available_dates <= target_entry_end)]
        
        for d in expanded_days:
            r_today = evaluate_mtf_weekly_setup(ticker, df_15m, df_htf, daily_htf, weekly_hist, mss_limit, scan_state, d, strict_opposite, target_method, target_entry_start, target_entry_end)
            if r_today: res.extend(r_today)

        if res:
            unique_res, seen_mss_lines, seen_entries = [], set(), set()
            for r in res: 
                if 'Stock name' not in r or r['Stock name'] is None: r['Stock name'] = ticker.replace('.NS', '')
                mss_val = r.get('MSS Line (75m/125m)', r.get('MSS Line', r.get('MSS price (Breaker)', None)))
                sig_mss, sig_entry = (r['Direction'], mss_val), (r['Direction'], r.get('Entry', r.get('Entry Level', None)))
                if sig_mss not in seen_mss_lines and sig_entry not in seen_entries:
                    seen_mss_lines.add(sig_mss); seen_entries.add(sig_entry); unique_res.append(r)
            return unique_res
        return None
    except: return None

# --- MAIN UI LAYOUT ---
st.markdown("<h2>⚡ Weekly MTF Precision Screener</h2>", unsafe_allow_html=True)
st.caption("Hardcoded for Previous Weekly High/Low Sweeps (Multiple Touches Allowed)")

with st.container():
    c1, c2 = st.columns(2)
    with c1:
        scan_state = st.selectbox(
            "Select Market State", 
            ["1. MSS completed, Entry awaited", "2. Running trades", "3. Backtester"]
        )
        state_code = scan_state.split(".")[0]
    with c2:
        target_method = st.selectbox("Target Strategy", ["Nearest 15 min swing point", "Fixed 1:2 Risk-to-Reward"])

with st.container():
    c5, c6 = st.columns(2)
    with c5:
        mss_limit = st.select_slider("Max Displacement Candles for MSS", options=list(range(1, 11)), value=6)
    with c6:
        st.write("")
        st.write("")
        strict_opposite = st.checkbox("Reject if Opposite Liq Touched", value=False)

if state_code == "3":
    with st.container():
        st.markdown("<p style='color:#E2E8F0;font-weight:600;'>Backtest Parameters</p>", unsafe_allow_html=True)
        today = pd.to_datetime(datetime.now(ist).date())
        c7, c8 = st.columns(2)
        valid_dates = get_valid_trading_dates()
        valid_dates_rev = list(reversed(valid_dates))
        if valid_dates_rev:
            with c7: from_date_str = st.selectbox("From Date", valid_dates_rev, index=len(valid_dates_rev)-1, format_func=lambda x: x.strftime('%d %b %Y'))
            with c8: to_date_str = st.selectbox("To Date", valid_dates_rev, index=0, format_func=lambda x: x.strftime('%d %b %Y'))
            start_date, end_date = pd.to_datetime(from_date_str), pd.to_datetime(to_date_str)
        else:
            start_date, end_date = today, today
        risk_per_trade = st.number_input("Risk per Trade (₹)", min_value=100, value=1000, step=100)
else:
    start_date = end_date = pd.to_datetime(datetime.now(ist).date())
    risk_per_trade = 1000

st.write("")
col_btn1, col_btn2 = st.columns([3,1])
with col_btn1: execute_scan = st.button("🚀 Execute Master Scan", type="primary")
with col_btn2:
    if st.button("🗑️ Clear Cache", type="secondary"):
        if os.path.exists(CACHE_DIR): shutil.rmtree(CACHE_DIR); os.makedirs(CACHE_DIR)
        st.session_state['scan_run'] = False
        st.session_state['scan_results'] = None
        st.rerun()

if execute_scan:
    if state_code == "3" and start_date > end_date: st.error("Error: 'From Date' must be earlier than or equal to 'To Date'.")
    else:
        keep_screen_awake()
        with st.spinner(f"Scanning Nifty 500 | Weekly MTF Logic | State: {state_code}..."):
            progress_bar = st.progress(0, text="Downloading Daily History... 0 / 500 assets (0%)")
            tickers = get_nifty500_symbols()
            results = []
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
                futures = {executor.submit(scan_ticker, tick, mss_limit, state_code, start_date.strftime('%Y-%m-%d'), end_date.strftime('%Y-%m-%d'), strict_opposite, target_method): tick for tick in tickers}
                
                completed = 0
                for f in concurrent.futures.as_completed(futures):
                    res = f.result()
                    if res: results.extend(res)
                    completed += 1
                    progress_bar.progress(completed / 500, text=f"Downloading History... {completed} / 500 assets ({int((completed/500)*100)}%)")
                    
            progress_bar.empty()
            
            st.session_state['scan_results'] = results
            st.session_state['current_start'] = start_date
            st.session_state['current_end'] = end_date
            st.session_state['current_state_code'] = state_code
            st.session_state['current_risk'] = risk_per_trade
            st.session_state['scan_run'] = True

if st.session_state.get('scan_run', False):
    results = st.session_state.get('scan_results', [])
    saved_state_code = st.session_state.get('current_state_code', state_code)
    saved_risk = st.session_state.get('current_risk', 1000)
    
    if not results: st.warning("No stocks matched these criteria. (Try expanding the date range).")
    else:
        df_all = pd.DataFrame(results)
        if saved_state_code == "3":
            def calculate_metrics(row):
                entry_key, sl_key, risk = 'Entry', 'SL', saved_risk
                risk_dist = abs(row[entry_key] - row[sl_key])
                if risk_dist == 0: return pd.Series([0.0, 0.0], index=['Profit/Loss (₹)', 'Funds Needed (₹)'])
                qty = int(risk / risk_dist)
                funds_needed = round(qty * row[entry_key], 2)
                reward_dist = abs(row['Target'] - row[entry_key])
                reward_ratio = reward_dist / risk_dist
                
                if row['Outcome'] == 'Target Hit': pnl = risk * reward_ratio
                elif row['Outcome'] == 'SL Hit': pnl = -risk
                elif row['Outcome'] == 'Time Square Off': pnl = qty * (row['Exit Price'] - row[entry_key]) if row['Direction'] == 'Bullish' else qty * (row[entry_key] - row['Exit Price'])
                else: pnl = qty * (row['CMP'] - row[entry_key]) if row['Direction'] == 'Bullish' else qty * (row[entry_key] - row['CMP'])
                return pd.Series([round(pnl, 2), funds_needed], index=['Profit/Loss (₹)', 'Funds Needed (₹)'])
            df_all[['Profit/Loss (₹)', 'Funds Needed (₹)']] = df_all.apply(calculate_metrics, axis=1)
        
        df_bull, df_bear = df_all[df_all['Direction'] == 'Bullish'], df_all[df_all['Direction'] == 'Bearish']
        
        tab1, tab2 = st.tabs(["🟢 Bullish Setups", "🔴 Bearish Setups"])
        
        def render_tab_content(df, title):
            st.markdown(f"<p style='color:#E2E8F0;'>Qualified Zones: <b>{len(df)}</b></p>", unsafe_allow_html=True)
            if df.empty: st.info(f"No {title} Setups.")
            else:
                cols = df.columns.tolist()
                if 'Stock name' in cols: cols.insert(0, cols.pop(cols.index('Stock name')))
                df = df[cols]
                if saved_state_code == "3":
                    total_pnl, total_funds = df['Profit/Loss (₹)'].sum(), df['Funds Needed (₹)'].sum()
                    wins, losses = len(df[df['Profit/Loss (₹)'] > 0]), len(df[df['Profit/Loss (₹)'] <= 0])
                    win_rate = (wins / len(df) * 100) if len(df) > 0 else 0
                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Total P&L", f"₹ {total_pnl:,.2f}")
                    c2.metric("Funds Reqd", f"₹ {total_funds:,.2f}")
                    c3.metric("Win Rate", f"{win_rate:.1f}%")
                    c4.metric("Trades", f"{wins}W/{losses}L")
                    st.write("")
                st.dataframe(df.drop(columns=['Direction']), use_container_width=True, hide_index=True)

        with tab1: render_tab_content(df_bull, "Demand")
        with tab2: render_tab_content(df_bear, "Supply")
