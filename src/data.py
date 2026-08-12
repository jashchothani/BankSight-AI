"""
BankSight AI — Data Layer
==========================
Data providers (adapters), SQLite database, and data quality management.

Provider Architecture:
    DataProvider (abstract)
    ├── MarketDataProvider   → OHLCV for stocks + indices
    ├── NewsProvider         → News headlines + metadata
    ├── MacroProvider        → RBI rates, bond yields, USD/INR
    └── FundamentalsProvider → Banking fundamentals (ROE, NIM, NPA, etc.)

Every record is tagged with a DataQuality flag:
    REAL / DEMO / SIMULATED / MISSING
"""

import sqlite3
import logging
import json
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

import config

log = logging.getLogger("DATA")

# ═══════════════════════════════════════════════════════════════════════════
# Data Quality Enum
# ═══════════════════════════════════════════════════════════════════════════

class DataQuality:
    REAL = "REAL"
    DEMO = "DEMO"
    SIMULATED = "SIMULATED"
    MISSING = "MISSING"


# ═══════════════════════════════════════════════════════════════════════════
# Abstract Providers
# ═══════════════════════════════════════════════════════════════════════════

class MarketDataProvider(ABC):
    @abstractmethod
    def fetch_historical(self, ticker: str, start: str, end: str = None) -> pd.DataFrame:
        """Return DataFrame with columns: Date, Open, High, Low, Close, Volume."""
        ...

    @abstractmethod
    def fetch_latest(self, ticker: str) -> dict:
        """Return latest available quote as dict."""
        ...

    @abstractmethod
    def provider_name(self) -> str:
        ...


class NewsProvider(ABC):
    @abstractmethod
    def fetch_news(self, symbol: str, days: int = 30) -> list[dict]:
        """Return list of dicts with: headline, source, timestamp, url."""
        ...

    @abstractmethod
    def provider_name(self) -> str:
        ...


class MacroProvider(ABC):
    @abstractmethod
    def get_macro_data(self) -> pd.DataFrame:
        """Return DataFrame with macro indicators over time."""
        ...

    @abstractmethod
    def provider_name(self) -> str:
        ...


class FundamentalsProvider(ABC):
    @abstractmethod
    def get_fundamentals(self, symbol: str) -> dict:
        """Return dict of fundamental metrics."""
        ...

    @abstractmethod
    def provider_name(self) -> str:
        ...


# ═══════════════════════════════════════════════════════════════════════════
# YFinance Market Data Provider
# ═══════════════════════════════════════════════════════════════════════════

