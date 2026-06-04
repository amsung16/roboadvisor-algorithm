# Roboadvisor Algorithm — Korean ETF Monthly Rebalancing Tool

A quantitative ETF ranking and portfolio management tool for Korean markets. At each monthly rebalancing date, it scores ETFs by momentum and volatility, applies client risk profile constraints, and outputs actual portfolio weights.

---

## How It Works

The strategy ranks ETFs using two signals:

| Signal | Metric | Direction |
|--------|--------|-----------|
| Momentum | 1-year return (last 252 trading days) | Higher = better |
| Volatility | Annualized log-return std dev | Lower = better |

These combine into a single composite score called **`frank`**:

```
frank = vrank + mrank - mrank3
```

Lower `frank` = better pick. The top-ranked ETFs are weighted and allocated based on the client's risk profile.

---

## Dynamic Universe Rule

At each rebalancing date, only ETFs with **at least 252 valid trading days** of price history are eligible. ETFs enter the investable universe automatically once they meet this threshold. Data before an ETF's actual listing date is never used.

```python
valid_counts = data.notna().sum()
universe = valid_counts[valid_counts >= 252].index.tolist()
```

---

## Risk Profile Constraints

Three client risk profiles based on regulatory filing. Each caps the maximum allocation to high-risk ETFs (annualized volatility > 25%):

| Profile | Max High-Risk Allocation |
|---------|--------------------------|
| A (공격형) | 60% |
| B (적극형) | 51% |
| C (안정성장형) | 42% |

If unconstrained weights breach the limit, high-risk ETF weights are scaled down and the remainder redistributes to lower-risk ETFs. All weights always sum to exactly 1.0.

---

## Portfolio Weights

Frank scores are converted to actual weights using inverse-frank weighting:

```
weight_i = (1 / frank_i) / sum(1 / frank_j for all j in top N)
```

Lower frank score = higher allocation. Risk profile constraints are then applied on top.

---

## Setup

### Requirements

```bash
pip install pykrx pandas numpy requests scipy seaborn
```

Or let Cell 0 handle it automatically — it runs the installs on startup.

### Run

Open `ESG자산배분v4_edited.ipynb` in Jupyter and run all cells (`Kernel → Restart & Run All`).

---

## Notebook Structure

| Cell | Description |
|------|-------------|
| 0 | Install dependencies + imports |
| 1 | Download 5 years of closing prices from KRX → `price.csv` |
| 2 | Auto-fetch ETF names from Naver Finance API |
| 3 | `get_universe_ranks()` — Dynamic Universe Rule → `rank2` |
| 4 | Display full rankings table |
| 5 | Save rankings to `rankings.csv` |
| 6 | Display top 10 ETFs |
| 7 | Momentum leaderboard (`ym1`) |
| 8 | Example: query a past rebalancing date |
| 11 | Hierarchical clustering heatmap → `clustering_heatmap.png` |
| 12 | `compute_weights()` — risk profile constraints + weight allocation |
| 13 | `backtest()` — monthly rebalancing simulation from 2024 to today |
| 14 | Backtest metrics + charts → `backtest_results.png` |

---

## ETF Universe (31 ETFs)

