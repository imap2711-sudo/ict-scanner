"""Weekly Sweep latest (W-75-15) – Streamlit app (Minal, 3 Nov 2026).
Same rules as the 'Weekly Sweep latest (W-75-15)' tab of the Daily Sweep Latest board (engine w75.py, 30 Oct 2026):
1 Weekly liquidity sweep THIS WEEK: PWL (previous week low) or WSL (weekly swing low, not broken since it formed) – the week's
  low so far goes below the level and the latest 15-min close is back above it. Sweep low = lowest 15-min candle of the week.
2 MSS on 75 min: a completed 75-min candle (09:15 / 10:30 / 11:45 / 13:00 / 14:15) after the sweep-low candle closes above the
  latest 75-min swing high left of the sweep low that is still unbroken. Only the first MSS counts.
3 Demand zone near the MSS line: high-quality 15-min or 5-min DZ formed in the rally sweep low -> MSS candle, untouched till the
  MSS, proximal within +/-2% of the MSS line (nearest). HQ DZ = 1-2 base candles (body < 40%) + bullish leg-out (body > 50%,
  range >= 1.5x largest base, close above base high); zone height >= 0.2%.
Trade (study): entry = DZ proximal on the first retrace after the MSS; SL = DZ distal; target = highest high after the MSS
  before the entry. Before entry: 15-min close below distal, or a candle opening below it -> Cancelled. Lives till week end.
Status: W waiting MSS · N no zone · E waiting entry · O open · T target hit · L SL hit · C cancelled.
Data: Yahoo Finance (daily 2 years, 15-min and 5-min last 60 days). For study, not trading advice.

Run:  pip install streamlit pandas plotly   then   streamlit run app.py
"""
import json, time, datetime as dt, collections, urllib.parse, urllib.request, concurrent.futures as cf
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