class YFinanceMarketProvider(MarketDataProvider):
    """Free market data via yfinance. No API key required."""

    def __init__(self):
        try:
            import yfinance  # noqa: F401
            self._available = True
        except ImportError:
            self._available = False
            log.warning("yfinance not installed — market data unavailable")

    def provider_name(self) -> str:
        return "yfinance"

    def fetch_historical(self, ticker: str, start: str, end: str = None) -> pd.DataFrame:
        if not self._available:
            return pd.DataFrame()
        import yfinance as yf
        try:
            log.info(f"Downloading {ticker} from {start}" + (f" to {end}" if end else ""))
            t = yf.Ticker(ticker)
            kwargs = {"start": start}
            if end:
                kwargs["end"] = end
            df = t.history(**kwargs)
            if df.empty:
                log.warning(f"No data returned for {ticker}")
                return pd.DataFrame()
            # Normalize columns
            df = df.reset_index()
            df = df.rename(columns={
                "Date": "date",
                "Open": "open",
                "High": "high",
                "Low": "low",
                "Close": "close",
                "Volume": "volume",
            })
            # Ensure date is date only (no timezone)
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None).dt.date
            # Keep only needed columns
            keep = ["date", "open", "high", "low", "close", "volume"]
            available = [c for c in keep if c in df.columns]
            df = df[available].copy()
            df["data_quality"] = DataQuality.REAL
            log.info(f"Downloaded {len(df)} rows for {ticker}")
            return df
        except Exception as e:
            log.error(f"Failed to fetch {ticker}: {e}")
            return pd.DataFrame()

    def fetch_latest(self, ticker: str) -> dict:
        if not self._available:
            return {}
        import yfinance as yf
        try:
            t = yf.Ticker(ticker)
            info = t.fast_info
            return {
                "price": float(info.get("lastPrice", info.get("previousClose", 0))),
                "previous_close": float(info.get("previousClose", 0)),
                "open": float(info.get("open", 0)),
                "day_high": float(info.get("dayHigh", 0)),
                "day_low": float(info.get("dayLow", 0)),
                "volume": int(info.get("lastVolume", 0)),
                "market_cap": float(info.get("marketCap", 0)),
                "data_quality": DataQuality.REAL,
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            log.error(f"Failed to fetch latest for {ticker}: {e}")
            return {}


# ═══════════════════════════════════════════════════════════════════════════
# YFinance News Provider
# ═══════════════════════════════════════════════════════════════════════════

class YFinanceNewsProvider(NewsProvider):
    """News headlines from yfinance (Yahoo Finance)."""

    def __init__(self):
        try:
            import yfinance  # noqa: F401
            self._available = True
        except ImportError:
            self._available = False

    def provider_name(self) -> str:
        return "yfinance"

    def fetch_news(self, symbol: str, days: int = 30) -> list[dict]:
        if not self._available:
            return []
        import yfinance as yf
        try:
            ticker_str = config.STOCK_TICKERS.get(symbol, symbol)
            t = yf.Ticker(ticker_str)
            raw_news = t.news if hasattr(t, "news") else []
            if not raw_news:
                return []
            articles = []
            cutoff = datetime.now() - timedelta(days=days)
            for item in raw_news:
                # yfinance news format varies by version
                content = item.get("content", item) if isinstance(item, dict) else item
                if isinstance(content, dict):
                    pub_ts = content.get("pubDate", content.get("providerPublishTime", ""))
                else:
                    continue

                # Parse timestamp
                if isinstance(pub_ts, (int, float)):
                    ts = datetime.fromtimestamp(pub_ts)
                elif isinstance(pub_ts, str) and pub_ts:
                    try:
                        ts = pd.to_datetime(pub_ts).to_pydatetime()
                        if ts.tzinfo:
                            ts = ts.replace(tzinfo=None)
                    except Exception:
                        ts = datetime.now()
                else:
                    ts = datetime.now()

                if ts < cutoff:
                    continue

                headline = content.get("title", content.get("headline", ""))
                source = content.get("provider", {})
                if isinstance(source, dict):
                    source = source.get("displayName", "Yahoo Finance")

                articles.append({
                    "headline": headline,
                    "source": str(source) if source else "Yahoo Finance",
                    "timestamp": ts.isoformat(),
                    "url": content.get("link", content.get("url", "")),
                    "symbol": symbol,
                    "data_quality": DataQuality.REAL,
                })
            log.info(f"Fetched {len(articles)} news articles for {symbol}")
            return articles
        except Exception as e:
            log.error(f"Failed to fetch news for {symbol}: {e}")
            return []


class NewsAPIDotOrgProvider(NewsProvider):
    """News headlines from newsapi.org API."""

    def __init__(self):
        self.api_key = getattr(config, "NEWS_API_KEY", "")

    def provider_name(self) -> str:
        return "newsapi"

    def fetch_news(self, symbol: str, days: int = 30) -> list[dict]:
        if not self.api_key:
            return []
        import requests
        try:
            bank_info = config.STOCKS.get(symbol, {})
            bank_name = bank_info.get("name", symbol)
            url = "https://newsapi.org/v2/everything"
            params = {
                "q": f'"{bank_name}" OR "{symbol}"',
                "language": "en",
                "sortBy": "publishedAt",
                "pageSize": 20,
                "apiKey": self.api_key
            }
            res = requests.get(url, params=params, timeout=10)
            if res.status_code != 200:
                log.warning(f"NewsAPI query failed with status {res.status_code}")
                return []
            
            data = res.json()
            raw_articles = data.get("articles", [])
            articles = []
            cutoff = datetime.now() - timedelta(days=days)
            for item in raw_articles:
                pub_time_str = item.get("publishedAt", "")
                if not pub_time_str:
                    continue
                try:
                    ts = pd.to_datetime(pub_time_str).to_pydatetime()
                    if ts.tzinfo:
                        ts = ts.replace(tzinfo=None)
                except Exception:
                    ts = datetime.now()
                
                if ts < cutoff:
                    continue
                    
                articles.append({
                    "headline": item.get("title", ""),
                    "source": item.get("source", {}).get("name", "NewsAPI"),
                    "timestamp": ts.isoformat(),
                    "url": item.get("url", ""),
                    "symbol": symbol,
                    "data_quality": DataQuality.REAL,
                })
            log.info(f"Fetched {len(articles)} news articles from NewsAPI for {symbol}")
            return articles
        except Exception as e:
            log.error(f"Failed to fetch from NewsAPI for {symbol}: {e}")
            return []


class MultiSourceNewsProvider(NewsProvider):
    """Aggregates and merges news from multiple API sources (yfinance + newsapi)."""

    def __init__(self):
        self.providers = [
            YFinanceNewsProvider(),
            NewsAPIDotOrgProvider()
        ]

    def provider_name(self) -> str:
        return "multi"

    def fetch_news(self, symbol: str, days: int = 30) -> list[dict]:
        combined_articles = []
        seen_headlines = set()

        for provider in self.providers:
            try:
                articles = provider.fetch_news(symbol, days=days)
                for a in articles:
                    clean_hl = "".join(c for c in a["headline"].lower() if c.isalnum())
                    if clean_hl not in seen_headlines:
                        seen_headlines.add(clean_hl)
                        combined_articles.append(a)
            except Exception as e:
                log.error(f"Provider {provider.provider_name()} failed for {symbol}: {e}")

        combined_articles.sort(key=lambda x: x["timestamp"], reverse=True)
        return combined_articles


# ═══════════════════════════════════════════════════════════════════════════
# Static Macro Provider (bundled data)
# ═══════════════════════════════════════════════════════════════════════════

class StaticMacroProvider(MacroProvider):
    """
    Bundled macro data for India. These are real historical values.
    In production, connect a live macro API for current data.
    """

    def provider_name(self) -> str:
        return "static"

    def get_macro_data(self) -> pd.DataFrame:
        # Real historical RBI repo rate milestones
        records = [
            {"date": "2015-01-15", "repo_rate": 7.75, "crr": 4.0, "slr": 21.5},
            {"date": "2015-06-02", "repo_rate": 7.25, "crr": 4.0, "slr": 21.5},
            {"date": "2016-04-05", "repo_rate": 6.50, "crr": 4.0, "slr": 21.25},
            {"date": "2016-10-04", "repo_rate": 6.25, "crr": 4.0, "slr": 20.75},
            {"date": "2017-08-02", "repo_rate": 6.00, "crr": 4.0, "slr": 20.0},
            {"date": "2018-06-06", "repo_rate": 6.25, "crr": 4.0, "slr": 19.5},
            {"date": "2018-08-01", "repo_rate": 6.50, "crr": 4.0, "slr": 19.5},
            {"date": "2019-02-07", "repo_rate": 6.25, "crr": 4.0, "slr": 19.25},
            {"date": "2019-06-06", "repo_rate": 5.75, "crr": 4.0, "slr": 19.0},
            {"date": "2019-10-04", "repo_rate": 5.15, "crr": 4.0, "slr": 18.75},
            {"date": "2020-03-27", "repo_rate": 4.40, "crr": 3.0, "slr": 18.25},
            {"date": "2020-05-22", "repo_rate": 4.00, "crr": 3.0, "slr": 18.0},
            {"date": "2022-05-04", "repo_rate": 4.40, "crr": 4.0, "slr": 18.0},
            {"date": "2022-06-08", "repo_rate": 4.90, "crr": 4.5, "slr": 18.0},
            {"date": "2022-09-30", "repo_rate": 5.90, "crr": 4.5, "slr": 18.0},
            {"date": "2023-02-08", "repo_rate": 6.50, "crr": 4.5, "slr": 18.0},
            {"date": "2024-06-07", "repo_rate": 6.50, "crr": 4.5, "slr": 18.0},
            {"date": "2025-02-07", "repo_rate": 6.25, "crr": 4.0, "slr": 18.0},
            {"date": "2025-04-09", "repo_rate": 6.00, "crr": 4.0, "slr": 18.0},
            {"date": "2025-06-06", "repo_rate": 5.75, "crr": 4.0, "slr": 18.0},
        ]
        df = pd.DataFrame(records)
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df["data_quality"] = DataQuality.REAL
        return df


# ═══════════════════════════════════════════════════════════════════════════
# YFinance Fundamentals Provider
# ═══════════════════════════════════════════════════════════════════════════

class YFinanceFundamentalsProvider(FundamentalsProvider):
    """Pull available fundamentals from yfinance .info."""

    def __init__(self):
        try:
            import yfinance  # noqa: F401
            self._available = True
        except ImportError:
            self._available = False

    def provider_name(self) -> str:
        return "yfinance"

    def get_fundamentals(self, symbol: str) -> dict:
        if not self._available:
            return {}
        import yfinance as yf
        try:
            ticker_str = config.STOCK_TICKERS.get(symbol, symbol)
            t = yf.Ticker(ticker_str)
            info = t.info or {}
            return {
                "symbol": symbol,
                "pe_ratio": info.get("trailingPE"),
                "pb_ratio": info.get("priceToBook"),
                "eps": info.get("trailingEps"),
                "roe": info.get("returnOnEquity"),
                "roa": info.get("returnOnAssets"),
                "revenue": info.get("totalRevenue"),
                "net_income": info.get("netIncomeToCommon"),
                "dividend_yield": info.get("dividendYield"),
                "market_cap": info.get("marketCap"),
                "book_value": info.get("bookValue"),
                "debt_to_equity": info.get("debtToEquity"),
                "timestamp": datetime.now().isoformat(),
                "data_quality": DataQuality.REAL,
            }
        except Exception as e:
            log.error(f"Failed to fetch fundamentals for {symbol}: {e}")
            return {}


# ═══════════════════════════════════════════════════════════════════════════
# Provider Factory
# ═══════════════════════════════════════════════════════════════════════════

def get_market_provider() -> MarketDataProvider:
    name = config.DATA_PROVIDER
    if name == "yfinance":
        return YFinanceMarketProvider()
    log.warning(f"Unknown market provider '{name}', falling back to yfinance")
    return YFinanceMarketProvider()


def get_news_provider() -> NewsProvider:
    return MultiSourceNewsProvider()


def get_macro_provider() -> MacroProvider:
    name = config.MACRO_PROVIDER
    if name == "static":
        return StaticMacroProvider()
    log.warning(f"Unknown macro provider '{name}', falling back to static")
    return StaticMacroProvider()


def get_fundamentals_provider() -> FundamentalsProvider:
    name = config.FUNDAMENTALS_PROVIDER
    if name == "yfinance":
        return YFinanceFundamentalsProvider()
    log.warning(f"Unknown fundamentals provider '{name}', falling back to yfinance")
    return YFinanceFundamentalsProvider()


# ═══════════════════════════════════════════════════════════════════════════
# SQLite Database
# ═══════════════════════════════════════════════════════════════════════════

_DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS market_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    data_quality TEXT DEFAULT 'REAL',
    UNIQUE(symbol, date)
);

