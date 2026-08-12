"""
BankSight AI — Configuration
=============================
Central configuration for the entire system.
All stock definitions, data providers, feature parameters, model hyperparameters,
and runtime settings are defined here.
"""

import os
import logging
from pathlib import Path
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Load .env (if present)
# ---------------------------------------------------------------------------
load_dotenv()

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
PREDICTIONS_DIR = DATA_DIR / "predictions"
MODELS_DIR = BASE_DIR / "models"
DB_DIR = BASE_DIR / "db"
DASHBOARD_DIR = BASE_DIR / "dashboard"

# Create directories
for d in [RAW_DIR, PROCESSED_DIR, PREDICTIONS_DIR, MODELS_DIR, DB_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DB_PATH = DB_DIR / "banksight.db"

# ---------------------------------------------------------------------------
# Mode
# ---------------------------------------------------------------------------
MODE = "live"

def is_demo_mode():
    """Strictly run in live mode (no demo mock fallback allowed)."""
    return False

# ---------------------------------------------------------------------------
# Data Providers
# ---------------------------------------------------------------------------
DATA_PROVIDER = os.getenv("DATA_PROVIDER", "yfinance")
NEWS_PROVIDER = os.getenv("NEWS_PROVIDER", "yfinance")
MACRO_PROVIDER = os.getenv("MACRO_PROVIDER", "static")
FUNDAMENTALS_PROVIDER = os.getenv("FUNDAMENTALS_PROVIDER", "yfinance")

# API Keys (never hard-coded)
MARKET_DATA_API_KEY = os.getenv("MARKET_DATA_API_KEY", "")
NEWS_API_KEY = os.getenv("NEWS_API_KEY", "")
MACRO_API_KEY = os.getenv("MACRO_API_KEY", "")

# SMTP Configuration for Email Alerts
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "alerts@banksight.ai")

# ---------------------------------------------------------------------------
# Stocks — Configurable list of Indian banking stocks
# ---------------------------------------------------------------------------
STOCKS = {
    "HDFCBANK": {
        "ticker": "HDFCBANK.NS",
        "name": "HDFC Bank",
        "type": "private",
        "weight_nifty": "high",
    },
    "ICICIBANK": {
        "ticker": "ICICIBANK.NS",
        "name": "ICICI Bank",
        "type": "private",
        "weight_nifty": "high",
    },
    "SBIN": {
        "ticker": "SBIN.NS",
        "name": "State Bank of India",
        "type": "psu",
        "weight_nifty": "high",
    },
    "AXISBANK": {
        "ticker": "AXISBANK.NS",
        "name": "Axis Bank",
        "type": "private",
        "weight_nifty": "medium",
    },
    "KOTAKBANK": {
        "ticker": "KOTAKBANK.NS",
        "name": "Kotak Mahindra Bank",
        "type": "private",
        "weight_nifty": "medium",
    },
}

# Helper: list of symbols
STOCK_SYMBOLS = list(STOCKS.keys())
STOCK_TICKERS = {s: info["ticker"] for s, info in STOCKS.items()}

# ---------------------------------------------------------------------------
# Market Indices
# ---------------------------------------------------------------------------
INDICES = {
    "NIFTY50": {"ticker": "^NSEI", "name": "NIFTY 50"},
    "BANKNIFTY": {"ticker": "^NSEBANK", "name": "Bank NIFTY"},
    "INDIAVIX": {"ticker": "^INDIAVIX", "name": "India VIX"},
}

# Currency
USDINR_TICKER = "USDINR=X"

# ---------------------------------------------------------------------------
# Historical Data
# ---------------------------------------------------------------------------
HISTORY_START = os.getenv("HISTORY_START", "2015-01-01")
HISTORY_PERIOD = os.getenv("HISTORY_PERIOD", "max")  # yfinance period param

# ---------------------------------------------------------------------------
# Feature Engineering
# ---------------------------------------------------------------------------
SMA_WINDOWS = [5, 10, 20, 50]
EMA_WINDOWS = [12, 26]
RSI_WINDOW = 14
ATR_WINDOW = 14
BOLLINGER_WINDOW = 20
BOLLINGER_STD = 2
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9
VOLATILITY_WINDOW = 20
VOLUME_MA_WINDOW = 20
MOMENTUM_WINDOWS = [5, 10, 20]
ROLLING_RETURN_WINDOWS = [1, 3, 5, 10, 20]

