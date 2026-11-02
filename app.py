import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import concurrent.futures
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

# --- PAGE SETUP ---
st.set_page_config(page_title="ICT Precision Scanner", layout="wide", page_icon="⚡")
ist = ZoneInfo('Asia/Kolkata')

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
st.title("⚡ Weekly ICT Sweep & MTF Screener")
if st.query_params.get("plain") != "1":
    st.markdown(custom_css, unsafe_allow_html=True)

# --- CONSTANTS ---
BASE_BODY_RATIO = 0.5                            
SL_PAD_BULL, SL_PAD_BEAR = 0.999, 1.001          
WINDOW_START, WINDOW_END = time(9, 45), time(13, 30)
MIN_RR = 1.0                                     
SWING_N = 2                                      
SWING_LOOKBACK_BARS = 125                        
ZONE_NEAREST = "Nearest to MSS line (above or below)"
ZONE_STRICT = "Strictly below MSS line (demand) / above (supply)"


@st.cache_data(ttl=86400, show_spinner=False)
def get_stock_symbols(universe):
    nifty500_csv = "360ONE,3MINDIA,ABB,ACC,AIAENG,APLAPOLLO,AUBANK,AARTIDRUGS,AARTIIND,AAVAS,ABBOTINDIA,ADANIENT,ADANIGREEN,ADANIPORTS,ADANIPOWER,ATGL,AWL,ABCAPITAL,ABFRL,AEGISCHEM,AETHER,AFFLE,AJANTPHARM,APLLTD,ALKEM,ALKYLAMINE,ALLCARGO,AMARAJABAT,AMBER,AMBUJACEM,ANANDAMATH,ANGELONE,ANURAS,APARINDS,APOLLOHOSP,APOLLOTYRE,APTUS,ASAHIINDIA,ASHOKLEY,ASIANPAINT,ASTERDM,ASTRAL,ATUL,AUROPHARMA,AVANTIFEED,DMART,AXISBANK,BEML,BSE,BAJAJ-AUTO,BAJAJFINSV,BAJFINANCE,BAJAJHLDNG,BALAMINES,BALKRISIND,BALRAMCHIN,BANDHANBNK,BANKBARODA,BANKINDIA,MAHABANK,BATAINDIA,BAYERCROP,BERGEPAINT,BDL,BEL,BHARATFORG,BHEL,BPCL,BHARTIARTL,BIOCON,BOSCHLTD,BRIGADE,BRITANNIA,MAPMYINDIA,CCL,CESC,CGPOWER,CAMS,CANFINHOME,CANBK,CAPLIPOINT,CARBORUNIV,CASTROLIND,CEATLTD,CENTRALBK,CDSL,CENTURYPLY,CENTURYTEX,CERA,CHALET,CHAMBLFERT,CHEMPLASTS,CHENNPETRO,CHOLAFIN,CHOLAHLDNG,CIPLA,CLEAN,COALINDIA,COCHINSHIP,COFORGE,COLPAL,CONCOR,COROMANDEL,CRAFTSMAN,CREDITACC,CROMPTON,CUB,CUMMINSIND,CYIENT,DCMSHRIRAM,DLF,DABUR,DALBHARAT,DEEPAKNTR,DELHIVERY,DEVYANI,DIVISLAB,DIXON,LALPATHLAB,DRREDDY,EIDPARRY,EIHOTEL,EPL,EASEMYTRIP,EICHERMOT,ELECON,ELGIEQUIP,EMAMILTD,ENDURANCE,ENGINERSIN,EQUITASBNK,ERIS,ESCORTS,EXIDEIND,FDC,NYKAA,FEDERALBNK,FACT,FINEORG,FINCABLES,FINPIPE,FSL,FORTIS,GRINFRA,GAIL,GMMPFAUDLR,GMRINFRA,GALAXYSURF,GARFIBRES,GICRE,GLAXO,GLENMARK,MEDANTA,GODFRYPHLP,GODREJAGRO,GODREJCP,GODREJIND,GODREJPROP,GRASIM,GESHIP,GRINDWELL,GUJGASLTD,GNFC,GSFC,GSPL,HAVELLS,HEG,HEGAM,HCLTECH,HDFCAMC,HDFCBANK,HDFCLIFE,HFCL,HAL,HINDALCO,HINDCOPPER,HINDPETRO,HINDUNILVR,HINDZINC,HONAUT,HSCL,HUDCO,ITC,IDBI,IDFCFIRSTB,IFBIND,IIFL,IRB,IRCON,ITI,INDIACEM,INDIAMART,INDIANB,IEX,INDHOTEL,IOC,IOB,IRCTC,IRFC,INDIGOPNTS,IGL,INDUSINDBK,NAUKRI,INFIBEAM,INFY,INOXWIND,INTELLECT,INDIGO,IPCALAB,JBCHEPHARM,JKCEMENT,JKLAKSHMI,JKPAPER,JKTYRE,JMFINANCIL,JSWENERGY,JSWSTEEL,JAICORPLTD,J&KBANK,JINDALSTEL,JINDALPHOT,JIOFIN,JUBILANT,JUBLFOOD,JUBLINGREA,JUBLPHARMA,KPRMILL,KEI,KNRCON,KPITTECH,KRBL,KSB,KAJARIACER,KALYANKJIL,KANSAINER,KARURVYSYA,KAYNES,KEC,KFINTECH,KOTAKBANK,KIMS,L&TFH,LTTS,LICHSGFIN,LTIM,LT,LATENTVIEW,LAURUSLABS,LEMONTREE,LICI,LINDEINDIA,LUPIN,MRF,MTARTECH,MACPOWER,LODHA,MGL,M&MFIN,M&M,MAHSEAMLES,MARICO,MARUTI,MASTEK,MAXHEALTH,MAXFIN,MAZDOCK,MEDPLUS,METROBRAND,METROPOLIS,MINDACORP,UNOINDA,MOTILALOFS,MPHASIS,MCX,MUTHOOTFIN,NATCOPHARM,NBCC,NCC,NHPC,NLCINDIA,NMDC,NOCIL,NTPC,OBEROIRLTY,ONGC,OIL,OLECTRA,PAYTM,OFSS,POLICYBKR,PCBL,PIIND,PNBHOUSING,PNCINFRA,PVRINOX,PAGEIND,PATANJALI,PERSISTENT,PETRONET,PFIZER,PHOENIXLTD,PIDILITIND,PEL,PPLPHARMA,POLYMED,POLYCAB,POONAWALLA,PFC,POWERGRID,PRAJIND,PRESTIGE,PRINCEPIPE,PRSMJOHNSN,PGHL,PNB,QUESS,RBLBANK,RECLTD,RHIM,RITES,RADICO,RVNL,RAILTEL,RAIN,RAMCOCEM,RATNAMANI,RAYMOND,REDINGTON,RELAXO,RELIANCE,RBA,ROUTE,SJVN,SKFINDIA,SRF,MOTHERSON,SANOFI,SAPPHIRE,SAREGAMA,SCHAEFFLER,SCHNEIDER,CIGNITITEC,SEQUENT,SHARDACROP,SHAREINDIA,SCI,SHREECEM,SHRIRAMFIN,SHYAMMETL,SIEMENS,SOBHA,SOLARINDS,SONACOMS,STARHEALTH,SBI,SAIL,SBM,STLTECH,STARCEMENT,SUDARSCHEM,SUMICHEM,SPARC,SUNPHARMA,SUNTV,SUNDARMFIN,SUNDRMFAST,SUNTECK,SUPREMEIND,SUVENPHAR,SUZLON,SWANENERGY,SYMPHONY,SYNGENE,TCIEXP,TCNSBRANDS,TCS,TATACHEM,TATACOMM,TATACONSUM,TATAELXSI,TATAINVEST,TATAMOTORS,TATAPOWER,TATASTEEL,TTML,TEAMLEASE,TECHM,TEJASNET,THERMAX,TIDEWATER,TIMKEN,TITAN,TORNTPHARM,TORNTPOWER,TRENT,TRIDENT,TRIVENI,TRIVENITQ,TUBEINVEST,UCOBANK,UPL,UTIAMC,UJJIVANSFB,ULTRACEMCO,UNIONBANK,UBL,MCDOWELL-N,VGUARD,VMART,VIPIND,VAIBHAVGBL,VTL,VARROC,VBL,VEDL,VENKEYS,VIJAYA,VINATIORGA,IDEA,VOLTAS,WELCORP,WELENT,WHIRLPOOL,WIPRO,YESBANK,ZFCVINDIA,ZEEL,ZENSARTECH,ZOMATO,ZYDUSLIFE"
    nifty200_csv = "ABB,ACC,ADANIENT,ADANIGREEN,ADANIPORTS,ADANIPOWER,ATGL,AWL,ABCAPITAL,ABFRL,APOLLOHOSP,ASHOKLEY,ASIANPAINT,ASTRAL,AUROPHARMA,DMART,AXISBANK,BSE,BAJAJ-AUTO,BAJAJFINSV,BAJFINANCE,BALKRISIND,BANDHANBNK,BANKBARODA,BANKINDIA,MAHABANK,BEL,BHARATFORG,BHEL,BPCL,BHARTIARTL,BOSCHLTD,BRITANNIA,CANBK,CHOLAFIN,CIPLA,COALINDIA,COCHINSHIP,COFORGE,COLPAL,CONCOR,CUMMINSIND,DLF,DABUR,DIVISLAB,DIXON,LALPATHLAB,DRREDDY,EICHERMOT,ESCORTS,FEDERALBNK,FACT,FORTIS,GAIL,GMRINFRA,GLENMARK,GODREJCP,GODREJPROP,GRASIM,GUJGASLTD,HAVELLS,HCLTECH,HDFCAMC,HDFCBANK,HDFCLIFE,HAL,HINDALCO,HINDCOPPER,HINDPETRO,HINDUNILVR,HINDZINC,HUDCO,ITC,IDBI,IDFCFIRSTB,IRB,IRCON,INDIANB,INDHOTEL,IOC,IOB,IRCTC,IRFC,IGL,INDUSINDBK,NAUKRI,INFY,INDIGO,JINDALSTEL,JIOFIN,JSWENERGY,JSWSTEEL,KALYANKJIL,KOTAKBANK,L&TFH,LTTS,LICHSGFIN,LTIM,LT,LICI,LUPIN,MRF,LODHA,M&MFIN,M&M,MARICO,MARUTI,MAXHEALTH,MAZDOCK,MUTHOOTFIN,NHPC,NMDC,NTPC,OBEROIRLTY,ONGC,OIL,PAYTM,POLICYBKR,PIIND,PFC,POWERGRID,PRESTIGE,PNB,RECLTD,RVNL,RELIANCE,SRF,MOTHERSON,SCHAEFFLER,SIEMENS,SOLARINDS,SBI,SAIL,SUNPHARMA,SUNTV,SUPREMEIND,SUZLON,TATACHEM,TATACOMM,TATACONSUM,TATAELXSI,TATAMOTORS,TATAPOWER,TATASTEEL,TECHM,TITAN,TORNTPHARM,TORNTPOWER,TRENT,TUBEINVEST,UCOBANK,ULTRACEMCO,UNIONBANK,UBL,MCDOWELL-N,VEDL,VOLTAS,WIPRO,YESBANK,ZOMATO,ZYDUSLIFE"

    if universe == "Nifty 200":
        return [s.strip() + ".NS" for s in nifty200_csv.split(",")]
    return [s.strip() + ".NS" for s in nifty500_csv.split(",")]