CREATE TABLE IF NOT EXISTS index_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    close REAL,
    volume REAL,
    data_quality TEXT DEFAULT 'REAL',
    UNIQUE(symbol, date)
);

CREATE TABLE IF NOT EXISTS news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    headline TEXT,
    source TEXT,
    timestamp TEXT,
    url TEXT,
    sentiment_score REAL,
    sentiment_label TEXT,
    category TEXT,
    importance REAL,
    data_quality TEXT DEFAULT 'REAL'
);

CREATE TABLE IF NOT EXISTS fundamentals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    timestamp TEXT,
    pe_ratio REAL,
    pb_ratio REAL,
    eps REAL,
    roe REAL,
    roa REAL,
    revenue REAL,
    net_income REAL,
    dividend_yield REAL,
    market_cap REAL,
    book_value REAL,
    debt_to_equity REAL,
    data_quality TEXT DEFAULT 'REAL'
);

CREATE TABLE IF NOT EXISTS macro_data (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    repo_rate REAL,
    crr REAL,
    slr REAL,
    bond_yield REAL,
    usd_inr REAL,
    inflation REAL,
    data_quality TEXT DEFAULT 'REAL'
);

CREATE TABLE IF NOT EXISTS features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    features_json TEXT,
    data_quality TEXT DEFAULT 'REAL',
    UNIQUE(symbol, date)
);

