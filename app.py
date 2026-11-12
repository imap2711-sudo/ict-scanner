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
    d['EMA8'] = d['Close'].ewm(span=8, adjust=False).mean()

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
# ENGINE 2: FLAG AFTER EMA8/20 CROSSOVER (both sides, via mirrored frame)
# Sequence: 1) HTF liquidity sweep  ->  2) EMA8 crosses above EMA20 (EMA20 turning up)
#           3) impulse "pole"       ->  4) tight flag resting near EMA8/EMA20, at/above the crossover
# ==========================================
def find_sweep(d, idx, window, use_sweep_date):
    """Lowest bar inside the window that took out the previous month/quarter/half-year low."""
    win = d.iloc[max(0, idx - window):idx + 1]
    swept = pd.Series(False, index=win.index)
    for nm in ('PML', 'PQL', 'PHL'):
        ref = win[nm] if use_sweep_date else d[nm].iloc[idx]
        swept = swept | (win['Low'] < ref)
    if not swept.any():
        return None
    sweep_idx = d.index.get_loc(win['Low'][swept].idxmin())
    hits = []
    for nm in ('PML', 'PQL', 'PHL'):
        ref = d[nm].iloc[sweep_idx] if use_sweep_date else d[nm].iloc[idx]
        if pd.notna(ref) and d['Low'].iloc[sweep_idx] < ref:
            hits.append((ref, nm))
    level_price, level_nm = min(hits)
    return sweep_idx, level_nm, level_price

def _front_checks(d, idx, p, side, log, collect, min_bars, close_slack=0.0):
    """Steps shared by the flag and flat-base patterns:
    HTF sweep -> downtrend into it -> EMA8/EMA20 crossover -> EMA20 curvature -> close vs EMA20.
    Returns a context dict, or None when the setup is rejected outright (only if `collect` is False,
    i.e. when no diagnosis trace is being built; with a trace we keep going to show every row)."""
    sg = 1 if side == "Bullish" else -1
    names = LEVEL_NAMES[side]
    w_trend = "downtrend" if sg == 1 else "uptrend"
    w_above = "above" if sg == 1 else "below"
    w_edge = "low" if sg == 1 else "high"
    e8, e20 = d['EMA8'].values, d['EMA20'].values
    close = d['Close'].iloc[idx]
    all_ok = True

    # ---- 1. HTF sweep (must come first) ----
    sw = find_sweep(d, idx, p['flag_sweep_window'], p['level_mode'].startswith("Sweep"))
    if sw is None:
        log("1. HTF level swept", False,
            f"no bar in the last {p['flag_sweep_window']} took out the previous month/quarter/half-year {w_edge}")
        return None
    sweep_idx, level_nm, level_price = sw
    sweep_day = d.index[sweep_idx]
    log("1. HTF level swept", True,
        f"{names[level_nm]} at ₹{sg * level_price:.2f} swept on {sweep_day.date()} ({idx - sweep_idx} bars ago)")

    if idx - sweep_idx < min_bars + 2:
        log("Time since sweep", False,
            f"sweep was only {idx - sweep_idx} bars ago; need at least {min_bars + 2} bars after it")
        return None

    # ---- 2. Macro trend into the sweep (optional) ----
    if p['need_downtrend']:
        ok = sweep_idx >= 20 and bool(e20[sweep_idx - 20] > e20[sweep_idx])
        log(f"Macro {w_trend} into sweep", ok,
            "not enough bars before the sweep" if sweep_idx < 20 else
            f"EMA20 20 bars before sweep {sg * e20[sweep_idx - 20]:.1f} → at sweep {sg * e20[sweep_idx]:.1f}")
        if not ok:
            all_ok = False
            if not collect: return None

    # ---- 3. EMA8 / EMA20 crossover after the sweep ----
    diff = (e8 - e20) / np.abs(e20) * 100
    gap = diff[idx]
    below = np.flatnonzero(diff[sweep_idx:idx + 1] < 0)
    cross_idx, age = None, None
    if len(below) == 0:
        log("2. EMA8 crossed EMA20 after the sweep", False,
            "EMA8 was never below EMA20 after the sweep, so no crossover happened after it")
        all_ok = False
        if not collect: return None
    else:
        j = sweep_idx + int(below[-1])
        if gap >= 0:
            cross_idx, age = j + 1, idx - (j + 1)
        else:
            age = 0
        ok_gap = gap >= -p['cross_tol']
        log("2. EMA8 at/above EMA20", ok_gap,
            f"EMA8 is {gap:+.2f}% vs EMA20 (allowed down to -{p['cross_tol']}% = about to cross)")
        ok_age = age <= p['cross_max_age']
        when = f"{d.index[cross_idx].date()} ({age} bars ago)" if cross_idx is not None else "not yet, EMA8 is just below EMA20"
        log("   Near the crossover", ok_age, f"crossover: {when}; max allowed age {p['cross_max_age']} bars")
        if not (ok_gap and ok_age):
            all_ok = False
            if not collect: return None

    # ---- 4. EMA20 curvature (bottoming and turning up) ----
    lb = p['curve_lookback']
    ok_ema, det = ema_curve_ok(d['EMA20'].iloc[max(0, idx - lb):idx + 1], p['ema_mode'], lookback=lb)
    log("3. EMA20 curvature", ok_ema, det)
    ok_rise = bool(e20[idx] > e20[idx - 3])
    log("   EMA20 turning in setup direction", ok_rise, f"EMA20 {sg * e20[idx - 3]:.1f} → {sg * e20[idx]:.1f} over 3 bars")
    ok_close = bool(close > e20[idx] - close_slack / 100 * abs(e20[idx]))
    log(f"   Close {w_above} EMA20" + (f" (±{close_slack}% slack)" if close_slack else ""), ok_close,
        f"Close {sg * close:.2f} vs EMA20 {sg * e20[idx]:.2f}")
    if not (ok_ema and ok_rise and ok_close):
        all_ok = False
        if not collect: return None

    return {'sweep_idx': sweep_idx, 'level_nm': level_nm, 'sweep_day': sweep_day,
            'cross_idx': cross_idx, 'all_ok': all_ok}

