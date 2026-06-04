# CLAUDE.md

## Project Overview

Korean ETF monthly rebalancing tool for an ESG investment advisory firm. Ranks 31 KRX-listed ETFs by a momentum + volatility composite score (frank), selects the top 10 each month, and allocates weights under three client risk profiles (A/B/C).

Two entry points:
- **`ESG자산배분v4_edited.ipynb`** — interactive analysis, rankings, clustering heatmap, backtest, charts
- **`etf_pipeline.py`** — standalone script for fetching and cleaning price data (`python etf_pipeline.py` or `--update`)

---

## Key Files

| File | Purpose |
|---|---|
| `ESG자산배분v4_edited.ipynb` | Main analysis notebook — run top to bottom |
| `etf_pipeline.py` | Price data pipeline (fetch, clean, anomaly log, heatmap) |
| `requirements.txt` | Python dependencies |
| `outputs/` | Notebook outputs: `price.csv`, `rankings.csv`, `clustering_heatmap.png`, `backtest_results.png` |
| `data/` | Pipeline outputs: `etf_prices.csv`, `etf_metadata.json`, `correlation_heatmap.png`, `anomalies.log` |
| `analysis.md` | Plain-language explanation of data, methodology, and graphs |

---

## Important Constants

These control core behaviour — change carefully:

| Constant | Location | Value | Effect |
|---|---|---|---|
| `MIN_HISTORY` | notebook Cell 3 | 252 | Minimum trading days before an ETF can enter the universe |
| `VOL_THRESHOLD` | notebook Cell 12 | 0.25 | Annualised vol cutoff for high-risk classification |
| `RISK_LIMITS` | notebook Cell 12 | A=0.60, B=0.51, C=0.42 | Max high-risk allocation per client profile |
| `start_date` | notebook Cell 1 | `"20210101"` | Start of price history download |
| `START_DATE` | `etf_pipeline.py` | `"2018-01-01"` | Start of pipeline price history |
| `MISSING_THRESHOLD` | `etf_pipeline.py` | 0.10 | Drop tickers with >10% missing trading days |

---

## Adding or Removing ETFs

**Notebook (Cell 1):** edit the `tickers` list — 6-digit KRX codes only.  
**Pipeline (`etf_pipeline.py`):** edit the `TICKERS` list at the top of the file.

ETF names are auto-fetched from the Naver Finance API at runtime — do not hardcode them. The fetch function validates that the ticker is exactly 6 numeric digits before constructing the URL.

---

## Running the Project

```bash
# Set up environment
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# Notebook
jupyter notebook ESG자산배분v4_edited.ipynb   # run all cells top to bottom

# Pipeline (full fetch)
python etf_pipeline.py

# Pipeline (incremental update since last run)
python etf_pipeline.py --update
```

---

## Architecture Notes

- **Universe eligibility**: at each rebalancing date, only ETFs with ≥ 252 non-null trading days are eligible. This means newly listed ETFs (e.g., AI/semiconductor ETFs listed 2024–2025) enter the backtest late. This causes the A/B/C profiles to look identical in early periods — it is correct behaviour, not a bug.
- **Frank score**: `frank = vrank + mrank - mrank3`. Lower is better. `mrank3` is a small fractional tiebreaker. Do not reorder the formula.
- **Weight constraint**: if unconstrained high-risk weight ≤ profile limit, weights are unchanged and all profiles are identical. The constraint only activates when it is actually exceeded.
- **ETF name fetching**: `fetch_etf_name()` calls `https://m.stock.naver.com/api/stock/{ticker}/basic`. It validates the ticker is `^\d{6}$` before the request. Falls back to the raw ticker code on any failure.
- **pykrx → yfinance fallback**: `etf_pipeline.py` tries pykrx first; if it returns empty data it falls back to yfinance with the `.KS` suffix.

---

## What Not to Do

- Do not hardcode ETF display names — they come from the Naver API.
- Do not lower `MIN_HISTORY` below 252 without understanding the momentum signal breaks at shorter windows.
- Do not add `venv/`, `data/`, or `outputs/` to git — they are in `.gitignore`.
- Do not present backtest results as long-term evidence — the current period (2024–2026) is a bull market favourable to momentum strategies.
