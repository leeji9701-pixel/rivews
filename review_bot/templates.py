from __future__ import annotations

from .models import Review


def rules_for(rules: dict, brand: str | None) -> dict:
    """브랜드별 문구를 적용한 규칙. 브랜드 문구에 빠진 항목이 있으면 오류 (다른 브랜드 문구가 달리지 않도록)."""
    if not brand or brand == rules.get("default_brand"):
        return rules
    over = (rules.get("brands") or {}).get(brand)
    if over is None:
        raise KeyError(f"templates.yaml 에 브랜드 '{brand}' 문구가 없습니다.")
    missing = [k for k in rules["positive"] if k not in over.get("positive", {})]
    missing += [c["name"] for c in rules["claim_categories"] if c["name"] not in over.get("claim_replies", {})]
    if "manual_default_reply" not in over:
        missing.append("manual_default_reply")
    if missing:
        raise KeyError(f"templates.yaml 브랜드 '{brand}' 에 빠진 문구: {', '.join(missing)}")
    merged = dict(rules)
    merged["positive"] = over["positive"]
    merged["claim_categories"] = [
        {**c, "reply": over["claim_replies"][c["name"]]} for c in rules["claim_categories"]
    ]
    merged["manual_default_reply"] = over["manual_default_reply"]
    return merged


def pick_template(review: Review, rules: dict) -> str:
    if review.rating == 3 and "three_star" in rules["positive"]:
        return "three_star"
    vip_min = int(rules.get("vip_min_orders", 3))
    if review.order_count and review.order_count >= vip_min:
        return "vip"
    if review.has_photo:
        return "photo"
    return "default"


def build_reply(review: Review, rules: dict) -> tuple[str, str]:
    """(템플릿 이름, 답글 본문) 반환. 앞의 '000님,' 은 플랫폼이 자동으로 붙인다."""
    name = pick_template(review, rules)
    body = rules["positive"][name].format(order_count=review.order_count or "")
    return name, body.strip()


def build_manual_draft(category: str | None, rules: dict) -> str:
    """확인 후 등록 리뷰의 답글 초안 (자동 등록하지 않음)."""
    for cat in rules.get("claim_categories", []):
        if cat["name"] == category:
            return cat["reply"].strip()
    return rules["manual_default_reply"].strip()