def evaluate_flag_day(ticker, d, idx, side, p, trace=None):
    sg = 1 if side == "Bullish" else -1
    names = LEVEL_NAMES[side]
    w_above = "above" if sg == 1 else "below"
    w_edge = "low" if sg == 1 else "high"

    def log(name, ok, detail=""):
        if trace is not None:
            trace.append({"Check": name, "Result": "✅ Pass" if ok else "❌ Fail", "Detail": detail})
        return ok

    if idx < 60:
        log("Enough history", False, f"only {idx} bars before this date")
        return None

    ctx = _front_checks(d, idx, p, side, log, trace is not None, p['flag_min'])
    if ctx is None:
        return None
    sweep_idx, level_nm, sweep_day = ctx['sweep_idx'], ctx['level_nm'], ctx['sweep_day']
    cross_idx, all_ok = ctx['cross_idx'], ctx['all_ok']
    e8, e20 = d['EMA8'].values, d['EMA20'].values
    close = d['Close'].iloc[idx]

    # ---- 5. Flag: try every length, keep the longest one that passes everything ----
    tries = []
    for L in range(p['flag_min'], p['flag_max'] + 1):
        s = idx - L + 1
        if s <= sweep_idx:
            break
        fw = d.iloc[s:idx + 1]
        fh, fl = fw['High'].max(), fw['Low'].min()
        pole_low = d['Low'].iloc[sweep_idx:s].min()
        pole_h = fh - pole_low
        pole_pct = pole_h / abs(pole_low) * 100
        rng_pct = (fh - fl) / abs(close) * 100
        pc = d['Close'].iloc[sweep_idx:s].values
        path = np.abs(np.diff(pc)).sum()
        eff = (pc[-1] - pc[0]) / path if path > 0 else 0.0     # 1.0 = straight line up, ~0.2 = choppy
        pole_speed = (pc[-1] - pc[0]) / max(len(pc) - 1, 1)                 # price gained per bar in the pole
        flag_speed = (close - d['Close'].iloc[s - 1]) / L                    # price gained per bar inside the flag
        stalled = pole_speed > 0 and flag_speed <= p['flag_speed_max'] * pole_speed
        holds = bool((fw['Low'] >= fw['EMA20'] - 0.005 * fw['EMA20'].abs()).all())
        near = min(abs(fl - e8[idx]) / abs(e8[idx]), abs(fl - e20[idx]) / abs(e20[idx])) * 100
        checks = [
            (f"Pole (sweep {w_edge} → flag top)", pole_pct >= p['pole_min'],
             f"{pole_pct:.1f}% move (need ≥ {p['pole_min']}%)"),
            ("Pole is a clean impulse", eff >= p['pole_eff'],
             f"directional efficiency {eff:.2f} (need ≥ {p['pole_eff']}; 1.0 = straight line, ~0.2 = choppy)"),
            ("Flag has stalled (not still rallying)", stalled,
             f"flag advances {flag_speed / pole_speed * 100 if pole_speed > 0 else 0:.0f}% as fast per bar as the pole "
             f"(need ≤ {int(p['flag_speed_max'] * 100)}%)"),
            ("Flag is tight", rng_pct <= p['flag_max_range'],
             f"{rng_pct:.1f}% range (need ≤ {p['flag_max_range']}%)"),
            ("Flag small vs pole", pole_h > 0 and (fh - fl) <= p['flag_retrace'] * pole_h,
             f"flag is {(fh - fl) / pole_h * 100 if pole_h > 0 else 0:.0f}% of the pole (need ≤ {int(p['flag_retrace'] * 100)}%)"),
            (f"Flag holds {w_above} EMA20", holds, "no flag bar closed through EMA20 (0.5% slack)" if holds else "a flag bar broke EMA20"),
            ("Flag is near EMA8/EMA20", near <= p['near_max'],
             f"flag {w_edge} is {near:.1f}% from the nearest EMA (need ≤ {p['near_max']}%)"),
        ]
        tries.append({'L': L, 'ok': all(c[1] for c in checks), 'score': sum(c[1] for c in checks),
                      'checks': checks, 'fh': fh, 'fl': fl, 'pole_pct': pole_pct})

    if not tries:
        log("4. Flag structure", False, "no room for a flag between the sweep and today")
        return None
    valid = [t for t in tries if t['ok']]
    chosen = max(valid, key=lambda t: t['L']) if valid else max(tries, key=lambda t: (t['score'], t['L']))
    for k, (nm, ok, det) in enumerate(chosen['checks']):
        log(("4. " if k == 0 else "   ") + nm, ok, det + (f" [flag length {chosen['L']} bars]" if k == 0 else ""))

    if not (all_ok and valid):
        return None

    return {
        "Pattern": "Flag",
        "Stock Symbol": ticker.replace('.NS', ''),
        "Trigger Date": d.index[idx].strftime('%Y-%m-%d'),
        "HTF Swept": names[level_nm],
        "Sweep Date": sweep_day.strftime('%Y-%m-%d'),
        "EMA8/20 Cross": d.index[cross_idx].strftime('%Y-%m-%d') if cross_idx is not None else "about to cross",
        "Flag Bars": chosen['L'],
        "Pole %": round(chosen['pole_pct'], 1),
        "Break Level (₹)": round(sg * chosen['fh'], 2),
        "Flag Stop (₹)": round(sg * chosen['fl'], 2),
        "EMA8 (₹)": round(sg * e8[idx], 2),
        "EMA20 (₹)": round(sg * e20[idx], 2),
        "Close (₹)": round(sg * close, 2),
    }