| Ticker | Name | Category |
|--------|------|----------|
| 069500 | KODEX 200 | Korea Large Cap |
| 229200 | KODEX 코스닥150 | Korea Mid/Small Cap |
| 379810 | KODEX 미국나스닥100 | US Tech |
| 379800 | KODEX 미국S&P500 | US Broad Market |
| 132030 | KODEX 골드선물(H) | Commodity |
| 192090 | TIGER 차이나CSI300 | China |
| 289250 | TIGER MSCI KOREA ESG유니버설 | ESG |
| 290130 | RISE ESG사회책임투자 | ESG |
| 352560 | KODEX 미국부동산리츠(H) | Real Estate |
| 091160 | KODEX 반도체 | Semiconductor |
| 487240 | KODEX AI전력핵심설비 | AI/Power |
| 483320 | ACE 엔비디아밸류체인액티브 | AI/Semiconductor |
| 449450 | PLUS K방산 | Defense |
| 466920 | SOL 조선TOP3플러스 | Shipbuilding |
| 494670 | TIGER 조선TOP10 | Shipbuilding |
| 458730 | TIGER 미국배당다우존스 | US Dividend |
| 498400 | KODEX 200타겟위클리커버드콜 | Covered Call |
| 381180 | TIGER 미국필라델피아반도체나스닥 | US Semiconductor |
| 314250 | KODEX 미국빅테크10(H) | US Big Tech |
| 371160 | TIGER 차이나항셍테크 | China Tech |
| 371460 | TIGER 차이나전기차SOLACTIVE | China EV |
| 245360 | TIGER 차이나HSCEI | China |
| 195930 | TIGER 유로스탁스50(합성 H) | Europe |
| 219480 | KODEX 미국S&P500선물(H) | US Broad Market (H) |
| 251350 | KODEX MSCI선진국 | Developed Markets |
| 195980 | PLUS 신흥국MSCI(합성H) | Emerging Markets |
| 305720 | KODEX 2차전지산업 | Battery |
| 462010 | TIGER 2차전지소재Fn | Battery Materials |
| 457480 | ACE 테슬라밸류체인액티브 | EV/Tesla |
| 487230 | KODEX 미국AI전력핵심인프라 | AI Infrastructure |
| 228790 | TIGER 화장품 | K-Beauty |

---

## Key Variables

| Variable | Description |
|----------|-------------|
| `price` | DataFrame of daily closing prices (rows = dates, columns = ETF names) |
| `MIN_HISTORY` | Minimum trading days required to enter universe (252) |
| `momentum` | ETF return over last 252 valid trading days |
| `vol` | Annualized volatility over last 252 valid trading days |
| `mrank` | Momentum rank (1 = highest return) |
| `vrank` | Volatility rank (1 = lowest risk) |
| `mrank3` | Linear tiebreaker weight, favors higher momentum on ties |
| `frank` | Composite score = `vrank + mrank - mrank3` (lower = better) |
| `rank2` | Final rankings table sorted by `frank` |
| `ym1` | `rank2` sorted by momentum rank |
| `rebal_date` | Last trading day of the previous month |
| `RISK_LIMITS` | Dict of max high-risk allocation per profile: A=60%, B=51%, C=42% |
| `VOL_THRESHOLD` | Volatility cutoff for high-risk classification (0.25 = 25%) |

---

## Backtesting

```python
portfolio, monthly_rets = backtest(price, risk_profile='B', top_n=10, initial_value=100_000_000)
```

Simulates monthly rebalancing from the first date with sufficient history to today. Returns a `pd.Series` of portfolio value indexed by month-end date.

To query rankings for any past date:

```python
result = get_universe_ranks(price, "2025-06-30")
display(result)
```

### Sample Backtest Results (Jan 2024 – Apr 2026)

| Metric | Profile A | Profile B | Profile C |
|--------|-----------|-----------|-----------|
| Total Return | +144.6% | +139.0% | +134.2% |
| CAGR | +48.9% | +47.4% | +46.1% |
| Sharpe Ratio | 3.13 | 3.26 | 3.39 |
| Max Drawdown | -4.8% | -4.8% | -4.8% |
| Win Rate | 87.5% | 87.5% | 87.5% |
| ₩100M → | ₩244M | ₩238M | ₩234M |

> **Note:** The backtest covers a 2.25-year bull market period favorable to momentum strategies. These results should not be presented as long-term performance evidence. A minimum of 5–7 years including a bear market cycle is needed for a credible regulatory claim.

---

## Output Files

| File | Description |
|------|-------------|
| `price.csv` | Raw closing prices for all ETFs |
| `rankings.csv` | Latest rebalancing rankings |
| `clustering_heatmap.png` | Hierarchical correlation clustering chart |
| `backtest_results.png` | Portfolio value + drawdown chart |

---

## Notes

- ETF names are fetched automatically from the Naver Finance API — no manual mapping needed
- `frank` weights momentum and volatility equally — it does not incorporate ESG scores, sector tilts, or fundamental factors
- High-risk classification is based on realized volatility (`vol > 25%`), not asset class labels
- KRX login credentials are not required for price data download
- Transaction costs and taxes are not modeled in the backtest
