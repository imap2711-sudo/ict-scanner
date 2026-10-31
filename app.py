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

