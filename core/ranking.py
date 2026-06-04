import numpy as np
import pandas as pd

MIN_HISTORY = 252


def get_universe_ranks(price_data, rebal_date):
    """Dynamic Universe Rule: only ETFs with >= 252 valid trading days as of rebal_date."""
    data = price_data[price_data.index <= str(rebal_date)]

    valid_counts = data.notna().sum()
    universe = valid_counts[valid_counts >= MIN_HISTORY].index.tolist()
    excluded  = valid_counts[valid_counts <  MIN_HISTORY]

    print(f"Rebalancing: {str(rebal_date)[:10]}  |  Universe: {len(universe)}/{len(price_data.columns)} ETFs")
    for etf, cnt in excluded.items():
        print(f"  Excluded {etf}: only {int(cnt)} trading days")

    results = {}
    for etf in universe:
        valid   = data[etf].dropna()                # never use pre-listing data
        base    = valid.iloc[-MIN_HISTORY]           # price 252 valid days ago
        last    = valid.iloc[-1]
        log_ret = np.log(valid.tail(MIN_HISTORY) / valid.tail(MIN_HISTORY).shift(1)).dropna()
        results[etf] = {
            "momentum": round(last / base, 3),
            "vol":      log_ret.std() * np.sqrt(250),
        }

    df = pd.DataFrame(results).T
    df["mrank"]  = df["momentum"].rank(ascending=False, method="min")
    df["vrank"]  = df["vol"].rank(ascending=True,  method="min")
    n = len(df)
    df_sorted = df.sort_values("mrank").copy()
    df_sorted["mrank3"] = [(n - i) / 100 for i in range(n)]
    df["mrank3"] = df_sorted["mrank3"]
    df["frank"]  = df["vrank"] + df["mrank"] - df["mrank3"]
    return df.sort_values("frank")