IST_NAME = 'Asia/Kolkata'


@st.cache_data(ttl=900, show_spinner=False, max_entries=1500)
def _download(ticker, period, interval):
    df = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False)
    if df is None or df.empty:
        raise ValueError(f"No data for {ticker} ({interval})")
    df = df[['Open', 'High', 'Low', 'Close']].copy()
    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_convert(IST_NAME).tz_localize(None)
    df.index = idx
    df = df[~df.index.duplicated(keep='last')].sort_index()
    return df.dropna()


def fetch_market_data(ticker, period, interval):
    try:
        return _download(ticker, period, interval)
    except Exception:
        return pd.DataFrame()


# ---------------------------------------------------------------------------
# RULE 2 & 3: Build 75-Minute Candles & Swing Logic (No Lookahead)
# ---------------------------------------------------------------------------
def build_75m_candles(df_15m):
    rows = []
    for _, group in df_15m.groupby(df_15m.index.normalize()):
        for i in range(0, len(group), 5):
            chunk = group.iloc[i:i + 5]
            if len(chunk) > 0:
                rows.append({
                    'Datetime': chunk.index[0],
                    'Open': chunk['Open'].iloc[0],
                    'High': chunk['High'].max(),
                    'Low': chunk['Low'].min(),
                    'Close': chunk['Close'].iloc[-1],
                    'End': chunk.index[-1],
                    'Complete': len(chunk) == 5
                })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).set_index('Datetime')


