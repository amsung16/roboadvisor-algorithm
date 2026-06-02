#!/usr/bin/env python3
"""
Korean ETF historical price pipeline.

Fetches daily closing prices via pykrx (yfinance fallback), cleans the data,
saves results locally, and prints a summary with a correlation heatmap.

Usage:
    python etf_pipeline.py           # full fetch from START_DATE to today
    python etf_pipeline.py --update  # append new data since last fetch

Note: add new tickers to TICKERS below, then run without --update to backfill.
"""

import argparse
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

# ── Configuration ──────────────────────────────────────────────────────────────
START_DATE = "2018-01-01"
DATA_DIR = Path("data")
PRICES_CSV = DATA_DIR / "etf_prices.csv"
METADATA_JSON = DATA_DIR / "etf_metadata.json"
HEATMAP_PNG = DATA_DIR / "correlation_heatmap.png"
ANOMALY_LOG = DATA_DIR / "anomalies.log"
MISSING_THRESHOLD = 0.10   # drop tickers with > 10% missing trading days
ANOMALY_THRESHOLD = -0.30  # flag single-day returns below -30%

# ── Ticker universe — edit here to add/remove ETFs ────────────────────────────
TICKERS: dict[str, dict] = {
    # Domestic equity
    "069500": {"name": "KODEX 200",                        "asset_class": "domestic_equity",  "risk_score": 4},
    "229200": {"name": "KODEX 코스닥150",                  "asset_class": "domestic_equity",  "risk_score": 4},
    # ESG
    "289250": {"name": "TIGER MSCI KOREA ESG유니버설",     "asset_class": "esg",              "risk_score": 4},
    "290130": {"name": "RISE ESG사회책임투자",             "asset_class": "esg",              "risk_score": 4},
    # US equity
    "379800": {"name": "KODEX 미국S&P500",                 "asset_class": "us_equity",        "risk_score": 4},
    "219480": {"name": "KODEX 미국S&P500선물(H)",          "asset_class": "us_equity",        "risk_score": 4},
    "379810": {"name": "KODEX 미국나스닥100",              "asset_class": "us_equity",        "risk_score": 5},
    "314250": {"name": "KODEX 미국빅테크10(H)",            "asset_class": "us_equity",        "risk_score": 5},
    "381180": {"name": "TIGER 미국필라델피아반도체나스닥", "asset_class": "us_equity",        "risk_score": 5},
    "458730": {"name": "TIGER 미국배당다우존스",           "asset_class": "us_equity",        "risk_score": 3},
    # US thematic
    "487240": {"name": "KODEX AI전력핵심설비",             "asset_class": "us_thematic",      "risk_score": 5},
    "487230": {"name": "KODEX 미국AI전력핵심인프라",       "asset_class": "us_thematic",      "risk_score": 5},
    "483320": {"name": "ACE 엔비디아밸류체인액티브",       "asset_class": "us_thematic",      "risk_score": 5},
    "457480": {"name": "ACE 테슬라밸류체인액티브",         "asset_class": "us_thematic",      "risk_score": 5},
    "498400": {"name": "KODEX 200타겟위클리커버드콜",      "asset_class": "us_thematic",      "risk_score": 3},
    # China / Asia
    "192090": {"name": "TIGER 차이나CSI300",               "asset_class": "china_equity",     "risk_score": 5},
    "245360": {"name": "TIGER 차이나HSCEI",                "asset_class": "china_equity",     "risk_score": 5},
    "371160": {"name": "TIGER 차이나항셍테크",             "asset_class": "china_equity",     "risk_score": 5},
    "371460": {"name": "TIGER 차이나전기차SOLACTIVE",      "asset_class": "china_equity",     "risk_score": 5},
    # Europe / Developed / EM
    "195930": {"name": "TIGER 유로스탁스50(합성 H)",       "asset_class": "foreign_equity",   "risk_score": 4},
    "251350": {"name": "KODEX MSCI선진국",                 "asset_class": "foreign_equity",   "risk_score": 4},
    "195980": {"name": "PLUS 신흥국MSCI(합성H)",           "asset_class": "foreign_equity",   "risk_score": 4},
    # Korea sector / thematic
    "091160": {"name": "KODEX 반도체",                     "asset_class": "domestic_sector",  "risk_score": 5},
    "305720": {"name": "KODEX 2차전지산업",                "asset_class": "domestic_sector",  "risk_score": 5},
    "462010": {"name": "TIGER 2차전지소재Fn",              "asset_class": "domestic_sector",  "risk_score": 5},
    "449450": {"name": "PLUS K방산",                       "asset_class": "domestic_sector",  "risk_score": 5},
    "466920": {"name": "SOL 조선TOP3플러스",               "asset_class": "domestic_sector",  "risk_score": 5},
    "494670": {"name": "TIGER 조선TOP10",                  "asset_class": "domestic_sector",  "risk_score": 5},
    "228790": {"name": "TIGER 화장품",                     "asset_class": "domestic_sector",  "risk_score": 5},
    # Real estate / commodity
    "352560": {"name": "KODEX 미국부동산리츠(H)",          "asset_class": "real_estate",      "risk_score": 4},
    "132030": {"name": "KODEX 골드선물(H)",                "asset_class": "gold",             "risk_score": 4},
}