# ==========================================
# ENGINE 3: FLAT BASE ON EMA20 (no significant pole)
# Sequence: 1) HTF liquidity sweep -> 2) EMA8/EMA20 crossover (or about to cross), EMA20 turning up
#           3) price coils in a tight, flag-like base hugging EMA20/EMA8, just above the crossover.
# Same front half as the flag pattern, but the run-up from the sweep low is small.
# ==========================================
def evaluate_base_day(ticker, d, idx, side, p, trace=None):
    sg = 1 if side == "Bullish" else -1
    names = LEVEL_NAMES[side]
    w_above = "above" if sg == 1 else "below"
    w_edge = "low" if sg == 1 else "high"

    def log(name, ok, detail=""):
        if trace is not None:
            trace.append({"Check": name, "Result": "✅ Pass" if ok else "❌ Fail", "Detail": detail})
        return ok

    if idx < 60:
        log("Enough history", False, f"only {idx} bars before this date")
        return None

    ctx = _front_checks(d, idx, p, side, log, trace is not None, p['base_min'], close_slack=p['base_slack'])
    if ctx is None:
        return None
    sweep_idx, level_nm, sweep_day = ctx['sweep_idx'], ctx['level_nm'], ctx['sweep_day']
    cross_idx, all_ok = ctx['cross_idx'], ctx['all_ok']
    e8, e20 = d['EMA8'].values, d['EMA20'].values
    close = d['Close'].iloc[idx]

    # ---- EMAs still close together: we are "near the crossover or just above it" ----
    gap = (e8[idx] - e20[idx]) / abs(e20[idx]) * 100
    ok_gap = gap <= p['base_max_gap']
    log("4. EMAs still close together", ok_gap, f"EMA8 is {gap:+.2f}% from EMA20 (need ≤ {p['base_max_gap']}%)")
    if not ok_gap:
        all_ok = False
        if trace is None: return None

    # ---- Base: try every length, keep the longest one that passes everything ----
    slack = p['base_slack'] / 100
    dist_close = (close - e20[idx]) / abs(e20[idx]) * 100
    tries = []
    for L in range(p['base_min'], p['base_max'] + 1):
        s = idx - L + 1
        if s <= sweep_idx:
            break
        bw = d.iloc[s:idx + 1]
        bh, bl = bw['High'].max(), bw['Low'].min()
        rng_pct = (bh - bl) / abs(close) * 100
        pole_low = d['Low'].iloc[sweep_idx:s].min()
        move_pct = (bh - pole_low) / abs(pole_low) * 100
        holds = bool((bw['Close'] >= bw['EMA20'] - slack * bw['EMA20'].abs()).all())
        near = min(abs(bl - e8[idx]) / abs(e8[idx]), abs(bl - e20[idx]) / abs(e20[idx])) * 100
        checks = [
            ("Base is tight", rng_pct <= p['base_max_range'],
             f"{rng_pct:.1f}% range (need ≤ {p['base_max_range']}%)"),
            ("No significant pole", move_pct <= p['base_pole_max'],
             f"only {move_pct:.1f}% from the sweep {w_edge} to the base top (need ≤ {p['base_pole_max']}%; "
             f"more than that is a pole → flag pattern)"),
            (f"Base holds {w_above} EMA20", holds,
             f"no base close was more than {p['base_slack']}% through EMA20 (wicks are allowed)" if holds else "a base bar closed through EMA20"),
            ("Close is just off EMA20", dist_close <= p['base_near'],
             f"close is {sg * dist_close:+.1f}% from EMA20 in the setup direction (need ≤ {p['base_near']}%)"),
            ("Base rests on EMA8/EMA20", near <= p['base_near'],
             f"base {w_edge} is {near:.1f}% from the nearest EMA (need ≤ {p['base_near']}%)"),
        ]
        tries.append({'L': L, 'ok': all(c[1] for c in checks), 'score': sum(c[1] for c in checks),
                      'checks': checks, 'bh': bh, 'bl': bl, 'move': move_pct})

    if not tries:
        log("5. Base structure", False, "no room for a base between the sweep and today")
        return None
    valid = [t for t in tries if t['ok']]
    chosen = max(valid, key=lambda t: t['L']) if valid else max(tries, key=lambda t: (t['score'], t['L']))
    for k, (nm, ok, det) in enumerate(chosen['checks']):
        log(("5. " if k == 0 else "   ") + nm, ok, det + (f" [base length {chosen['L']} bars]" if k == 0 else ""))

    if not (all_ok and valid):
        return None

    return {
        "Pattern": "Flat base",
        "Stock Symbol": ticker.replace('.NS', ''),
        "Trigger Date": d.index[idx].strftime('%Y-%m-%d'),
        "HTF Swept": names[level_nm],
        "Sweep Date": sweep_day.strftime('%Y-%m-%d'),
        "EMA8/20 Cross": d.index[cross_idx].strftime('%Y-%m-%d') if cross_idx is not None else "about to cross",
        "Base Bars": chosen['L'],
        "Move Since Sweep %": round(chosen['move'], 1),
        "Break Level (₹)": round(sg * chosen['bh'], 2),
        "Base Stop (₹)": round(sg * chosen['bl'], 2),
        "EMA8 (₹)": round(sg * e8[idx], 2),
        "EMA20 (₹)": round(sg * e20[idx], 2),
        "Close (₹)": round(sg * close, 2),
    }

