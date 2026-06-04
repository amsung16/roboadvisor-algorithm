"""
core/report.py — LLM-powered Korean advisory report generator.

Calls the Claude API to write a plain-language rebalancing summary in Korean.
Falls back to a plain-text DataFrame summary if the API is unavailable.
"""

import os
from pathlib import Path

import pandas as pd

from core.weights import RISK_LIMITS

_MODEL = "claude-opus-4-6"


# ── Internal helpers ───────────────────────────────────────────────────────

def _format_table(weights: pd.DataFrame) -> str:
    header = f"{'종목명':<32} {'비중':>6}  {'모멘텀':>7}  {'변동성':>6}  {'프랭크':>6}  고위험"
    sep = "-" * 72
    rows = [header, sep]
    for etf, row in weights.iterrows():
        flag = "✓" if row["is_high_risk"] else " "
        rows.append(
            f"{etf:<32} {row['weight']:>6.1%}  {row['momentum']:>7.3f}"
            f"  {row['vol']:>6.1%}  {row['frank']:>6.2f}  {flag}"
        )
    return "\n".join(rows)


def _describe_changes(current: pd.DataFrame, prev: pd.DataFrame | None) -> str:
    if prev is None:
        return "첫 번째 리밸런싱으로 이전 월 데이터가 없습니다."

    curr_set = set(current.index)
    prev_set = set(prev.index)

    lines = []
    new_etfs = sorted(curr_set - prev_set)
    removed_etfs = sorted(prev_set - curr_set)

    if new_etfs:
        lines.append(f"신규 편입: {', '.join(new_etfs)}")
    if removed_etfs:
        lines.append(f"제외: {', '.join(removed_etfs)}")

    shifts = []
    for etf in sorted(curr_set & prev_set):
        delta = current.loc[etf, "weight"] - prev.loc[etf, "weight"]
        if abs(delta) > 0.02:
            shifts.append(f"{etf} ({delta:+.1%})")
    if shifts:
        lines.append(f"비중 변화 >2%: {', '.join(shifts)}")

    return "\n".join(lines) if lines else "전월 대비 구성 변화 없음 (비중 ±2% 이내 유지)."


def _build_prompt(
    current_weights: pd.DataFrame,
    prev_weights: pd.DataFrame | None,
    risk_profile: str,
    rebal_date: str,
) -> str:
    limit = RISK_LIMITS[risk_profile]
    high_risk_alloc = current_weights.loc[current_weights["is_high_risk"], "weight"].sum()

    return f"""당신은 ESG 투자 자문사의 포트폴리오 매니저입니다.
아래 데이터를 바탕으로 고객용 한국어 자문 보고서를 작성해주세요.

## 리밸런싱 정보
- 기준일: {rebal_date}
- 리스크 프로필: {risk_profile}형 (고위험 자산 한도: {limit:.0%})
- 현재 고위험 자산 비중: {high_risk_alloc:.1%}

## 포트폴리오 구성 (상위 10개 ETF)
{_format_table(current_weights)}

## 전월 대비 변경사항
{_describe_changes(current_weights, prev_weights)}

## 작성 지침
- 전문적이지만 이해하기 쉬운 한국어로 작성하세요 (전문 용어 최소화).
- 정확히 3개의 문단으로 구성하세요:
  1문단: 이번 달 주요 편입 종목과 선정 이유 (모멘텀과 안정성 중심으로 설명)
  2문단: 전월 대비 주요 변경사항과 그 배경
  3문단: 리스크 고려사항, 고위험 자산 비중 현황, 이 보고서가 자문 목적으로만 제공됨을 명시
- 수익을 약속하거나 데이터 범위를 초과하는 예측을 하지 마세요.
- 400단어 이내로 작성하세요."""


def _plain_summary(
    current_weights: pd.DataFrame,
    prev_weights: pd.DataFrame | None,
    risk_profile: str,
    rebal_date: str,
) -> str:
    """Plain-text fallback built directly from DataFrames — no LLM required."""
    limit = RISK_LIMITS[risk_profile]
    high_risk_alloc = current_weights.loc[current_weights["is_high_risk"], "weight"].sum()

    lines = [
        f"[{rebal_date}] 월간 리밸런싱 요약 — {risk_profile}형 (고위험 한도 {limit:.0%})",
        "",
        "포트폴리오 구성:",
        _format_table(current_weights),
        "",
        f"고위험 자산 총 비중: {high_risk_alloc:.1%} / 한도 {limit:.0%}",
        "",
        "변경사항:",
        _describe_changes(current_weights, prev_weights),
        "",
        "※ 이 요약은 자문 목적으로만 제공되며 수익을 보장하지 않습니다.",
    ]
    return "\n".join(lines)


# ── Public API ─────────────────────────────────────────────────────────────

def generate_report(
    current_weights: pd.DataFrame,
    prev_weights: pd.DataFrame | None,
    risk_profile: str,
    rebal_date: str,
) -> str:
    """
    Call the Claude API to produce a plain-language Korean advisory report.
    Falls back to a plain-text summary if the API call fails for any reason.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    try:
        import anthropic

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is not set")

        client = anthropic.Anthropic(api_key=api_key)
        prompt = _build_prompt(current_weights, prev_weights, risk_profile, rebal_date)

        message = client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text

    except Exception as e:
        print(f"[generate_report] API call failed ({e}) — returning plain summary.")
        return _plain_summary(current_weights, prev_weights, risk_profile, rebal_date)


def save_report(report: str, rebal_date: str, risk_profile: str) -> Path:
    """Save report string to outputs/report_{rebal_date}_{risk_profile}.txt"""
    out_dir = Path("outputs")
    out_dir.mkdir(exist_ok=True)
    path = out_dir / f"report_{rebal_date}_{risk_profile}.txt"
    path.write_text(report, encoding="utf-8")
    return path