# ── Logging ────────────────────────────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("etf_pipeline")
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    fh = logging.FileHandler(ANOMALY_LOG, encoding="utf-8")
    fh.setLevel(logging.WARNING)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


# ── Data fetching ──────────────────────────────────────────────────────────────

def _to_pykrx_date(d: str) -> str:
    return d.replace("-", "")


def _fetch_pykrx(ticker: str, start: str, end: str) -> pd.Series | None:
    try:
        from pykrx import stock

        df = stock.get_etf_ohlcv_by_date(_to_pykrx_date(start), _to_pykrx_date(end), ticker)
        if df is None or df.empty:
            df = stock.get_market_ohlcv_by_date(_to_pykrx_date(start), _to_pykrx_date(end), ticker)
        if df is None or df.empty:
            return None

        series = df["종가"].rename(ticker)
        series.index = pd.to_datetime(series.index)
        return series
    except Exception:
        return None


def _fetch_yfinance(ticker: str, start: str, end: str) -> pd.Series | None:
    try:
        import yfinance as yf

        df = yf.download(f"{ticker}.KS", start=start, end=end, auto_adjust=True, progress=False)
        if df.empty:
            return None

        # yfinance may return MultiIndex columns when auto_adjust=True
        close = df["Close"]
        if isinstance(close, pd.DataFrame):
            close = close.iloc[:, 0]
        close = close.rename(ticker)
        close.index = pd.to_datetime(close.index)
        return close
    except Exception:
        return None


def fetch_ticker(ticker: str, start: str, end: str, logger: logging.Logger) -> pd.Series | None:
    logger.info(f"  [{ticker}] {TICKERS[ticker]['name']} — pykrx...")
    series = _fetch_pykrx(ticker, start, end)
    if series is not None and not series.empty:
        logger.info(f"  [{ticker}] ✓ {len(series)} rows via pykrx")
        return series

    logger.warning(f"  [{ticker}] pykrx failed — trying yfinance")
    series = _fetch_yfinance(ticker, start, end)
    if series is not None and not series.empty:
        logger.info(f"  [{ticker}] ✓ {len(series)} rows via yfinance")
        return series

    logger.error(f"  [{ticker}] ✗ both sources failed — skipping")
    return None


def build_price_matrix(
    tickers: dict, start: str, end: str, logger: logging.Logger
) -> pd.DataFrame:
    series_list = []
    for ticker in tickers:
        s = fetch_ticker(ticker, start, end, logger)
        if s is not None:
            series_list.append(s)

    if not series_list:
        logger.error("No data fetched. Check your internet connection and pykrx install.")
        sys.exit(1)

    df = pd.concat(series_list, axis=1)
    df.index = pd.to_datetime(df.index)
    df.sort_index(inplace=True)
    return df


# ── Cleaning ───────────────────────────────────────────────────────────────────

def clean_prices(
    df: pd.DataFrame, logger: logging.Logger, is_update: bool = False
) -> pd.DataFrame:
    """Reindex to business-day calendar, drop sparse tickers, forward-fill."""
    full_idx = pd.bdate_range(df.index.min(), df.index.max(), freq="B")
    df = df.reindex(full_idx)
    df.index.name = "date"

    if not is_update:
        missing_pct = df.isna().mean()
        to_drop = missing_pct[missing_pct > MISSING_THRESHOLD].index.tolist()
        for t in to_drop:
            logger.warning(
                f"Dropping {t} ({TICKERS.get(t, {}).get('name', t)}): "
                f"{missing_pct[t]:.1%} missing exceeds {MISSING_THRESHOLD:.0%} threshold"
            )
        df.drop(columns=to_drop, inplace=True)

    df.ffill(inplace=True)
    return df


def detect_anomalies(
    df: pd.DataFrame, logger: logging.Logger, since: str | None = None
) -> None:
    """Log any single-day return below ANOMALY_THRESHOLD to the anomaly log."""
    returns = df.pct_change()
    if since:
        returns = returns[returns.index >= pd.Timestamp(since)]

    flagged = returns[returns < ANOMALY_THRESHOLD].stack()
    for (dt, ticker), ret in flagged.items():
        logger.warning(
            f"ANOMALY | {ticker} | {TICKERS.get(ticker, {}).get('name', ticker)} "
            f"| {dt.date()} | {ret:+.1%}"
        )

    if flagged.empty:
        logger.info("No anomalies detected.")
    else:
        logger.info(f"{len(flagged)} anomaly event(s) logged to {ANOMALY_LOG}")


# ── Persistence ────────────────────────────────────────────────────────────────

def load_existing_prices(logger: logging.Logger) -> pd.DataFrame | None:
    if not PRICES_CSV.exists():
        return None
    df = pd.read_csv(PRICES_CSV, index_col=0, parse_dates=True)
    logger.info(f"Loaded existing prices: {df.shape[0]} rows, last date = {df.index.max().date()}")
    return df


