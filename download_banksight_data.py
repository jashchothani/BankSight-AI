import yfinance as yf
import pandas as pd
import time

START = "2015-01-01"
END = "2026-08-08"  # yfinance end date is exclusive, so +1 day to include 2026-08-07

TICKERS = {
    "HDFCBANK.NS": "HDFCBANK",
    "ICICIBANK.NS": "ICICIBANK",
    "SBIN.NS": "SBIN",
    "AXISBANK.NS": "AXISBANK",
    "KOTAKBANK.NS": "KOTAKBANK",
    "^NSEI": "NIFTY50",
    "^NSEBANK": "BANKNIFTY",
    "^INDIAVIX": "INDIAVIX",
}

for ticker, name in TICKERS.items():
    print(f"Downloading {ticker} ({name})...")
    try:
        df = yf.download(
            ticker,
            start=START,
            end=END,
            auto_adjust=False,   # keep raw OHLC + separate Adj Close, matches yfinance adapter convention
            actions=False,
            progress=False,
        )

        # yfinance sometimes returns MultiIndex columns (ticker, field) for a single ticker
        # depending on version — flatten if so.
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        df.index.name = "Date"
        out_path = f"{name}.csv"
        df.to_csv(out_path)
        print(f"  -> saved {out_path} ({len(df)} rows, "
              f"{df.index.min().date()} to {df.index.max().date()})")
    except Exception as e:
        print(f"  !! FAILED for {ticker}: {e}")

    time.sleep(1)  # be polite to Yahoo's endpoint, avoid rate-limiting

print("\nDone. Upload the 8 CSVs (HDFCBANK.csv, ICICIBANK.csv, SBIN.csv, "
      "AXISBANK.csv, KOTAKBANK.csv, NIFTY50.csv, BANKNIFTY.csv, INDIAVIX.csv).")