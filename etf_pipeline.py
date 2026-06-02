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

import requests
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

# ── Ticker universe — add/remove codes here ───────────────────────────────────
TICKERS: list[str] = [
    "069500", "229200",                          # Domestic equity
    "289250", "290130",                          # ESG
    "379800", "219480", "379810", "314250",      # US equity
    "381180", "458730",                          # US equity (cont.)
    "487240", "487230", "483320", "457480",      # US thematic
    "498400",                                    # Covered call
    "192090", "245360", "371160", "371460",      # China / Asia
    "195930", "251350", "195980",                # Europe / Developed / EM
    "091160", "305720", "462010", "449450",      # Korea sector
    "466920", "494670", "228790",                # Korea sector (cont.)
    "352560", "132030",                          # Real estate / gold
]

# Module-level metadata cache — populated by build_ticker_meta() in main()
_META: dict[str, dict] = {}


# ── ETF metadata helpers ───────────────────────────────────────────────────────

def fetch_etf_name(ticker: str) -> str:
    """Fetch ETF display name from Naver Finance mobile API."""
    try:
        url = f"https://m.stock.naver.com/api/stock/{ticker}/basic"
        resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=5)
        if resp.ok:
            return resp.json().get("stockName", ticker)
    except Exception:
        pass
    return ticker


def _classify_asset_class(name: str) -> str:
    if any(k in name for k in ["ESG", "사회책임"]):
        return "esg"
    if any(k in name for k in ["골드", "금선물"]):
        return "gold"
    if any(k in name for k in ["부동산", "리츠"]):
        return "real_estate"
    if any(k in name for k in ["차이나", "HSCEI", "항셍", "중국"]):
        return "china_equity"
    if any(k in name for k in ["유로", "선진국", "신흥국"]):
        return "foreign_equity"
    if any(k in name for k in ["AI", "엔비디아", "테슬라", "핵심설비", "핵심인프라", "위클리커버드콜"]):
        return "us_thematic"
    if any(k in name for k in ["미국", "S&P", "나스닥", "빅테크", "배당다우", "필라델피아"]):
        return "us_equity"
    if any(k in name for k in ["반도체", "2차전지", "조선", "방산", "화장품"]):
        return "domestic_sector"
    return "domestic_equity"


def _classify_risk_score(name: str) -> int:
    if any(k in name for k in ["AI", "엔비디아", "테슬라", "반도체", "2차전지", "조선",
                                 "방산", "화장품", "차이나", "항셍", "나스닥", "빅테크", "필라델피아"]):
        return 5
    if any(k in name for k in ["위클리커버드콜", "배당다우", "골드", "부동산", "리츠"]):
        return 3
    return 4


def build_ticker_meta(tickers: list[str], logger: logging.Logger | None = None) -> dict[str, dict]:
    """Fetch names from Naver API and auto-classify asset_class / risk_score."""
    meta = {}
    for ticker in tickers:
        name = fetch_etf_name(ticker)
        meta[ticker] = {
            "name": name,
            "asset_class": _classify_asset_class(name),
            "risk_score": _classify_risk_score(name),
        }
        if logger:
            logger.info(f"  [{ticker}] {name}  ({meta[ticker]['asset_class']}, risk={meta[ticker]['risk_score']})")
    return meta


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
    logger.info(f"  [{ticker}] {_META.get(ticker, {}).get('name', ticker)} — pykrx...")
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
    tickers: list, start: str, end: str, logger: logging.Logger
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
                f"Dropping {t} ({_META.get(t, {}).get('name', t)}): "
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
            f"ANOMALY | {ticker} | {_META.get(ticker, {}).get('name', ticker)} "
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
            "Name":          _META.get(ticker, {}).get("name", ticker),
            "Asset Class":   _META.get(ticker, {}).get("asset_class", ""),
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
        short = _META.get(t, {}).get("name", t).replace("KODEX ", "").replace("선물", "F")
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

    global _META
    logger.info(f"Fetching names for {len(TICKERS)} tickers from Naver API...")
    _META = build_ticker_meta(TICKERS, logger)

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
    save_metadata(_META, logger)
    print_summary(df)
    plot_correlation(df, logger)
    logger.info("Done.")


if __name__ == "__main__":
    main()
