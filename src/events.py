"""
BankSight AI — Historical Event Similarity Engine
=================================================
Finds historical situations similar to the current market state using
cosine similarity on a specialized feature vector.
"""

import logging
import json
import numpy as np
import pandas as pd
from datetime import datetime
from sklearn.metrics.pairwise import cosine_similarity

import config
from src.data import Database

log = logging.getLogger("EVENTS")

class EventSimilarityEngine:
    def __init__(self, db: Database = None):
        self.db = db or Database()

    def _build_similarity_vector(self, row: pd.Series) -> np.ndarray:
        """
        Extract specific features to form the state vector for similarity comparison.
        We focus on momentum, volatility, and market-relative performance.
        """
        keys = [
            "return_5d",
            "return_20d",
            "volatility_20d",
            "rsi",
            "macd_hist",
            "bb_position",
            "rel_return_nifty_5d",
            "rel_return_banknifty_5d",
            "vix_level"
        ]
        
        vec = []
        for k in keys:
            val = row.get(k, np.nan)
            if pd.isna(val) or val is None:
                val = 0.0 # fallback
            # Normalize some values for scale
            if k == "rsi": val = (val - 50) / 50.0  # -1 to 1
            elif k == "vix_level": val = val / 20.0 # rough scaling
            vec.append(float(val))
            
        return np.array(vec, dtype=float).reshape(1, -1)

    def find_similar_events(self, symbol: str, current_date: str) -> dict:
        """
        Given a symbol and a date, find the top N most similar historical dates.
        Returns a dictionary with similar dates and aggregated outcome statistics.
        """
        # Load features for this symbol
        query = "SELECT date, features_json FROM features WHERE symbol = ? ORDER BY date"
        with self.db._connect() as conn:
            rows = conn.execute(query, (symbol,)).fetchall()
            
        if not rows:
            return {"error": "No feature data available"}

        # Build dataframe of features
        data = []
        target_row = None
        target_idx = -1
        
        for i, r in enumerate(rows):
            date = r["date"]
            try:
                feats = json.loads(r["features_json"])
                feats["date"] = date
                data.append(feats)
                if date.split()[0] == current_date.split()[0]:
                    target_row = feats
                    target_idx = i
            except Exception:
                pass
                
        if target_row is None:
            # If current date not found, use the most recent one
            target_row = data[-1]
            target_idx = len(data) - 1
            current_date = target_row["date"]
            
        df = pd.DataFrame(data)
        
        # We only want to search *history* (strictly before current_date) to prevent look-ahead,
        # but since we are just doing similarity to explain the present, we can search all history
        # except the current date itself. However, to be strictly correct, we should only compare
        # against dates at least 7 days in the past (so their 7d outcomes are known).
        
        search_df = df.iloc[:target_idx - 7] if target_idx >= 7 else pd.DataFrame()
        
        if search_df.empty or len(search_df) < 50:
            return {"error": "Not enough historical data for comparison"}
            
        target_vec = self._build_similarity_vector(pd.Series(target_row))
        
        similarities = []
        for idx, row in search_df.iterrows():
            hist_vec = self._build_similarity_vector(row)
            sim = cosine_similarity(target_vec, hist_vec)[0][0]
            similarities.append((row["date"], sim, row))
            
        # Sort by similarity, descending
        similarities.sort(key=lambda x: x[1], reverse=True)
        top_n = similarities[:config.EVENT_SIMILARITY_TOP_N]
        
        # We need the outcomes for these historical dates.
        # We fetch the actual prices from market_data to calculate exact returns
        outcomes_1d = []
        outcomes_5d = []
        outcomes_7d = []
        similar_events = []
        
        for hist_date, sim, row in top_n:
            if sim < config.EVENT_MIN_SIMILARITY:
                continue
                
            # We already have targets in the feature JSON if they were computed
            ret_1d = row.get("target_1d_return")
            ret_5d = row.get("target_5d_return")
            ret_7d = row.get("target_7d_return")
            
            if ret_1d is not None and not pd.isna(ret_1d): outcomes_1d.append(ret_1d)
            if ret_5d is not None and not pd.isna(ret_5d): outcomes_5d.append(ret_5d)
            if ret_7d is not None and not pd.isna(ret_7d): outcomes_7d.append(ret_7d)
            
            similar_events.append({
                "date": hist_date,
                "similarity": float(sim),
                "return_5d": float(ret_5d) if ret_5d is not None else None
            })
            
        if not similar_events:
            return {"message": "No highly similar historical events found."}
            
        # Compute statistics
        stats = {
            "current_date": current_date,
            "similar_events_count": len(similar_events),
            "events": similar_events
        }
        
        if outcomes_5d:
            stats["avg_return_5d"] = float(np.mean(outcomes_5d))
            stats["median_return_5d"] = float(np.median(outcomes_5d))
            stats["positive_outcome_rate_5d"] = float(np.mean([1 if x > 0 else 0 for x in outcomes_5d]))
            stats["negative_outcome_rate_5d"] = float(np.mean([1 if x < 0 else 0 for x in outcomes_5d]))
            
        return stats