def save_prices(df: pd.DataFrame, logger: logging.Logger) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(PRICES_CSV, index=True)
    logger.info(f"Saved {PRICES_CSV}  ({df.shape[0]} rows × {df.shape[1]} tickers)")


def save_metadata(tickers: dict, logger: logging.Logger) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(METADATA_JSON, "w", encoding="utf-8") as f:
        json.dump(tickers, f, ensure_ascii=False, indent=2)
    logger.info(f"Saved {METADATA_JSON}")


# ── Reporting ──────────────────────────────────────────────────────────────────

def print_summary(df: pd.DataFrame) -> None:
    today = df.index.max()
    one_year_ago = today - pd.DateOffset(years=1)

    rows = []
    for ticker in df.columns:
        series = df[ticker].dropna()
        if series.empty:
            continue

        missing_pct = df[ticker].isna().mean()
        current_price = series.iloc[-1]

        past = series[series.index <= one_year_ago]
        ret_1y = f"{(current_price / past.iloc[-1] - 1) * 100:+.1f}%" if not past.empty else "N/A"

        rows.append({
            "Ticker":        ticker,
            "Name":          TICKERS.get(ticker, {}).get("name", ticker),
            "Asset Class":   TICKERS.get(ticker, {}).get("asset_class", ""),
            "Date Range":    f"{series.index.min().date()} – {series.index.max().date()}",
            "Missing":       f"{missing_pct:.1%}",
            "Current (KRW)": f"{current_price:,.0f}",
            "1Y Return":     ret_1y,
        })

    summary = pd.DataFrame(rows)
    col_w = {c: max(len(c), summary[c].str.len().max()) for c in summary.columns}
    sep = "  ".join("─" * col_w[c] for c in summary.columns)

    print(f"\n{'ETF PIPELINE SUMMARY':^{len(sep)}}")
    print(sep)
    print("  ".join(c.ljust(col_w[c]) for c in summary.columns))
    print(sep)
    for _, row in summary.iterrows():
        print("  ".join(str(row[c]).ljust(col_w[c]) for c in summary.columns))
    print(sep + "\n")


def plot_correlation(df: pd.DataFrame, logger: logging.Logger) -> None:
    returns = df.pct_change().dropna(how="all")
    corr = returns.corr()

    labels = []
    for t in corr.columns:
        short = TICKERS.get(t, {}).get("name", t).replace("KODEX ", "").replace("선물", "F")
        labels.append(f"{t}\n{short}")

    n = len(corr)
    fig, ax = plt.subplots(figsize=(max(9, n * 1.2), max(7, n)))
    mask = np.triu(np.ones_like(corr, dtype=bool), k=1)  # lower triangle + diagonal

    sns.heatmap(
        corr,
        mask=mask,
        annot=True,
        fmt=".2f",
        cmap="RdYlGn",
        center=0,
        vmin=-1,
        vmax=1,
        linewidths=0.5,
        square=True,
        ax=ax,
        xticklabels=labels,
        yticklabels=labels,
    )
    ax.set_title("ETF Daily Return Correlations", fontsize=13, pad=14)
    plt.tight_layout()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(HEATMAP_PNG, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"Saved {HEATMAP_PNG}")


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Korean ETF historical price pipeline")
    parser.add_argument(
        "--update",
        action="store_true",
        help="Append trading days since last fetch instead of re-fetching from scratch",
    )
    args = parser.parse_args()

    logger = setup_logging()
    today_str = date.today().strftime("%Y-%m-%d")

    # Determine fetch window
    if args.update:
        existing = load_existing_prices(logger)
        if existing is None:
            logger.info("No existing data found — running full fetch.")
            start, is_update, df_existing = START_DATE, False, None
        else:
            next_start = (existing.index.max() + timedelta(days=1)).strftime("%Y-%m-%d")
            if next_start > today_str:
                logger.info("Already up to date.")
                print_summary(existing)
                plot_correlation(existing, logger)
                return
            logger.info(f"Incremental fetch: {next_start} → {today_str}")
            start, is_update, df_existing = next_start, True, existing
    else:
        start, is_update, df_existing = START_DATE, False, None

    # Fetch
    logger.info(f"Fetching {len(TICKERS)} tickers  |  {start} → {today_str}")
    df_new = build_price_matrix(TICKERS, start, today_str, logger)

    # Merge with existing on update
    if is_update and df_existing is not None:
        combined = pd.concat([df_existing, df_new], axis=0)
        combined = combined[~combined.index.duplicated(keep="last")]
        combined.sort_index(inplace=True)
        df = clean_prices(combined, logger, is_update=True)
        detect_anomalies(df, logger, since=start)
    else:
        df = clean_prices(df_new, logger, is_update=False)
        detect_anomalies(df, logger)

    # Save & report
    save_prices(df, logger)
    save_metadata(TICKERS, logger)
    print_summary(df)
    plot_correlation(df, logger)
    logger.info("Done.")


if __name__ == "__main__":
    main()