# Targets
TARGET_HORIZONS = [1, 3, 5, 7]  # trading days
DIRECTION_THRESHOLD = 0.005  # ±0.5% considered NEUTRAL

# ---------------------------------------------------------------------------
# News / NLP
# ---------------------------------------------------------------------------
NEWS_LOOKBACK_DAYS = 30
NEWS_SENTIMENT_WINDOWS = [1, 3, 7]  # days for rolling sentiment

NEWS_CATEGORIES = [
    "RBI", "INTEREST_RATE", "RESULTS", "NPA", "NIM",
    "MANAGEMENT", "REGULATION", "FRAUD", "M_AND_A",
    "CREDIT_RATING", "MACRO", "GLOBAL_MARKET", "OTHER",
]

# Banking-specific sentiment words (augment VADER)
FINANCIAL_LEXICON = {
    # Positive
    "upgrade": 2.0, "outperform": 1.8, "beat": 1.5, "exceed": 1.5,
    "growth": 1.2, "profit": 1.3, "dividend": 1.0, "recovery": 1.5,
    "bullish": 1.8, "rally": 1.5, "breakout": 1.3, "strong": 1.0,
    "expansion": 1.2, "robust": 1.3, "improved": 1.2, "surged": 1.5,
    "casa improvement": 1.5, "nim expansion": 1.5, "credit growth": 1.2,
    "rate cut": 1.3, "capital adequacy": 1.0,
    # Negative
    "downgrade": -2.0, "underperform": -1.8, "miss": -1.5, "default": -2.5,
    "fraud": -3.0, "scam": -3.0, "npa": -1.8, "bad loan": -2.0,
    "slippage": -1.5, "provision": -1.2, "bearish": -1.8, "crash": -2.0,
    "sell-off": -1.8, "decline": -1.2, "weak": -1.0, "loss": -1.5,
    "rate hike": -1.0, "inflation": -0.8, "stress": -1.3,
    "write-off": -1.8, "restructuring": -1.0, "liquidity crunch": -2.0,
}

# ---------------------------------------------------------------------------
# Event Similarity
# ---------------------------------------------------------------------------
EVENT_SIMILARITY_TOP_N = 10
EVENT_MIN_SIMILARITY = 0.7

# ---------------------------------------------------------------------------
# Model Training
# ---------------------------------------------------------------------------
# Walk-forward validation
TRAIN_MIN_DAYS = 504  # ~2 years of trading days
VALIDATION_DAYS = 126  # ~6 months
TEST_DAYS = 63  # ~3 months
WALK_FORWARD_STEP = 252  # step forward by ~1 year

# Model hyperparameters
XGBOOST_PARAMS = {
    "n_estimators": 50,
    "max_depth": 6,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 5,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
    "random_state": 42,
}

LIGHTGBM_PARAMS = {
    "n_estimators": 50,
    "max_depth": 6,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_samples": 20,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
    "random_state": 42,
    "verbose": -1,
}

RANDOM_FOREST_PARAMS = {
    "n_estimators": 50,
    "max_depth": 10,
    "min_samples_split": 10,
    "min_samples_leaf": 5,
    "random_state": 42,
    "n_jobs": 1,
}

# ---------------------------------------------------------------------------
# Prediction
# ---------------------------------------------------------------------------
PREDICTION_UPDATE_INTERVAL = 60  # seconds (for real-time mode)
RETRAIN_SCHEDULE = "daily"  # "daily", "weekly"

# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------
FLASK_HOST = os.getenv("FLASK_HOST", "0.0.0.0")
FLASK_PORT = int(os.getenv("FLASK_PORT", "5000"))
FLASK_DEBUG = os.getenv("FLASK_DEBUG", "true").lower() == "true"

# ---------------------------------------------------------------------------
# Kafka (optional)
# ---------------------------------------------------------------------------
KAFKA_ENABLED = os.getenv("KAFKA_ENABLED", "false").lower() == "true"
KAFKA_BOOTSTRAP_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
KAFKA_TOPIC_MARKET = os.getenv("KAFKA_TOPIC_MARKET", "banksight.market")
KAFKA_TOPIC_NEWS = os.getenv("KAFKA_TOPIC_NEWS", "banksight.news")

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "[%(name)s] %(message)s"

def setup_logging():
    """Configure logging for the entire application."""
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
        format=LOG_FORMAT,
    )
    # Suppress noisy third-party loggers
    for noisy in ["urllib3", "yfinance", "peewee", "matplotlib"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)

setup_logging()
