import streamlit as st
import pandas as pd
import numpy as np
import requests
import io
import time
import warnings
import concurrent.futures
from datetime import datetime, timedelta

warnings.filterwarnings('ignore')

st.set_page_config(page_title="ICT Doji Resting Screener", layout="wide")

HISTORY_DAYS = 365

FALLBACK_TICKERS = [
    'RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'ICICIBANK.NS', 'BHARTIARTL.NS', 'SBIN.NS',
    'INFY.NS', 'LICI.NS', 'ITC.NS', 'HINDUNILVR.NS', 'LT.NS', 'BAJFINANCE.NS',
    'HCLTECH.NS', 'MARUTI.NS', 'SUNPHARMA.NS', 'TATAMOTORS.NS', 'TATASTEEL.NS',
    'ONGC.NS', 'KOTAKBANK.NS', 'NTPC.NS', 'AXISBANK.NS', 'POWERGRID.NS', 'TITAN.NS'
]

# ==========================================
# UNIVERSE & ROBUST MAPPING
# ==========================================
@st.cache_data(ttl=86400)
def get_dhan_symbol_mapping():
    try:
        url = "https://images.dhan.co/api-data/api-scrip-master.csv"
        df = pd.read_csv(url, low_memory=False)
        df_nse = df[df['SEM_EXM_EXCH_ID'] == 'NSE']

        mapping = {}
        for _, row in df_nse.iterrows():
            sec_id = str(row['SEM_SMST_SECURITY_ID'])
            trade_sym = str(row.get('SEM_TRADING_SYMBOL', '')).strip()
            custom_sym = str(row.get('SEM_CUSTOM_SYMBOL', '')).strip()

            if trade_sym: mapping[trade_sym] = sec_id
            if custom_sym: mapping[custom_sym] = sec_id

            if trade_sym.endswith('-EQ'): mapping[trade_sym.replace('-EQ', '')] = sec_id
            if custom_sym.endswith('-EQ'): mapping[custom_sym.replace('-EQ', '')] = sec_id

        return mapping
    except Exception:
        return {}

def fetch_nse_csv(url):
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            df = pd.read_csv(io.StringIO(res.text))
            col = 'Symbol' if 'Symbol' in df.columns else 'SYMBOL'
            return [str(s).strip() + '.NS' for s in df[col]]
    except Exception:
        pass
    return []

@st.cache_data(ttl=86400)
def get_nifty200_symbols():
    res = fetch_nse_csv("https://nsearchives.nseindia.com/content/indices/ind_nifty200list.csv")
    return res if res else FALLBACK_TICKERS

@st.cache_data(ttl=86400)
def get_nifty500_symbols():
    res = fetch_nse_csv("https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv")
    return res if res else FALLBACK_TICKERS

@st.cache_data(ttl=86400)
def get_all_nse_symbols():
    res = fetch_nse_csv("https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv")
    return res if res else FALLBACK_TICKERS