def get_nearest_untested_75m_swing(df_75m, sweep_bar_dt, direction='high'):
    """
    Identifies the nearest unmitigated 75m fractal swing strictly BEFORE the sweep candle.
    Prevents lookahead bias by ensuring the confirming bar is completed before the sweep.
    """
    if sweep_bar_dt not in df_75m.index:
        closest_time = df_75m.index.asof(sweep_bar_dt)
        if pd.isna(closest_time):
            return None, None
        loc = df_75m.index.get_loc(closest_time)
    else:
        loc = df_75m.index.get_loc(sweep_bar_dt)

    for i in range(loc - 2, 0, -1):
        if direction == 'high':
            h = df_75m['High'].iloc[i]
            if h > df_75m['High'].iloc[i - 1] and h > df_75m['High'].iloc[i + 1]:
                if df_75m['Close'].iloc[i + 1:loc].max() < h:
                    return df_75m.index[i], h
        else:
            l = df_75m['Low'].iloc[i]
            if l < df_75m['Low'].iloc[i - 1] and l < df_75m['Low'].iloc[i + 1]:
                if df_75m['Close'].iloc[i + 1:loc].min() > l:
                    return df_75m.index[i], l
    return None, None


# ---------------------------------------------------------------------------
# RULE 4: Exactly one completed 75m candle closing beyond the MSS line
# No activation window restriction applied.
# ---------------------------------------------------------------------------
def find_activation(df_75m, sweep_bar_dt, mss_price, direction):
    bars = df_75m[df_75m['Complete'] & (df_75m.index >= sweep_bar_dt)]
    if bars.empty:
        return None
    beyond = (bars['Close'] > mss_price) if direction == 'Bullish' else (bars['Close'] < mss_price)
    hits = bars[beyond]
    return hits['End'].iloc[0] if not hits.empty else None