CREATE TABLE IF NOT EXISTS predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_id TEXT UNIQUE,
    timestamp TEXT,
    symbol TEXT,
    current_price REAL,
    prediction_1d REAL,
    prediction_3d REAL,
    prediction_5d REAL,
    prediction_7d REAL,
    direction_1d TEXT,
    direction_3d TEXT,
    direction_5d TEXT,
    direction_7d TEXT,
    confidence_1d REAL,
    confidence_3d REAL,
    confidence_5d REAL,
    confidence_7d REAL,
    return_1d REAL,
    return_3d REAL,
    return_5d REAL,
    return_7d REAL,
    model_version TEXT,
    features_version TEXT,
    explanation_json TEXT,
    data_quality TEXT DEFAULT 'REAL'
);

CREATE TABLE IF NOT EXISTS prediction_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prediction_id TEXT,
    actual_price_1d REAL,
    actual_price_3d REAL,
    actual_price_5d REAL,
    actual_price_7d REAL,
    actual_return_1d REAL,
    actual_return_3d REAL,
    actual_return_5d REAL,
    actual_return_7d REAL,
    error_1d REAL,
    error_3d REAL,
    error_5d REAL,
    error_7d REAL,
    direction_correct_1d INTEGER,
    direction_correct_3d INTEGER,
    direction_correct_5d INTEGER,
    direction_correct_7d INTEGER,
    evaluated_at TEXT
);

