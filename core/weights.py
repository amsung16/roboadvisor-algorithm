RISK_LIMITS = {'A': 0.60, 'B': 0.51, 'C': 0.42}
VOL_THRESHOLD = 0.25


def compute_weights(ranks_df, risk_profile='B', top_n=10):
    """
    Convert frank scores to portfolio weights, applying the risk profile constraint.
    - Selects top_n ETFs by frank score.
    - Weights are proportional to inverse frank score (lower frank = higher weight).
    - If high-risk allocation (vol > 25%) exceeds the profile limit, high-risk
      weights are scaled down and the remainder redistributes to lower-risk ETFs.
    """
    if risk_profile not in RISK_LIMITS:
        raise ValueError(f"risk_profile must be one of {list(RISK_LIMITS.keys())}")

    limit = RISK_LIMITS[risk_profile]
    selected = ranks_df.head(top_n).copy()

    # Inverse frank weighting — lower frank score gets higher weight
    inv_frank = 1 / selected['frank']
    selected['weight'] = inv_frank / inv_frank.sum()
    selected['is_high_risk'] = selected['vol'] > VOL_THRESHOLD

    high_risk_w = selected.loc[selected['is_high_risk'], 'weight'].sum()

    # Scale down high-risk if over limit, redistribute to low-risk
    if high_risk_w > limit:
        scale = limit / high_risk_w
        selected.loc[selected['is_high_risk'], 'weight'] *= scale
        leftover = 1.0 - selected['weight'].sum()
        low_mask = ~selected['is_high_risk']
        if low_mask.any():
            low_w = selected.loc[low_mask, 'weight']
            selected.loc[low_mask, 'weight'] += leftover * (low_w / low_w.sum())
        else:
            selected['weight'] /= selected['weight'].sum()

    return selected[['momentum', 'vol', 'frank', 'is_high_risk', 'weight']]
