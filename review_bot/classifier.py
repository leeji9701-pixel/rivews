from __future__ import annotations

from dataclasses import dataclass

from .models import Review, normalize

AUTO = "자동답글"
MANUAL = "확인후등록"


@dataclass
class Decision:
    kind: str
    reason: str


def classify(review: Review, rules: dict) -> Decision:
    text = normalize(review.text)

    abusive = [k for k in rules.get("abusive_keywords", []) if normalize(k) in text]
    if abusive:
        return Decision(MANUAL, f"욕설/비방: {', '.join(abusive)}")

    claims = [k for k in rules.get("claim_keywords", []) if normalize(k) in text]
    if claims:
        return Decision(MANUAL, f"클레임 키워드: {', '.join(claims)}")

    if review.rating is None:
        return Decision(MANUAL, "별점 확인 불가")

    if review.rating <= int(rules.get("manual_max_rating", 2)):
        return Decision(MANUAL, f"저별점 {review.rating}점")

    return Decision(AUTO, f"{review.rating}점 일반 리뷰")
