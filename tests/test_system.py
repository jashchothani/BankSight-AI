"""
BankSight AI — System Tests
============================
Tests data integrity, future leakage, and API endpoints.
"""

import os
import sys
import json
import pytest
import pandas as pd
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import config
from src.data import Database, DataQuality
from src.features import FeatureEngine

@pytest.fixture
def test_db():
    # Use in-memory SQLite for testing
    db = Database(db_path=":memory:")
    yield db

def test_future_leakage(test_db):
    """
    CRITICAL: Verify that the feature generator does NOT leak future information
    into the feature set, except for the explicit target columns.
    """
    # 1. Create dummy market data
    dates = pd.date_range(start="2024-01-01", periods=100, freq="B")
    df = pd.DataFrame({
        "date": dates,
        "open": range(100, 200),
        "high": range(105, 205),
        "low": range(95, 195),
        "close": range(102, 202),
        "volume": [1000] * 100,
        "data_quality": [DataQuality.REAL] * 100
    })
    df["date"] = df["date"].dt.date
    
    # 2. Generate features
    engine = FeatureEngine(test_db)
    feat_df = engine.generate_features(df, "TESTBANK")
    
    # 3. Test for leakage
    # We test this by changing the FUTURE close price of a specific date and ensuring
    # the features for the CURRENT date do NOT change (only targets should change).
    
    target_idx = 50
    current_date = df.iloc[target_idx]["date"]
    
    # Get original features for target_idx
    original_features = feat_df.iloc[target_idx].copy()
    
    # Modify a future price (e.g., target_idx + 5)
    future_idx = target_idx + 5
    df_modified = df.copy()
    df_modified.loc[future_idx, "close"] = 9999 # Huge artificial spike
    
    # Recompute features
    feat_df_mod = engine.generate_features(df_modified, "TESTBANK")
    modified_features = feat_df_mod.iloc[target_idx].copy()
    
    # Features that SHOULD NOT change
    feature_cols = engine.extract_feature_names(feat_df)
    
    for col in feature_cols:
        val1 = original_features[col]
        val2 = modified_features[col]
        # Allow small floating point differences, handle NaNs
        if pd.isna(val1) and pd.isna(val2):
            continue
        assert abs(val1 - val2) < 1e-6, f"LEAKAGE DETECTED: Feature '{col}' at index {target_idx} changed when future price was modified!"
        
    # Features that SHOULD change (targets)
    assert original_features["target_5d_return"] != modified_features["target_5d_return"], "Target failed to update when future changed."


def test_data_pipeline_missing_handler(test_db):
    """Verify that the engine gracefully handles missing index/macro data."""
    df = pd.DataFrame({
        "date": [datetime.now().date()],
        "open": [100], "high": [105], "low": [95], "close": [102], "volume": [1000]
    })
    # Passing dataframe WITHOUT Nifty/VIX columns
    engine = FeatureEngine(test_db)
    feat_df = engine.generate_features(df, "TESTBANK")
    
    # Should not crash, and index-relative features should be absent or NaN
    assert "rel_return_nifty_1d" not in feat_df.columns

def test_no_demo_mode_policy():
    """Verify system strictly rejects demo mode fallbacks as per live-only policy."""
    assert config.is_demo_mode() == False
