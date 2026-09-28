import pytest

from review_bot.classifier import AUTO, MANUAL, classify
from review_bot.config import load_yaml
from review_bot.models import Review
from review_bot.schedule import parse_time
from review_bot.templates import build_manual_draft, build_reply

RULES = load_yaml("templates.yaml")


def r(rating, text="맛있어요", orders=None, photo=False):
    return Review("baemin", "배민_계정1", "고객", rating, text, orders, photo)


@pytest.mark.parametrize("rating", [3, 4, 5])
def test_3_to_5_stars_are_auto(rating):
    assert classify(r(rating), RULES).kind == AUTO


@pytest.mark.parametrize("rating", [1, 2, None])
def test_low_or_unknown_rating_needs_check(rating):
    assert classify(r(rating), RULES).kind == MANUAL


def test_claim_keyword_overrides_high_rating():
    d = classify(r(5, "맛은 좋은데 머리 카락이 나왔어요"), RULES)  # 띄어쓰기 무시
    assert d.kind == MANUAL and "머리카락" in d.reason


def test_abusive_needs_check():
    assert classify(r(4, "ㅅㅂ 늦네"), RULES).kind == MANUAL


def test_template_priority():
    assert build_reply(r(3, orders=7, photo=True), RULES)[0] == "three_star"
    assert build_reply(r(5, orders=7, photo=True), RULES)[0] == "vip"
    assert build_reply(r(5, orders=2, photo=True), RULES)[0] == "photo"
    assert build_reply(r(4, orders=1), RULES)[0] == "default"


def test_vip_template_fills_order_count_and_has_no_name_prefix():
    _, body = build_reply(r(5, orders=12), RULES)
    assert "무려 12번째나" in body
    assert "{" not in body and not body.startswith("000님")
    assert body.startswith("안녕하세요! 101번지") and "고객님!" not in body.splitlines()[0]


def test_three_star_promises_better_next_time():
    _, body = build_reply(r(3), RULES)
    assert "다음번에는 꼭 만족" in body


@pytest.mark.parametrize("text,category", [
    ("먹고 배탈 났어요", "건강이상"),
    ("머리카락 나옴 위생 최악", "이물질/위생"),
    ("돈까스가 덜익었어요", "조리상태"),
    ("소스 누락됐어요", "누락/배달"),
    ("환불해주세요", "환불요청"),
])
def test_claim_category_and_draft(text, category):
    d = classify(r(5, text), RULES)
    assert (d.kind, d.category) == (MANUAL, category)
    draft = build_manual_draft(d.category, RULES)
    assert draft.startswith("101번지 남산돈까스 본점입니다.")


def test_low_rating_without_keyword_gets_default_draft():
    d = classify(r(1, "그냥 그래요"), RULES)
    assert d.category is None
    assert build_manual_draft(d.category, RULES) == RULES["manual_default_reply"].strip()


@pytest.mark.parametrize("raw,expected", [("8:30", "08:30"), ("13시30분", "13:30"), ("9시", "09:00")])
def test_parse_time(raw, expected):
    assert parse_time(raw) == expected


def test_parse_time_rejects_garbage():
    with pytest.raises(ValueError):
        parse_time("25:00")
