"""
回测系统独立页面（调试用）

用法: streamlit run code/backtest/web_app.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import streamlit as st
st.set_page_config(page_title="回测系统", layout="wide")
st.markdown("<h1 style='font-size:1.6rem'>🔄 回测系统</h1>", unsafe_allow_html=True)

from code.backtest.web import render_backtest_page
render_backtest_page()