BAND = 0.02
UA = {"User-Agent": "Mozilla/5.0"}
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
SYMS = """360ONE AADHARHFC AARTIIND AAVAS ABB ABBOTINDIA ABCAPITAL ABDL ABREL ABSLAMC ACC ACE ACMESOLAR ACUTAAS ADANIENSOL ADANIENT
ADANIGREEN ADANIPORTS ADANIPOWER AEGISLOG AEGISVOPAK AETHER AFCONS AFFLE AIAENG AIIL AJANTPHARM ALKEM AMBER AMBUJACEM ANANDRATHI
ANANTRAJ ANGELONE ANTHEM ANURAS APARINDS APLAPOLLO APOLLOHOSP APOLLOTYRE APTUS ARE&M ASAHIINDIA ASHOKLEY ASIANPAINT ASTERDM ASTRAL
ATGL ATHERENERG ATUL AUBANK AUROPHARMA AVANTIFEED AWL AXISBANK AZAD BAJAJ-AUTO BAJAJFINSV BAJAJHFL BAJAJHLDNG BAJFINANCE
BALKRISIND BALRAMCHIN BANDHANBNK BANKBARODA BANKINDIA BATAINDIA BBOX BDL BEL BELRISE BEML BERGEPAINT BHARATCOAL BHARATFORG BHARTIARTL
BHARTIHEXA BHEL BIOCON BIRET BLS BLUESTARCO BOSCHLTD BPCL BRIGADE BRITANNIA BSE BSOFT CAMS CANBK CANFINHOME CANHLIFE CAPLIPOINT
CARBORUNIV CARTRADE CASTROLIND CCL CDSL CEATLTD CEMPRO CENTRALBK CESC CGCL CGPOWER CHAMBLFERT CHENNPETRO CHOICEIN CHOLAFIN
CHOLAHLDNG CIEINDIA CIPLA CLEAN CLEANMAX CMPDI COALINDIA COCHINSHIP COFORGE COHANCE COLPAL CONCOR CONCORDBIO COROMANDEL CPPLUS
CRAFTSMAN CREDITACC CRISIL CROMPTON CUB CUMMINSIND CUPID CYIENT DABUR DALBHARAT DATAPATTNS DEEPAKFERT DEEPAKNTR DELHIVERY DEVYANI
DIVISLAB DIXON DLF DMART DOMS DRREDDY ECLERX EICHERMOT EIDPARRY EIHOTEL ELECON ELGIEQUIP EMAMILTD EMBASSY EMCURE EMMVEE
ENDURANCE ENGINERSIN ENRIN ESCORTS ETERNAL EXIDEIND FACT FEDERALBNK FINCABLES FIRSTCRY FIVESTAR FLUOROCHEM FORCEMOT FORTIS FRACTAL
FSL GABRIEL GAIL GALLANTT GESHIP GICRE GILLETTE GLAND GLAXO GLENMARK GMDCLTD GMRAIRPORT GODFRYPHLP GODREJCP GODREJIND GODREJPROP
GPIL GRANULES GRAPHITE GRASIM GRAVITA GROWW GRSE GVT&D HAL HAVELLS HBLENGINE HCLTECH HDBFS HDFCAMC HDFCBANK HDFCLIFE HEGAM
HEROMOTOCO HEXT HFCL HINDALCO HINDCOPPER HINDPETRO HINDUNILVR HINDZINC HOMEFIRST HONASA HONAUT HSCL HUDCO HYUNDAI ICICIAMC ICICIBANK
ICICIGI ICICILIFE IDBI IDEA IDFCFIRSTB IEX IFCI IGIL IGL IIFL IKS INDHOTEL INDIACEM INDIAMART INDIANB INDIGO INDUSINDBK INDUSTOWER
INFY INOXINDIA INOXWIND INTELLECT IOB IOC IPCALAB IRB IRCON IRCTC IREDA IRFC ITC ITCHOTELS ITI J&KBANK JAINREC JBMA JINDALSAW
JINDALSTEL JIOFIN JKCEMENT JKTYRE JMFINANCIL JPPOWER JSL JSWCEMENT JSWENERGY JSWINFRA JSWSTEEL JUBLFOOD JUBLINGREA JWL JYOTICNC
KAJARIACER KALYANKJIL KARURVYSYA KAYNES KEC KEI KFINTECH KIMS KIRLOSBROS KIRLOSENG KOTAKBANK KPIL KPITTECH KPRMILL KSB LALPATHLAB
LAURUSLABS LEMONTREE LENSKART LGEINDIA LICHSGFIN LICI LINDEINDIA LLOYDSME LODHA LT LTF LTFOODS LTM LTTS LUPIN M&M M&MFIN MAHABANK
MANAPPURAM MANKIND MARICO MARUTI MAXHEALTH MAZDOCK MCX MEDANTA MEESHO MFSL MGL MINDACORP MMTC MOTHERSON MOTILALOFS MPHASIS MRF MRPL
MSUMI MTARTECH MUTHOOTFIN NAM-INDIA NATCOPHARM NATIONALUM NAUKRI NAVA NAVINFLUOR NBCC NCC NESTLEIND NETWEB NEULANDLAB NH NHPC
NIACL NLCINDIA NMDC NSLNISP NTPC NTPCGREEN NUVAMA NUVOCO NYKAA OBEROIRLTY OFSS OIL OLAELEC OLECTRA ONESOURCE ONGC PAGEIND PARADEEP
PATANJALI PAYTM PCBL PERSISTENT PETRONET PFC PFOCUS PGEL PHOENIXLTD PIDILITIND PIIND PINELABS PIRAMALFIN PNB PNBHOUSING POLICYBZR
POLYCAB POLYMED POONAWALLA POWERGRID POWERINDIA PPLPHARMA PREMIERENE PRESTIGE PRIVISCL PTCIL PVRINOX PWL RADICO RAILTEL RAINBOW
RAMCOCEM RBLBANK RECLTD REDINGTON RELIANCE RHIM RITES RKFORGE RPOWER RRKABEL RUBICON RVNL SAGILITY SAIL SAILIFE SAMMAANCAP SANSERA
SARDAEN SBICARD SBILIFE SBIN SCHAEFFLER SCHNEIDER SCI SHREECEM SHRIPISTON SHRIRAMFIN SHYAMMETL SIEMENS SIGNATURE SJVN SOBHA
SOLARINDS SONACOMS SRF STARHEALTH STLTECH SUMICHEM SUNDARMFIN SUNPHARMA SUNTV SUPREMEIND SUZLON SWANCORP SWIGGY SYNGENE SYRMA TARIL
TATACAP TATACHEM TATACOMM TATACONSUM TATAELXSI TATAINVEST TATAPOWER TATASTEEL TATATECH TBOTEK TCS TDPOWERSYS TECHM TECHNOE TEGA
TEJASNET TENNIND THANGAMAYL THERMAX TIINDIA TIMKEN TITAGARH TITAN TMCV TMPV TORNTPHARM TORNTPOWER TRENT TRIDENT TRITURBINE TTML
TVSMOTOR UBL UCOBANK UJJIVANSFB ULTRACEMCO UNIONBANK UNITDSPR UNOMINDA UPL URBANCO USHAMART UTIAMC VAML VBL VEDL VEDPOWER VIJAYA VISL
VMM VOGL VOLTAS VTL WAAREEENER WELCORP WELSPUNLIV WHIRLPOOL WIPRO WOCKPHARMA YESBANK ZEEL ZENSARTECH ZENTEC ZFCVINDIA ZYDUSLIFE
ZYDUSWELL""".split()
SN = dict(W='Waiting MSS', N='No zone', E='Waiting entry', O='Open', T='Target hit', L='SL hit', C='Cancelled')


