import numpy as np
import pandas as pd

from core.ranking import get_universe_ranks, MIN_HISTORY
from core.weights import compute_weights


def backtest(price_data, risk_profile='B', top_n=10, initial_value=100_000_000):
    """
    Simulate monthly rebalancing from the first month with enough history to today.
    Returns a pd.Series of portfolio value indexed by month-end date.
    """
    idx = pd.DatetimeIndex(price_data.index)
    month_ends = idx[idx.is_month_end].tolist()

    # Only start once at least MIN_HISTORY trading days exist
    valid_ends = []
    for d in month_ends:
        data_so_far = price_data[price_data.index <= str(d)]
        if data_so_far.notna().sum().max() >= MIN_HISTORY:
            valid_ends.append(d)

    if len(valid_ends) < 2:
        print("Not enough data to backtest.")
        return None

    values = {valid_ends[0]: float(initial_value)}

    for i in range(len(valid_ends) - 1):
        rebal_date  = valid_ends[i]
        next_date   = valid_ends[i + 1]

        try:
            ranks   = get_universe_ranks(price_data, rebal_date)
            weights = compute_weights(ranks, risk_profile, top_n)
        except Exception as e:
            values[next_date] = list(values.values())[-1]
            continue

        p0 = price_data[price_data.index <= str(rebal_date)].iloc[-1]
        p1 = price_data[price_data.index <= str(next_date)].iloc[-1]

        monthly_ret = sum(
            row['weight'] * (p1[etf] / p0[etf] - 1)
            for etf, row in weights.iterrows()
            if etf in p0.index and pd.notna(p0[etf]) and pd.notna(p1.get(etf))
        )
        values[next_date] = list(values.values())[-1] * (1 + monthly_ret)

    return pd.Series(values)


def backtest_metrics(portfolio):
    """Compute summary performance metrics for a portfolio value series."""
    total_return = portfolio.iloc[-1] / portfolio.iloc[0] - 1
    n_years = (portfolio.index[-1] - portfolio.index[0]).days / 365.25
    cagr = (1 + total_return) ** (1 / n_years) - 1

    monthly_returns = portfolio.pct_change().dropna()
    sharpe = (monthly_returns.mean() / monthly_returns.std()) * np.sqrt(12)

    rolling_max = portfolio.cummax()
    drawdown = (portfolio - rolling_max) / rolling_max
    max_dd = drawdown.min()

    win_rate = (monthly_returns > 0).sum() / len(monthly_returns)

    return {
        "Total Return":  f"{total_return:+.1%}",
        "CAGR":          f"{cagr:+.1%}",
        "Sharpe Ratio":  f"{sharpe:.2f}",
        "Max Drawdown":  f"{max_dd:.1%}",
        "Monthly Win Rate": f"{win_rate:.1%}",
        "Final Value (₩)": f"{portfolio.iloc[-1]:,.0f}",
    }
