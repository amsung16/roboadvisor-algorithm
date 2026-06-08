#!/usr/bin/env python3
"""
advisor.py — ESG Advisory CLI

Usage:
  python advisor.py --onboard --name "홍길동"
  python advisor.py --rebalance --profile B
  python advisor.py --rebalance --profile B --explain
  python advisor.py --status --profile B
  python advisor.py --history
  python advisor.py --reset-profile
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

import pandas as pd
import requests

from core.ranking import get_universe_ranks
from core.weights import compute_weights, RISK_LIMITS
from core.report import generate_report
from core.onboarding import run_onboarding, INVESTOR_PROFILE_PATH

OUTPUTS = Path("outputs")
APPROVED_WEIGHTS_PATH = OUTPUTS / "approved_weights.json"
APPROVAL_LOG_PATH = OUTPUTS / "approval_log.csv"
PRICE_CSV = OUTPUTS / "price.csv"

_name_cache: dict[str, str] = {}


# ── ETF name fetching ──────────────────────────────────────────────────────

def fetch_etf_name(ticker: str) -> str:
    if ticker in _name_cache:
        return _name_cache[ticker]
    if not re.match(r"^\d{6}$", ticker):
        _name_cache[ticker] = ticker
        return ticker
    try:
        url = f"https://m.stock.naver.com/api/stock/{ticker}/basic"
        r = requests.get(url, timeout=5)
        r.raise_for_status()
        name = r.json().get("stockName", ticker)
    except Exception:
        name = ticker
    _name_cache[ticker] = name
    return name


# ── Data helpers ───────────────────────────────────────────────────────────

def load_price() -> pd.DataFrame:
    price = pd.read_csv(PRICE_CSV, index_col=0, parse_dates=True)
    price.index = pd.to_datetime(price.index)
    return price


def last_month_end(price: pd.DataFrame) -> pd.Timestamp:
    """Last available trading day in price data."""
    if price.index.empty:
        raise ValueError("Price data is empty")
    return price.index[-1]


def load_prev_weights(profile: str) -> pd.DataFrame | None:
    if not APPROVED_WEIGHTS_PATH.exists():
        return None
    data = json.loads(APPROVED_WEIGHTS_PATH.read_text(encoding="utf-8"))
    if data.get("profile") != profile:
        return None
    w = data.get("weights", {})
    if not w:
        return None
    return pd.DataFrame.from_dict(w, orient="index", columns=["weight"])


def compute_turnover(current: pd.DataFrame, prev: pd.DataFrame | None) -> float:
    if prev is None:
        return 1.0
    all_etfs = set(current.index) | set(prev.index)
    total = sum(
        abs(
            (current.loc[e, "weight"] if e in current.index else 0.0)
            - (prev.loc[e, "weight"] if e in prev.index else 0.0)
        )
        for e in all_etfs
    )
    return total / 2


# ── Row building ───────────────────────────────────────────────────────────

def _signal(change: float, curr_w: float, prev_w: float) -> str:
    if prev_w > 0 and curr_w == 0:
        return "✗ SELL"
    if prev_w == 0 and curr_w > 0:
        return "↑ BUY"
    if change > 0.01:
        return "↑ BUY"
    if change < -0.01:
        return "↓ REDUCE"
    return "→ HOLD"


def build_rows(current: pd.DataFrame, prev: pd.DataFrame | None) -> list[tuple]:
    """Return list of (ticker, name, curr_w, change, signal) sorted by weight desc, sells last."""
    prev_tickers = set(prev.index) if prev is not None else set()
    rows = []

    for ticker in current.sort_values("weight", ascending=False).index:
        curr_w = float(current.loc[ticker, "weight"])
        prev_w = float(prev.loc[ticker, "weight"]) if (prev is not None and ticker in prev.index) else 0.0
        change = curr_w - prev_w
        rows.append((ticker, fetch_etf_name(ticker), curr_w, change, _signal(change, curr_w, prev_w)))

    for ticker in sorted(prev_tickers - set(current.index)):
        prev_w = float(prev.loc[ticker, "weight"])
        rows.append((ticker, fetch_etf_name(ticker), 0.0, -prev_w, "✗ SELL"))

    return rows


# ── Display: rich ──────────────────────────────────────────────────────────

def _print_proposal_rich(rows, profile, rebal_date, weights, turnover):
    from rich.console import Console
    from rich.table import Table
    from rich import box
    from rich.text import Text

    console = Console()
    limit = RISK_LIMITS[profile]
    high_risk_alloc = float(weights.loc[weights["is_high_risk"], "weight"].sum())
    within = high_risk_alloc <= limit

    table = Table(
        title=f"REBALANCING PROPOSAL │ Profile {profile} │ {str(rebal_date)[:10]}",
        box=box.DOUBLE_EDGE,
        show_header=True,
        header_style="bold",
    )
    table.add_column("ETF", min_width=28)
    table.add_column("WEIGHT", justify="right", min_width=7)
    table.add_column("CHANGE", justify="right", min_width=7)
    table.add_column("SIGNAL", min_width=10)

    for row in rows:
        name, curr_w, change, signal = row[1], row[2], row[3], row[4]
        if change > 0:
            change_txt = Text(f"+{change:.1%}", style="green")
        elif change < 0:
            change_txt = Text(f"{change:.1%}", style="red")
        else:
            change_txt = Text("  0.0%", style="dim")

        if "BUY" in signal:
            sig_txt = Text(signal, style="green")
        elif "REDUCE" in signal:
            sig_txt = Text(signal, style="yellow")
        elif "SELL" in signal:
            sig_txt = Text(signal, style="red")
        else:
            sig_txt = Text(signal, style="dim")

        table.add_row(name[:30], f"{curr_w:.1%}" if curr_w else "0.0%", change_txt, sig_txt)

    console.print(table)

    risk_color = "green" if within else "red"
    risk_check = "✓ Within limit" if within else "✗ Over limit"
    console.print(
        f"  High-risk allocation: [bold]{high_risk_alloc:.1%}[/bold] (limit {limit:.0%})  "
        f"[{risk_color}]{risk_check}[/{risk_color}]"
    )
    console.print(f"  Estimated turnover: {turnover:.1%}\n")


# ── Display: plain text fallback ───────────────────────────────────────────

def _print_proposal_plain(rows, profile, rebal_date, weights, turnover):
    limit = RISK_LIMITS[profile]
    high_risk_alloc = float(weights.loc[weights["is_high_risk"], "weight"].sum())
    within = high_risk_alloc <= limit

    W = 64
    bar = "═" * W
    sep = "─" * W

    print(f"╔{bar}╗")
    title = f"REBALANCING PROPOSAL │ Profile {profile} │ {str(rebal_date)[:10]}"
    print(f"║  {title:<{W - 2}}║")
    print(f"╠{bar}╣")
    print(f"║  {'ETF':<28}  {'WEIGHT':>7}  {'CHANGE':>7}  {'SIGNAL':<10}║")
    print(f"║  {sep}║")

    for row in rows:
        name, curr_w, change, signal = row[1], row[2], row[3], row[4]
        name_col = name[:28]
        w_col = f"{curr_w:.1%}" if curr_w else "0.0%"
        if change > 0:
            c_col = f"+{change:.1%}"
        elif change == 0:
            c_col = "  0.0%"
        else:
            c_col = f"{change:.1%}"
        print(f"║  {name_col:<28}  {w_col:>7}  {c_col:>7}  {signal:<10}║")

    risk_check = "✓ Within limit" if within else "✗ Over limit"
    risk_line = f"High-risk allocation: {high_risk_alloc:.1%} (limit {limit:.0%})  {risk_check}"
    turnover_line = f"Estimated turnover: {turnover:.1%}"
    print(f"╠{bar}╣")
    print(f"║  {risk_line:<{W - 2}}║")
    print(f"║  {turnover_line:<{W - 2}}║")
    print(f"╚{bar}╝\n")


def print_proposal(rows, profile, rebal_date, weights, turnover):
    try:
        _print_proposal_rich(rows, profile, rebal_date, weights, turnover)
    except ImportError:
        _print_proposal_plain(rows, profile, rebal_date, weights, turnover)


# ── Persistence ────────────────────────────────────────────────────────────

def save_approval(weights: pd.DataFrame, profile: str, rebal_date, turnover: float, rows: list[tuple]):
    OUTPUTS.mkdir(exist_ok=True)

    payload = {
        "profile": profile,
        "date": str(rebal_date)[:10],
        "weights": {t: float(weights.loc[t, "weight"]) for t in weights.index},
    }
    APPROVED_WEIGHTS_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    top3 = [row[1] for row in rows if row[2] > 0][:3]
    log_exists = APPROVAL_LOG_PATH.exists()
    with APPROVAL_LOG_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not log_exists:
            writer.writerow(["date", "profile", "turnover", "approved_by", "top3_etfs"])
        writer.writerow([str(rebal_date)[:10], profile, f"{turnover:.4f}", "human", ";".join(top3)])


# ── Approval loop ──────────────────────────────────────────────────────────

def run_approval(weights, prev_weights, profile, rebal_date, rows, turnover, dry_run):
    while True:
        print("Type 'y' to approve │ 'n' to reject │ 'explain' for AI report │ 'q' to quit")
        try:
            choice = input("→ ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)

        if choice == "y":
            if dry_run:
                print("--dry-run: skipping save.")
            else:
                save_approval(weights, profile, rebal_date, turnover, rows)
                print("✓ Rebalancing approved and logged.")
            return
        elif choice == "n":
            print("✗ Rebalancing rejected. No changes logged.")
            return
        elif choice == "explain":
            print("\nGenerating AI report...\n")
            report = generate_report(weights, prev_weights, profile, str(rebal_date)[:10])
            print(report)
            print()
        elif choice == "q":
            sys.exit(0)
        else:
            print("Enter 'y', 'n', 'explain', or 'q'.")


# ── Profile resolution ─────────────────────────────────────────────────────

def resolve_profile(profile_arg: str | None) -> str:
    """Return the profile to use: explicit arg > saved profile > error."""
    if profile_arg:
        return profile_arg
    if INVESTOR_PROFILE_PATH.exists():
        data = json.loads(INVESTOR_PROFILE_PATH.read_text(encoding="utf-8"))
        saved = data.get("profile")
        if saved in RISK_LIMITS:
            name = data.get("name", "")
            print(f"저장된 프로필 사용: {name}님 ({saved}형)\n")
            return saved
    print("프로필이 없습니다. 먼저 python advisor.py --onboard 를 실행하세요.")
    sys.exit(1)


# ── Commands ───────────────────────────────────────────────────────────────

def cmd_onboard(name: str | None):
    if not name:
        try:
            name = input("투자자 이름을 입력하세요: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)
    if not name:
        print("이름을 입력해주세요.")
        sys.exit(1)
    run_onboarding(name)


def cmd_reset_profile(name: str | None):
    if INVESTOR_PROFILE_PATH.exists():
        INVESTOR_PROFILE_PATH.unlink()
        print("기존 프로필이 삭제되었습니다.\n")
    cmd_onboard(name)


def cmd_rebalance(profile: str, explain: bool, dry_run: bool):
    price = load_price()
    rebal_date = last_month_end(price)
    prev_weights = load_prev_weights(profile)

    print()
    ranks = get_universe_ranks(price, rebal_date)
    weights = compute_weights(ranks, risk_profile=profile, top_n=10)
    turnover = compute_turnover(weights, prev_weights)
    rows = build_rows(weights, prev_weights)

    print()
    print_proposal(rows, profile, rebal_date, weights, turnover)

    if explain:
        print("Generating AI report...\n")
        report = generate_report(weights, prev_weights, profile, str(rebal_date)[:10])
        print(report)
        print()

    run_approval(weights, prev_weights, profile, rebal_date, rows, turnover, dry_run)


def cmd_status(profile: str):
    price = load_price()
    rebal_date = last_month_end(price)
    prev_weights = load_prev_weights(profile)

    print()
    ranks = get_universe_ranks(price, rebal_date)
    weights = compute_weights(ranks, risk_profile=profile, top_n=10)
    turnover = compute_turnover(weights, prev_weights)
    rows = build_rows(weights, prev_weights)

    print()
    print_proposal(rows, profile, rebal_date, weights, turnover)

    if not APPROVAL_LOG_PATH.exists():
        print("No approval log found.")
        return

    last = None
    with APPROVAL_LOG_PATH.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["profile"] == profile:
                last = row

    if last:
        print(f"Last approved: {last['date']}  (turnover {float(last['turnover']):.1%})")
    else:
        print(f"No prior approvals for profile {profile}.")


def cmd_history():
    if not APPROVAL_LOG_PATH.exists():
        print("No approval history found.")
        return

    with APPROVAL_LOG_PATH.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if not rows:
        print("Approval log is empty.")
        return

    try:
        from rich.console import Console
        from rich.table import Table
        from rich import box

        console = Console()
        table = Table(title="Approval History", box=box.DOUBLE_EDGE)
        table.add_column("Date", min_width=12)
        table.add_column("Profile", justify="center", min_width=8)
        table.add_column("Turnover", justify="right", min_width=10)
        table.add_column("Top 3 ETFs", min_width=40)

        for r in rows:
            table.add_row(
                r["date"],
                r["profile"],
                f"{float(r['turnover']):.1%}",
                r.get("top3_etfs", "").replace(";", ", "),
            )
        console.print(table)
    except ImportError:
        print(f"\n{'Date':<12}  {'Profile':<8}  {'Turnover':<10}  Top 3 ETFs")
        print("-" * 72)
        for r in rows:
            top3 = r.get("top3_etfs", "").replace(";", ", ")
            print(f"{r['date']:<12}  {r['profile']:<8}  {float(r['turnover']):.1%}        {top3}")
        print()


# ── Entry point ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="ESG Advisory CLI")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--rebalance", action="store_true", help="Compute and approve a rebalancing")
    mode.add_argument("--status", action="store_true", help="Show current computed weights")
    mode.add_argument("--history", action="store_true", help="Show past approved rebalancings")
    mode.add_argument("--onboard", action="store_true", help="Run investor risk-profile questionnaire")
    mode.add_argument("--reset-profile", action="store_true", help="Delete saved profile and re-run onboarding")
    parser.add_argument("--profile", choices=["A", "B", "C"], help="Risk profile (overrides saved profile)")
    parser.add_argument("--name", help="Investor name for onboarding")
    parser.add_argument("--explain", action="store_true", help="Auto-generate AI report before approval")
    parser.add_argument("--dry-run", action="store_true", help="Skip saving; useful for testing")

    args = parser.parse_args()

    if args.onboard:
        cmd_onboard(args.name)
    elif args.reset_profile:
        cmd_reset_profile(args.name)
    elif args.rebalance:
        cmd_rebalance(resolve_profile(args.profile), args.explain, args.dry_run)
    elif args.status:
        cmd_status(resolve_profile(args.profile))
    elif args.history:
        cmd_history()


if __name__ == "__main__":
    main()