# ---------------------------------------------------------------------------
# RULE 6: Untested 15m Swing Target (Prior price action)
# ---------------------------------------------------------------------------
def get_untested_15m_swing_target(df_15m, activation_idx, entry_price, direction, active_sl):
    hist = df_15m.loc[:activation_idx].iloc[-SWING_LOOKBACK_BARS:]
    highs, lows = hist['High'].to_numpy(), hist['Low'].to_numpy()
    n, last = SWING_N, len(hist) - 1
    risk_dist = abs(entry_price - active_sl)

    for i in range(last - n, n - 1, -1):
        if direction == 'Bullish':
            h = highs[i]
            if h <= entry_price:
                continue
            # Rule 6: Target considered if and only if it offers RR >= 1:1
            if (h - entry_price) < (MIN_RR * risk_dist):
                continue
            if h > highs[i - n:i].max() and h > highs[i + 1:i + n + 1].max() and highs[i + 1:].max() < h:
                return float(h)
        else:
            lo = lows[i]
            if lo >= entry_price:
                continue
            # Rule 6: Target considered if and only if it offers RR >= 1:1
            if (entry_price - lo) < (MIN_RR * risk_dist):
                continue
            if lo < lows[i - n:i].min() and lo < lows[i + 1:i + n + 1].min() and lows[i + 1:].min() > lo:
                return float(lo)
    return None