# ---------------------------------------------------------------- data (Yahoo Finance)
def _get(url):
    for k in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30) as r: return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (404, 422): return None
            time.sleep(1 + 2 * k)
        except Exception: time.sleep(1 + 2 * k)


def _yahoo(sym, iv, rng):
    j = _get(f"https://query1.finance.yahoo.com/v8/finance/chart/{urllib.parse.quote(sym + '.NS')}?interval={iv}&range={rng}")
    try: return j['chart']['result'][0]
    except Exception: return None


def _daily(r):
    q = r['indicators']['quote'][0]; B = []
    for t, o, h, l, c in zip(r.get('timestamp') or [], q['open'], q['high'], q['low'], q['close']):
        if None in (o, h, l, c) or min(o, h, l, c) <= 0: continue
        d = dt.datetime.fromtimestamp(t + 19800, dt.timezone.utc).strftime('%Y-%m-%d')
        b = (d, o, max(o, h, l, c), min(o, h, l, c), c)
        if B and B[-1][0] == d: B[-1] = b
        else: B.append(b)
    return B


def _intra(r, m, nowt):
    q = r['indicators']['quote'][0]; out = {}
    for t, o, h, l, c in zip(r.get('timestamp') or [], q['open'], q['high'], q['low'], q['close']):
        if None in (o, h, l, c) or min(o, h, l, c) <= 0: continue
        d = dt.datetime.fromtimestamp(t + 19800, dt.timezone.utc).replace(tzinfo=None)
        mins = d.hour * 60 + d.minute - 555
        if d.second or mins < 0 or mins % m or d.hour * 60 + d.minute >= 930: continue
        if d + dt.timedelta(minutes=m) > nowt: continue                    # completed candles only
        out[d] = (d.strftime('%Y-%m-%d %H:%M'), round(o, 2), round(max(o, h, l, c), 2), round(min(o, h, l, c), 2), round(c, 2))
    return [out[k] for k in sorted(out)]


def load(sym, stamp):
    """daily, 15-min and 5-min candles for one stock (stamp = refresh key)."""
    nowt = dt.datetime.now(IST).replace(tzinfo=None)
    rd, r15, r5 = _yahoo(sym, '1d', '2y'), _yahoo(sym, '15m', '60d'), _yahoo(sym, '5m', '60d')
    if not rd or not r15: return None
    return _daily(rd), _intra(r15, 15, nowt), (_intra(r5, 5, nowt) if r5 else [])


