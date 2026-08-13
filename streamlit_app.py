"""
MIZAN — Procurement Intelligence
Streamlit Cloud entry point.

This file exists so Streamlit Community Cloud can find the app.
The actual app lives at mizan_app/app.py.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

# Redirect Streamlit Cloud to the real app
from mizan_app.app import *