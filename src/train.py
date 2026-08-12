"""
BankSight AI — Model Training
==============================
Walk-forward training for predicting stock returns.
Trains XGBoost, LightGBM, and Random Forest models and saves versioned models.
"""

import os
import uuid
import json
import logging
from datetime import datetime
import joblib
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

import config
from src.data import Database

try:
    import xgboost as xgb
    XGB_AVAILABLE = True
except ImportError:
    XGB_AVAILABLE = False

try:
    import lightgbm as lgb
    LGB_AVAILABLE = True
except ImportError:
    LGB_AVAILABLE = False

log = logging.getLogger("TRAIN")

class WalkForwardTrainer:
    def __init__(self, db: Database = None):
        self.db = db or Database()

    def load_dataset(self, target: str = "target_5d_return") -> tuple[pd.DataFrame, list[str]]:
        """
        Load features for all stocks from the DB and align with targets.
        We drop rows where the target is NaN (e.g., the most recent days).
        """
        query = "SELECT symbol, date, features_json FROM features ORDER BY date"
        with self.db._connect() as conn:
            rows = conn.execute(query).fetchall()

        if not rows:
            log.warning("No features found in database.")
            return pd.DataFrame(), []

        data = []
        for r in rows:
            try:
                feats = json.loads(r["features_json"])
                feats["symbol"] = r["symbol"]
                feats["date"] = r["date"]
                # We need the target to be present
                if target in feats and not pd.isna(feats[target]):
                    data.append(feats)
            except Exception:
                pass

        df = pd.DataFrame(data)
        if df.empty:
            return df, []
            
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        # Extract feature columns (numerical only, exclude targets)
        feature_cols = [c for c in df.columns if c not in ["symbol", "date"] and not c.startswith("target_")]
        
        # Replace infinity with NaN
        df[feature_cols] = df[feature_cols].replace([np.inf, -np.inf], np.nan)
        
        # We need to fill NaNs in features (some models handle them, some don't)
        # XGBoost/LightGBM handle NaNs, but RF needs them filled.
        # We'll forward fill per symbol, then fill remaining with 0.
        df[feature_cols] = df.groupby("symbol")[feature_cols].ffill()
        df[feature_cols] = df[feature_cols].fillna(0)
        
        return df, feature_cols

    def evaluate(self, y_true, y_pred):
        """Calculate regression metrics."""
        return {
            "mae": float(mean_absolute_error(y_true, y_pred)),
            "rmse": float(np.sqrt(mean_squared_error(y_true, y_pred))),
            "r2": float(r2_score(y_true, y_pred)),
            "dir_acc": float(np.mean(np.sign(y_true) == np.sign(y_pred)))
        }

    def train_model(self, algo: str, df: pd.DataFrame, feature_cols: list[str], target: str):
        """Train a single model using walk-forward validation and retrain on full data."""
        log.info(f"Training {algo} for {target}...")
        
        # Parameters
        if algo == "xgboost" and XGB_AVAILABLE:
            model_class = xgb.XGBRegressor
            params = config.XGBOOST_PARAMS
        elif algo == "lightgbm" and LGB_AVAILABLE:
            model_class = lgb.LGBMRegressor
            params = config.LIGHTGBM_PARAMS
        elif algo == "random_forest":
            model_class = RandomForestRegressor
            params = config.RANDOM_FOREST_PARAMS
        else:
            log.warning(f"Algorithm {algo} not available or unknown.")
            return None

        # -------------------------------------------------------------
        # 1. Walk-Forward Validation
        # -------------------------------------------------------------
        # Find unique dates for splitting
        dates = np.sort(df["date"].unique())
        total_days = len(dates)
        
        if total_days < config.TRAIN_MIN_DAYS + config.TEST_DAYS:
            log.warning(f"Not enough days ({total_days}) for walk-forward validation.")
            # Fallback: simple train-test split (80-20)
            split_idx = int(len(df) * 0.8)
            train = df.iloc[:split_idx]
            test = df.iloc[split_idx:]
            
            model = model_class(**params)
            model.fit(train[feature_cols], train[target])
            preds = model.predict(test[feature_cols])
            metrics = self.evaluate(test[target], preds)
        else:
            # Proper Walk-Forward
            all_preds = []
            all_trues = []
            
            start_idx = config.TRAIN_MIN_DAYS
            split_count = 0
            while start_idx < total_days:
                train_end_date = dates[start_idx]
                test_end_date = dates[min(start_idx + config.WALK_FORWARD_STEP, total_days - 1)]
                
                train = df[df["date"] < train_end_date]
                test = df[(df["date"] >= train_end_date) & (df["date"] < test_end_date)]
                
                if not test.empty:
                    split_count += 1
                    log.info(f"  Fitting split {split_count} (train: {len(train)}, test: {len(test)})...")
                    model = model_class(**params)
                    model.fit(train[feature_cols], train[target])
                    preds = model.predict(test[feature_cols])
                    all_preds.extend(preds)
                    all_trues.extend(test[target])
                    
                start_idx += config.WALK_FORWARD_STEP
                
            metrics = self.evaluate(all_trues, all_preds)
            
        log.info(f"{algo} Validation Metrics: {metrics}")

        # -------------------------------------------------------------
        # 2. Train Final Model on All Data
        # -------------------------------------------------------------
        final_model = model_class(**params)
        final_model.fit(df[feature_cols], df[target])
        
        # -------------------------------------------------------------
        # 3. Save Model
        # -------------------------------------------------------------
        version = f"{algo}_v{uuid.uuid4().hex[:8]}"
        filename = f"{version}.pkl"
        filepath = config.MODELS_DIR / filename
        
        # Save to disk
        joblib.dump({
            "model": final_model,
            "features": feature_cols,
            "target": target
        }, filepath)
        
        # Save to DB
        db_info = {
            "model_version": version,
            "algorithm": algo,
            "target": target,
            "training_timestamp": datetime.now().isoformat(),
            "training_start": pd.to_datetime(dates[0]).strftime("%Y-%m-%d"),
            "training_end": pd.to_datetime(dates[-1]).strftime("%Y-%m-%d"),
            "feature_version": "1.0",
            "metrics": metrics,
            "file_path": str(filepath),
            "is_active": 1  # For simplicity, we just make the newest active
        }
        self.db.save_model_version(db_info)
        
        # Deactivate old models for this algo/target
        with self.db._connect() as conn:
            conn.execute(
                "UPDATE model_versions SET is_active = 0 WHERE algorithm = ? AND target = ? AND model_version != ?",
                (algo, target, version)
            )
            
        log.info(f"Saved {version} to {filepath}")
        return version

    def train_all(self):
        """Train all models for all targets."""
        algorithms = []
        if XGB_AVAILABLE: algorithms.append("xgboost")
        if LGB_AVAILABLE: algorithms.append("lightgbm")
        
        if not algorithms:
            log.error("Neither XGBoost nor LightGBM is available for training!")
            return
        
        for h in config.TARGET_HORIZONS:
            target = f"target_{h}d_return"
            df, feature_cols = self.load_dataset(target)
            if df.empty:
                continue
                
            for algo in algorithms:
                self.train_model(algo, df, feature_cols, target)

def run_training():
    trainer = WalkForwardTrainer()
    trainer.train_all()

if __name__ == "__main__":
    config.setup_logging()
    run_training()
