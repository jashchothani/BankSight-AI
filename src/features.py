"""
BankSight AI — Feature Engineering
===================================
Constructs point-in-time features preventing look-ahead bias.

Features:
- Technical (SMA, EMA, RSI, MACD, Bollinger, ATR)
- Market-relative (vs Nifty, vs Bank Nifty)
- Volatility
- Targets (1D, 5D, 7D returns + direction labels)
"""

import logging
import json
import numpy as np
import pandas as pd
from datetime import datetime

import config
from src.data import Database

log = logging.getLogger("FEATURES")

class FeatureEngine:
    def __init__(self, db: Database = None):
        self.db = db or Database()

    def generate_features(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """
        Generate all features for a single stock DataFrame.
        Input df MUST contain: date, open, high, low, close, volume.
        It may optionally contain index closes (nifty50_close, banknifty_close, indiavix_close, usdinr_close)
        and macro data (repo_rate).
        """
        if df.empty or len(df) < 50:
            log.warning(f"Not enough data to generate features for {symbol}")
            return df

        df = df.copy()
        df.sort_values("date", inplace=True)
        df.reset_index(drop=True, inplace=True)

        # Basic Price & Volume Returns
        df["return_1d"] = df["close"].pct_change(1)
        df["log_return_1d"] = np.log(df["close"] / df["close"].shift(1))
        df["volume_change"] = df["volume"].pct_change(1)

        # ---------------------------------------------------------
        # Technical Features
        # ---------------------------------------------------------
        # SMA & Price-to-SMA ratio
        for w in config.SMA_WINDOWS:
            sma_col = f"sma_{w}"
            df[sma_col] = df["close"].rolling(window=w).mean()
            df[f"price_to_{sma_col}"] = df["close"] / df[sma_col] - 1

        # EMA
        for w in config.EMA_WINDOWS:
            df[f"ema_{w}"] = df["close"].ewm(span=w, adjust=False).mean()

        # MACD
        ema_fast = df["close"].ewm(span=config.MACD_FAST, adjust=False).mean()
        ema_slow = df["close"].ewm(span=config.MACD_SLOW, adjust=False).mean()
        df["macd"] = ema_fast - ema_slow
        df["macd_signal"] = df["macd"].ewm(span=config.MACD_SIGNAL, adjust=False).mean()
        df["macd_hist"] = df["macd"] - df["macd_signal"]

        # RSI
        delta = df["close"].diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=config.RSI_WINDOW).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=config.RSI_WINDOW).mean()
        rs = gain / loss.replace(0, np.nan)  # avoid division by zero
        df["rsi"] = 100 - (100 / (1 + rs))
        df["rsi"] = df["rsi"].fillna(50)

        # ATR (Average True Range)
        high_low = df["high"] - df["low"]
        high_close = np.abs(df["high"] - df["close"].shift())
        low_close = np.abs(df["low"] - df["close"].shift())
        ranges = pd.concat([high_low, high_close, low_close], axis=1)
        true_range = np.max(ranges, axis=1)
        df["atr"] = true_range.rolling(window=config.ATR_WINDOW).mean()
        df["atr_pct"] = df["atr"] / df["close"]

        # Bollinger Bands
        sma_bb = df["close"].rolling(window=config.BOLLINGER_WINDOW).mean()
        std_bb = df["close"].rolling(window=config.BOLLINGER_WINDOW).std()
        df["bb_upper"] = sma_bb + (std_bb * config.BOLLINGER_STD)
        df["bb_lower"] = sma_bb - (std_bb * config.BOLLINGER_STD)
        df["bb_width"] = (df["bb_upper"] - df["bb_lower"]) / sma_bb
        df["bb_position"] = (df["close"] - df["bb_lower"]) / (df["bb_upper"] - df["bb_lower"]).replace(0, np.nan)

        # Volume MA
        for w in [5, 20]:
            df[f"volume_ma_{w}"] = df["volume"].rolling(window=w).mean()
            df[f"volume_to_ma_{w}"] = df["volume"] / df[f"volume_ma_{w}"]

        # Rolling Returns (Momentum)
        for w in config.ROLLING_RETURN_WINDOWS:
            df[f"return_{w}d"] = df["close"].pct_change(w)

        # Volatility
        df["volatility_20d"] = df["return_1d"].rolling(window=config.VOLATILITY_WINDOW).std() * np.sqrt(252)

        # ---------------------------------------------------------
        # Market-Relative Features (if index data exists)
        # ---------------------------------------------------------
        if "nifty50_close" in df.columns:
            df["nifty_return_1d"] = df["nifty50_close"].pct_change(1)
            df["nifty_return_5d"] = df["nifty50_close"].pct_change(5)
            df["rel_return_nifty_1d"] = df["return_1d"] - df["nifty_return_1d"]
            df["rel_return_nifty_5d"] = df["return_5d"] - df["nifty_return_5d"]

        if "banknifty_close" in df.columns:
            df["banknifty_return_1d"] = df["banknifty_close"].pct_change(1)
            df["banknifty_return_5d"] = df["banknifty_close"].pct_change(5)
            df["rel_return_banknifty_1d"] = df["return_1d"] - df["banknifty_return_1d"]
            df["rel_return_banknifty_5d"] = df["return_5d"] - df["banknifty_return_5d"]

        if "indiavix_close" in df.columns:
            df["vix_level"] = df["indiavix_close"]
            df["vix_change_1d"] = df["indiavix_close"].pct_change(1)

        # ---------------------------------------------------------
        # Targets (Future Returns - For Training Only)
        # ---------------------------------------------------------
        # A target for day T is the return from T's close to T+horizon's close.
        # Strict rule: Targets are shifted backwards. Feature row T corresponds to Target T.
        for h in config.TARGET_HORIZONS:
            df[f"target_{h}d_return"] = df["close"].shift(-h) / df["close"] - 1

            # Directional targets
            def categorize_direction(ret):
                if pd.isna(ret): return np.nan
                if ret > config.DIRECTION_THRESHOLD: return "UP"
                if ret < -config.DIRECTION_THRESHOLD: return "DOWN"
                return "NEUTRAL"

            df[f"target_{h}d_dir"] = df[f"target_{h}d_return"].apply(categorize_direction)

            # Binary targets for UP/DOWN probability models
            df[f"target_{h}d_up"] = (df[f"target_{h}d_return"] > config.DIRECTION_THRESHOLD).astype(float)
            # Mask NaNs back to NaN (since astype(float) converts NaNs to 0)
            df.loc[df[f"target_{h}d_return"].isna(), f"target_{h}d_up"] = np.nan

        return df

    def extract_feature_names(self, df: pd.DataFrame) -> list[str]:
        """Return list of valid feature columns (excluding targets, dates, etc.)."""
        exclude = ["id", "symbol", "date", "open", "high", "low", "close", "volume", "data_quality"]
        exclude += [c for c in df.columns if c.startswith("target_") or c.endswith("_close")]
        return [c for c in df.columns if c not in exclude and df[c].dtype in [np.float64, np.float32, np.int64, np.int32]]

    def save_features_to_db(self, df: pd.DataFrame, symbol: str):
        """Save computed features to the database as JSON strings per day."""
        if df.empty:
            return

        feature_cols = self.extract_feature_names(df)
        target_cols = [c for c in df.columns if c.startswith("target_")]
        all_save_cols = feature_cols + target_cols + ["close"]
        
        with self.db._connect() as conn:
            for _, row in df.iterrows():
                # We only save if we have basic features (drop rows with all NaNs at the start)
                if pd.isna(row.get("return_1d")):
                    continue

                feat_dict = {}
                for col in all_save_cols:
                    val = row[col]
                    is_num = isinstance(val, (int, float, np.number)) and not isinstance(val, bool)
                    if not pd.isna(val) and (not is_num or not np.isinf(val)):
                        feat_dict[col] = float(val) if isinstance(val, (np.floating, float)) else val
                
                conn.execute(
                    """INSERT OR REPLACE INTO features
                       (symbol, date, features_json, data_quality)
                       VALUES (?, ?, ?, ?)""",
                    (symbol, str(row["date"]), json.dumps(feat_dict), row.get("data_quality", "REAL"))
                )
        log.info(f"Saved features for {symbol}")

def generate_all_features():
    from src.data import DataPipeline
    pipeline = DataPipeline()
    engine = FeatureEngine(pipeline.db)
    
    for symbol in config.STOCK_SYMBOLS:
        log.info(f"Generating features for {symbol}...")
        df = pipeline.get_unified_dataset(symbol)
        if not df.empty:
            feat_df = engine.generate_features(df, symbol)
            engine.save_features_to_db(feat_df, symbol)
            
    log.info("Feature engineering complete.")
