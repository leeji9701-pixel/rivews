"""실제 배민 셀프서비스 화면 구조(2026-09 페이지점검 기준)를 본뜬 가짜 화면으로 selectors.yaml 검증.
실제 고객 정보는 넣지 않았다."""
import os

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

from review_bot.config import Account, Store, load_yaml  # noqa: E402
from review_bot.site import ReviewSite  # noqa: E402

STAR_ON = '<svg width="16" aria-hidden="true"><path d="M1" fill="#FFC600"></path></svg>'
STAR_OFF = '<svg width="16" aria-hidden="true"><path d="M1" fill="#D5D7D9"></path></svg>'


def card(idx, nick, stars, review_no, text="", orders=None, photo=False, replied=False):
    order = (f'<div class="ReviewOrderCount-module__og1o"><span>{orders}회 주문 고객</span>'
             '<span>(최근 6개월 누적 주문)</span></div>') if orders else ""
    body_text = f'<span data-atelier-component="Typography">{text}</span>' if text else ""
    img = '<img alt="리뷰 사진" src="x.png">' if photo else ""
    reply = ('<div class="ReviewCommentBox-module__QOie"><p class="CommentItem-module__w2un">답글</p></div>'
             '<button>사장님 댓글 추가하기</button>') if replied else '<button>사장님 댓글 등록하기</button>'
    return f"""
<div data-index="{idx}"><div data-atelier-component="Container">
 <div class="ReviewContent-module__Ksg4" data-atelier-component="Container">
  <div data-atelier-component="Flex">
   <div><div class="ReviewItem-module__rH3h"><div class="ReviewItem-module__s9r6">
     <div data-atelier-component="Flex">
      <div data-atelier-component="Flex"><span data-atelier-component="Badge"><span>한집배달</span></span>
        <span data-atelier-component="Typography">{nick}</span></div>
      <div data-atelier-component="Flex"><div>{STAR_ON * stars}{STAR_OFF * (5 - stars)}</div>
        <span data-atelier-component="Typography">2026년 9월 28일</span></div>
      <span data-atelier-component="Typography">리뷰번호 {review_no}</span>
     </div></div>
     <div class="ReviewItem-module__btRe">{order}</div></div></div>
   <div><div data-atelier-component="Flex">{body_text}
     <div data-atelier-component="Flex">{img}</div>
     <div data-atelier-component="Flex">{reply}</div></div></div>
  </div></div></div></div>"""


PAGE = f"""
<div class="ShopSelect-module__Nmhh"><div class="ShopSelect-module__JWCr">
 <div class="ShopSelect-module__J8wl"><h3 class="ShopSelect-module__b8Mn">[음식배달] 101번지 남산돈까스 본점</h3></div>
 <select class="Select-module__a623 ShopSelect-module___pC1">
  <option value="13119541">[음식배달] 101번지 남산돈까스 본점 / 돈까스 13119541</option>
  <option value="14928762">[음식배달] 가가솥밥 / 한식 14928762</option>
 </select></div></div>
<div role="tablist"><button role="tab">전체(3)</button><button role="tab">미답변(2)</button></div>
{card(0, "손님A", 5, "2026092800000001", "맛있어요", orders=4, photo=True)}
{card(1, "손님B", 4, "2026092800000002", replied=True)}
{card(2, "손님C", 1, "2026092800000003", "머리카락 나왔어요")}
"""


@pytest.fixture
def site():
    sel = load_yaml("selectors.yaml")["baemin"]
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
        page = browser.new_page()
        page.set_content(PAGE)
        yield ReviewSite(page, Account("baemin", "배민_계정1", "B1"), sel, delay=(0, 0))
        browser.close()


def test_review_page_and_shop_url(site):
    assert site.is_review_page(3000)
    assert site._reviews_url() == "https://self.baemin.com/shops/13119541/reviews"


def test_extract_unanswered(site):
    a, c = list(site.iter_unanswered(max_steps=5))
    assert (a.author, a.rating, a.order_count, a.has_photo, a.text) == ("손님A", 5, 4, True, "맛있어요")
    assert a.date_text == "리뷰번호 2026092800000001"
    assert (c.author, c.rating, c.order_count, c.has_photo) == ("손님C", 1, None, False)


def test_store_select_finds_gagasotbap_option(site, monkeypatch):
    opened = []
    monkeypatch.setattr(site, "_open_reviews_page", lambda shop_id=None: opened.append(shop_id) or True)
    monkeypatch.setattr(site, "_current_shop_id", lambda: opened[-1] if opened else None)
    assert site.switch_store(Store("가가솥밥", "gagasotbap", "14928762"))
    assert opened == ["14928762"]
    assert not site.switch_store(Store("없는매장", "namsan"))