CREATE TABLE IF NOT EXISTS model_versions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_version TEXT UNIQUE,
    algorithm TEXT,
    target TEXT,
    training_timestamp TEXT,
    training_start TEXT,
    training_end TEXT,
    feature_version TEXT,
    metrics_json TEXT,
    file_path TEXT,
    is_active INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT,
    symbol TEXT,
    event_type TEXT,
    description TEXT,
    feature_vector_json TEXT,
    outcome_1d REAL,
    outcome_5d REAL,
    outcome_7d REAL
);

CREATE TABLE IF NOT EXISTS subscriptions (
    email TEXT,
    symbol TEXT,
    created_at TEXT,
    PRIMARY KEY(email, symbol)
);

CREATE INDEX IF NOT EXISTS idx_market_symbol_date ON market_data(symbol, date);
CREATE INDEX IF NOT EXISTS idx_news_symbol ON news(symbol);
CREATE INDEX IF NOT EXISTS idx_predictions_symbol ON predictions(symbol);
CREATE INDEX IF NOT EXISTS idx_model_active ON model_versions(is_active);
"""


class Database:
    """SQLite database manager."""

    def __init__(self, db_path: str = None):
        self.db_path = str(db_path or config.DB_PATH)
        self._init_db()

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript(_DB_SCHEMA)
        log.info(f"Database initialized at {self.db_path}")

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # --- Market Data ---

    def save_market_data(self, symbol: str, df: pd.DataFrame):
        """Save OHLCV data for a stock."""
        if df.empty:
            return
        with self._connect() as conn:
            for _, row in df.iterrows():
                conn.execute(
                    """INSERT OR REPLACE INTO market_data
                       (symbol, date, open, high, low, close, volume, data_quality)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (symbol, str(row["date"]), row.get("open"), row.get("high"),
                     row.get("low"), row.get("close"), row.get("volume"),
                     row.get("data_quality", DataQuality.REAL)),
                )
        log.info(f"Saved {len(df)} rows for {symbol}")

    def get_market_data(self, symbol: str, start: str = None, end: str = None) -> pd.DataFrame:
        query = "SELECT * FROM market_data WHERE symbol = ?"
        params = [symbol]
        if start:
            query += " AND date >= ?"
            params.append(start)
        if end:
            query += " AND date <= ?"
            params.append(end)
        query += " ORDER BY date"
        with self._connect() as conn:
            df = pd.read_sql_query(query, conn, params=params)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"]).dt.date
        return df

    # --- Index Data ---

    def save_index_data(self, symbol: str, df: pd.DataFrame):
        if df.empty:
            return
        with self._connect() as conn:
            for _, row in df.iterrows():
                conn.execute(
                    """INSERT OR REPLACE INTO index_data
                       (symbol, date, close, volume, data_quality)
                       VALUES (?, ?, ?, ?, ?)""",
                    (symbol, str(row["date"]), row.get("close"),
                     row.get("volume"), row.get("data_quality", DataQuality.REAL)),
                )

    def get_index_data(self, symbol: str, start: str = None) -> pd.DataFrame:
        query = "SELECT * FROM index_data WHERE symbol = ?"
        params = [symbol]
        if start:
            query += " AND date >= ?"
            params.append(start)
        query += " ORDER BY date"
        with self._connect() as conn:
            df = pd.read_sql_query(query, conn, params=params)
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"]).dt.date
        return df

    # --- News ---

    def save_news(self, articles: list[dict]):
        if not articles:
            return
        with self._connect() as conn:
            for a in articles:
                conn.execute(
                    """INSERT INTO news
                       (symbol, headline, source, timestamp, url,
                        sentiment_score, sentiment_label, category, importance, data_quality)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (a.get("symbol"), a.get("headline"), a.get("source"),
                     a.get("timestamp"), a.get("url"),
                     a.get("sentiment_score"), a.get("sentiment_label"),
                     a.get("category"), a.get("importance"),
                     a.get("data_quality", DataQuality.REAL)),
                )

    def get_news(self, symbol: str = None, limit: int = 50, before_date: str = None) -> list[dict]:
        query = "SELECT * FROM news"
        params = []
        conditions = []
        if symbol:
            conditions.append("symbol = ?")
            params.append(symbol)
        if before_date:
            conditions.append("timestamp <= ?")
            if len(before_date) <= 10:
                before_dt = before_date + "T23:59:59"
            else:
                before_dt = before_date
            params.append(before_dt)
            
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    # --- Fundamentals ---

    def save_fundamentals(self, data: dict):
        if not data:
            return
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO fundamentals
                   (symbol, timestamp, pe_ratio, pb_ratio, eps, roe, roa,
                    revenue, net_income, dividend_yield, market_cap,
                    book_value, debt_to_equity, data_quality)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (data.get("symbol"), data.get("timestamp"),
                 data.get("pe_ratio"), data.get("pb_ratio"), data.get("eps"),
                 data.get("roe"), data.get("roa"), data.get("revenue"),
                 data.get("net_income"), data.get("dividend_yield"),
                 data.get("market_cap"), data.get("book_value"),
                 data.get("debt_to_equity"),
                 data.get("data_quality", DataQuality.REAL)),
            )

    def get_fundamentals(self, symbol: str) -> dict:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM fundamentals WHERE symbol = ? ORDER BY timestamp DESC LIMIT 1",
                (symbol,),
            ).fetchone()
        return dict(row) if row else {}

    # --- Macro ---

    def save_macro_data(self, df: pd.DataFrame):
        if df.empty:
            return
        with self._connect() as conn:
            for _, row in df.iterrows():
                conn.execute(
                    """INSERT OR REPLACE INTO macro_data
                       (date, repo_rate, crr, slr, bond_yield, usd_inr,
                        inflation, data_quality)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (str(row["date"]), row.get("repo_rate"), row.get("crr"),
                     row.get("slr"), row.get("bond_yield"), row.get("usd_inr"),
                     row.get("inflation"),
                     row.get("data_quality", DataQuality.REAL)),
                )

    def get_macro_data(self) -> pd.DataFrame:
        with self._connect() as conn:
            df = pd.read_sql_query(
                "SELECT * FROM macro_data ORDER BY date", conn
            )
        if not df.empty:
            df["date"] = pd.to_datetime(df["date"]).dt.date
        return df

    # --- Predictions ---

    def save_prediction(self, pred: dict):
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO predictions
                   (prediction_id, timestamp, symbol, current_price,
                    prediction_1d, prediction_3d, prediction_5d, prediction_7d,
                    direction_1d, direction_3d, direction_5d, direction_7d,
                    confidence_1d, confidence_3d, confidence_5d, confidence_7d,
                    return_1d, return_3d, return_5d, return_7d,
                    model_version, features_version, explanation_json, data_quality)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (pred.get("prediction_id"), pred.get("timestamp"),
                 pred.get("symbol"), pred.get("current_price"),
                 pred.get("prediction_1d"), pred.get("prediction_3d"),
                 pred.get("prediction_5d"), pred.get("prediction_7d"),
                 pred.get("direction_1d"), pred.get("direction_3d"),
                 pred.get("direction_5d"), pred.get("direction_7d"),
                 pred.get("confidence_1d"), pred.get("confidence_3d"),
                 pred.get("confidence_5d"), pred.get("confidence_7d"),
                 pred.get("return_1d"), pred.get("return_3d"),
                 pred.get("return_5d"), pred.get("return_7d"),
                 pred.get("model_version"), pred.get("features_version"),
                 json.dumps(pred.get("explanation", {})),
                 pred.get("data_quality", DataQuality.REAL)),
            )

    def get_predictions(self, symbol: str = None, limit: int = 100) -> list[dict]:
        query = "SELECT * FROM predictions"
        params = []
        if symbol:
            query += " WHERE symbol = ?"
            params.append(symbol)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def get_latest_prediction(self, symbol: str) -> Optional[dict]:
        preds = self.get_predictions(symbol, limit=1)
        return preds[0] if preds else None

    # --- Model Versions ---

    def save_model_version(self, info: dict):
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO model_versions
                   (model_version, algorithm, target, training_timestamp,
                    training_start, training_end, feature_version,
                    metrics_json, file_path, is_active)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (info["model_version"], info["algorithm"], info.get("target"),
                 info["training_timestamp"], info.get("training_start"),
                 info.get("training_end"), info.get("feature_version"),
                 json.dumps(info.get("metrics", {})), info.get("file_path"),
                 info.get("is_active", 0)),
            )

    def get_active_model(self, algorithm: str = None, target: str = None) -> Optional[dict]:
        query = "SELECT * FROM model_versions WHERE is_active = 1"
        params = []
        if algorithm:
            query += " AND algorithm = ?"
            params.append(algorithm)
        if target:
            query += " AND target = ?"
            params.append(target)
        query += " ORDER BY training_timestamp DESC LIMIT 1"
        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
        return dict(row) if row else None

    def get_all_model_versions(self) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM model_versions ORDER BY training_timestamp DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    # --- Events ---

    def save_events(self, events: list[dict]):
        if not events:
            return
        with self._connect() as conn:
            for e in events:
                conn.execute(
                    """INSERT INTO events
                       (date, symbol, event_type, description,
                        feature_vector_json, outcome_1d, outcome_5d, outcome_7d)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (e.get("date"), e.get("symbol"), e.get("event_type"),
                     e.get("description"), json.dumps(e.get("feature_vector", {})),
                     e.get("outcome_1d"), e.get("outcome_5d"), e.get("outcome_7d")),
                )

    def get_events(self, symbol: str = None, limit: int = 100) -> list[dict]:
        query = "SELECT * FROM events"
        params = []
        if symbol:
            query += " WHERE symbol = ?"
            params.append(symbol)
        query += " ORDER BY date DESC LIMIT ?"
        params.append(limit)
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    # --- Prediction Results ---

    def save_prediction_result(self, result: dict):
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO prediction_results
                   (prediction_id, actual_price_1d, actual_price_3d, actual_price_5d, actual_price_7d,
                    actual_return_1d, actual_return_3d, actual_return_5d, actual_return_7d,
                    error_1d, error_3d, error_5d, error_7d,
                    direction_correct_1d, direction_correct_3d, direction_correct_5d, direction_correct_7d,
                    evaluated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (result.get("prediction_id"),
                 result.get("actual_price_1d"), result.get("actual_price_3d"),
                 result.get("actual_price_5d"), result.get("actual_price_7d"),
                 result.get("actual_return_1d"), result.get("actual_return_3d"),
                 result.get("actual_return_5d"), result.get("actual_return_7d"),
                 result.get("error_1d"), result.get("error_3d"),
                 result.get("error_5d"), result.get("error_7d"),
                 result.get("direction_correct_1d"), result.get("direction_correct_3d"),
                 result.get("direction_correct_5d"), result.get("direction_correct_7d"),
                 result.get("evaluated_at", datetime.now().isoformat())),
            )

    def get_prediction_results(self, limit: int = 200) -> list[dict]:
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT p.*, pr.actual_return_1d, pr.actual_return_3d, pr.actual_return_5d,
                          pr.actual_return_7d, pr.error_1d, pr.error_3d, pr.error_5d,
                          pr.error_7d, pr.direction_correct_1d, pr.direction_correct_3d,
                          pr.direction_correct_5d, pr.direction_correct_7d
                   FROM predictions p
                   LEFT JOIN prediction_results pr ON p.prediction_id = pr.prediction_id
                   ORDER BY p.timestamp DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    # --- Subscriptions ---

    def add_subscription(self, email: str, symbol: str):
        """Add or update daily alert subscription for an email."""
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO subscriptions (email, symbol, created_at)
                   VALUES (?, ?, ?)""",
                (email.lower().strip(), symbol, datetime.now().isoformat())
            )
        log.info(f"Subscribed {email} to {symbol} alerts.")

    def get_subscriptions(self) -> list[dict]:
        """Fetch all active subscriptions."""
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM subscriptions").fetchall()
        return [dict(r) for r in rows]

    def remove_subscription(self, email: str, symbol: str = None):
        """Remove a subscription."""
        with self._connect() as conn:
            if symbol:
                conn.execute("DELETE FROM subscriptions WHERE email = ? AND symbol = ?", (email.lower().strip(), symbol))
            else:
                conn.execute("DELETE FROM subscriptions WHERE email = ?", (email.lower().strip(),))
        log.info(f"Unsubscribed {email} from alerts.")