# ==========================================
# DIRECT HTTP DHAN FETCHING
# ==========================================
def fetch_dhan_data(security_id, client_id, access_token):
    try:
        url = "https://api.dhan.co/v2/charts/historical"
        headers = {
            "access-token": access_token.strip(),
            "Content-Type": "application/json",
            "Accept": "application/json"
        }

        from_date_str = (datetime.today() - timedelta(days=HISTORY_DAYS)).strftime('%Y-%m-%d')
        to_date_str = datetime.today().strftime('%Y-%m-%d')

        payload = {
            "securityId": str(security_id),
            "exchangeSegment": "NSE_EQ",
            "instrument": "EQUITY",
            "expiryCode": 0,
            "oi": False,
            "fromDate": from_date_str,
            "toDate": to_date_str
        }

        response = requests.post(url, headers=headers, json=payload, timeout=8)

        if not response.text.strip() or response.status_code != 200:
            return pd.DataFrame()

        try:
            data = response.json()
        except ValueError:
            return pd.DataFrame()

        if 'open' in data and 'close' in data:
            if not data['open']:
                return pd.DataFrame()

            df = pd.DataFrame(data)
            if df.empty:
                return pd.DataFrame()

            ts_col = next((c for c in ['timestamp', 'start_Time', 'Timestamp'] if c in df.columns), None)
            if ts_col is None:
                return pd.DataFrame()

            if pd.api.types.is_numeric_dtype(df[ts_col]):
                first = df[ts_col].iloc[0]
                unit = 'ms' if first > 1e11 else 's'
                ts = pd.to_datetime(df[ts_col], unit=unit, utc=True)
                # Dhan's legacy format counts seconds from 1980-01-01 instead of 1970
                if ts.iloc[0].year < 2000:
                    ts = pd.to_datetime(df[ts_col] + 315532800, unit='s', utc=True)
                ts = ts.dt.tz_convert('Asia/Kolkata').dt.tz_localize(None)
            else:
                ts = pd.to_datetime(df[ts_col])
                if ts.dt.tz is not None:
                    ts = ts.dt.tz_localize(None)

            df.index = pd.DatetimeIndex(ts.dt.normalize())
            df.index.name = 'Date'
            df = df.drop(columns=[ts_col])

            df.rename(columns={'open': 'Open', 'high': 'High', 'low': 'Low',
                               'close': 'Close', 'volume': 'Volume'}, inplace=True)
            df = df[~df.index.duplicated(keep='last')]
            df.sort_index(inplace=True)
            return df

        return pd.DataFrame()
    except Exception:
        return pd.DataFrame()

