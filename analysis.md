# ESG ETF Portfolio — Data & Analysis Guide

## Data

**Universe:** 31 Korean ETFs listed on KRX, covering 8 asset classes.

| Asset Class | Example ETFs |
|---|---|
| Domestic equity | KODEX 200, KODEX 코스닥150 |
| ESG | RISE ESG사회책임투자, TIGER MSCI KOREA ESG유니버설 |
| US equity | KODEX 미국S&P500, KODEX 미국나스닥100 |
| US thematic | ACE 엔비디아밸류체인액티브, TIGER 미국필라델피아반도체나스닥, KODEX AI전력핵심설비 |
| Covered call | KODEX 200타겟위클리커버드콜 |
| China / Asia | TIGER 차이나CSI300, TIGER 차이나HSCEI |
| Europe / Developed / EM | TIGER 유로스탁스50, KODEX MSCI선진국, PLUS 신흥국MSCI |
| Korea sector | KODEX 반도체, PLUS K방산, SOL 조선TOP3플러스 |
| Real estate / Gold | KODEX 미국부동산리츠(H), KODEX 골드선물(H) |

**Source:** Daily closing prices via `pykrx` (KRX official data).  
**Range:** 2021-01-01 to present (5 years).  
**Eligibility rule:** An ETF must have at least 252 valid trading days before it can enter the portfolio. Newer ETFs (listed 2024–2025) are excluded until they meet this threshold.

---

## Ranking Methodology

At each monthly rebalancing date, every eligible ETF is scored on two dimensions:

### Momentum (mrank)
```
momentum = price_today / price_252_trading_days_ago
```
Measures how much the ETF has appreciated over the past year of valid trading days. Higher momentum = better rank.

### Volatility (vrank)
```
vol = annualised std of daily log returns over past 252 trading days
```
Measures riskiness. Lower volatility = better rank (the portfolio prefers steadier ETFs, all else equal).

### Frank Score (combined rank)
```
frank = vrank + mrank - mrank3
```
`mrank3` is a small fractional tie-breaker that slightly rewards the top momentum names. **Lower frank = better.** The top 10 ETFs by frank score are selected each month.

---

## Risk Profiles

ETFs with annualised vol > 25% are classified as **high-risk**. Each client profile caps how much of the portfolio can be allocated to them:

| Profile | Max high-risk allocation | Target client |
|---|---|---|
| A | 60% | Aggressive |
| B | 51% | Moderate |
| C | 42% | Conservative |

**Weight calculation:**
1. Assign each of the top 10 ETFs a weight proportional to `1 / frank` (lower frank = higher weight).
2. If the total high-risk weight exceeds the profile limit, scale down all high-risk weights proportionally and redistribute the remainder to low-risk ETFs.

---

## Graphs

### Correlation Heatmap (`outputs/clustering_heatmap.png`)
Shows pairwise daily return correlations across all 31 ETFs, with hierarchical clustering grouping similar ETFs together. Use this to understand diversification — ETFs in the same cluster move together and provide less diversification benefit when held simultaneously.

### Portfolio Value Chart (top panel)
Tracks the growth of a ₩100M starting investment from the first eligible rebalancing date to present, for each risk profile:
- **Red (A):** aggressive, higher high-risk allocation
- **Blue (B):** moderate
- **Green (C):** conservative, lower high-risk allocation

All three lines are **identical in the early period** because high-risk thematic ETFs (AI, semiconductor, covered call) were listed in 2024–2025 and hadn't accumulated 252 days of history yet. During that period, all three profiles were selecting from the same lower-vol universe and computing identical weights. Divergence appears once those ETFs become eligible and the risk constraints start binding differently across profiles.

### Rolling Volatility Chart (bottom panel)
Shows 6-month rolling annualised volatility (%) of each profile's monthly returns. Same story as the portfolio value chart: lines overlap early because the portfolios are identical, then separate as thematic ETFs enter the universe.

When the lines are spread apart, it means the risk constraint is actively working — Profile C is genuinely carrying less volatility than A because it is being forced to hold more of its weight in lower-vol ETFs.

---

## Key Findings

- **The risk constraint has no effect until ~2024.** Before then, the unconstrained high-risk allocation was already below 42% (the tightest limit), so all three profiles computed the same weights.
- **Post-2024 divergence is real.** Once AI/semiconductor ETFs entered the universe, the unconstrained high-risk allocation rose to ~59%, and the constraints started reshaping portfolios meaningfully.
- **Higher risk = higher return in this period.** Profile A outperforms C on total return because 2024–2026 was a bull run for thematic tech ETFs. In a downturn, Profile C's lower-vol weighting would offer more protection.