PATTERN_FLAG = "Flag after EMA8/20 crossover (new)"
PATTERN_BASE = "Flat base on EMA20, no pole (new)"
PATTERN_DOJI = "Doji rest on EMA20 (original)"
PATTERN_BOTH = "All patterns"

def evaluate_patterns(ticker, d, idx, side, p):
    """Runs the selected pattern(s); returns a list of result dicts."""
    out = []
    flag_hit = False
    if p['pattern'] in (PATTERN_FLAG, PATTERN_BOTH):
        r = evaluate_flag_day(ticker, d, idx, side, p)
        if r:
            out.append(r)
            flag_hit = True
    if p['pattern'] in (PATTERN_BASE, PATTERN_BOTH) and not flag_hit:   # a flag already covers this day
        r = evaluate_base_day(ticker, d, idx, side, p)
        if r: out.append(r)
    if p['pattern'] in (PATTERN_DOJI, PATTERN_BOTH):
        r = evaluate_day(ticker, d, idx, side, p)
        if r: out.append({"Pattern": "Doji rest", **r})
    return out

# ==========================================
# WRAPPER FUNCTIONS (CACHED)
# ==========================================
@st.cache_data(ttl=1800, show_spinner=False)
def get_cached_stock_df(security_id, client_id, access_token):
    return fetch_dhan_data(security_id, client_id, access_token)

