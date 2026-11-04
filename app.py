import yfinance as yf
import pandas as pd
import numpy as np
import requests
import io
import concurrent.futures
from datetime import datetime, date
import warnings

warnings.filterwarnings('ignore')

# -------------------------------------------------------------
# 1. UNIVERSE FETCH (NIFTY 500 EQUITIES)
# -------------------------------------------------------------
def get_nifty500_symbols():
    url = "https://niftyindices.com/IndexConstituent/ind_nifty500list.csv"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        df = pd.read_csv(io.StringIO(res.text))
        return [str(sym).strip() + '.NS' for sym in df['Symbol']]
    except Exception:
        # Fallback list of top liquid symbols if offline
        return ['RELIANCE.NS', 'TCS.NS', 'HDFCBANK.NS', 'ICICIBANK.NS', 'BHARTIARTL.NS', 
                'SBIN.NS', 'INFY.NS', 'LT.NS', 'TATAMOTORS.NS', 'DIXON.NS', 'PERSISTENT.NS']

# -------------------------------------------------------------
# 2. DATA FETCHER & TIMEFRAME RESAMPLING
# -------------------------------------------------------------
def fetch_and_resample(ticker):
    try:
        t = yf.Ticker(ticker)
        df_d = t.history(period="3y", interval="1d", auto_adjust=False)
        if df_d.empty or len(df_d) < 100:
            return None, None, None
            
        df_d.index = df_d.index.tz_localize(None)
        
        # Resample Daily to Weekly (ITF)
        df_w = df_d.resample('W-FRI').agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).dropna()
        
        # Resample Daily to Monthly (HTF)
        df_m = df_d.resample('ME').agg({
            'Open': 'first', 'High': 'max', 'Low': 'min', 'Close': 'last', 'Volume': 'sum'
        }).dropna()
        
        return df_d, df_w, df_m
    except Exception:
        return None, None, None