# ---------------------------------------------------------------------------
# RULE 5: Supply & Demand Zone Extraction
# ---------------------------------------------------------------------------
def find_sd_zone(df_15m, sweep_time, activation_time, mss_price, direction, zone_method,
                 zone_position=ZONE_NEAREST):
    try:
        leg_df = df_15m.loc[sweep_time:activation_time].copy()
        if len(leg_df) < 3:
            return None, None

        leg_df['Body'] = abs(leg_df['Open'] - leg_df['Close'])
        leg_df['Range'] = leg_df['High'] - leg_df['Low']
        leg_df['Is_Base'] = (leg_df['Body'] / leg_df['Range'].replace(0, 0.001)) <= BASE_BODY_RATIO

        leg_df['Eligible'] = True
        if zone_position == ZONE_STRICT:
            leg_df['Eligible'] = (leg_df['High'] < mss_price) if direction == 'Bullish' else (leg_df['Low'] > mss_price)

        base_candles = leg_df[leg_df['Is_Base'] & leg_df['Eligible']].copy()
        if base_candles.empty:
            return None, None

        base_candles['Dist_to_MSS'] = abs(((base_candles['High'] + base_candles['Low']) / 2) - mss_price)
        closest_base_idx = base_candles['Dist_to_MSS'].idxmin()

        leg_df['Block'] = (~leg_df['Is_Base']).cumsum()
        target_block = leg_df.loc[closest_base_idx, 'Block']
        zone_candles = leg_df[(leg_df['Is_Base']) & (leg_df['Eligible']) & (leg_df['Block'] == target_block)]
        if zone_candles.empty:
            return None, None

        if zone_method == "Strict (Base + Leg-Out)":
            last_base_idx = zone_candles.index[-1]
            post_base = leg_df.loc[last_base_idx:]
            if len(post_base) <= 1:
                return None, None
            post_base = post_base.iloc[1:]
            if direction == 'Bullish':
                valid_legout = post_base[(post_base['Close'] > post_base['Open']) & (~post_base['Is_Base'])]
            else:
                valid_legout = post_base[(post_base['Close'] < post_base['Open']) & (~post_base['Is_Base'])]
            if valid_legout.empty:
                return None, None

        if direction == 'Bullish':
            return zone_candles['High'].max(), zone_candles['Low'].min()
        return zone_candles['Low'].min(), zone_candles['High'].max()
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# RULE 6 & 7: Execution Engine with Dynamic New Swing High/Low Target Update
# ---------------------------------------------------------------------------
def simulate_intraday_execution(df_15m, activation_idx, entry_price, active_sl, initial_target, qty,
                                direction, max_wait_hours, trading_window, cap_rr):
    post_activation_df = df_15m.loc[activation_idx:]
    if len(post_activation_df) <= 1:
        return None
    tracking_df = post_activation_df.iloc[1:]

    entry_time, open_px = None, None
    max_wait_candles = int(max_wait_hours * 4)
    tracking_df_entry = tracking_df.iloc[:max_wait_candles]
    
    current_target = initial_target
    target_hit_before_entry = False
    new_swing_target_formed = None
    risk_dist = round(abs(entry_price - active_sl), 2)

    for i, (idx, row) in enumerate(tracking_df_entry.iterrows()):
        # SL hit prior to entry fills
        if direction == 'Bullish' and row['Low'] <= active_sl:
            return {"Entry Date": "-", "Outcome": "Gap SL Void", "P&L (₹)": 0.0, "Exit Price": "-"}
        if direction == 'Bearish' and row['High'] >= active_sl:
            return {"Entry Date": "-", "Outcome": "Gap SL Void", "P&L (₹)": 0.0, "Exit Price": "-"}

        in_window = True
        if trading_window == "09:45 - 13:30":
            in_window = WINDOW_START <= idx.time() < WINDOW_END

        fills = in_window and ((direction == 'Bullish' and row['Low'] <= entry_price) or
                               (direction == 'Bearish' and row['High'] >= entry_price))

        # Check if original target is tagged before entry
        if direction == 'Bullish':
            if row['High'] >= current_target:
                target_hit_before_entry = True
        else:
            if row['Low'] <= current_target:
                target_hit_before_entry = True

        # Rule 6: Track if a NEW 15m swing forms before entry
        history_window = df_15m.loc[:idx]
        if len(history_window) >= (2 * SWING_N + 1):
            check_idx = len(history_window) - 1 - SWING_N
            highs_sub = history_window['High'].to_numpy()
            lows_sub = history_window['Low'].to_numpy()
            if direction == 'Bullish':
                h_candidate = highs_sub[check_idx]
                if (h_candidate > highs_sub[check_idx - SWING_N:check_idx].max() and 
                    h_candidate > highs_sub[check_idx + 1:check_idx + SWING_N + 1].max()):
                    if (h_candidate - entry_price) >= (MIN_RR * risk_dist):
                        new_swing_target_formed = float(h_candidate)
            else:
                l_candidate = lows_sub[check_idx]
                if (l_candidate < lows_sub[check_idx - SWING_N:check_idx].min() and 
                    l_candidate < lows_sub[check_idx + 1:check_idx + SWING_N + 1].min()):
                    if (entry_price - l_candidate) >= (MIN_RR * risk_dist):
                        new_swing_target_formed = float(l_candidate)

        if fills:
            # If target was hit before entry, evaluate if new swing formed
            if target_hit_before_entry:
                if new_swing_target_formed is not None:
                    current_target = new_swing_target_formed
                else:
                    return {"Entry Date": "-", "Outcome": "Target Missed", "P&L (₹)": 0.0, "Exit Price": "-"}
            elif new_swing_target_formed is not None:
                current_target = new_swing_target_formed

            entry_time, open_px = idx, row['Open']
            break

    if entry_time is None:
        return {"Entry Date": "-", "Outcome": "No Entry", "P&L (₹)": 0.0, "Exit Price": "-"}

    # Fill execution price
    if direction == 'Bullish':
        actual_entry = round(open_px if open_px < entry_price else entry_price, 2)
    else:
        actual_entry = round(open_px if open_px > entry_price else entry_price, 2)

    # Dynamic RR capping (No, 1:1.5, 1:2, 1:3)
    cap_map = {"1:1.5": 1.5, "1:2": 2.0, "1:3": 3.0}
    if direction == 'Bullish':
        target_dist = round(current_target - entry_price, 2)
        if cap_rr in cap_map and risk_dist > 0:
            max_r = cap_map[cap_rr]
            if (target_dist / risk_dist) > max_r:
                target_dist = round(max_r * risk_dist, 2)
                current_target = round(entry_price + target_dist, 2)
    else:
        target_dist = round(entry_price - current_target, 2)
        if cap_rr in cap_map and risk_dist > 0:
            max_r = cap_map[cap_rr]
            if (target_dist / risk_dist) > max_r:
                target_dist = round(max_r * risk_dist, 2)
                current_target = round(entry_price - target_dist, 2)

    actual_rr = round(target_dist / risk_dist, 1) if risk_dist > 0 else 0

    end_of_day = entry_time.replace(hour=23, minute=59, second=59)
    day_df = df_15m.loc[entry_time:end_of_day]

    outcome = "Time Square Off"
    exit_price = day_df['Close'].iloc[-1]

    for n, (idx, row) in enumerate(day_df.iterrows()):
        can_target = n > 0
        if direction == 'Bullish':
            if row['Low'] <= active_sl:
                outcome, exit_price = "SL Hit", active_sl
                break
            elif can_target and row['High'] >= current_target:
                outcome, exit_price = "Target Hit", current_target
                break
        else:
            if row['High'] >= active_sl:
                outcome, exit_price = "SL Hit", active_sl
                break
            elif can_target and row['Low'] <= current_target:
                outcome, exit_price = "Target Hit", current_target
                break

    current_time = datetime.now(ist)
    is_today = entry_time.date() == current_time.date()
    if is_today and (current_time.hour < 15 or (current_time.hour == 15 and current_time.minute < 30)):
        if outcome == "Time Square Off":
            outcome = "Running (Live)"

    pnl = round(qty * (exit_price - actual_entry), 2) if direction == 'Bullish' else round(qty * (actual_entry - exit_price), 2)

    return {
        "Entry Date": entry_time.strftime('%Y-%m-%d %H:%M'),
        "Target": current_target,
        "Target RR": f"1:{actual_rr}",
        "Outcome": outcome,
        "Exit Price": round(exit_price, 2),
        "P&L (₹)": pnl
    }


