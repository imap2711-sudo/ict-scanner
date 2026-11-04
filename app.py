import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import requests
import io
import concurrent.futures
import time
import os
import pickle
import gc
from datetime import datetime, date, time as dtime
import warnings
import logging

warnings.filterwarnings('ignore')
logging.getLogger('yfinance').setLevel(logging.CRITICAL)

st.set_page_config(page_title="GTF MIT & WIT Demand Zone Scanner", layout="wide")

CACHE_DIR_DAILY = "/tmp/gtf_daily_cache"
CACHE_DIR_1H = "/tmp/gtf_1h_cache"
os.makedirs(CACHE_DIR_DAILY, exist_ok=True)
os.makedirs(CACHE_DIR_1H, exist_ok=True)