# ---------------------------------------------------------------- engine (same as w75.py)
def hq_dzones(B, a, b):
    Z = []
    rng = lambda k: B[k][2] - B[k][3]
    br = lambda k: abs(B[k][4] - B[k][1]) / rng(k) if rng(k) > 0 else 0
    for i in range(max(0, a), b + 1):
        for k in (1, 2):
            bs = list(range(i, i + k)); lo = i + k
            if lo >= len(B) or lo > b: break
            if not all(br(x) < 0.40 for x in bs): continue
            if not (B[lo][4] > B[lo][1] and br(lo) > 0.50): continue
            if rng(lo) < 1.5 * max(rng(x) for x in bs) or B[lo][4] <= max(B[x][2] for x in bs): continue
            zb, zt = min(B[x][3] for x in bs), max(max(B[x][1], B[x][4]) for x in bs)
            if zt - zb < 0.002 * zt: continue
            Z.append((lo, round(zb, 2), round(zt, 2), B[i][0], k)); break
    return Z


wkey = lambda d: dt.date.fromisoformat(d).isocalendar()[:2]
end15 = lambda t: (pd.Timestamp(t) + pd.Timedelta(minutes=15)).strftime('%H:%M')
end_t = lambda t: (pd.Timestamp(t) + pd.Timedelta(minutes=15)).strftime('%Y-%m-%d %H:%M')


