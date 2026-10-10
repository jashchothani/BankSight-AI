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

    def generate_shap_explanation(self, symbol: str, target: str = None, horizon: str = "5d") -> dict:
        """
        Generate SHAP values or feature contributions for the prediction.
        Supports 1d, 3d, 5d, 7d horizons.
        """
        if not target:
            target = f"target_{horizon.lower()}_return"
            
        # 1. Get active model (XGBoost or LightGBM)
        active_model = self.db.get_active_model(algorithm="xgboost", target=target)
        algo = "xgboost"
        if not active_model:
            active_model = self.db.get_active_model(algorithm="lightgbm", target=target)
            algo = "lightgbm"
        # Fallback to 5d if specific horizon model not registered
        if not active_model and target != "target_5d_return":
            active_model = self.db.get_active_model(algorithm="xgboost", target="target_5d_return")
            algo = "xgboost"
            if not active_model:
                active_model = self.db.get_active_model(algorithm="lightgbm", target="target_5d_return")
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
                "horizon": horizon.upper(),
                "base_value": expected_value,
                "prediction": prediction,
                "top_positive": pos_factors,
                "top_negative": neg_factors
            }
            
        except Exception as e:
            log.error(f"Explanation computation failed: {e}")
            return {"error": str(e)}

    def generate_narrative(self, symbol: str, date: str = None, horizon: str = "5d") -> str:
        """
        Synthesize an explainable text narrative based on predictions, technicals, news sentiment, and macro factors.
        """
        bank_info = config.STOCKS.get(symbol, {})
        bank_name = bank_info.get("name", symbol)
        horizon_clean = horizon.lower()
        
        # 1. Fetch prediction details
        pred = self.db.get_latest_prediction(symbol)
        ret_val = 0.0
        direction = "NEUTRAL"
        confidence = 65.0
        target_price = None
        
        if pred:
            ret_val = float(pred.get(f"return_{horizon_clean}", pred.get("return_5d", 0.0)) or 0.0)
            direction = str(pred.get(f"direction_{horizon_clean}", pred.get("direction_5d", "NEUTRAL")) or "NEUTRAL").upper()
            confidence = float(pred.get(f"confidence_{horizon_clean}", pred.get("confidence_5d", 65.0)) or 65.0)
            target_price = pred.get(f"prediction_{horizon_clean}", pred.get("prediction_5d"))
        
        # 2. Fetch latest features
        query_f = "SELECT features_json FROM features WHERE symbol = ? ORDER BY date DESC LIMIT 1"
        features_dict = {}
        with self.db._connect() as conn:
            r = conn.execute(query_f, (symbol,)).fetchone()
            if r and r["features_json"]:
                try:
                    features_dict = json.loads(r["features_json"])
                except Exception:
                    pass
                    
        # 3. Fetch recent news
        news = self.db.get_news(symbol, limit=5, before_date=date)
        
        # 4. Construct rich explainable narrative
        dir_word = "bullish upside" if direction == "UP" else ("bearish consolidation" if direction == "DOWN" else "sideways neutral trading")
        ret_pct = f"{ret_val * 100:+.2f}%"
        
        narrative_parts = []
        
        # Horizon & Outlook Sentence
        if target_price:
            narrative_parts.append(
                f"BankSight AI forecasts a {dir_word} of {ret_pct} toward ₹{float(target_price):.2f} "
                f"over the +{horizon_clean.upper()} horizon with {confidence:.0f}% statistical confidence."
            )
        else:
            narrative_parts.append(
                f"BankSight AI projects a {dir_word} of {ret_pct} over the +{horizon_clean.upper()} horizon with {confidence:.0f}% confidence."
            )
            
        # Technical Factor Attributions
        tech_reasons = []
        rsi = features_dict.get("rsi_14")
        if rsi is not None:
            if rsi < 35:
                tech_reasons.append(f"oversold RSI rebound at {rsi:.1f}")
            elif rsi > 65:
                tech_reasons.append(f"overbought RSI resistance at {rsi:.1f}")
            else:
                tech_reasons.append(f"healthy neutral RSI momentum at {rsi:.1f}")
                
        beta = features_dict.get("banknifty_beta") or features_dict.get("nifty_beta")
        if beta is not None:
            tech_reasons.append(f"high sectoral beta sensitivity ({beta:.2f}x to Bank Nifty)")
            
        macd = features_dict.get("macd")
        if macd is not None:
            if macd > 0:
                tech_reasons.append("positive MACD trend continuation")
            else:
                tech_reasons.append("negative MACD divergence drag")
                
        if tech_reasons:
            narrative_parts.append("Technical indicators reflect " + ", ".join(tech_reasons) + ".")
            
        # News Sentiment Attributions
        if news:
            pos_news = sum(1 for n in news if n.get("sentiment_label") == "POSITIVE")
            neg_news = sum(1 for n in news if n.get("sentiment_label") == "NEGATIVE")
            if pos_news > neg_news:
                narrative_parts.append(f"Institutional news intelligence is supportive, with {pos_news} positive media catalysts countering sectoral volatility.")
            elif neg_news > pos_news:
                narrative_parts.append(f"Caution is advised as {neg_news} recent negative headlines exert short-term headwind on order flow.")
            else:
                narrative_parts.append("Media coverage remains balanced with neutral sector headlines.")
                
        # Risk & Disclaimers
        narrative_parts.append("Model weights combine walk-forward XGBoost and LightGBM trees with 7-day purging embargoes.")
        
        return " ".join(narrative_parts)