# -------------------------------------------------------------
# 3. MIT STRATEGY ENGINE
# -------------------------------------------------------------
def scan_mit_trades_october(ticker, df_d, df_w, df_m, risk_per_trade=5000):
    try:
        cmp = float(df_d['Close'].iloc[-1])
        if cmp < 100:
            return []

        # --- A. MONTHLY CURVE ANALYSIS (HTF) ---
        # Find 12-month high and low to evaluate if price is in the lower 50% (Low on Curve)
        m_recent = df_m.iloc[-12:]
        if len(m_recent) < 6:
            return []
        m_high = m_recent['High'].max()
        m_low = m_recent['Low'].min()
        curve_range = m_high - m_low
        if curve_range <= 0:
            return []

        # --- B. WEEKLY TREND ANALYSIS (ITF) ---
        # 20 EMA trend filter on weekly chart
        df_w['EMA20'] = df_w['Close'].ewm(span=20, adjust=False).mean()

        # --- C. DAILY DEMAND ZONE (LTF EXECUTION) ---
        df_d['Range'] = (df_d['High'] - df_d['Low']).replace(0, np.nan)
        df_d['Body'] = abs(df_d['Close'] - df_d['Open'])
        df_d['Body_Ratio'] = df_d['Body'] / df_d['Range']
        df_d['isLegIn'] = df_d['Body_Ratio'] > 0.60
        df_d['isBase'] = df_d['Body_Ratio'] < 0.40
        df_d['isBullish'] = df_d['Close'] > df_d['Open']
        df_d['isLegOut'] = df_d['isBullish'] & (df_d['Body_Ratio'] > 0.60)

        trades = []
        n = len(df_d)

        # Scan for zones formed in the trailing 2 years
        for i in range(4, n - 1):
            if not df_d['isLegOut'].iloc[i]:
                continue

            # Identify 1-base or 2-base DBR / RBR
            is_1base = df_d['isBase'].iloc[i-1] and df_d['isLegIn'].iloc[i-2]
            is_2base = False
            if i >= 5:
                is_2base = df_d['isBase'].iloc[i-1] and df_d['isBase'].iloc[i-2] and df_d['isLegIn'].iloc[i-3]

            if not (is_1base or is_2base):
                continue

            # Zone Boundaries
            if is_1base:
                base_high = df_d['High'].iloc[i-1]
                proximal = max(df_d['Open'].iloc[i-1], df_d['Close'].iloc[i-1])
                distal = df_d['Low'].iloc[i-1]
                base_date = df_d.index[i-1]
                legin_range = df_d['Range'].iloc[i-2]
            else:
                base_high = max(df_d['High'].iloc[i-1], df_d['High'].iloc[i-2])
                proximal = max(df_d['Open'].iloc[i-1], df_d['Close'].iloc[i-1], df_d['Open'].iloc[i-2], df_d['Close'].iloc[i-2])
                distal = min(df_d['Low'].iloc[i-1], df_d['Low'].iloc[i-2])
                base_date = df_d.index[i-1]
                legin_range = df_d['Range'].iloc[i-3]

            first_legout_range = df_d['Range'].iloc[i]
            first_legout_close = df_d['Close'].iloc[i]

            # Quality Check 1: 2x Departure Imbalance
            if legin_range > (0.50 * first_legout_range):
                continue
            # Quality Check 2: 1% Breakout Clearance above base
            if first_legout_close < (base_high * 1.01):
                continue

            # Check Departure Momentum (>= 7% move)
            curr = i
            while curr + 1 < n and df_d['isLegOut'].iloc[curr + 1]:
                curr += 1
            last_legout_idx = curr
            pct_move = ((df_d['Close'].iloc[last_legout_idx] - proximal) / proximal) * 100
            if pct_move < 7.0:
                continue

            # Stop Loss & Risk
            sl_points = proximal - distal
            if sl_points <= 0 or (sl_points / proximal) > 0.035: # Cap wide zones > 3.5%
                continue
            target_price = proximal + (2 * sl_points)
            qty = int(risk_per_trade / sl_points)

            # Check Forward Retest
            is_tested = False
            is_invalidated = False
            entry_idx = None

            for j in range(last_legout_idx + 1, n):
                d_low = df_d['Low'].iloc[j]
                d_close = df_d['Close'].iloc[j]

                if not is_tested:
                    if d_close < distal:
                        is_invalidated = True
                        break
                    if d_low <= (proximal * 1.0025):
                        is_tested = True
                        entry_idx = j
                        break

            # FILTER FOR OCTOBER 2026 ENTRIES ONLY
            if is_tested and not is_invalidated and entry_idx is not None:
                entry_dt = df_d.index[entry_idx]
                if entry_dt.year == 2026 and entry_dt.month == 10:
                    
                    # 1. VERIFY HTF (MONTHLY CURVE) AT TIME OF ENTRY
                    curve_pos = (proximal - m_low) / curve_range
                    if curve_pos > 0.60:  # Must be in lower 60% of macro curve
                        continue

                    # 2. VERIFY ITF (WEEKLY TREND) AT TIME OF ENTRY
                    w_slice = df_w[df_w.index <= entry_dt]
                    if len(w_slice) < 5:
                        continue
                    # Price above or near 20-week EMA
                    weekly_close = w_slice['Close'].iloc[-1]
                    weekly_ema = w_slice['EMA20'].iloc[-1]
                    if weekly_close < (weekly_ema * 0.97): # Reject strong downtrends
                        continue

                    # 3. EVALUATE OUTCOME (Swing holding: up to 30 trading days)
                    outcome = "Pending"
                    exit_date = None
                    pnl = 0.0

                    for k in range(entry_idx, min(entry_idx + 35, n)):
                        bar_high = df_d['High'].iloc[k]
                        bar_low = df_d['Low'].iloc[k]
                        bar_close = df_d['Close'].iloc[k]

                        if bar_low < distal:
                            outcome = "Loss"
                            exit_date = df_d.index[k].strftime('%Y-%m-%d')
                            pnl = -(qty * sl_points)
                            break
                        elif bar_high >= target_price:
                            outcome = "Win (Target 1:2)"
                            exit_date = df_d.index[k].strftime('%Y-%m-%d')
                            pnl = qty * (target_price - proximal)
                            break
                    else:
                        # If still holding after 35 days
                        curr_pnl = qty * (df_d['Close'].iloc[-1] - proximal)
                        outcome = "Holding / Open"
                        exit_date = "Active"
                        pnl = curr_pnl

                    trades.append({
                        "Symbol": ticker.replace('.NS', ''),
                        "Entry Date": entry_dt.strftime('%Y-%m-%d'),
                        "Zone Type": "DBR" if is_1base else "2-Base DBR",
                        "Entry (₹)": round(proximal, 2),
                        "SL (₹)": round(distal, 2),
                        "Target (₹)": round(target_price, 2),
                        "SL %": round((sl_points / proximal) * 100, 2),
                        "Curve Pos": f"{round(curve_pos * 100)}% (Low)" if curve_pos < 0.4 else "Equilibrium",
                        "Outcome": outcome,
                        "Exit Date": exit_date,
                        "P&L (₹)": round(pnl, 2)
                    })

        return trades
    except Exception:
        return []

# -------------------------------------------------------------
# 4. EXECUTION RUNNER
# -------------------------------------------------------------
def run_october_mit_backtest():
    symbols = get_nifty500_symbols()
    print(f"Loaded {len(symbols)} stocks. Starting MIT scan for October 2026...")
    
    all_mit_trades = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        future_map = {}
        for s in symbols:
            future = executor.submit(fetch_and_resample, s)
            future_map[future] = s
            
        for future in concurrent.futures.as_completed(future_map):
            s = future_map[future]
            df_d, df_w, df_m = future.result()
            if df_d is not None:
                res = scan_mit_trades_october(s, df_d, df_w, df_m)
                if res:
                    all_mit_trades.extend(res)
                    print(f" Found {len(res)} MIT trade(s) in {s.replace('.NS', '')}")

    if all_mit_trades:
        df_results = pd.DataFrame(all_mit_trades)
        df_results = df_results.sort_values(by="Entry Date").reset_index(drop=True)
        print("\n================== OCTOBER 2026 MIT RESULTS ==================")
        print(df_results.to_string())
        df_results.to_csv("MIT_October_2026_Trades.csv", index=False)
        print("\nSaved to 'MIT_October_2026_Trades.csv'")
    else:
        print("\nNo high-scoring MIT trades matched the strict curve + trend + zone filters.")

if __name__ == "__main__":
    run_october_mit_backtest()
