"""
core/onboarding.py — Investor risk-profile questionnaire.
"""

import json
import sys
from datetime import date
from pathlib import Path

from core.weights import RISK_LIMITS

INVESTOR_PROFILE_PATH = Path("outputs/investor_profile.json")

QUESTIONS = [
    {
        "text": "Q1. 투자 목적은 무엇인가요?",
        "options": [
            ("원금 보전 및 안정적 이자 수익", 5),
            ("안정적 수익과 일부 성장 추구", 10),
            ("장기적 자산 성장 추구", 15),
            ("공격적 자산 증대 추구", 20),
        ],
    },
    {
        "text": "Q2. 투자 가능 기간은 얼마나 되시나요?",
        "options": [
            ("6개월 미만", 5),
            ("6개월 ~ 1년", 10),
            ("1년 ~ 3년", 15),
            ("3년 이상", 20),
        ],
    },
    {
        "text": "Q3. 투자 경험이 있으신가요?",
        "options": [
            ("투자 경험 없음", 5),
            ("예적금 위주", 8),
            ("펀드/ETF 경험 있음", 15),
            ("주식 직접 투자 경험 있음", 20),
        ],
    },
    {
        "text": "Q4. 자산의 몇 %를 이 포트폴리오에 투자하실 예정인가요?",
        "options": [
            ("10% 미만", 20),
            ("10% ~ 30%", 15),
            ("30% ~ 50%", 10),
            ("50% 이상", 5),
        ],
    },
    {
        "text": "Q5. 포트폴리오가 20% 하락한다면?",
        "options": [
            ("즉시 전액 매도한다", 5),
            ("절반을 매도한다", 10),
            ("그대로 유지한다", 15),
            ("추가 매수 기회로 본다", 20),
        ],
    },
    {
        "text": "Q6. 기대 연간 수익률은?",
        "options": [
            ("3% 미만", 5),
            ("3% ~ 7%", 10),
            ("7% ~ 15%", 15),
            ("15% 이상", 20),
        ],
    },
]


def _ask(q: dict) -> int:
    print(f"\n{q['text']}")
    for i, (label, score) in enumerate(q["options"], 1):
        print(f"  {i}) {label} ({score}점)")
    while True:
        try:
            raw = input("→ ").strip()
            idx = int(raw)
            if 1 <= idx <= len(q["options"]):
                return idx
        except (ValueError, KeyboardInterrupt, EOFError):
            pass
        print(f"  1에서 {len(q['options'])} 사이의 숫자를 입력하세요.")


def _score_to_profile(score: int) -> tuple[str, str]:
    if score >= 81:
        return "A", "공격형"
    if score >= 61:
        return "B", "위험중립형"
    return "C", "안정추구형"


def run_onboarding(name: str) -> dict:
    print(f"\n안녕하세요, {name}님! 투자 성향 설문을 시작합니다.")

    answers = []
    total = 0
    for q in QUESTIONS:
        idx = _ask(q)
        _, score = q["options"][idx - 1]
        answers.append(idx)
        total += score

    profile, label = _score_to_profile(total)
    limit = RISK_LIMITS[profile]

    W = 36
    print(f"\n{'═' * W}")
    print(f"투자자: {name}")
    print(f"총점: {total}점 / 120점")
    print(f"투자 성향: {profile}형 ({label})")
    print(f"최대 위험자산 비중: {limit:.0%}")
    print(f"{'═' * W}")

    try:
        confirm = input("이 성향으로 저장할까요? [y/N] → ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print()
        sys.exit(0)

    if confirm != "y":
        print("저장을 취소했습니다.")
        return {}

    result = {
        "name": name,
        "profile": profile,
        "score": total,
        "created_at": str(date.today()),
        "answers": answers,
    }

    Path("outputs").mkdir(exist_ok=True)
    INVESTOR_PROFILE_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(f"\n✓ 프로필이 저장되었습니다. 이제 다음 명령어를 사용하세요:")
    print(f"  python advisor.py --rebalance")
    print(f"(--profile 옵션 없이도 저장된 {profile}형이 자동으로 적용됩니다)")

    return result