def scan_live_setups(ticker, security_id, setup_type, client_id, access_token, p):
    df = get_cached_stock_df(security_id, client_id, access_token)
    if df.empty or len(df) < 200: return []

    cmp = df['Close'].iloc[-1]
    if pd.isna(cmp) or cmp < 100: return []

    d = prepare_frame(df, setup_type)
    return evaluate_patterns(ticker, d, len(d) - 1, setup_type, p)

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
        out.extend(evaluate_patterns(ticker, d, int(idx), setup_type, p))
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
st.sidebar.header("Pattern")
pattern = st.sidebar.selectbox(
    "Pattern to scan for", [PATTERN_FLAG, PATTERN_BASE, PATTERN_DOJI, PATTERN_BOTH], index=0,
    help="Flag: HTF sweep → EMA8 crosses above EMA20 → impulse (pole) → tight flag near EMA8/EMA20 (e.g. TITAN). "
         "Flat base: same sweep and crossover, but no significant pole; price coils tightly on/just above EMA20. "
         "Doji: your original setup with a doji resting on the EMA20. "
         "All patterns: runs all three (a flag match on a day suppresses the flat-base match for that day).")

st.sidebar.divider()
st.sidebar.header("Filter Settings")
st.sidebar.caption("Defaults are tuned to also catch early-reversal setups like COLPAL. "
                   "Original values are noted on each control.")