# ═══════════════════════════════════════════════════════════════════════════
# Data Pipeline — Orchestrate downloads
# ═══════════════════════════════════════════════════════════════════════════

class DataPipeline:
    """Orchestrate data fetching, storage, and retrieval."""

    def __init__(self):
        self.db = Database()
        self.market = get_market_provider()
        self.news = get_news_provider()
        self.macro = get_macro_provider()
        self.fundamentals = get_fundamentals_provider()
        self._status = {
            "market": "unknown",
            "news": "unknown",
            "macro": "unknown",
            "fundamentals": "unknown",
            "last_update": None,
        }

    @property
    def status(self):
        return self._status

    def download_all_historical(self):
        """Download historical data for all stocks and indices."""
        log.info("Starting full historical data download...")
        start = config.HISTORY_START

        # Stocks
        for symbol, info in config.STOCKS.items():
            try:
                df = self.market.fetch_historical(info["ticker"], start)
                if not df.empty:
                    self.db.save_market_data(symbol, df)
                    self._status["market"] = "connected"
                else:
                    self._status["market"] = "no_data"
            except Exception as e:
                log.error(f"Failed downloading {symbol}: {e}")
                self._status["market"] = "error"

        # Indices
        for idx_symbol, idx_info in config.INDICES.items():
            try:
                df = self.market.fetch_historical(idx_info["ticker"], start)
                if not df.empty:
                    self.db.save_index_data(idx_symbol, df)
            except Exception as e:
                log.error(f"Failed downloading index {idx_symbol}: {e}")

        # USD/INR
        try:
            df = self.market.fetch_historical(config.USDINR_TICKER, start)
            if not df.empty:
                self.db.save_index_data("USDINR", df)
        except Exception as e:
            log.error(f"Failed downloading USD/INR: {e}")

        # Macro data
        try:
            macro_df = self.macro.get_macro_data()
            self.db.save_macro_data(macro_df)
            self._status["macro"] = "connected"
        except Exception as e:
            log.error(f"Failed loading macro data: {e}")
            self._status["macro"] = "error"

        self._status["last_update"] = datetime.now().isoformat()
        log.info("Historical data download complete")

    def update_news(self):
        """Fetch latest news for all stocks."""
        for symbol in config.STOCK_SYMBOLS:
            try:
                articles = self.news.fetch_news(symbol, days=config.NEWS_LOOKBACK_DAYS)
                if articles:
                    self.db.save_news(articles)
                    self._status["news"] = "connected"
            except Exception as e:
                log.error(f"Failed fetching news for {symbol}: {e}")
                self._status["news"] = "error"

    def update_fundamentals(self):
        """Fetch latest fundamentals for all stocks."""
        for symbol in config.STOCK_SYMBOLS:
            try:
                data = self.fundamentals.get_fundamentals(symbol)
                if data:
                    self.db.save_fundamentals(data)
                    self._status["fundamentals"] = "connected"
            except Exception as e:
                log.error(f"Failed fetching fundamentals for {symbol}: {e}")
                self._status["fundamentals"] = "error"

    def get_unified_dataset(self, symbol: str) -> pd.DataFrame:
        """
        Build a unified dataset for a single stock, joining market data
        with index data and macro data. This is used by the feature engine.
        """
        # Stock OHLCV
        df = self.db.get_market_data(symbol)
        if df.empty:
            log.warning(f"No market data for {symbol}")
            return pd.DataFrame()

        df["date"] = pd.to_datetime(df["date"])

        # Index data — merge Nifty, Bank Nifty, VIX, USD/INR
        for idx_sym in list(config.INDICES.keys()) + ["USDINR"]:
            idx_df = self.db.get_index_data(idx_sym)
            if not idx_df.empty:
                idx_df["date"] = pd.to_datetime(idx_df["date"])
                idx_df = idx_df[["date", "close"]].rename(
                    columns={"close": f"{idx_sym.lower()}_close"}
                )
                df = df.merge(idx_df, on="date", how="left")

        # Macro data — forward-fill from milestone dates
        macro_df = self.db.get_macro_data()
        if not macro_df.empty:
            macro_df["date"] = pd.to_datetime(macro_df["date"])
            macro_df = macro_df[["date", "repo_rate", "crr", "slr"]].copy()
            df = df.merge(macro_df, on="date", how="left")
            for col in ["repo_rate", "crr", "slr"]:
                if col in df.columns:
                    df[col] = df[col].ffill()

        df = df.sort_values("date").reset_index(drop=True)
        return df


# ═══════════════════════════════════════════════════════════════════════════
# Module-level convenience
# ═══════════════════════════════════════════════════════════════════════════

def init_pipeline() -> DataPipeline:
    """Create and return a DataPipeline instance."""
    return DataPipeline()
