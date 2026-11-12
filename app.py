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
