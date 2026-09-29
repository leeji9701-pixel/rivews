"""배민/쿠팡이츠 사장님 사이트 공통 조작. 화면 요소는 config/selectors.yaml 에서 읽는다."""
from __future__ import annotations

import logging
import random
import re
import time
from collections.abc import Iterator
from pathlib import Path

from playwright.sync_api import Locator, Page
from playwright.sync_api import TimeoutError as PWTimeout

from .config import Account, Store
from .models import Review

log = logging.getLogger(__name__)


class ReviewSite:
    def __init__(self, page: Page, account: Account, selectors: dict, delay=(2.0, 5.0)):
        self.page = page
        self.account = account
        self.sel = selectors
        self.r = selectors["reviews"]
        self.delay = delay
        self.store_name = ""
        self.shop_id: str | None = None
        page.set_default_timeout(15000)

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

    def goto(self, url: str) -> bool:
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            return True
        except Exception as e:  # 접속 차단(ERR_HTTP2_PROTOCOL_ERROR 등), 주소 오류, 시간 초과
            log.error("%s: %s 접속 실패 - %s", self.account.label, url, str(e).splitlines()[0])
            return False

    def _blocked(self) -> bool:
        if "Access Denied" in (self.page.title() or ""):
            log.error("%s: 플랫폼이 접속을 차단했습니다 (Access Denied).", self.account.label)
            return True
        return False

    # ---------- 리뷰 페이지 주소 ----------
    def _current_shop_id(self) -> str | None:
        """배민처럼 주소에 가게번호가 들어가는 경우, 현재 선택된 가게번호를 찾는다."""
        m = re.search(r"/shops/(\d+)", self.page.url)
        if m:
            return m.group(1)
        src = self.sel.get("shop_id_from")
        if src and self._exists(src):
            try:
                value = self.page.locator(src).first.input_value()
                if value:
                    return value
            except Exception:
                pass
        links = self.page.locator("a[href*='/shops/']")
        if links.count():
            m = re.search(r"/shops/(\d+)", links.first.get_attribute("href") or "")
            if m:
                return m.group(1)
        return None

    def _reviews_url(self, shop_id: str | None = None) -> str | None:
        url = self.account.reviews_url or self.sel["reviews_url"]
        if "{shop_id}" not in url:
            return url
        shop_id = shop_id or self.shop_id or self._current_shop_id()
        return url.format(shop_id=shop_id) if shop_id else None

    # ---------- 로그인 ----------
    def is_review_page(self, timeout_ms: int = 15000) -> bool:
        try:
            self.page.wait_for_selector(self.r["list_ready"], timeout=timeout_ms)
            return True
        except PWTimeout:
            return False

    def _is_login_page(self) -> bool:
        return self._exists(self.sel["login"]["id_input"])

    def _open_reviews_page(self, shop_id: str | None = None) -> bool:
        """홈 화면을 거쳐 리뷰 화면으로 이동 (바로 깊은 주소로 들어가면 차단되는 경우가 있어서)."""
        home = self.sel.get("home_url")
        if home and not shop_id:
            if not self.goto(home) or self._blocked():
                return False
            self.page.wait_for_timeout(2500)
            if self._is_login_page():
                return False
        nav = self.r.get("reviews_nav")
        if nav and not shop_id and self._exists(nav):
            self.page.locator(nav).first.click()
        else:
            url = self._reviews_url(shop_id)
            if not url:
                log.error("%s: 리뷰 화면 주소(가게번호)를 찾지 못했습니다.", self.account.label)
                return False
            if not self.goto(url) or self._blocked():
                return False
        ok = self.is_review_page()
        if ok:
            self.shop_id = self._current_shop_id() or shop_id
        return ok

    def ensure_logged_in(self, creds: tuple[str, str] | None) -> bool:
        if self._open_reviews_page():
            return True
        if self._blocked():
            return False
        if not creds:
            log.error("%s: .env 에 아이디/비밀번호가 없습니다.", self.account.label)
            return False

        L = self.sel["login"]
        if not self._is_login_page() and (not self.goto(L["url"]) or self._blocked()):
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

        if self._open_reviews_page():
            return True
        log.error(
            "%s: 로그인 실패 (문자 인증 요구 가능). '2_최초로그인.bat' 으로 직접 로그인해 주세요.",
            self.account.label,
        )
        return False

    # ---------- 매장 선택 (여러 매장 계정) ----------
    def _current_store_is(self, store: Store) -> bool:
        sw = self.sel.get("store_switch") or {}
        if sw.get("mode") == "select" and store.store_id and self.shop_id == store.store_id:
            return True
        cur = sw.get("current")
        if not cur or not self._exists(cur):
            return False
        text = " ".join(self.page.locator(cur).all_inner_texts())
        return store.name in text or bool(store.store_id and store.store_id in text)

    def _switch_by_select(self, store: Store, sw: dict) -> bool:
        """배민: 매장 선택 목록(select)에서 매장 번호를 찾아 그 매장의 리뷰 화면으로 이동."""
        options = self.page.locator(sw["select"]).first.locator("option")
        target = None
        for i in range(options.count()):
            opt = options.nth(i)
            value = opt.get_attribute("value") or ""
            label = opt.text_content() or ""
            if (store.store_id and (value == store.store_id or store.store_id in label)) or (
                not store.store_id and store.name in label
            ):
                target = value
                break
        if not target:
            log.error("%s: 매장 목록에 '%s' 이(가) 없습니다.", self.account.label, store.name)
            return False
        if not self._open_reviews_page(shop_id=target):
            return False
        self.shop_id = target
        return self._current_shop_id() == target

    def _switch_by_click(self, store: Store, sw: dict) -> None:
        if sw.get("home_url"):
            self.goto(sw["home_url"])
            self.page.wait_for_timeout(2000)
        if self._current_store_is(store):
            return
        self.page.locator(sw["open"]).first.click(timeout=10000)
        self.pause()
        options = self.page.locator(sw["option"])
        for label in filter(None, [store.store_id, store.name]):
            match = options.filter(has_text=label)
            if match.count():
                match.first.click()
                break
        self.page.wait_for_timeout(2500)

    def switch_store(self, store: Store) -> bool:
        """매장을 선택한다. 선택된 매장을 확인하지 못하면 False (다른 매장에 답글이 달리지 않도록)."""
        sw = self.sel.get("store_switch") or {}
        try:
            if sw.get("mode") == "select":
                ok = self._switch_by_select(store, sw)
            else:
                self._switch_by_click(store, sw)
                ok = self._current_store_is(store) and self._open_reviews_page()
            if not ok or not self._current_store_is(store):
                log.error("%s: '%s' 매장 선택을 확인하지 못해 건너뜁니다.", self.account.label, store.name)
                return False
            return True
        except Exception as e:
            log.error("%s: '%s' 매장 선택 실패 - %s", self.account.label, store.name, str(e).splitlines()[0])
            return False

    # ---------- 리뷰 목록 ----------
    def open_reviews(self, store: Store | None = None) -> None:
        self.store_name = store.name if store else ""
        tab = self.r.get("unanswered_tab")
        if tab and self._exists(tab):
            self.page.locator(tab).first.click()
            self.page.wait_for_timeout(2500)

    def _cards(self) -> Locator:
        return self.page.locator(self.r["card"])

    def _scroll_more(self) -> None:
        """화면에 보이는 리뷰만 불러오는 목록이라 조금씩 내려가며 읽는다."""
        more = self.r.get("load_more")
        if more and self._exists(more) and self.page.locator(more).first.is_visible():
            self.page.locator(more).first.click()
        else:
            cards = self._cards()
            if cards.count():
                last = cards.last
                last.scroll_into_view_if_needed()
                box = last.bounding_box()
                if box:
                    self.page.mouse.move(box["x"] + box["width"] / 2, box["y"] + min(box["height"] / 2, 200))
            self.page.mouse.wheel(0, int(self.r.get("scroll_step", 1200)))
        self.page.wait_for_timeout(1500)

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
        order_src = self._text(card, self.r.get("order_count_text", ""))
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
            store=self.store_name,
        )

    def iter_unanswered(self, max_steps: int = 300) -> Iterator[Review]:
        """미답변 리뷰를 하나씩 돌려준다. 받은 쪽에서 답글/캡처를 처리한 뒤 다음 리뷰로 넘어간다."""
        seen: set[str] = set()
        stale = 0
        for _ in range(max_steps):
            if stale >= 3:
                return
            target, new = None, 0
            cards = self._cards()
            for i in range(cards.count()):
                card = cards.nth(i)
                try:
                    review = self.extract(card)
                    answered = self._exists(self.r["reply_exists"], card)
                except Exception:
                    continue  # 스크롤 중 사라진 카드
                if review.key in seen:
                    continue
                seen.add(review.key)
                new += 1
                if not answered:
                    target = review
                    break
            if target:
                stale = 0
                yield target
                continue
            stale = stale + 1 if new == 0 else 0
            self._scroll_more()

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

    def open_reply_box(self, card: Locator) -> Locator:
        card.scroll_into_view_if_needed()
        card.locator(self.r["reply_button"]).first.click()
        self.pause()
        box = card.locator(self.r["reply_textarea"]).first
        return box if box.count() else self.page.locator(self.r["reply_textarea"]).last

    def post_reply(self, key: str, body: str) -> bool:
        card = self.find_card(key)
        if card is None:
            log.warning("%s: 답글 달 리뷰를 화면에서 찾지 못했습니다.", self.account.label)
            return False
        author = self._text(card, self.r["author"])
        box = self.open_reply_box(card)
        # 플랫폼이 미리 넣어둔 '000님, ' 은 지우지 않고 그 뒤에 본문을 붙인다
        prefix = box.input_value()
        if not prefix.strip():
            prefix = f"{author}님, " if author else ""
        elif not prefix.endswith((" ", "\n")):
            prefix += " "
        box.fill(prefix + body)
        self.pause()
        scope = card if self._exists(self.r["reply_submit"], card) else self.page
        scope.locator(self.r["reply_submit"]).last.click()
        self.page.wait_for_timeout(2500)
        card = self.find_card(key)
        return card is None or self._exists(self.r["reply_exists"], card)
