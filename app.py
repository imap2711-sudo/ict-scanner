"""
Nifty 500 intraday strategy scanner + backtester (Streamlit)

Strategy (long shown; short is the exact mirror):
 1. Previous-week LOW (or HIGH) is swept on the day (wick through the level,
    15m candle closes back inside).
 2. After the sweep, nearest UNTESTED 75m swing high (low for shorts) = MSS line.
 3. A 75m displacement candle CLOSES above (below) the MSS line - same day as sweep.
 4. On 15m, find a fresh demand zone (supply zone) in the vicinity of the MSS line.
 5. Entry at zone PROXIMAL, SL below DISTAL, target = nearest untested 15m swing point.
 6. Trade only if RR >= minimum (default 1:1).
 7. Position size = risk per trade (default Rs 500) / (entry - SL).

Data: Yahoo Finance via yfinance (15m history is limited to ~60 days).
"""
from __future__ import annotations

import io
from datetime import date, timedelta
from types import SimpleNamespace

import numpy as np
import pandas as pd
import requests
import streamlit as st
import yfinance as yf
from numpy.lib.stride_tricks import sliding_window_view as swv

IST = "Asia/Kolkata"
MIN_NS = 60 * 10**9
MIN15 = 15 * MIN_NS
BAR75 = 75 * MIN_NS

FALLBACK = [
    "RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "SBIN", "BHARTIARTL", "ITC", "LT",
    "AXISBANK", "KOTAKBANK", "HINDUNILVR", "BAJFINANCE", "MARUTI", "SUNPHARMA", "NTPC",
    "POWERGRID", "ONGC", "TITAN", "ULTRACEMCO", "ASIANPAINT", "WIPRO", "HCLTECH", "TECHM",
    "ADANIENT", "ADANIPORTS", "COALINDIA", "JSWSTEEL", "TATASTEEL", "HINDALCO", "BAJAJFINSV",
    "NESTLEIND", "DRREDDY", "CIPLA", "EICHERMOT", "GRASIM", "INDUSINDBK", "M&M", "BPCL", "TRENT",
]


# --------------------------------------------------------------------------- #
# Data
# --------------------------------------------------------------------------- #
@st.cache_data(ttl=86400, show_spinner=False)
def get_nifty500():
    url = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        return [s.strip() + ".NS" for s in df["Symbol"].dropna().astype(str)]
    except Exception:
        return None


@st.cache_data(ttl=900, show_spinner=False)
def download(symbols: tuple, interval: str, period: str, daily: bool = False):
    out = {}
    for i in range(0, len(symbols), 40):
        batch = list(symbols[i:i + 40])
        try:
            raw = yf.download(batch, period=period, interval=interval, group_by="ticker",
                              auto_adjust=False, progress=False, threads=True)
        except Exception:
            continue
        if raw is None or raw.empty:
            continue
        for s in batch:
            try:
                d = raw[s] if isinstance(raw.columns, pd.MultiIndex) else raw
                d = d[["Open", "High", "Low", "Close"]].dropna().copy()
            except Exception:
                continue
            if d.empty:
                continue
            idx = pd.DatetimeIndex(d.index)
            if daily:
                if idx.tz is not None:
                    idx = idx.tz_convert(IST).tz_localize(None)
                d.index = idx.normalize()
            else:
                if idx.tz is None:
                    idx = idx.tz_localize("UTC")
                d.index = idx.tz_convert(IST)
            out[s] = d[~d.index.duplicated(keep="last")].sort_index()
    return out


def ns(idx):
    """DatetimeIndex (tz-aware) -> int64 UTC nanoseconds."""
    return idx.tz_convert("UTC").as_unit("ns").asi8


def to_75m(df15):
    """Per-day 75m candles anchored at 09:15 (5 candles / session). Incomplete bars dropped."""
    parts = []
    for _, g in df15.groupby(df15.index.normalize()):
        r = g.resample("75min", origin="start").agg(
            Open=("Open", "first"), High=("High", "max"), Low=("Low", "min"),
            Close=("Close", "last"), n=("Close", "count"))
        parts.append(r[r["n"] == 5])
    if not parts:
        return pd.DataFrame()
    return pd.concat(parts).drop(columns="n")


