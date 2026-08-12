"""
BankSight AI — Evaluation
==========================
Tracks predictions against actual future outcomes and computes metrics.
"""

import logging
from datetime import datetime
import pandas as pd
import numpy as np

import config
from src.data import Database

log = logging.getLogger("EVALUATION")

class Evaluator:
    def __init__(self, db: Database = None):
        self.db = db or Database()

    def evaluate_pending_predictions(self):
        """
        Find predictions whose target horizon has passed and compute accuracy.
        """
        preds = self.db.get_predictions(limit=1000)
        
        for p in preds:
            # We already have a result? Skip.
            # (In a real implementation we'd check if prediction_id is in prediction_results)
            
            symbol = p["symbol"]
            pred_date = pd.to_datetime(p["timestamp"]).date()
            
            # Need to get market data after pred_date
            md = self.db.get_market_data(symbol, start=str(pred_date))
            if md.empty:
                continue
                
            # If we don't have enough future days to evaluate the 7d target, skip
            # For simplicity, we just check if we have the index
            # A robust implementation uses actual trading days calendar
            
            # Simple check: 
            # md row 0 should be pred_date (or close to it)
            if len(md) > 7:
                result = {
                    "prediction_id": p["prediction_id"],
                    "evaluated_at": datetime.now().isoformat()
                }
                
                base_price = p["current_price"]
                
                # Evaluate 1D
                if len(md) > 1:
                    act_1 = md.iloc[1]["close"]
                    result["actual_price_1d"] = act_1
                    result["actual_return_1d"] = (act_1 / base_price) - 1
                    if p.get("return_1d") is not None:
                        result["error_1d"] = result["actual_return_1d"] - p["return_1d"]
                        act_dir = 1 if result["actual_return_1d"] > 0 else -1
                        pred_dir = 1 if p["return_1d"] > 0 else -1
                        result["direction_correct_1d"] = 1 if act_dir == pred_dir else 0

                # Evaluate 3D
                if len(md) > 3:
                    act_3 = md.iloc[3]["close"]
                    result["actual_price_3d"] = act_3
                    result["actual_return_3d"] = (act_3 / base_price) - 1
                    if p.get("return_3d") is not None:
                        result["error_3d"] = result["actual_return_3d"] - p["return_3d"]
                        act_dir = 1 if result["actual_return_3d"] > 0 else -1
                        pred_dir = 1 if p["return_3d"] > 0 else -1
                        result["direction_correct_3d"] = 1 if act_dir == pred_dir else 0

                # Evaluate 5D
                if len(md) > 5:
                    act_5 = md.iloc[5]["close"]
                    result["actual_price_5d"] = act_5
                    result["actual_return_5d"] = (act_5 / base_price) - 1
                    if p.get("return_5d") is not None:
                        result["error_5d"] = result["actual_return_5d"] - p["return_5d"]
                        act_dir = 1 if result["actual_return_5d"] > 0 else -1
                        pred_dir = 1 if p["return_5d"] > 0 else -1
                        result["direction_correct_5d"] = 1 if act_dir == pred_dir else 0

                # Evaluate 7D
                if len(md) > 7:
                    act_7 = md.iloc[7]["close"]
                    result["actual_price_7d"] = act_7
                    result["actual_return_7d"] = (act_7 / base_price) - 1
                    if p.get("return_7d") is not None:
                        result["error_7d"] = result["actual_return_7d"] - p["return_7d"]
                        act_dir = 1 if result["actual_return_7d"] > 0 else -1
                        pred_dir = 1 if p["return_7d"] > 0 else -1
                        result["direction_correct_7d"] = 1 if act_dir == pred_dir else 0

                self.db.save_prediction_result(result)

    def get_system_metrics(self) -> dict:
        """Aggregate metrics across all active models and predictions."""
        # 1. Model metrics from DB
        models = self.db.get_all_model_versions()
        active_models = [m for m in models if m["is_active"] == 1]
        
        model_stats = []
        for m in active_models:
            try:
                metrics = json.loads(m["metrics_json"])
                model_stats.append({
                    "algorithm": m["algorithm"],
                    "target": m["target"],
                    "mae": metrics.get("mae", 0),
                    "dir_acc": metrics.get("dir_acc", 0)
                })
            except Exception:
                pass

        # 2. Live prediction metrics
        results = self.db.get_prediction_results()
        if results:
            df = pd.DataFrame(results)
            live_acc = {}
            for h in [1, 3, 5, 7]:
                col = f"direction_correct_{h}d"
                if col in df.columns:
                    live_acc[f"{h}d"] = df[col].mean()
        else:
            live_acc = {"1d": None, "3d": None, "5d": None, "7d": None}

        return {
            "model_stats": model_stats,
            "live_accuracy": live_acc
        }

if __name__ == "__main__":
    evaluator = Evaluator()
    evaluator.evaluate_pending_predictions()
    print(evaluator.get_system_metrics())
