"""
BankSight AI — Prediction & Inference
======================================
Loads trained models, computes ensemble predictions, and scales probabilities.
"""

import logging
import uuid
import joblib
from datetime import datetime
import pandas as pd
import numpy as np

import config
from src.data import Database
from src.features import FeatureEngine

log = logging.getLogger("PREDICT")

class Predictor:
    def __init__(self, db: Database = None):
        self.db = db or Database()
        self.models = {}
        self.load_active_models()

    def load_active_models(self):
        """Load all active models from DB into memory."""
        self.models = {}
        versions = self.db.get_all_model_versions()
        active = [v for v in versions if v.get("is_active") == 1]
        
        for v in active:
            target = v["target"]
            algo = v["algorithm"]
            path = v["file_path"]
            
            try:
                data = joblib.load(path)
                if target not in self.models:
                    self.models[target] = {}
                self.models[target][algo] = {
                    "model": data["model"],
                    "features": data["features"],
                    "version": v["model_version"]
                }
            except Exception as e:
                log.error(f"Failed to load model {v['model_version']} from {path}: {e}")

    def generate_forecasts(self, symbol: str) -> dict:
        """
        Generate forecasts for 1D, 5D, 7D.
        Requires the latest features for the symbol.
        """
        # Get latest features
        query = "SELECT * FROM features WHERE symbol = ? ORDER BY date DESC LIMIT 1"
        with self.db._connect() as conn:
            row = conn.execute(query, (symbol,)).fetchone()
            
        if not row:
            log.warning(f"No features available for {symbol}")
            return None
            
        import json
        features_dict = json.loads(row["features_json"])
        feat_df = pd.DataFrame([features_dict])
        
        # Ensure latest price exists
        current_price = feat_df["close"].iloc[0] if "close" in feat_df.columns else None
        
        if current_price is None:
            # Fallback to market data
            md = self.db.get_market_data(symbol)
            if not md.empty:
                current_price = md["close"].iloc[-1]
            else:
                return None

        pred_id = uuid.uuid4().hex[:12]
        
        result = {
            "prediction_id": pred_id,
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "current_price": float(current_price),
            "data_quality": row["data_quality"] if "data_quality" in row.keys() else "REAL"
        }
        
        used_versions = []

        # Predict for each horizon
        for h in config.TARGET_HORIZONS:
            target = f"target_{h}d_return"
            
            if target not in self.models:
                continue
                
            algo_preds = {}
            for algo, m_info in self.models[target].items():
                model = m_info["model"]
                req_features = m_info["features"]
                
                # Align features
                X = pd.DataFrame(index=[0], columns=req_features)
                for f in req_features:
                    X[f] = feat_df[f].iloc[0] if f in feat_df.columns else 0.0
                
                # Fill NAs
                X = X.fillna(0.0)
                
                # Predict
                try:
                    p = model.predict(X)[0]
                    algo_preds[algo] = float(p)
                    if m_info["version"] not in used_versions:
                        used_versions.append(m_info["version"])
                except Exception as e:
                    log.error(f"Prediction failed for {algo} on {target}: {e}")
                    
            primary_pred = algo_preds.get("xgboost")
            benchmark_pred = algo_preds.get("lightgbm")
            
            # Fallbacks
            if primary_pred is None and benchmark_pred is not None:
                primary_pred = benchmark_pred
            if benchmark_pred is None and primary_pred is not None:
                benchmark_pred = primary_pred
                
            if primary_pred is not None:
                result[f"return_{h}d"] = primary_pred
                result[f"prediction_{h}d"] = current_price * (1 + primary_pred)
                result[f"benchmark_return_{h}d"] = benchmark_pred
                result[f"benchmark_prediction_{h}d"] = current_price * (1 + benchmark_pred)
                
                if primary_pred > config.DIRECTION_THRESHOLD:
                    result[f"direction_{h}d"] = "UP"
                elif primary_pred < -config.DIRECTION_THRESHOLD:
                    result[f"direction_{h}d"] = "DOWN"
                else:
                    result[f"direction_{h}d"] = "NEUTRAL"
                    
                conf = min(50 + (abs(primary_pred) * 1000), 99)
                result[f"confidence_{h}d"] = float(conf)

        result["model_version"] = ",".join(used_versions)
        result["features_version"] = "1.0"
        
        # Add event similarity explanation
        from src.events import EventSimilarityEngine
        event_engine = EventSimilarityEngine(self.db)
        events_stats = event_engine.find_similar_events(symbol, str(row["date"]))
        result["explanation"] = {"events": events_stats}

        self.db.save_prediction(result)
        return result

def generate_all_predictions():
    db = Database()
    predictor = Predictor(db)
    
    for symbol in config.STOCK_SYMBOLS:
        log.info(f"Generating predictions for {symbol}...")
        predictor.generate_forecasts(symbol)

if __name__ == "__main__":
    config.setup_logging()
    generate_all_predictions()
