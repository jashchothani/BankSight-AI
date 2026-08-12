"""
BankSight AI — Setup Script
============================
Initializes the database, downloads historical data, generates features,
and runs the first model training cycle.
"""

import os
import sys
import logging
from datetime import datetime

# Ensure we can import our modules
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import config

def setup():
    config.setup_logging()
    log = logging.getLogger("SETUP")
    log.info("Starting BankSight AI Setup...")
    
    # 1. Initialize Database & Download Data
    log.info("--- Step 1: Downloading Historical Data ---")
    from src.data import init_pipeline
    pipeline = init_pipeline()
    pipeline.download_all_historical()
    pipeline.update_fundamentals()
    
    # Optional: fetch and analyze initial news
    try:
        from src.news import update_and_analyze_news
        update_and_analyze_news()
    except Exception as e:
        log.warning(f"Initial news fetch/analysis failed: {e}")
        
    # 2. Feature Engineering
    log.info("--- Step 2: Generating Features ---")
    from src.features import generate_all_features
    generate_all_features()
    
    # 3. Model Training
    log.info("--- Step 3: Training Initial Models ---")
    from src.train import run_training
    run_training()
    
    # 4. Generate Initial Predictions
    log.info("--- Step 4: Generating Predictions ---")
    from src.predict import generate_all_predictions
    generate_all_predictions()
    
    log.info("Setup complete! You can now start the dashboard with: python app.py")

if __name__ == "__main__":
    setup()
