from __future__ import annotations

from .models import Review


def pick_template(review: Review, rules: dict) -> str:
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
