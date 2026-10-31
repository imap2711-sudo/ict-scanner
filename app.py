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

def get_dynamic_target(df, start_idx, end_idx, entry_price, risk_dist, direction):
    # Dynamically scans historical swing points and enforces a strict Minimum 1:1 RR requirement.
    swings = []
    try:
        sub_df = df.loc[start_idx:end_idx]
        if len(sub_df) < 3:
            swings.append(sub_df['High'].max() if direction == 'Bullish' else sub_df['Low'].min())
        else:
            for i in range(1, len(sub_df)-1):
                if direction == 'Bullish':
                    if sub_df['High'].iloc[i] > sub_df['High'].iloc[i-1] and sub_df['High'].iloc[i] > sub_df['High'].iloc[i+1]:
                        swings.append(sub_df['High'].iloc[i])
                else:
                    if sub_df['Low'].iloc[i] < sub_df['Low'].iloc[i-1] and sub_df['Low'].iloc[i] < sub_df['Low'].iloc[i+1]:
                        swings.append(sub_df['Low'].iloc[i])
            # Always append the absolute extreme of the move to ensure structural highs are captured
            if direction == 'Bullish': swings.append(sub_df['High'].max())
            else: swings.append(sub_df['Low'].min())
        
        # Filter for targets that guarantee at least 1:1 RR, then pick the nearest one.
        if direction == 'Bullish':
            valid_swings = [s for s in swings if (s - entry_price) >= risk_dist]
            return min(valid_swings) if valid_swings else None
        else:
            valid_swings = [s for s in swings if (entry_price - s) >= risk_dist]
            return max(valid_swings) if valid_swings else None
    except: return None

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

def evaluate_mtf_weekly_setup(ticker, df_15m, df_75m, daily_htf, weekly_hist, mss_limit, scan_state, d, strict_opposite, target_method, target_entry_start, target_entry_end, risk_per_trade):
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
                            if len(np.unique(df_75m.loc[sweep_idx_75m:mss_idx_75m].index.date)) <= 2:
                                proximal, distal, legout_count = find_sd_zone(df_15m, sweep_idx_75m, mss_idx_75m, sh_val_75m, 'Bullish')
                                
                                if proximal and distal and 1 <= legout_count <= 3:
                                    entry_price = round(proximal, 2)
                                    active_sl = round(distal * 0.999, 2)
                                    risk_dist = round(abs(entry_price - active_sl), 2)
                                    
                                    if risk_dist > 0:
                                        qty = int(risk_per_trade / risk_dist)
                                        if qty > 0:
                                            # Wait for 75m candle to close before confirming entry track
                                            mss_close_time = mss_idx_75m + pd.Timedelta(minutes=75)
                                            tracking_df = df_15m[df_15m.index >= mss_close_time]
                                            touched_entry_df = tracking_df[tracking_df['Low'] <= entry_price]
                                            
                                            entry_idx = touched_entry_df.index[0] if not touched_entry_df.empty else None
                                            eval_end_idx = entry_idx if entry_idx else df_15m.index[-1]
                                            
                                            # Dynamically scan target only after entry is confirmed
                                            if target_method == "Fixed 1:2 Risk-to-Reward":
                                                active_target = round(entry_price + (2 * risk_dist), 2)
                                            else:
                                                active_target = get_dynamic_target(df_15m, sweep_idx_75m, eval_end_idx, entry_price, risk_dist, 'Bullish')
                                                if active_target: active_target = round(active_target, 2)
                                                
                                            if active_target and active_target > entry_price and active_sl < entry_price:
                                                theoretical_rr = round((active_target - entry_price) / risk_dist, 2)
                                                
                                                if theoretical_rr >= 1.0:
                                                    setup_data = {"Direction": "Bullish", "Stock name": ticker, "CMP": round(cmp, 2), "Base Start (Sweep)": sweep_idx_75m.strftime(time_fmt), "Base End (MSS)": mss_idx_75m.strftime(time_fmt), "MSS Line (75m)": round(sh_val_75m, 2), "15m Leg-out Candles": legout_count, "Entry Type": "15m S/D Base", "Entry": entry_price, "SL": active_sl, "Target": active_target, "Target RR": f"1:{theoretical_rr}", "Entry Distance": f"{round(((cmp - entry_price)/cmp)*100, 2)}%", "Entry Time": "Pending"}
                                                    
                                                    if entry_idx is None:
                                                        if scan_state == "1": setups.append(setup_data)
                                                    else:
                                                        if (entry_idx.date() - mss_idx_75m.date()).days <= 5:
                                                            open_px = df_15m.loc[entry_idx, 'Open']
                                                            if open_px > active_sl:
                                                                actual_entry = round(open_px if open_px < entry_price else entry_price, 2)
                                                                actual_risk_dist = round(abs(actual_entry - active_sl), 2)
                                                                actual_target_dist = round(abs(active_target - actual_entry), 2)
                                                                
                                                                if actual_risk_dist > 0:
                                                                    actual_rr = round(actual_target_dist / actual_risk_dist, 2)
                                                                    # Final Check: Did slippage destroy the 1:1 edge?
                                                                    if actual_rr >= 1.0:
                                                                        funds_needed = round(qty * actual_entry, 2)
                                                                        
                                                                        setup_data.update({
                                                                            "Entry Time": entry_idx.strftime('%Y-%m-%d %H:%M'), 
                                                                            "Entry": actual_entry