# ---------------------------------------------------------------------------
# Setup Builder: 75m Sweep & No Activation Window
# ---------------------------------------------------------------------------
def build_setup(ticker, direction, sweep_bar_dt, df_15m, df_75m, zone_method, risk_amt, cap_rr,
                zone_position=ZONE_NEAREST):
    bullish = direction == 'Bullish'

    # Rule 3: 75m MSS Swing
    mss_idx, mss_val = get_nearest_untested_75m_swing(df_75m, sweep_bar_dt, 'high' if bullish else 'low')
    if mss_idx is None:
        return None

    # Rule 4: Exactly one completed 75m candle closing beyond MSS line (No window limit)
    activation_idx = find_activation(df_75m, sweep_bar_dt, mss_val, direction)
    if activation_idx is None:
        return None

    sweep_time = df_75m.loc[sweep_bar_dt, 'Datetime'] if 'Datetime' in df_75m.columns else sweep_bar_dt

    # Rule 5: Zone Extraction
    proximal, distal = find_sd_zone(df_15m, sweep_time, activation_idx, mss_val, direction, zone_method, zone_position)
    if not proximal or not distal:
        return None

    entry_price = round(proximal, 2)
    active_sl = round(distal * (SL_PAD_BULL if bullish else SL_PAD_BEAR), 2)

    # Rule 6: Untested 15m swing target
    target_val = get_untested_15m_swing_target(df_15m, activation_idx, entry_price, direction, active_sl)
    if target_val is None:
        return None
    active_target = round(target_val, 2)

    risk_dist = round(abs(entry_price - active_sl), 2)
    target_dist = round(active_target - entry_price, 2) if bullish else round(entry_price - active_target, 2)

    # Pre-cap check
    cap_map = {"1:1.5": 1.5, "1:2": 2.0, "1:3": 3.0}
    if cap_rr in cap_map and risk_dist > 0:
        max_r = cap_map[cap_rr]
        if (target_dist / risk_dist) > max_r:
            target_dist = round(max_r * risk_dist, 2)
            active_target = round(entry_price + target_dist, 2) if bullish else round(entry_price - target_dist, 2)

    if risk_dist <= 0 or target_dist < (MIN_RR * risk_dist):
        return None

    qty = int(risk_amt / risk_dist)
    if qty <= 0:
        return None

    return {
        "Stock": ticker.replace('.NS', ''),
        "Type": direction,
        "Sweep Time": sweep_time,
        "Activation Time": activation_idx,
        "MSS Line": mss_val,
        "Entry": entry_price,
        "SL": active_sl,
        "Target": active_target,
        "Target RR": f"1:{round(target_dist / risk_dist, 1)}",
        "Qty": qty
    }


