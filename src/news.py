"""
BankSight AI — News & NLP Engine
=================================
Fetches news, computes VADER sentiment augmented with a financial lexicon,
and classifies news into banking-specific topics.
"""

import logging
import nltk
from nltk.sentiment.vader import SentimentIntensityAnalyzer
from datetime import datetime, timedelta
import pandas as pd
import json

import config
from src.data import Database, get_news_provider

log = logging.getLogger("NEWS")

class NLPEngine:
    def __init__(self, db: Database = None):
        self.db = db or Database()
        self.provider = get_news_provider()
        self._ensure_nltk_data()
        
        self.sia = SentimentIntensityAnalyzer()
        # Update VADER lexicon with our financial terminology
        self.sia.lexicon.update(config.FINANCIAL_LEXICON)

    def _ensure_nltk_data(self):
        try:
            nltk.data.find('sentiment/vader_lexicon.zip')
        except LookupError:
            nltk.download('vader_lexicon', quiet=True)

    def classify_category(self, text: str) -> str:
        """Classify a headline into a banking topic."""
        text_lower = text.lower()
        
        if any(w in text_lower for w in ["rbi", "shaktikanta", "das", "central bank"]):
            return "RBI"
        if any(w in text_lower for w in ["rate", "repo", "crr", "slr", "hike", "cut"]):
            return "INTEREST_RATE"
        if any(w in text_lower for w in ["q1", "q2", "q3", "q4", "quarter", "results", "profit", "loss", "pat"]):
            return "RESULTS"
        if any(w in text_lower for w in ["npa", "bad loan", "slippage", "provision", "write-off"]):
            return "NPA"
        if any(w in text_lower for w in ["nim", "margin", "yield"]):
            return "NIM"
        if any(w in text_lower for w in ["ceo", "md", "board", "management", "director", "resigns", "appoint"]):
            return "MANAGEMENT"
        if any(w in text_lower for w in ["fraud", "scam", "cbi", "ed", "investigation"]):
            return "FRAUD"
        if any(w in text_lower for w in ["merger", "acquire", "acquisition", "stake"]):
            return "M_AND_A"
        if any(w in text_lower for w in ["rating", "moody", "fitch", "s&p", "crisil", "icra"]):
            return "CREDIT_RATING"
            
        return "OTHER"

    def calculate_importance(self, text: str, source: str) -> float:
        """Estimate the importance of a news item (0.0 to 1.0)."""
        text_lower = text.lower()
        importance = 0.5 # base
        
        # High impact keywords
        if any(w in text_lower for w in ["fraud", "resigns", "merger", "rbi curbs", "penalty"]):
            importance += 0.3
            
        # Reputable sources carry more weight (simplified logic)
        reputable = ["reuters", "bloomberg", "mint", "economic times", "moneycontrol", "business standard"]
        if any(s in source.lower() for s in reputable):
            importance += 0.1
            
        return min(1.0, importance)

    def analyze_news(self, articles: list[dict]) -> list[dict]:
        """Process raw articles to add sentiment and classification."""
        processed = []
        for article in articles:
            headline = article.get("headline", "")
            if not headline:
                continue
                
            scores = self.sia.polarity_scores(headline)
            compound = scores["compound"]
            
            if compound > 0.15:
                label = "POSITIVE"
            elif compound < -0.15:
                label = "NEGATIVE"
            else:
                label = "NEUTRAL"
                
            category = self.classify_category(headline)
            importance = self.calculate_importance(headline, article.get("source", ""))
            
            article["sentiment_score"] = compound
            article["sentiment_label"] = label
            article["category"] = category
            article["importance"] = importance
            processed.append(article)
            
        return processed

    def get_news_features_for_date(self, symbol: str, target_date: datetime.date) -> dict:
        """
        Aggregate news sentiment up to a specific date for feature engineering.
        Ensures no look-ahead by only using news <= target_date.
        """
        # Get news for the last N days before target_date
        start_date = (target_date - timedelta(days=max(config.NEWS_SENTIMENT_WINDOWS))).isoformat()
        end_date = (target_date + timedelta(days=1)).isoformat() # up to midnight of target date
        
        # This is a bit inefficient for bulk processing, but fine for inference
        # For training, it's better to do rolling aggregations in pandas
        query = """
            SELECT * FROM news 
            WHERE symbol = ? AND timestamp >= ? AND timestamp < ?
            ORDER BY timestamp DESC
        """
        with self.db._connect() as conn:
            rows = conn.execute(query, (symbol, start_date, end_date)).fetchall()
            
        if not rows:
            return {}
            
        df = pd.DataFrame([dict(r) for r in rows])
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["days_old"] = (pd.to_datetime(target_date) - df["timestamp"].dt.date).dt.days
        
        features = {}
        for w in config.NEWS_SENTIMENT_WINDOWS:
            w_df = df[df["days_old"] < w]
            if not w_df.empty:
                # Weighted sentiment (importance * sentiment)
                weighted_sent = (w_df["sentiment_score"] * w_df["importance"]).mean()
                features[f"news_sentiment_{w}d"] = weighted_sent
                features[f"news_count_{w}d"] = len(w_df)
                features[f"news_pos_count_{w}d"] = len(w_df[w_df["sentiment_label"] == "POSITIVE"])
                features[f"news_neg_count_{w}d"] = len(w_df[w_df["sentiment_label"] == "NEGATIVE"])
            else:
                features[f"news_sentiment_{w}d"] = 0.0
                features[f"news_count_{w}d"] = 0
                features[f"news_pos_count_{w}d"] = 0
                features[f"news_neg_count_{w}d"] = 0
                
        return features

def update_and_analyze_news():
    db = Database()
    nlp = NLPEngine(db)
    provider = get_news_provider()
    
    for symbol in config.STOCK_SYMBOLS:
        log.info(f"Fetching news for {symbol}...")
        raw_articles = provider.fetch_news(symbol, days=config.NEWS_LOOKBACK_DAYS)
        if raw_articles:
            processed = nlp.analyze_news(raw_articles)
            db.save_news(processed)
            log.info(f"Saved {len(processed)} analyzed articles for {symbol}")
