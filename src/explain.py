"""
BankSight AI — Explainability
==============================
Generates SHAP explanations for predictions to understand "Why did it move?"
"""

import logging
import json
import joblib
import pandas as pd
import numpy as np
try:
    import shap
    SHAP_AVAILABLE = True
except ImportError:
    SHAP_AVAILABLE = False

import config
from src.data import Database

log = logging.getLogger("EXPLAIN")

class Explainer:
    def __init__(self, db: Database = None):
        self.db = db or Database()

    def generate_shap_explanation(self, symbol: str, target: str = "target_5d_return") -> dict:
        """
        Generate SHAP values or feature contributions for the prediction.
        """
        # 1. Get active model (XGBoost or LightGBM)
        active_model = self.db.get_active_model(algorithm="xgboost", target=target)
        algo = "xgboost"
        if not active_model:
            active_model = self.db.get_active_model(algorithm="lightgbm", target=target)
            algo = "lightgbm"
        if not active_model:
            return {"error": "No model available for explanation."}

        try:
            data = joblib.load(active_model["file_path"])
            model = data["model"]
            features = data["features"]
        except Exception as e:
            return {"error": f"Failed to load model: {e}"}

        # 2. Get latest features
        query = "SELECT * FROM features WHERE symbol = ? ORDER BY date DESC LIMIT 1"
        with self.db._connect() as conn:
            row = conn.execute(query, (symbol,)).fetchone()
            
        if not row:
            return {"error": "No features available."}

        features_dict = json.loads(row["features_json"])
        
        # Prepare input vector
        X = pd.DataFrame(index=[0], columns=features)
        for f in features:
            X[f] = features_dict.get(f, 0.0)
        X = X.fillna(0.0)

        # 3. Compute contributions (SHAP values)
        try:
            sv = None
            expected_value = 0.0
            prediction = float(model.predict(X)[0])
            
            if SHAP_AVAILABLE:
                try:
                    explainer = shap.TreeExplainer(model)
                    shap_values = explainer.shap_values(X)
                    sv = shap_values[0]
                    expected_value = float(explainer.expected_value)
                except Exception as e:
                    log.warning(f"SHAP library failed, falling back to native: {e}")
                    
            if sv is None:
                # Fallback to native contributions
                if algo == "xgboost":
                    import xgboost as xgb
                    booster = model.get_booster()
                    dmat = xgb.DMatrix(X)
                    contribs = booster.predict(dmat, pred_contribs=True)[0]
                    sv = contribs[:-1]
                    expected_value = float(contribs[-1])
                elif algo == "lightgbm":
                    contribs = model.predict(X, pred_contrib=True)[0]
                    sv = contribs[:-1]
                    expected_value = float(contribs[-1])
                else:
                    importances = getattr(model, "feature_importances_", None)
                    if importances is not None:
                        sv = []
                        for idx, f in enumerate(features):
                            val = float(X[f].iloc[0])
                            sv.append(importances[idx] * np.sign(val) * min(abs(val), 2.0))
                        expected_value = prediction - sum(sv)
                    else:
                        return {"error": "No explainability method available."}
            
            # Extract top factors
            feature_impacts = []
            for i, f in enumerate(features):
                impact = float(sv[i])
                if abs(impact) > 1e-6: # Ignore tiny impacts
                    feature_impacts.append({
                        "feature": f,
                        "value": float(X[f].iloc[0]),
                        "impact": impact
                    })
                    
            # Sort by absolute impact
            feature_impacts.sort(key=lambda x: abs(x["impact"]), reverse=True)
            
            # Separate pos/neg
            pos_factors = [f for f in feature_impacts if f["impact"] > 0][:5]
            neg_factors = [f for f in feature_impacts if f["impact"] < 0][:5]
            
            return {
                "base_value": expected_value,
                "prediction": prediction,
                "top_positive": pos_factors,
                "top_negative": neg_factors
            }
            
        except Exception as e:
            log.error(f"Explanation computation failed: {e}")
            return {"error": str(e)}

    def generate_narrative(self, symbol: str, date: str) -> str:
        """
        Synthesize a text narrative based on market data, news, and events.
        """
        # In a full implementation, this could use an LLM.
        # For now, it's a rule-based template filler.
        
        news = self.db.get_news(symbol, limit=5, before_date=date)
        events = self.db.get_events(symbol, limit=1)
        
        narrative = f"On {date}, {config.STOCKS.get(symbol, {}).get('name', symbol)} "
        narrative += "was influenced by a mix of factors. "
        
        if news:
            pos = sum(1 for n in news if n["sentiment_label"] == "POSITIVE")
            neg = sum(1 for n in news if n["sentiment_label"] == "NEGATIVE")
            
            if pos > neg:
                narrative += "Recent news sentiment was predominantly positive. "
            elif neg > pos:
                narrative += "Recent news sentiment was predominantly negative. "
                
        return narrative