def evaluate_ticker(ticker, start_date_val, end_date_val, risk_amt, zone_method, app_mode,
                    max_wait_hours, trading_window, cap_rr, zone_position=ZONE_NEAREST):
    raw_setups = []
    internal_start = start_date_val - timedelta(days=10) if app_mode == "Today's Live Trades" else start_date_val - timedelta(days=20)

    df_15m = fetch_market_data(ticker, "60d", "15m")
    daily_htf = fetch_market_data(ticker, "1y", "1d")
    if df_15m.empty or daily_htf.empty:
        return []

    df_75m = build_75m_candles(df_15m)
    if df_75m.empty:
        return []

    weekly_hist = daily_htf.resample('W-MON', closed='left', label='left').agg({'High': 'max', 'Low': 'min'}).dropna()
    completed_75m = df_75m[df_75m['Complete']].copy()
    scan_bars = completed_75m[(completed_75m.index >= pd.Timestamp(internal_start)) & 
                              (completed_75m.index <= pd.Timestamp(end_date_val) + pd.Timedelta(days=1))]

    # Rule 2: 75-Minute Liquidity Sweep
    for sweep_bar_dt, sweep_row in scan_bars.iterrows():
        current_monday = (sweep_bar_dt.normalize() - pd.Timedelta(days=sweep_bar_dt.weekday())).replace(hour=0, minute=0, second=0)
        past_weekly = weekly_hist.loc[weekly_hist.index < current_monday]
        if past_weekly.empty:
            continue

        pwl, pwh = past_weekly['Low'].iloc[-1], past_weekly['High'].iloc[-1]

        setup = None
        if sweep_row['Low'] <= pwl:
            setup = build_setup(ticker, 'Bullish', sweep_bar_dt, df_15m, df_75m, zone_method, risk_amt, cap_rr, zone_position)
        if setup is None and sweep_row['High'] >= pwh:
            setup = build_setup(ticker, 'Bearish', sweep_bar_dt, df_15m, df_75m, zone_method, risk_amt, cap_rr, zone_position)

        if setup is not None:
            raw_setups.append(setup)

    # Deduplicate: Keep latest sweep if multiple lead to the same activation
    deduped_setups = {}
    for s in raw_setups:
        key = (s['Stock'], s['Type'], s['Activation Time'])
        if key not in deduped_setups or s['Sweep Time'] > deduped_setups[key]['Sweep Time']:
            deduped_setups[key] = s

    temp_setups = []
    today_str = datetime.now(ist).strftime('%Y-%m-%d')

    for s in deduped_setups.values():
        exec_data = simulate_intraday_execution(df_15m, s['Activation Time'], s['Entry'], s['SL'], s['Target'],
                                                s['Qty'], s['Type'], max_wait_hours, trading_window, cap_rr)
        if not exec_data:
            continue

        s.update(exec_data)
        s['Sweep Time'] = s['Sweep Time'].strftime('%Y-%m-%d %H:%M') if isinstance(s['Sweep Time'], (pd.Timestamp, datetime)) else str(s['Sweep Time'])
        s['Activation Time'] = s['Activation Time'].strftime('%Y-%m-%d %H:%M') if isinstance(s['Activation Time'], (pd.Timestamp, datetime)) else str(s['Activation Time'])

        entry_date_str = exec_data.get("Entry Date", "-")
        outcome = exec_data.get("Outcome", "")

        if app_mode == "Today's Live Trades":
            if entry_date_str.startswith(today_str):
                temp_setups.append(s)
            elif outcome == "No Entry" and s['Activation Time'].startswith(today_str):
                s["Outcome"] = "Pending Entry"
                temp_setups.append(s)

        elif app_mode == "Backtester":
            if entry_date_str != "-" and outcome != "Gap SL Void":
                try:
                    entry_date_obj = datetime.strptime(entry_date_str, '%Y-%m-%d %H:%M').date()
                    if start_date_val <= entry_date_obj <= end_date_val:
                        temp_setups.append(s)
                except ValueError:
                    pass

    # Rule 7: One trade per stock per calendar day
    def _order(s):
        executed = s.get("Entry Date", "-") != "-"
        return (0 if executed else 1, s["Entry Date"] if executed else s["Activation Time"])

    final_setups, daily_tracker = [], set()
    for s in sorted(temp_setups, key=_order):
        day_str = (s["Entry Date"] if s["Entry Date"] != "-" else s["Activation Time"]).split()[0]
        dedup_key = (s['Stock'], day_str)
        if dedup_key not in daily_tracker:
            daily_tracker.add(dedup_key)
            final_setups.append(s)

    return final_setups


# --- UI EXECUTION ---
st.write("Executing 7-Rule ICT Framework with 75m Sweeps and Dynamic Target Tracking.")

wait_options_dict = {
    "30 min": 0.5, "1 hr": 1.0, "1:30 hrs": 1.5, "2 hrs": 2.0, "2:30 hrs": 2.5,
    "3 hrs": 3.0, "3:30 hrs": 3.5, "4 hrs": 4.0, "4:30 hrs": 4.5, "5 hrs": 5.0,
    "5:30 hrs": 5.5, "6 hrs": 6.0, "6:30 hrs": 6.5, "7 hrs": 7.0, "7:30 hrs": 7.5,
    "8 hrs": 8.0, "8:30 hrs": 8.5, "9 hrs": 9.0, "9:30 hrs": 9.5, "10 hrs": 10.0
}

app_mode = st.radio("Operating Mode", ["Today's Live Trades", "Backtester"], horizontal=True)