def weekly_levels(daily):
    idx = daily.index
    wk = idx - pd.to_timedelta(idx.weekday, unit="D")
    return daily.groupby(wk).agg(H=("High", "max"), L=("Low", "min"))


# --------------------------------------------------------------------------- #
# Strategy engine
# --------------------------------------------------------------------------- #
def swing_high(h, n):
    N = len(h)
    f = np.zeros(N, dtype=bool)
    if N < 2 * n + 1:
        return f
    w = swv(h, 2 * n + 1)
    others = np.delete(w, n, axis=1)
    f[n:N - n] = w[:, n] > others.max(axis=1)
    return f


def _arrays(df, sign):
    o = df["Open"].to_numpy(float) * sign
    c = df["Close"].to_numpy(float) * sign
    if sign == 1:
        h = df["High"].to_numpy(float)
        l = df["Low"].to_numpy(float)
    else:  # mirror: shorts become longs on negated prices
        h = -df["Low"].to_numpy(float)
        l = -df["High"].to_numpy(float)
    body = (pd.Series(np.abs(c - o)).rolling(10, min_periods=3).mean()
            .shift(1).fillna(0.0).to_numpy())
    return o, h, l, c, body


def make_side(df15, df75, sign, p):
    S = SimpleNamespace(sign=sign)
    S.o15, S.h15, S.l15, S.c15, S.body15 = _arrays(df15, sign)
    S.o75, S.h75, S.l75, S.c75, S.body75 = _arrays(df75, sign)
    S.t15, S.d15 = ns(df15.index), ns(df15.index.normalize())
    S.t75, S.d75 = ns(df75.index), ns(df75.index.normalize())
    S.sh15 = swing_high(S.h15, p["n15"])
    S.sh75 = swing_high(S.h75, p["n75"])
    return S


def nearest_target(S, upto, fill, p):
    """Nearest untested 15m swing high above `fill`, using candles before index `upto`."""
    h, best = S.h15, None
    for j in range(max(0, upto - p["tlook"]), upto - p["n15"]):
        if S.sh15[j] and h[j] > fill and h[j + 1:upto].max() < h[j]:
            if best is None or h[j] < best:
                best = h[j]
    return best


