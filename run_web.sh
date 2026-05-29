#!/bin/bash
cd "$(dirname "$0")"
STREAMLIT_EMAIL="" python3 -m streamlit run app.py --server.port 8501 --server.headless true