if app_mode == "Backtester":
    r1c1, r1c2, r1c3, r1c4 = st.columns(4)
    today = datetime.now(ist).date()
    with r1c1: start_date = st.date_input("Entry Start Date", today - timedelta(days=5))
    with r1c2: end_date = st.date_input("Entry End Date", today)
    with r1c3: universe_selection = st.selectbox("Stock Universe", ["Nifty 200", "Nifty 500"])
    with r1c4: zone_method = st.selectbox("Zone Identification", ["Standard (Base Only)", "Strict (Base + Leg-Out)"])

    r2c1, r2c2, r2c3, r2c4 = st.columns(4)
    with r2c1: risk_amt = st.number_input("Risk Per Trade (₹)", value=1000, step=100)
    with r2c2: trading_window = st.selectbox("Entry Window", ["Full Day (09:15 - 15:30)", "09:45 - 13:30"])
    with r2c3:
        max_wait_label = st.selectbox("Max Wait to Entry", list(wait_options_dict.keys()), index=19)
        max_wait_hours = wait_options_dict[max_wait_label]
    with r2c4: cap_rr = st.selectbox("Cap RR?", ["No", "1:1.5", "1:2", "1:3"])
else:
    r1c1, r1c2, r1c3 = st.columns(3)
    today = datetime.now(ist).date()
    start_date, end_date = today, today
    with r1c1: universe_selection = st.selectbox("Stock Universe", ["Nifty 200", "Nifty 500"])
    with r1c2: zone_method = st.selectbox("Zone Identification", ["Standard (Base Only)", "Strict (Base + Leg-Out)"])
    with r1c3: risk_amt = st.number_input("Risk Per Trade (₹)", value=1000, step=100)

    r2c1, r2c2, r2c3 = st.columns(3)
    with r2c1: trading_window = st.selectbox("Entry Window", ["Full Day (09:15 - 15:30)", "09:45 - 13:30"])
    with r2c2:
        max_wait_label = st.selectbox("Max Wait to Entry", list(wait_options_dict.keys()), index=19)
        max_wait_hours = wait_options_dict[max_wait_label]
    with r2c3: cap_rr = st.selectbox("Cap RR?", ["No", "1:1.5", "1:2", "1:3"])

zone_position = st.selectbox(
    "15m Zone Condition vs MSS Line",
    [ZONE_NEAREST, ZONE_STRICT],
    help="Nearest: base candles closest to MSS line. Strictly below/above: Demand strictly below MSS / Supply strictly above MSS.")

if st.button("🚀 Execute Scan", type="primary"):
    with st.spinner(f"Scanning {universe_selection} across {app_mode}..."):
        tickers = get_stock_symbols(universe_selection)
        all_setups = []
        progress_bar = st.progress(0)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
            futures = {executor.submit(evaluate_ticker, t, start_date, end_date, risk_amt, zone_method,
                                       app_mode, max_wait_hours, trading_window, cap_rr, zone_position): t for t in tickers}
            completed = 0
            for f in concurrent.futures.as_completed(futures):
                try:
                    res = f.result()
                except Exception:
                    res = []
                if res:
                    all_setups.extend(res)
                completed += 1
                progress_bar.progress(completed / len(tickers))

        progress_bar.empty()

        if all_setups:
            df = pd.DataFrame(all_setups)
            cols_order = ["Stock", "Type", "Sweep Time", "Activation Time", "MSS Line", "Entry Date", "Entry",
                          "SL", "Target", "Target RR", "Qty", "Outcome", "Exit Price", "P&L (₹)"]

            df_bull = df[df['Type'] == 'Bullish'].copy()
            df_bear = df[df['Type'] == 'Bearish'].copy()

            if not df_bull.empty:
                df_bull = df_bull[[c for c in cols_order if c in df_bull.columns]]
                df_bull = df_bull.sort_values(by="Entry Date", ascending=True)
            if not df_bear.empty:
                df_bear = df_bear[[c for c in cols_order if c in df_bear.columns]]
                df_bear = df_bear.sort_values(by="Entry Date", ascending=True)

            tab1, tab2 = st.tabs(["🟢 Bullish Setups", "🔴 Bearish Setups"])

            def render_tab(df_sub):
                if df_sub.empty:
                    st.info("No triggered trades in this category.")
                    return

                completed_trades = df_sub[df_sub['Outcome'].isin(["Target Hit", "SL Hit", "Time Square Off", "Running (Live)"])]
                wins = int((completed_trades['P&L (₹)'] > 0).sum())
                losses = int((completed_trades['P&L (₹)'] < 0).sum())
                total = len(completed_trades)
                win_rate = (wins / total) * 100 if total > 0 else 0
                total_pnl = completed_trades['P&L (₹)'].sum()

                m1, m2, m3, m4, m5 = st.columns(5)
                m1.metric("Active / Completed Trades", total)
                m2.metric("Winners", wins)
                m3.metric("Losers", losses)
                m4.metric("Win Rate", f"{win_rate:.1f}%")
                m5.metric("Net Profit / Loss", f"₹ {total_pnl:,.2f}")

                st.dataframe(df_sub, width="stretch", hide_index=True)

            with tab1: render_tab(df_bull)
            with tab2: render_tab(df_bear)
        else:
            st.warning("No setups met all conditions for the selected mode.")