# ==========================================
# FRAME PREPARATION
# ------------------------------------------
# Bearish setups are evaluated by MIRRORING the price frame (negating prices and swapping
# High/Low). A bearish setup then looks exactly like a bullish one, so a single engine
# handles both sides. All displayed prices are un-mirrored again.
# ==========================================
def _period_start(kind, key):
    if kind == 'M':
        return pd.Timestamp(int(key // 12), int(key % 12) + 1, 1)
    if kind == 'Q':
        return pd.Timestamp(int(key // 4), int(key % 4) * 3 + 1, 1)
    return pd.Timestamp(int(key // 2), int(key % 2) * 6 + 1, 1)

def prepare_frame(df, side):
    d = df[['Open', 'High', 'Low', 'Close']].astype(float)
    if side == "Bearish":
        d = pd.DataFrame({'Open': -d['Open'], 'High': -d['Low'],
                          'Low': -d['High'], 'Close': -d['Close']}, index=d.index)
    d = d.copy()
    d['EMA20'] = d['Close'].ewm(span=20, adjust=False).mean()

    ix = d.index
    keys = {
        'PML': ('M', ix.year * 12 + ix.month - 1),
        'PQL': ('Q', ix.year * 4 + (ix.month - 1) // 3),
        'PHL': ('H', ix.year * 2 + (ix.month - 1) // 6),
    }
    # Previous-month / quarter / half-year low for every bar (the "as of that bar" level).
    # A first period that is only partially covered by the downloaded history is dropped,
    # otherwise its low would be wrong and would create fake sweeps.
    for col, (kind, arr) in keys.items():
        k = pd.Series(np.asarray(arr), index=ix)
        grp = d['Low'].groupby(k).min()
        first_key = int(k.iloc[0])
        if ix[0] > _period_start(kind, first_key) + pd.Timedelta(days=7):
            grp = grp.drop(first_key, errors='ignore')
        d[col] = (k - 1).map(grp)
    return d

# ==========================================
# CURVATURE MATH
# ==========================================
def ema_curve_ok(ema_series, mode, lookback=20):
    """Is the EMA20 forming a bottom? (bearish frames are mirrored, so this covers both sides)"""
    if mode == "Off":
        return True, "filter is off"
    if len(ema_series) < lookback:
        return False, "not enough bars"
    r = ema_series.iloc[-lookback:].values
    mi = int(np.argmin(r))
    start, end, trough = r[0], r[-1], r[mi]
    ago = lookback - 1 - mi
    where = f"EMA20 low was {ago} bars ago"

    if mi < 4:
        return False, f"EMA20 low is too far back ({where})"
    if start <= trough:
        return False, "EMA20 did not fall into a low within the window"

    if mode.startswith("Relaxed"):
        if end <= trough:
            return False, f"EMA20 is still at its low, no upturn yet ({where})"
        return True, f"EMA20 has turned up ({where})"

    # Strict (original rules)
    if mi > lookback - 4:
        return False, f"EMA20 low is too recent ({where}); strict mode needs 3+ bars of upturn"
    if end <= trough:
        return False, "EMA20 has not risen above its low"
    trough_vals = r[max(0, mi - 2):min(lookback, mi + 3)]
    trough_range = trough_vals.max() - trough_vals.min()
    total_depth = max(start, end) - trough
    if total_depth == 0:
        return False, "EMA20 is flat"
    if trough_range > total_depth * 0.5:
        return False, "EMA20 bottom is too sharp (V-shaped), not rounded"
    return True, f"rounded EMA20 bottom ({where})"

# ==========================================
# ENGINE (both sides)
# ==========================================
LEVEL_NAMES = {
    "Bullish": {'PML': 'PML', 'PQL': 'PQL', 'PHL': 'PHL'},
    "Bearish": {'PML': 'PMH', 'PQL': 'PQH', 'PHL': 'PHH'},
}

def evaluate_day(ticker, d, idx, side, p, trace=None):
    """
    d     : frame from prepare_frame(df, side)
    idx   : integer position of the trigger candle
    trace : pass a list to receive a pass/fail row for every check (used by the Diagnose tab)
    """
    sg = 1 if side == "Bullish" else -1
    names = LEVEL_NAMES[side]
    w_trend = "downtrend" if sg == 1 else "uptrend"
    w_above = "above" if sg == 1 else "below"
    w_edge = "low" if sg == 1 else "high"

    def log(name, ok, detail=""):
        if trace is not None:
            trace.append({"Check": name, "Result": "✅ Pass" if ok else "❌ Fail", "Detail": detail})
        return ok

    if idx < 60:
        log("Enough history", False, f"only {idx} bars before this date")
        return None

    row = d.iloc[idx]
    ema_val = row['EMA20']

    # ---- Independent checks (cheap, so run first) ----
    ok_ema, det = ema_curve_ok(d['EMA20'].iloc[max(0, idx - 20):idx + 1], p['ema_mode'])
    log("EMA20 curvature", ok_ema, det)
    if not ok_ema and trace is None:
        return None

    ok_close = bool(row['Close'] > ema_val)
    log(f"Trigger candle closes {w_above} EMA20", ok_close,
        f"Close {sg * row['Close']:.2f} vs EMA20 {sg * ema_val:.2f}")
    if not ok_close and trace is None:
        return None

    dist = (row['Low'] - ema_val) / abs(ema_val) * 100
    ok_dist = p['dist_min'] <= dist <= p['dist_max']
    log(f"Trigger candle's {w_edge} is close to EMA20", ok_dist,
        f"distance {dist:.2f}% (allowed {p['dist_min']}% to {p['dist_max']}%)")
    if not ok_dist and trace is None:
        return None

    # ---- 1. Higher-timeframe sweep inside the lookback window ----
    use_sweep_date = p['level_mode'].startswith("Sweep")
    win = d.iloc[max(0, idx - p['sweep_window']):idx + 1]
    swept = pd.Series(False, index=win.index)
    for nm in ('PML', 'PQL', 'PHL'):
        ref = win[nm] if use_sweep_date else d[nm].iloc[idx]
        swept = swept | (win['Low'] < ref)

    if not swept.any():
        log("HTF level swept", False,
            f"no bar in the last {p['sweep_window']} took out the previous month/quarter/half-year {w_edge}")
        return None

    sweep_day = win['Low'][swept].idxmin()
    sweep_idx = d.index.get_loc(sweep_day)
    hits = []
    for nm in ('PML', 'PQL', 'PHL'):
        ref = d[nm].iloc[sweep_idx] if use_sweep_date else d[nm].iloc[idx]
        if pd.notna(ref) and d['Low'].iloc[sweep_idx] < ref:
            hits.append((ref, nm))
    level_price, level_nm = min(hits)
    log("HTF level swept", True,
        f"{names[level_nm]} at ₹{sg * level_price:.2f} swept on {sweep_day.date()} ({idx - sweep_idx} bars ago)")

    # ---- 2. Macro trend into the sweep ----
    if sweep_idx < 40:
        log(f"Macro {w_trend} into sweep", False, "sweep is too early in the available data")
        return None
    e40 = d['EMA20'].iloc[sweep_idx - 40]
    e20 = d['EMA20'].iloc[sweep_idx - 20]
    e0 = d['EMA20'].iloc[sweep_idx]
    ok_trend = bool(e40 > e20 > e0)
    log(f"Macro {w_trend} into sweep", ok_trend,
        f"EMA20 40/20/0 bars before sweep: {sg * e40:.1f} → {sg * e20:.1f} → {sg * e0:.1f}")
    if not ok_trend:
        return None

    # ---- 3. Nearest untested swing before the sweep ----
    pre = d.iloc[max(0, sweep_idx - 60):sweep_idx]
    if len(pre) < 5:
        log("Untested swing before sweep", False, "not enough bars before the sweep")
        return None
    H = pre['High'].values
    nearest = None
    for i in range(len(H) - 2, 0, -1):
        if H[i] > H[i - 1] and H[i] > H[i + 1] and H[i + 1:].max() < H[i]:
            nearest = H[i]
            break
    if nearest is None:
        log("Untested swing before sweep", False, "no untested swing point found")
        return None
    log("Untested swing before sweep", True, f"₹{sg * nearest:.2f}")

    # ---- 4. Market structure shift ----
    post = d.iloc[sweep_idx:idx + 1]
    ok_mss = bool((post['Close'] > nearest).any())
    log("Market structure shift", ok_mss,
        f"a close {w_above} ₹{sg * nearest:.2f} after the sweep " + ("happened" if ok_mss else "has not happened"))
    if not ok_mss:
        return None

    # ---- 5. First close beyond EMA20 after the sweep ----
    above = post[post['Close'] > post['EMA20']]
    if above.empty:
        log(f"Breakout {w_above} EMA20", False, "no close beyond EMA20 since the sweep")
        return None
    first_idx = d.index.get_loc(above.index[0])
    log(f"Breakout {w_above} EMA20", True, f"first close {w_above} EMA20 on {above.index[0].date()}")

    # ---- 6. Price stayed on the trend side of EMA20 before that breakout ----
    ptw = d.iloc[max(0, first_idx - p['pretouch_window']):first_idx]
    touches = int((ptw['High'] >= ptw['EMA20']).sum())
    ok_pt = touches <= p['pretouch_max']
    log("Clean trend before breakout", ok_pt,
        f"{touches} bars touched/crossed EMA20 in the {p['pretouch_window']} bars before the breakout "
        f"(max allowed {p['pretouch_max']})")
    if not ok_pt:
        return None

    # ---- 7. At least one doji resting on the right side of EMA20 ----
    rw = d.iloc[max(first_idx, idx - p['doji_bars'] + 1):idx + 1]
    body = (rw['Open'] - rw['Close']).abs()
    rng = rw['High'] - rw['Low']
    dojis = int(((rng > 0) & (body <= rng * p['doji_body']) & (rw['Close'] > rw['EMA20'])).sum())
    ok_doji = dojis >= 1
    log("Doji resting on EMA20", ok_doji,
        f"{dojis} doji in the last {p['doji_bars']} bars (body <= {int(p['doji_body'] * 100)}% of range)")
    if not ok_doji:
        return None

    if not (ok_ema and ok_close and ok_dist):
        return None

    return {
        "Stock Symbol": ticker.replace('.NS', ''),
        "Trigger Date": d.index[idx].strftime('%Y-%m-%d'),
        "HTF Swept": names[level_nm],
        "Sweep Date": sweep_day.strftime('%Y-%m-%d'),
        ("Pre-Sweep High (₹)" if sg == 1 else "Pre-Sweep Low (₹)"): round(sg * nearest, 2),
        "EMA20 Rest (₹)": round(sg * ema_val, 2),
        "Close (₹)": round(sg * row['Close'], 2),
    }

# ==========================================
# WRAPPER FUNCTIONS (CACHED)
# ==========================================
@st.cache_data(ttl=1800, show_spinner=False)
def get_cached_stock_df(security_id, client_id, access_token):
    return fetch_dhan_data(security_id, client_id, access_token)

def scan_live_setups(ticker, security_id, setup_type, client_id, access_token, p):
    df = get_cached_stock_df(security_id, client_id, access_token)
    if df.empty or len(df) < 200: return None

    cmp = df['Close'].iloc[-1]
    if pd.isna(cmp) or cmp < 100: return None

    d = prepare_frame(df, setup_type)
    return evaluate_day(ticker, d, len(d) - 1, setup_type, p)

def backtest_setups(ticker, security_id, start_date, end_date, setup_type, client_id, access_token, p):
    df = get_cached_stock_df(security_id, client_id, access_token)
    if df.empty or len(df) < 200: return []

    d = prepare_frame(df, setup_type)
    dates = d.index.normalize()
    mask = (dates >= pd.Timestamp(start_date)) & (dates <= pd.Timestamp(end_date))

    out = []
    for idx in np.flatnonzero(mask):
        if idx < 130: continue
        cmp = df['Close'].iloc[idx]
        if pd.isna(cmp) or cmp < 100: continue
        res = evaluate_day(ticker, d, int(idx), setup_type, p)
        if res: out.append(res)
    return out

# ==============================
# STREAMLIT UI
# ==============================
st.title("ICT Doji Resting Screener (Lightning Fast)")
st.markdown("Macro Trend -> Untested HTF Sweep -> Daily MSS -> Flag -> Pinpoint Curvature Doji Rest")

st.sidebar.header("Dhan API Configuration")
CLIENT_ID = st.sidebar.text_input("Dhan Client ID", type="password")
ACCESS_TOKEN = st.sidebar.text_input("Dhan Access Token", type="password")

if st.sidebar.button("Test API Connection"):
    with st.sidebar:
        if not CLIENT_ID or not ACCESS_TOKEN:
            st.error("Please enter credentials first.")
        else:
            st.write("Testing API via HDFCBANK (SecID: 1333)...")
            res = fetch_dhan_data("1333", CLIENT_ID, ACCESS_TOKEN)
            if res.empty:
                st.error("API returned empty data. Check token.")
            else:
                st.success(f"Success! Fetched {len(res)} daily candles "
                           f"({res.index[0].date()} to {res.index[-1].date()}).")

st.sidebar.divider()
universe_option = st.sidebar.selectbox("Select Stock Universe", ["Nifty 200", "Nifty 500", "All NSE Stocks (> ₹100)"])

st.sidebar.divider()
st.sidebar.header("Filter Settings")
st.sidebar.caption("Defaults are tuned to also catch early-reversal setups like COLPAL. "
                   "Original values are noted on each control.")

ema_mode = st.sidebar.selectbox(
    "EMA20 curvature filter",
    ["Relaxed (early turn)", "Strict (original)", "Off"], index=0,
    help="Strict needs the EMA20 low to be 4-16 bars back and a rounded bottom. "
         "Relaxed only needs the EMA20 to have fallen and started turning up.")
level_mode = st.sidebar.selectbox(
    "HTF levels measured as of",
    ["Sweep date (recommended)", "Trigger date (original)"], index=0,
    help="Original compares the sweep against the previous month/quarter/half-year of the TRIGGER date. "
         "If the sweep happened in an earlier month, that level can include the sweep candle itself "
         "and the sweep is missed.")
pretouch_max = st.sidebar.slider(
    "Max bars touching EMA20 before breakout", 0, 30, 12,
    help="Original = 5. Counted over the 30 bars before the first close back above EMA20.")

with st.sidebar.expander("Advanced"):
    sweep_window = st.slider("Sweep must be within last N bars", 10, 80, 40, help="Original = 40")
    pretouch_window = st.slider("Pre-breakout window (bars)", 10, 60, 30, help="Original = 30")
    doji_bars = st.slider("Look for doji in last N bars", 1, 10, 6, help="Original = 6")
    doji_body = st.slider("Doji body as % of candle range", 10, 60, 35, help="Original = 35") / 100
    dist_min = st.number_input("Min distance of trigger candle's edge from EMA20 (%)", value=-1.0, step=0.5)
    dist_max = st.number_input("Max distance of trigger candle's edge from EMA20 (%)", value=2.0, step=0.5)

P = {
    'ema_mode': ema_mode,
    'level_mode': level_mode,
    'pretouch_max': pretouch_max,
    'pretouch_window': pretouch_window,
    'sweep_window': sweep_window,
    'doji_bars': doji_bars,
    'doji_body': doji_body,
    'dist_min': dist_min,
    'dist_max': dist_max,
}

if not CLIENT_ID or not ACCESS_TOKEN:
    st.info("👈 Please enter your Dhan API Client ID and Access Token in the sidebar to run scans.")
    st.stop()

bullish_tab, bearish_tab, diag_tab = st.tabs(
    ["Bullish Setups (Sweep Low)", "Bearish Setups (Sweep High)", "🔍 Diagnose a Stock"])

def execute_scan(setup_type, mode, start_date=None, end_date=None):
    with st.spinner(f"Lightning scanning {universe_option} (Concurrent batches)..."):
        if universe_option == "Nifty 200": tickers = get_nifty200_symbols()
        elif universe_option == "Nifty 500": tickers = get_nifty500_symbols()
        else: tickers = get_all_nse_symbols()

        mapping = get_dhan_symbol_mapping()
        if not mapping:
            st.error("Failed to fetch Dhan Symbol Mapping. Check connection.")
            return

        my_bar = st.progress(0)
        results = []
        errors = 0

        chunk_size = 50
        ticker_chunks = [tickers[i:i + chunk_size] for i in range(0, len(tickers), chunk_size)]

        total_processed = 0
        for chunk in ticker_chunks:
            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                futures = {}
                for t in chunk:
                    clean_sym = t.replace('.NS', '')
                    sec_id = mapping.get(clean_sym)
                    if sec_id:
                        if mode == "live":
                            futures[executor.submit(scan_live_setups, t, sec_id, setup_type, CLIENT_ID, ACCESS_TOKEN, P)] = t
                        else:
                            futures[executor.submit(backtest_setups, t, sec_id, start_date, end_date, setup_type, CLIENT_ID, ACCESS_TOKEN, P)] = t
                    else:
                        total_processed += 1

                for future in concurrent.futures.as_completed(futures):
                    try:
                        res = future.result()
                    except Exception:
                        res = None
                        errors += 1
                    if res:
                        if mode == "live": results.append(res)
                        else: results.extend(res)
                    total_processed += 1
                    my_bar.progress(min(total_processed / len(tickers), 1.0))

            time.sleep(0.05)

        my_bar.empty()

        if errors:
            st.caption(f"{errors} symbols were skipped due to errors.")

        if results:
            if mode == "backtest": results.sort(key=lambda x: x['Trigger Date'])
            df_res = pd.DataFrame(results)
            st.success(f"Found {len(df_res)} {setup_type} Setups!")
            st.dataframe(df_res, use_container_width=True)

            if mode == "backtest":
                csv = df_res.to_csv(index=False).encode('utf-8')
                st.download_button(label="Download Backtest Data", data=csv,
                                   file_name=f"{setup_type}_Backtest.csv", mime="text/csv")
        else:
            st.warning(f"No {setup_type} setups found in the specified criteria.")

with bullish_tab:
    st.markdown("Identifies a sustained **Macro Downtrend**, an **untested HTF low sweep**, daily **MSS**, a breakout above the **EMA 20**, and a flag pulling back to print at least one **Doji resting precisely ON the EMA**.")
    if st.button("Run Live Bullish Screener"): execute_scan("Bullish", "live")

    st.divider()
    st.markdown("#### Backtest Custom Date Range (Bullish)")
    col1, col2 = st.columns(2)
    with col1: start_b = st.date_input("From Date (Bullish)", datetime.today() - timedelta(days=30))
    with col2: end_b = st.date_input("To Date (Bullish)", datetime.today())
    if st.button("Run Bullish Backtester"): execute_scan("Bullish", "backtest", start_b, end_b)

with bearish_tab:
    st.markdown("Identifies a sustained **Macro Uptrend**, an **untested HTF high sweep**, daily **MSS (Downside)**, a drop below the **EMA 20**, and a rally flag printing at least one **Doji resting tightly BENEATH the EMA**.")
    if st.button("Run Live Bearish Screener"): execute_scan("Bearish", "live")

    st.divider()
    st.markdown("#### Backtest Custom Date Range (Bearish)")
    col3, col4 = st.columns(2)
    with col3: start_br = st.date_input("From Date (Bearish)", datetime.today() - timedelta(days=30))
    with col4: end_br = st.date_input("To Date (Bearish)", datetime.today())
    if st.button("Run Bearish Backtester"): execute_scan("Bearish", "backtest", start_br, end_br)

with diag_tab:
    st.markdown("Check any stock against every filter, using the current **Filter Settings** from the sidebar. "
                "Failed checks tell you exactly why a stock did not appear.")
    c1, c2, c3 = st.columns(3)
    diag_sym = c1.text_input("NSE symbol (without .NS)", value="COLPAL").strip().upper().replace('.NS', '')
    diag_side = c2.selectbox("Setup type", ["Bullish", "Bearish"], key="diag_side")
    diag_date = c3.date_input("As of date", datetime.today(), key="diag_date")

    if st.button("Run diagnosis"):
        mapping = get_dhan_symbol_mapping()
        sec_id = mapping.get(diag_sym)
        if not sec_id:
            st.error(f"'{diag_sym}' was not found in the Dhan symbol list.")
        else:
            raw = get_cached_stock_df(sec_id, CLIENT_ID, ACCESS_TOKEN)
            if raw.empty:
                st.error("No data returned for this stock. Check the token and try again.")
            else:
                d = prepare_frame(raw, diag_side)
                pos = int(d.index.searchsorted(pd.Timestamp(diag_date), side='right')) - 1
                if pos < 0:
                    st.error("That date is before the available data.")
                else:
                    sg = 1 if diag_side == "Bullish" else -1
                    r = raw.iloc[pos]
                    st.caption(
                        f"Candle used: {raw.index[pos].date()} | O {r['Open']:.2f}  H {r['High']:.2f}  "
                        f"L {r['Low']:.2f}  C {r['Close']:.2f} | EMA20 {sg * d['EMA20'].iloc[pos]:.2f} "
                        f"| {len(raw)} candles loaded ({raw.index[0].date()} to {raw.index[-1].date()}). "
                        f"Compare with your chart to confirm the data matches.")
                    trace = []
                    res = evaluate_day(diag_sym, d, pos, diag_side, P, trace)
                    st.dataframe(pd.DataFrame(trace), use_container_width=True, hide_index=True)
                    if res:
                        st.success("This stock WOULD be listed with the current settings.")
                        st.dataframe(pd.DataFrame([res]), use_container_width=True, hide_index=True)
                    else:
                        st.warning("This stock would NOT be listed. See the ❌ rows above. "
                                   "Loosen the matching setting in the sidebar and run again.")