def find_trade(S, day_ns, level, p):
    """Look for one long setup (in sign-space) on a given day. Returns dict or None."""
    t, o, h, l, c = S.t15, S.o15, S.h15, S.l15, S.c15
    n15 = len(t)
    i0 = int(np.searchsorted(S.d15, day_ns, "left"))
    i1 = int(np.searchsorted(S.d15, day_ns, "right"))
    j0 = int(np.searchsorted(S.d75, day_ns, "left"))
    j1 = int(np.searchsorted(S.d75, day_ns, "right"))
    if i1 - i0 < 8 or j1 - j0 < 2:
        return None

    # 1) liquidity sweep of previous-week level (same day)
    sw = None
    for i in range(i0, i1):
        if l[i] < level and (c[i] > level or not p["reject"]):
            sw = i
            break
    if sw is None:
        return None

    # 2) MSS line = nearest untested 75m swing high above price, known at sweep time
    k = int(np.searchsorted(S.t75, t[sw], "right")) - 1
    if k < j0 or k >= j1:
        return None
    ref = c[sw]
    mss = None
    for j in range(max(0, k - p["lb75"]), k - p["n75"]):
        if S.sh75[j] and S.h75[j] > ref:
            lv = S.h75[j]
            a = int(np.searchsorted(t, S.t75[j] + BAR75, "left"))
            if a <= sw and h[a:sw + 1].max() < lv and (mss is None or lv < mss):
                mss = lv
    if mss is None:
        return None

    # 3) 75m displacement candle closing beyond MSS line (same day)
    disp = None
    for m in range(k, j1):
        body = S.c75[m] - S.o75[m]
        if S.c75[m] > mss and body > 0 and body >= p["disp"] * S.body75[m]:
            disp = m
            break
    if disp is None:
        return None
    tm = S.t75[disp] + BAR75
    e = int(np.searchsorted(t, tm, "left"))      # first 15m candle after the 75m close
    if e >= i1 or e <= i0:
        return None

    # 4) fresh 15m demand zone near the MSS line
    v = p["vic"] / 100.0
    band_lo, band_hi = mss - abs(mss) * v, mss + abs(mss) * v
    zone = None
    for i in range(e - 1, max(1, e - p["zlook"]) - 1, -1):
        body = c[i] - o[i]
        if body <= 0 or body < p["imp"] * S.body15[i]:
            continue
        base, b = [], i - 1
        while b >= 0 and len(base) < 3 and abs(c[b] - o[b]) <= p["base"] * body:
            base.append(b)
            b -= 1
        if not base or c[i] <= max(h[x] for x in base):
            continue
        prox = max(max(o[x], c[x]) for x in base)
        dist = min(l[x] for x in base)
        if i + 1 <= e - 1 and l[i + 1:e].min() <= prox:   # already tested
            continue
        if prox >= c[e - 1]:                               # must sit below price
            continue
        if dist <= band_hi and prox >= band_lo:
            score = abs(prox - mss)
            if zone is None or score < zone[0]:
                zone = (score, prox, dist)
    if zone is None:
        return None
    _, prox, dist = zone
    sl = dist - abs(dist) * p["buf"] / 100.0

    # 5) entry on proximal touch
    cutoff = day_ns + p["cutoff"] * MIN_NS
    entry_i = fill = None
    for i in range(e, i1):
        if t[i] > cutoff:
            break
        if l[i] <= prox:
            entry_i, fill = i, min(o[i], prox)
            break
    live = (i1 == n15) and (t[i1 - 1] < day_ns + 915 * MIN_NS)   # day still in progress
    s = S.sign
    rec = dict(side="LONG" if s == 1 else "SHORT", sweep_ns=t[sw], level=s * level,
               mss=s * mss, mss_ns=tm, prox=s * prox, dist=s * dist)

    if entry_i is None:                                   # setup valid, limit order waiting
        if not (live and t[i1 - 1] < cutoff):
            return None
        tgt = nearest_target(S, i1, prox, p)
        if tgt is None or prox <= sl:
            return None
        rr = (tgt - prox) / (prox - sl)
        if rr < p["min_rr"]:
            return None
        rec.update(entry_ns=None, entry=s * prox, sl=s * sl, target=s * tgt, rr=rr, qty=None,
                   exit_ns=None, exit=None, status="PENDING", pnl=None, r=None, risk=None)
        return rec

    if fill <= sl:
        return None
    tgt = nearest_target(S, entry_i, fill, p)
    if tgt is None:
        return None
    rps = fill - sl
    rr = (tgt - fill) / rps
    if rr < p["min_rr"]:                                  # 6) RR filter
        return None
    qty = int(p["risk"] // rps)
    if qty < 1:
        return None

    # exits (SL assumed first when SL and target are both inside one candle)
    exit_i = xp = reason = None
    if l[entry_i] <= sl:
        exit_i, xp, reason = entry_i, sl, "SL"
    else:
        for i in range(entry_i + 1, i1):
            if l[i] <= sl:
                exit_i, xp, reason = i, min(sl, o[i]), "SL"
                break
            if h[i] >= tgt:
                exit_i, xp, reason = i, max(tgt, o[i]), "TARGET"
                break
    if exit_i is None:
        exit_i, xp, reason = i1 - 1, c[i1 - 1], ("OPEN" if live else "EOD")

    gross = qty * (xp - fill)
    costs = qty * (abs(fill) + abs(xp)) * p["cost"] / 100.0
    rec.update(entry_ns=t[entry_i], entry=s * fill, sl=s * sl, target=s * tgt, rr=rr, qty=qty,
               exit_ns=t[exit_i], exit=s * xp, status=reason, pnl=gross - costs,
               r=(xp - fill) / rps, risk=qty * rps)
    return rec


# --------------------------------------------------------------------------- #
# Backtest orchestration
# --------------------------------------------------------------------------- #
def fmt_ns(x):
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return "-"
    return pd.Timestamp(int(x), tz="UTC").tz_convert(IST).strftime("%d-%b-%Y %H:%M")


def naive_dt(x):
    if x is None:
        return pd.NaT
    return pd.Timestamp(int(x), tz="UTC").tz_convert(IST).tz_localize(None)


def backtest(d15, dd, symbols, start, end, p, progress=None):
    rows = []
    total = max(len(symbols), 1)
    for n, sym in enumerate(symbols):
        if progress is not None:
            progress.progress((n + 1) / total, text=f"Scanning {sym}  ({n + 1}/{total})")
        df15, daily = d15.get(sym), dd.get(sym)
        if df15 is None or daily is None or len(df15) < 100:
            continue
        df75 = to_75m(df15)
        if len(df75) < 20:
            continue
        wk = weekly_levels(daily)
        sides = (make_side(df15, df75, 1, p), make_side(df15, df75, -1, p))
        for day in pd.DatetimeIndex(df15.index.normalize().unique()):
            dn = day.tz_localize(None)
            if dn < start or dn > end:
                continue
            prev = dn - pd.Timedelta(days=dn.weekday() + 7)       # Monday of previous week
            if prev not in wk.index:
                continue
            pwh, pwl = float(wk.at[prev, "H"]), float(wk.at[prev, "L"])
            cands = []
            for S, level in ((sides[0], pwl), (sides[1], -pwh)):
                r = find_trade(S, day.value, level, p)
                if r:
                    r["symbol"] = sym.replace(".NS", "")
                    r["date"] = dn
                    cands.append(r)
            if cands:   # one trade per stock per day: earliest entry wins
                cands.sort(key=lambda r: r["entry_ns"] if r["entry_ns"] is not None else 10**30)
                rows.append(cands[0])
    return rows


def build_df(rows):
    if not rows:
        return pd.DataFrame()
    recs = []
    for r in rows:
        recs.append({
            "Symbol": r["symbol"], "Side": r["side"],
            "Date": r["date"].strftime("%d-%b-%Y"),
            "Entry Time": fmt_ns(r["entry_ns"]) if r["entry_ns"] else "Pending",
            "Entry": round(r["entry"], 2), "SL": round(r["sl"], 2), "Target": round(r["target"], 2),
            "RR": round(r["rr"], 2), "Qty": r["qty"],
            "Exit Time": fmt_ns(r["exit_ns"]) if r["exit_ns"] else "-",
            "Exit": round(r["exit"], 2) if r["exit"] is not None else None,
            "Result": r["status"],
            "Risk (Rs)": round(r["risk"], 2) if r["risk"] is not None else None,
            "P&L (Rs)": round(r["pnl"], 2) if r["pnl"] is not None else None,
            "R": round(r["r"], 2) if r["r"] is not None else None,
            "Sweep Time": fmt_ns(r["sweep_ns"]), "Swept Level (PWH/PWL)": round(r["level"], 2),
            "MSS Line (75m)": round(r["mss"], 2), "MSS Close Time (75m)": fmt_ns(r["mss_ns"]),
            "Zone Proximal": round(r["prox"], 2), "Zone Distal": round(r["dist"], 2),
            "_entry_dt": naive_dt(r["entry_ns"]), "_exit_dt": naive_dt(r["exit_ns"]),
        })
    df = pd.DataFrame(recs)
    return df.sort_values("_entry_dt", na_position="last").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# UI
# --------------------------------------------------------------------------- #
MAIN_COLS = ["Date", "Symbol", "Side", "Entry Time", "Entry", "SL", "Target", "RR", "Qty",
             "Exit Time", "Exit", "Result", "P&L (Rs)"]


def show_results(df, p):
    if df.empty:
        st.info("No setups matched the rules in this period. Try a longer period, more symbols, "
                "or loosen the advanced parameters.")
        return
    closed = df[df["Result"].isin(["TARGET", "SL", "EOD"])].sort_values("_exit_dt")
    live = df[df["Result"].isin(["OPEN", "PENDING"])]

    t1, t2, t3, t4 = st.tabs(["Summary", "Trade log", "Live / pending setups", "Rules & assumptions"])

    with t1:
        if closed.empty:
            st.info("No closed trades in this period.")
        else:
            pnl = closed["P&L (Rs)"]
            wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
            cum = pnl.cumsum()
            max_dd = (cum - np.maximum(cum.cummax(), 0)).min()
            pf = wins.sum() / abs(losses.sum()) if losses.sum() != 0 else float("inf")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Net P&L (Rs)", f"{pnl.sum():,.0f}")
            c2.metric("Trades", len(closed))
            c3.metric("Win rate", f"{len(wins) / len(closed) * 100:.0f}%")
            c4.metric("Profit factor", "inf" if pf == float("inf") else f"{pf:.2f}")
            c5, c6, c7, c8 = st.columns(4)
            c5.metric("Avg win (Rs)", f"{wins.mean():,.0f}" if len(wins) else "0")
            c6.metric("Avg loss (Rs)", f"{losses.mean():,.0f}" if len(losses) else "0")
            c7.metric("Max drawdown (Rs)", f"{max_dd:,.0f}")
            c8.metric("Expectancy / trade (Rs)", f"{pnl.mean():,.0f}")
            st.caption(f"Risk per trade Rs {p['risk']:,.0f}. Targets: {(closed['Result'] == 'TARGET').sum()}, "
                       f"stop-losses: {(closed['Result'] == 'SL').sum()}, "
                       f"end-of-day exits: {(closed['Result'] == 'EOD').sum()}.")
            st.subheader("Equity curve")
            st.line_chart(pd.DataFrame({"Cumulative P&L (Rs)": cum.values},
                                       index=closed["_exit_dt"].values))
            st.subheader("Daily P&L")
            daily = closed.groupby(closed["_exit_dt"].dt.normalize())["P&L (Rs)"].sum()
            st.bar_chart(daily)

    with t2:
        show_all = st.checkbox("Show setup details (sweep time, MSS line, zone)", value=False)
        cols = [c for c in df.columns if not c.startswith("_")] if show_all else MAIN_COLS
        view = closed[cols] if not closed.empty else pd.DataFrame(columns=cols)
        st.dataframe(view, hide_index=True)
        st.caption("Entry/Exit Time = start time of the 15m candle in which the fill happened (IST).")
        st.download_button("Download trade log (CSV)",
                           df[[c for c in df.columns if not c.startswith("_")]].to_csv(index=False),
                           "nifty500_backtest_trades.csv", "text/csv")

    with t3:
        if live.empty:
            st.write("No pending or open setups in the latest session of the downloaded data.")
        else:
            st.write("PENDING = valid setup, limit order at zone proximal not yet touched. "
                     "OPEN = entered, still running at the last available candle.")
            st.dataframe(live[[c for c in df.columns if not c.startswith("_")]], hide_index=True)

    with t4:
        st.markdown("""
**Rules implemented**
1. Previous calendar week's high/low (from daily data). Sweep = a 15m candle wicks through the level and closes back inside (toggle in advanced settings).
2. After the sweep, the nearest untested 75m swing high (long) / swing low (short) formed *before* the sweep is the MSS line.
3. A 75m candle must close beyond the MSS line, with a body at least *k* x the average of the prior 10 candles. Sweep and this close must be on the **same day**.
4. On 15m: a fresh (untested) demand/supply zone = 1-3 small base candles followed by an impulse candle that closes out of the base. It must overlap a band around the MSS line.
5. Entry = limit at zone proximal, SL = just beyond distal (small buffer), target = nearest untested 15m swing point.
6. Trade skipped if RR < minimum. Quantity = risk / (entry - SL), rounded down.
7. One trade per stock per day, last entry time configurable, open positions squared off at the session close.

**Assumptions to be aware of**
- If SL and target both fall inside one 15m candle, the SL is assumed to hit first (conservative). Target is only checked from the candle after entry.
- 75m candles are built from 15m data, anchored at 09:15 (5 per session).
- Yahoo Finance provides only ~60 days of 15m data, so the backtest window is limited to about two months. For longer tests, plug in a broker data feed (Zerodha, Dhan, Upstox).
- Swing points, zones and displacement have no single universal definition; the tunable parameters are in the sidebar.
- Educational tool, not investment advice.
""")


def main():
    st.set_page_config(page_title="Nifty 500 Intraday Sweep-MSS Backtester", layout="wide")
    st.title("Nifty 500 intraday: liquidity sweep -> 75m MSS -> 15m zone")
    st.caption("app.py version 3 loaded. On a phone, open the sidebar with the > arrow at the top-left.")

    sb = st.sidebar
    sb.header("Universe")
    uni = sb.radio("Stock list", ["Nifty 500 (NSE list)", "Custom list"])
    if uni.startswith("Nifty"):
        syms = get_nifty500()
        if syms is None:
            sb.warning("Could not fetch the NSE Nifty 500 list. Using a 40-stock fallback; "
                       "use 'Custom list' to paste your own symbols.")
            syms = [s + ".NS" for s in FALLBACK]
        top_n = sb.slider("Scan first N symbols", 10, len(syms), min(100, len(syms)))
        syms = syms[:top_n]
    else:
        txt = sb.text_area("Symbols (comma or newline separated, NSE tickers)",
                           "RELIANCE, TCS, HDFCBANK, ICICIBANK, INFY, SBIN")
        syms = [s.strip().upper() for s in txt.replace("\n", ",").split(",") if s.strip()]
        syms = [s if "." in s else s + ".NS" for s in syms]

    sb.header("Backtest")
    today = date.today()
    rng = sb.date_input("Period", (today - timedelta(days=30), today),
                        min_value=today - timedelta(days=59), max_value=today)
    risk = sb.number_input("Risk per trade (Rs)", 100.0, 100000.0, 500.0, 100.0)
    min_rr = sb.number_input("Minimum RR", 0.5, 10.0, 1.0, 0.25)

    with sb.expander("Advanced parameters"):
        n75 = st.slider("75m swing strength (bars each side)", 1, 4, 2)
        n15 = st.slider("15m swing strength (bars each side)", 1, 5, 2)
        disp = st.slider("Displacement body vs avg body (x)", 0.5, 3.0, 1.0, 0.1)
        imp = st.slider("Zone impulse body vs avg body (x)", 0.5, 4.0, 1.5, 0.1)
        base = st.slider("Zone base candle max body vs impulse", 0.2, 1.0, 0.6, 0.05)
        vic = st.slider("Zone vicinity to MSS line (%)", 0.1, 2.0, 0.5, 0.1)
        buf = st.slider("SL buffer beyond distal (%)", 0.0, 0.5, 0.05, 0.01)
        cutoff_h = st.time_input("Last entry candle", value=pd.Timestamp("14:30").time())
        reject = st.checkbox("Sweep must close back inside the level", True)
        cost = st.number_input("Costs (% of turnover, both legs combined)", 0.0, 1.0, 0.0, 0.01)
        zlook = st.slider("Zone lookback (15m candles)", 20, 300, 100)

    p = dict(risk=risk, min_rr=min_rr, n75=n75, n15=n15, disp=disp, imp=imp, base=base, vic=vic,
             buf=buf, cutoff=cutoff_h.hour * 60 + cutoff_h.minute, reject=reject, cost=cost,
             zlook=zlook, lb75=40, tlook=500)

    if sb.button("Run backtest", type="primary"):
        if not isinstance(rng, (list, tuple)) or len(rng) != 2:
            st.error("Please select both a start and an end date.")
            st.stop()
        start, end = pd.Timestamp(rng[0]), pd.Timestamp(rng[1])
        with st.spinner("Downloading 15m and daily data from Yahoo Finance..."):
            d15 = download(tuple(syms), "15m", "60d")
            dd = download(tuple(syms), "1d", "6mo", True)
        if not d15 or not dd:
            st.error("No data could be downloaded. Try again in a few minutes or reduce the symbol count.")
            st.stop()
        bar = st.progress(0.0)
        rows = backtest(d15, dd, syms, start, end, p, bar)
        bar.empty()
        st.session_state["res"] = (build_df(rows), p, len(d15), start, end)

    if "res" in st.session_state:
        df, p_used, n_loaded, s0, e0 = st.session_state["res"]
        st.caption(f"{n_loaded} symbols with data | {s0:%d-%b-%Y} to {e0:%d-%b-%Y}")
        show_results(df, p_used)
    else:
        st.info("Choose your universe and period in the sidebar, then click **Run backtest**.")


# Call main() unconditionally: Streamlit re-runs this script on every interaction, and
# some hosting setups do not set __name__ == "__main__", which leaves a blank page.
try:
    main()
except Exception as exc:  # show the error on screen instead of a blank page
    st.error("The app hit an error while loading.")
    st.exception(exc)
