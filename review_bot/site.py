"""배민/쿠팡이츠 사장님 사이트 공통 조작. 화면 요소는 config/selectors.yaml 에서 읽는다."""
from __future__ import annotations

import logging
import random
import re
import time
from pathlib import Path

from playwright.sync_api import Locator, Page
from playwright.sync_api import TimeoutError as PWTimeout

from .config import Account
from .models import Review

log = logging.getLogger(__name__)


class ReviewSite:
    def __init__(self, page: Page, account: Account, selectors: dict, delay=(2.0, 5.0)):
        self.page = page
        self.account = account
        self.sel = selectors
        self.r = selectors["reviews"]
        self.delay = delay
        self.reviews_url = account.reviews_url or selectors["reviews_url"]

    # ---------- 공통 ----------
    def pause(self) -> None:
        time.sleep(random.uniform(*self.delay))

    def _exists(self, css: str, root: Page | Locator | None = None) -> bool:
        return bool(css) and (root or self.page).locator(css).count() > 0

    def _text(self, root: Locator, css: str) -> str:
        if not css:
            return ""
        loc = root.locator(css).first
        return loc.inner_text().strip() if loc.count() else ""

    # ---------- 로그인 ----------
    def is_review_page(self, timeout_ms: int = 15000) -> bool:
        try:
            self.page.wait_for_selector(self.r["list_ready"], timeout=timeout_ms)
            return True
        except PWTimeout:
            return False

    def goto(self, url: str) -> bool:
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            return True
        except Exception as e:  # 접속 차단(ERR_HTTP2_PROTOCOL_ERROR 등), 주소 오류, 시간 초과
            log.error("%s: %s 접속 실패 - %s", self.account.label, url, str(e).splitlines()[0])
            return False

    def ensure_logged_in(self, creds: tuple[str, str] | None) -> bool:
        if self.goto(self.reviews_url) and self.is_review_page(8000):
            return True
        if not creds:
            log.error("%s: .env 에 아이디/비밀번호가 없습니다.", self.account.label)
            return False

        L = self.sel["login"]
        if not self._exists(L["id_input"]) and not self.goto(L["url"]):
            return False
        try:
            self.page.fill(L["id_input"], creds[0], timeout=10000)
            self.pause()
            self.page.fill(L["pw_input"], creds[1])
            self.pause()
            self.page.click(L["submit"])
            self.page.wait_for_load_state("networkidle", timeout=20000)
        except PWTimeout:
            log.warning("%s: 로그인 화면 요소를 찾지 못했습니다.", self.account.label)

        if self.goto(self.reviews_url) and self.is_review_page():
            return True
        log.error(
            "%s: 로그인 실패 (문자 인증 요구 가능). '2_최초로그인.bat' 으로 직접 로그인해 주세요.",
            self.account.label,
        )
        return False

    # ---------- 리뷰 목록 ----------
    def open_reviews(self) -> None:
        if self.r.get("unanswered_tab") and self._exists(self.r["unanswered_tab"]):
            self.page.locator(self.r["unanswered_tab"]).first.click()
            self.pause()
        self._load_all()

    def _cards(self) -> Locator:
        return self.page.locator(self.r["card"])

    def _load_all(self, max_rounds: int = 30) -> None:
        for _ in range(max_rounds):
            before = self._cards().count()
            more = self.r.get("load_more")
            if more and self.page.locator(more).first.is_visible():
                self.page.locator(more).first.click()
            else:
                self.page.mouse.wheel(0, 6000)
            self.page.wait_for_timeout(1500)
            if self._cards().count() == before:
                break

    def _rating(self, card: Locator) -> int | None:
        cfg = self.r["rating"]
        if cfg.get("mode") == "count":
            n = card.locator(cfg["selector"]).count()
            return n if 1 <= n <= 5 else None
        loc = card.locator(cfg["selector"]).first
        if not loc.count():
            return None
        raw = loc.get_attribute(cfg["attribute"]) if cfg.get("attribute") else loc.inner_text()
        m = re.search(cfg.get("regex", r"([1-5])"), raw or "")
        return int(m.group(1)) if m else None

    def extract(self, card: Locator) -> Review:
        order_src = self._text(card, self.r.get("order_count_text", "")) or card.inner_text()
        m = re.search(self.r.get("order_count_regex", r"(\d+)\s*번째"), order_src)
        return Review(
            platform=self.account.platform,
            account=self.account.name,
            author=self._text(card, self.r["author"]),
            rating=self._rating(card),
            text=self._text(card, self.r["text"]),
            order_count=int(m.group(1)) if m else None,
            has_photo=self._exists(self.r.get("photo", ""), card),
            date_text=self._text(card, self.r.get("date", "")),
        )

    def unanswered(self) -> list[Review]:
        reviews = []
        cards = self._cards()
        for i in range(cards.count()):
            card = cards.nth(i)
            if self._exists(self.r["reply_exists"], card):
                continue
            try:
                reviews.append(self.extract(card))
            except Exception as e:  # 한 카드 오류로 전체가 멈추지 않도록
                log.warning("%s: %d번째 리뷰 읽기 실패 - %s", self.account.label, i + 1, e)
        return reviews

    def find_card(self, key: str) -> Locator | None:
        cards = self._cards()
        for i in range(cards.count()):
            card = cards.nth(i)
            try:
                if self.extract(card).key == key:
                    return card
            except Exception:
                continue
        return None

    # ---------- 동작 ----------
    def capture(self, key: str, path: Path) -> bool:
        card = self.find_card(key)
        if card is None:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        card.scroll_into_view_if_needed()
        card.screenshot(path=str(path))
        return True

    def post_reply(self, key: str, body: str) -> bool:
        card = self.find_card(key)
        if card is None:
            log.warning("%s: 답글 달 리뷰를 화면에서 찾지 못했습니다.", self.account.label)
            return False
        card.scroll_into_view_if_needed()
        card.locator(self.r["reply_button"]).first.click()
        self.pause()
        box = card.locator(self.r["reply_textarea"]).first
        if not box.count():
            box = self.page.locator(self.r["reply_textarea"]).last
        box.fill(body)
        self.pause()
        scope = card if self._exists(self.r["reply_submit"], card) else self.page
        scope.locator(self.r["reply_submit"]).last.click()
        self.page.wait_for_timeout(2500)
        card = self.find_card(key)
        return card is None or self._exists(self.r["reply_exists"], card)