ema_mode = st.sidebar.selectbox(
    "EMA20 curvature filter",
    ["Relaxed (early turn)", "Strict (original)", "Off"], index=0,
    help="Strict needs a rounded EMA20 bottom (doji pattern: low 4-16 bars back). "
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

with st.sidebar.expander("Sweep & crossover (flag + flat base)"):
    flag_sweep_window = st.slider("Sweep must be within last N bars", 20, 120, 60)
    need_downtrend = st.checkbox("Require a downtrend (falling EMA20) into the sweep", value=True)
    cross_tol = st.number_input("EMA8 may still be this % below EMA20 (about to cross)", value=0.3, step=0.1, min_value=0.0)
    cross_max_age = st.slider("Crossover no older than N bars", 3, 80, 30,
                              help="Keeps the setup close to the crossover point.")
    curve_lookback = st.slider("EMA20 curvature window (bars)", 20, 60, 40)

with st.sidebar.expander("Flag pattern settings"):
    flag_min, flag_max = st.slider("Flag length (bars)", 3, 20, (4, 12))
    pole_min = st.number_input("Min pole (sweep low → flag top) %", value=7.0, step=0.5)
    pole_eff = st.slider("Pole cleanliness (0 = any, 1 = straight line)", 0.0, 1.0, 0.40, 0.05,
                         help="Net move / total up-and-down travel of the closes in the pole. "
                              "Filters out choppy, sideways drifts that happen to end higher.")
    flag_max_range = st.number_input("Max flag range % of price", value=5.0, step=0.5)
    flag_retrace = st.slider("Flag range as % of pole (max)", 10, 100, 40) / 100
    flag_speed_max = st.slider("Flag may advance at most this % as fast as the pole", 0, 100, 40,
                               help="Stops the tail of a still-running rally being mistaken for a flag.") / 100
    near_max = st.number_input("Flag low max distance from nearest EMA8/EMA20 %", value=3.0, step=0.5)

with st.sidebar.expander("Flat base settings (no pole)"):
    base_min, base_max = st.slider("Base length (bars)", 4, 30, (6, 15),
                                   help="Longer than a flag, because there is no pole to make it obvious.")
    base_max_range = st.number_input("Max base range % of price", value=5.0, step=0.5)
    base_pole_max = st.number_input("Max move from sweep low to base top %", value=7.0, step=0.5,
                                    help="Above this the move counts as a pole and belongs to the flag pattern.")
    base_max_gap = st.number_input("Max EMA8 distance above EMA20 %", value=2.0, step=0.5,
                                   help="Keeps the base at the crossover point or just above it.")
    base_near = st.number_input("Max distance of close / base edge from EMA20 %", value=2.5, step=0.5)
    base_slack = st.number_input("Allowed dip through EMA20 %", value=0.5, step=0.25, min_value=0.0)

P = {
    'base_min': base_min,
    'base_max': base_max,
    'base_max_range': base_max_range,
    'base_pole_max': base_pole_max,
    'base_max_gap': base_max_gap,
    'base_near': base_near,
    'base_slack': base_slack,
    'pattern': pattern,
    'flag_sweep_window': flag_sweep_window,
    'need_downtrend': need_downtrend,
    'cross_tol': cross_tol,
    'cross_max_age': cross_max_age,
    'curve_lookback': curve_lookback,
    'flag_min': flag_min,
    'flag_max': flag_max,
    'pole_min': pole_min,
    'pole_eff': pole_eff,
    'flag_speed_max': flag_speed_max,
    'flag_max_range': flag_max_range,
    'flag_retrace': flag_retrace,
    'near_max': near_max,
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
                        results.extend(res)
                    total_processed += 1
                    my_bar.progress(min(total_processed / len(tickers), 1.0))

            time.sleep(0.05)

        my_bar.empty()

        if errors:
            st.caption(f"{errors} symbols were skipped due to errors.")

        if results:
            if mode == "backtest": results.sort(key=lambda x: x['Trigger Date'])
            df_res = pd.DataFrame(results)
            front = [c for c in ['Pattern', 'Stock Symbol', 'Trigger Date'] if c in df_res.columns]
            df_res = df_res[front + [c for c in df_res.columns if c not in front]]
            st.success(f"Found {len(df_res)} {setup_type} Setups!")
            st.dataframe(df_res, use_container_width=True)

            if mode == "backtest":
                csv = df_res.to_csv(index=False).encode('utf-8')
                st.download_button(label="Download Backtest Data", data=csv,
                                   file_name=f"{setup_type}_Backtest.csv", mime="text/csv")
        else:
            st.warning(f"No {setup_type} setups found in the specified criteria.")

with bullish_tab:
    st.markdown("**Flag pattern:** HTF low sweep → EMA8 crosses above EMA20 (EMA20 turning up) → impulse → tight flag resting near EMA8/EMA20, at or above the crossover.  \n"
                "**Flat base pattern:** same sweep and crossover, but no significant pole; price coils tightly on or just above EMA20 near the crossover.  \n"
                "**Doji pattern:** macro downtrend, untested HTF low sweep, daily MSS, breakout above EMA20, then a doji resting on the EMA.")
    st.caption(f"Active pattern: {pattern}")
    if st.button("Run Live Bullish Screener"): execute_scan("Bullish", "live")

    st.divider()
    st.markdown("#### Backtest Custom Date Range (Bullish)")
    col1, col2 = st.columns(2)
    with col1: start_b = st.date_input("From Date (Bullish)", datetime.today() - timedelta(days=30))
    with col2: end_b = st.date_input("To Date (Bullish)", datetime.today())
    if st.button("Run Bullish Backtester"): execute_scan("Bullish", "backtest", start_b, end_b)

with bearish_tab:
    st.markdown("Mirror image of the bullish setups: HTF **high** sweep → EMA8 crosses **below** EMA20 → impulse down → tight bear flag under EMA8/EMA20.")
    st.caption(f"Active pattern: {pattern}")
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
                    st.caption(f"EMA8 {sg * d['EMA8'].iloc[pos]:.2f}")
                    runs = []
                    if pattern in (PATTERN_FLAG, PATTERN_BOTH): runs.append(("Flag after EMA8/20 crossover", evaluate_flag_day))
                    if pattern in (PATTERN_BASE, PATTERN_BOTH): runs.append(("Flat base on EMA20 (no pole)", evaluate_base_day))
                    if pattern in (PATTERN_DOJI, PATTERN_BOTH): runs.append(("Doji rest on EMA20", evaluate_day))
                    for title, fn in runs:
                        st.markdown(f"##### {title}")
                        trace = []
                        res = fn(diag_sym, d, pos, diag_side, P, trace)
                        st.dataframe(pd.DataFrame(trace), use_container_width=True, hide_index=True)
                        if res:
                            st.success("This stock WOULD be listed with the current settings.")
                            st.dataframe(pd.DataFrame([res]), use_container_width=True, hide_index=True)
                        else:
                            st.warning("This stock would NOT be listed. See the ❌ rows above. "
                                       "Loosen the matching setting in the sidebar and run again.")