def run(DB, B, B5, day, today):
    """state of the W-75-15 setup for every 15-min slot of `day` -> (entries, setup facts)"""
    T = [b[0] for b in B]; T5 = [b[0] for b in B5]
    dayidx = collections.defaultdict(list)
    for i, t in enumerate(T): dayidx[t[:10]].append(i)
    if day not in dayidx: return None
    have = {b[0] for b in DB if b[0] != today}
    extra = [(d, B[ix[0]][1], max(B[k][2] for k in ix), min(B[k][3] for k in ix), B[ix[-1]][4]) for d, ix in dayidx.items() if (d not in have and len(ix) >= 20) or d == today]
    if extra: DB = sorted([b for b in DB if b[0] != today] + extra)
    W = []
    for b in DB:
        k = wkey(b[0])
        if not W or W[-1][0] != k: W.append([k, b[3]])
        else: W[-1][1] = min(W[-1][1], b[3])
    wpos = {w[0]: j for j, w in enumerate(W)}
    LV = collections.defaultdict(list)
    for j in range(1, len(W)): LV[W[j][0]].append(('PWL', W[j - 1][1]))
    for j in range(1, len(W) - 1):
        if W[j][1] < W[j - 1][1] and W[j][1] < W[j + 1][1]:
            for m in range(j + 2, len(W)):
                LV[W[m][0]].append(('WSL', W[j][1]))
                if W[m][1] < W[j][1]: break
    G = collections.OrderedDict()
    for i, t in enumerate(T):
        m = int(t[11:13]) * 60 + int(t[14:16]) - 555; G.setdefault((t[:10], m // 75), []).append(i)
    K = [ix for ix in G.values() if len(ix) == 5]
    B75 = [(T[ix[0]], B[ix[0]][1], max(B[j][2] for j in ix), min(B[j][3] for j in ix), B[ix[-1]][4], ix[-1]) for ix in K]
    SH75 = [i for i in range(1, len(B75) - 1) if B75[i][2] > B75[i - 1][2] and B75[i][2] > B75[i + 1][2]]
    endk = {b[5]: j for j, b in enumerate(B75)}

    def mline(swl):
        for i in reversed(SH75):
            if B75[i + 1][5] >= swl: continue
            h = B75[i][2]
            if max(B[j][2] for j in range(B75[i][5] + 1, swl + 1)) <= h: return h, B75[i][0]
        return None

    def zone(swl, km, line):
        cand = [('15m', q) for q in hq_dzones(B, swl, km) if not any(B[k][3] <= q[2] for k in range(q[0] + 1, km + 1))]
        a5 = next((k for k, t in enumerate(T5) if t >= T[swl]), None)
        b5 = next((k for k, t in enumerate(T5) if t >= end_t(T[km])), len(B5)) - 1
        if a5 is not None and b5 > a5:
            cand += [('5m', q) for q in hq_dzones(B5, a5, b5) if not any(B5[k][3] <= q[2] for k in range(q[0] + 1, b5 + 1))]
        cand = [(tf, q, (q[2] / line - 1) * 100) for tf, q in cand if abs(q[2] / line - 1) <= BAND]
        if not cand: return None
        tf, q, d = min(cand, key=lambda c: (abs(c[2]), c[0] != '15m'))
        return dict(tf=tf, b=q[1], t=q[2], st=q[3], lt=(T5 if tf == '5m' else T)[q[0]], nb=q[4], d=round(d, 2))

    wk = wkey(day); lvls = LV.get(wk, [])
    if not lvls or wk not in wpos: return None
    ids = [i for i in range(len(T)) if wkey(T[i][:10]) == wk and T[i][:10] <= day]
    low = swl = lock = S = mx = mxa = None; ent = []; seen = False
    for k in ids:
        if low is None or B[k][3] < low: low = B[k][3]; swl = k
        c = B[k][4]; st_ = '0'
        if lock is None:
            sw = [(kd, lv) for kd, lv in lvls if low < lv < c]
            ml = mline(swl) if sw else None
            if sw and ml:
                st_ = 'W'; seen = True
                S = dict(sl_t=T[swl], lo=round(low, 2), k='+'.join(sorted({x[0] for x in sw})), lv=sorted({round(x[1], 2) for x in sw}), line=ml[0], lt=ml[1])
                if k in endk and k > swl and B75[endk[k]][4] > ml[0]:
                    lock = dict(km=k); S['mss'] = T[B75[endk[k]][5] - 4]; S['mc'] = T[k]
                    z = zone(swl, k, ml[0]); mx = mxa = B[k][2]
                    if z: S['z'] = z; lock['ph'] = 'E'
                    else: lock['ph'] = 'N'
                    st_ = lock['ph']
        else:
            ph = lock['ph']
            if ph == 'E':
                z = S['z']
                if B[k][1] < z['b']: ph = 'C'; S['xt'] = T[k]
                elif B[k][3] <= z['t']:
                    S['en'] = z['t']; S['sl'] = z['b']; S['tp'] = round(mx, 2); S['tr'] = T[k]
                    S['rr'] = round((mx - z['t']) / (z['t'] - z['b']), 2) if z['t'] > z['b'] else None
                    if B[k][3] <= z['b']: ph = 'L'; S['xt'] = T[k]
                    else: ph = 'O'
                elif c < z['b']: ph = 'C'; S['xt'] = T[k]
                else: mx = max(mx, B[k][2])
            elif ph == 'O':
                if B[k][3] <= S['sl']: ph = 'L'; S['xt'] = T[k]
                elif B[k][2] >= S['tp']: ph = 'T'; S['xt'] = T[k]
            lock['ph'] = ph; st_ = ph; mxa = max(mxa, B[k][2])
        if T[k][:10] != day: continue
        if st_ == '0' and not seen: continue
        ent.append(dict(slot=end15(T[k]), st=st_, c=c, S=dict(S) if S else None))
    return ent if any(e['st'] != '0' for e in ent) else None


# ---------------------------------------------------------------- page
st.set_page_config(page_title='Weekly Sweep latest (W-75-15)', layout='wide')
st.title('Weekly Sweep latest (W-75-15)')
st.caption('Weekly liquidity sweep (PWL / WSL) → 75-min MSS → 15 / 5-min demand zone near the MSS line. Yahoo Finance data, study only.')
with st.expander('Rules'):
    st.markdown(__doc__.split('Run:')[0].replace('\n', '  \n'))

now = dt.datetime.now(IST)
c1, c2, c3 = st.columns([1, 1, 1])
bucket = int(time.time() // 600) * 600                 # data shared by all visitors, renewed every 10 minutes
if c3.button('🔄 Refresh data'): st.session_state['stamp'] = time.time()
stamp = max(bucket, st.session_state.get('stamp', 0))
universe = st.sidebar.text_area('Stocks (NSE symbols)', ' '.join(SYMS), height=150).split()


@st.cache_data(ttl=600, show_spinner=False)
def load_all(syms, stamp):
    with cf.ThreadPoolExecutor(12) as ex: res = list(ex.map(lambda s: (s, load(s, stamp)), syms))
    return {s: v for s, v in res if v and len(v[1]) >= 60}


with st.spinner(f'Fetching {len(universe)} stocks from Yahoo (about a minute)…'):
    DATA = load_all(tuple(universe), stamp)
days = sorted({b[0][:10] for v in DATA.values() for b in v[1]})
if not days: st.error('No data from Yahoo right now. Try Refresh.'); st.stop()
day = c1.selectbox('Date', days[::-1], index=0)
today = now.strftime('%Y-%m-%d')
slots = [f'{h:02d}:{m:02d}' for h in range(9, 16) for m in (0, 15, 30, 45) if '09:30' <= f'{h:02d}:{m:02d}' <= '15:30']


@st.cache_data(ttl=600, show_spinner=False)
def compute(day, stamp, n):
    out = {}
    for s, (DB, B, B5) in DATA.items():
        try: e = run(DB, B, B5, day, today)
        except Exception: e = None
        if e: out[s] = e
    return out


with st.spinner('Running the W-75-15 rules…'):
    R = compute(day, stamp, len(DATA))
last_slot = max((e['slot'] for v in R.values() for e in v), default='15:30')
okslots = [x for x in slots if x <= last_slot] or slots
slot = c2.selectbox('Time', okslots[::-1], index=0)

rows = []
for s, ent in R.items():
    e = None
    for x in ent:
        if x['slot'] <= slot: e = x
    if not e or e['st'] == '0': continue
    S = e['S'] or {}; z = S.get('z') or {}; st_ = e['st']
    trade = st_ in 'OTL'
    pl = None
    if st_ == 'T': pl = (S['tp'] / S['en'] - 1) * 100
    elif st_ == 'L': pl = (S['sl'] / S['en'] - 1) * 100
    elif st_ == 'O': pl = (e['c'] / S['en'] - 1) * 100
    rows.append({'Stock': s, 'Status': SN[st_], 'Liquidity': S.get('k'), 'Level swept': ' / '.join(str(x) for x in S.get('lv', [])),
                 'Sweep low': S.get('lo'), 'Sweep time': S.get('sl_t'), 'MSS line': S.get('line'), 'Line time': S.get('lt'),
                 'MSS 75m candle': S.get('mss') if st_ != 'W' else None,
                 'Zone TF': z.get('tf') if st_ != 'W' else None, 'Zone': f"{z['b']} – {z['t']}" if z and st_ != 'W' else None,
                 'Zone vs line %': z.get('d') if st_ != 'W' else None,
                 'Entry': S.get('en') if trade else (z.get('t') if z and st_ != 'W' else None),
                 'SL': S.get('sl') if trade else (z.get('b') if z and st_ != 'W' else None),
                 'Target': S.get('tp') if trade else None, 'R:R': S.get('rr') if trade else None,
                 'Entered': S.get('tr') if trade else None, 'Exit': S.get('xt') if st_ in 'TLC' else None,
                 'CMP': e['c'], 'P/L %': round(pl, 2) if pl is not None else None, '_st': st_, '_S': S})
df = pd.DataFrame(rows)
cnt = collections.Counter(r['_st'] for r in rows)
m = st.columns(7)
for col, k in zip(m, 'EOTLWNC'): col.metric(SN[k], cnt.get(k, 0))

f1, f2, f3, f4, f5 = st.columns(5)
stat = f1.multiselect('Status', list(SN.values()), default=['Waiting entry', 'Open'])
liq = f2.selectbox('Liquidity', ['Any', 'PWL', 'WSL', 'Both'])
ztf = f3.selectbox('Zone TF', ['15 or 5 min', '15m', '5m'])
band = f4.selectbox('Zone vs MSS line', ['±2%', '±1%', '±0.5%'])
q = f5.text_input('Stock search').strip().upper()
if not df.empty:
    bd = float(band.strip('±%'))
    df.loc[(df['_st'] != 'W') & df['Zone vs line %'].notna() & (df['Zone vs line %'].abs() > bd), 'Status'] = 'No zone'
    v = df[df['Status'].isin(stat)] if stat else df
    if liq == 'Both': v = v[v['Liquidity'].fillna('').str.contains(r'\+')]
    elif liq != 'Any': v = v[v['Liquidity'].fillna('').str.contains(liq)]
    if ztf != '15 or 5 min': v = v[v['Zone TF'] == ztf]
    if q: v = v[v['Stock'].str.contains(q, regex=False)]
    order = {'Open': 0, 'Waiting entry': 1, 'Target hit': 2, 'SL hit': 3, 'Cancelled': 4, 'No zone': 5, 'Waiting MSS': 6}
    v = v.assign(_o=v['Status'].map(order)).sort_values(['_o', 'Stock'])
    st.caption(f'{day} {slot} – candles completed by this time only · {len(v)} rows · data fetched {dt.datetime.fromtimestamp(stamp, IST):%d %b %H:%M} IST')
    st.dataframe(v.drop(columns=['_st', '_S', '_o']), hide_index=True, width='stretch')

    pick = st.selectbox('Chart', ['–'] + list(v['Stock']))
    if pick != '–':
        r = v[v['Stock'] == pick].iloc[0]; S = r['_S']; DB, B, B5 = DATA[pick]
        ws = dt.date.fromisoformat(day) - dt.timedelta(days=dt.date.fromisoformat(day).weekday()); ps = (ws - dt.timedelta(days=7)).isoformat()
        cut = day + ' ' + (pd.Timestamp(day + ' ' + slot) - pd.Timedelta(minutes=15)).strftime('%H:%M')
        b = [x for x in B if ps <= x[0] <= cut]
        fig = go.Figure(go.Candlestick(x=list(range(len(b))), open=[x[1] for x in b], high=[x[2] for x in b], low=[x[3] for x in b], close=[x[4] for x in b],
                                       text=[x[0] for x in b], hoverinfo='text+y'))
        for y in S.get('lv', []): fig.add_hline(y=y, line_dash='dot', line_color='crimson', annotation_text=f'Swept {y}')
        if S.get('line'): fig.add_hline(y=S['line'], line_dash='dash', line_color='royalblue', annotation_text=f"MSS line {S['line']}")
        z = S.get('z')
        if z and r['_st'] != 'W': fig.add_hrect(y0=z['b'], y1=z['t'], fillcolor='green', opacity=0.15, line_width=0, annotation_text='DZ ' + z['tf'])
        if S.get('tp') and r['_st'] in 'OTL':
            fig.add_hline(y=S['tp'], line_color='green', annotation_text=f"Target {S['tp']}")
            fig.add_hline(y=S['sl'], line_dash='dash', line_color='crimson', annotation_text=f"SL {S['sl']}")
        tv = [i for i, x in enumerate(b) if x[0].endswith('09:15')]
        fig.update_layout(height=480, xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=30, b=10), title=f'{pick} – {r["Status"]}',
                          xaxis=dict(tickvals=tv, ticktext=[b[i][0][5:10] for i in tv]))
        st.plotly_chart(fig, width='stretch')
else:
    st.info('No stock has a weekly sweep at this time.')
