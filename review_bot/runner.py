from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

from .classifier import AUTO, classify
from .config import DATA_DIR, Account, Settings, load_yaml
from .sheets import DailyReport, PendingSheet
from .site import ReviewSite
from .templates import build_manual_draft, build_reply, rules_for

log = logging.getLogger(__name__)


def _open_context(p, account: Account, headless: bool, channel: str | None = None):
    """PC에 설치된 크롬(channel='chrome')을 우선 사용. 쿠팡 등은 기본 Chromium 접속을 차단하기도 한다."""
    account.session_dir.mkdir(parents=True, exist_ok=True)
    opts = dict(
        headless=headless,
        locale="ko-KR",
        timezone_id="Asia/Seoul",
        viewport={"width": 1400, "height": 900},
        args=["--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"],
    )
    if channel:
        try:
            return p.chromium.launch_persistent_context(str(account.session_dir), channel=channel, **opts)
        except Exception as e:
            log.warning("%s 브라우저를 열 수 없어 기본 브라우저로 진행합니다 (%s)", channel, str(e).splitlines()[0])
    return p.chromium.launch_persistent_context(str(account.session_dir), **opts)


def _safe(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "_", name)[:40]


def run(settings: Settings, account_name: str | None = None) -> None:
    selectors = load_yaml("selectors.yaml")
    rules = load_yaml("templates.yaml")
    pending = PendingSheet(settings.folder("pending_file"))
    report = DailyReport(settings.folder("reports"))
    capture_dir = settings.folder("captures") / datetime.now().strftime("%Y-%m-%d")
    known = pending.keys()
    stats = {"auto": 0, "draft": 0, "manual": 0, "fail": 0}

    with sync_playwright() as p:
        for account in settings.find_accounts(account_name):
            log.info("===== %s 시작 =====", account.label)
            ctx = _open_context(p, account, settings.headless, settings.browser_channel)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            site = ReviewSite(page, account, selectors[account.platform], settings.delay_range)
            try:
                if not site.ensure_logged_in(account.credentials()):
                    stats["fail"] += 1
                    continue
                stores = settings.stores_for(account) or [None]  # None = 매장 전환 없는 일반 계정
                posted = 0
                for store in stores:
                    if store is not None:
                        log.info("--- 매장: %s ---", store.name)
                        if not site.switch_store(store):
                            stats["fail"] += 1
                            continue
                    brand_rules = rules_for(rules, store.brand if store else None)
                    site.open_reviews(store)
                    posted = _process(site, account, brand_rules, settings, pending, report,
                                      capture_dir, known, stats, posted)
            except Exception:
                stats["fail"] += 1
                log.exception("%s 처리 중 오류", account.label)
                err = DATA_DIR / "errors" / f"{datetime.now():%Y%m%d_%H%M%S}_{account.env_prefix}.png"
                err.parent.mkdir(parents=True, exist_ok=True)
                try:
                    page.screenshot(path=str(err), full_page=True)
                    log.info("오류 화면 저장: %s", err)
                except Exception:
                    pass
            finally:
                ctx.close()

    pending_path = pending.save()
    report_path = report.save()
    log.info(
        "완료 | 자동등록 %d · 초안(시험운영) %d · 검수대기 %d · 실패 %d",
        stats["auto"], stats["draft"], stats["manual"], stats["fail"],
    )
    if stats["manual"]:
        log.info("검수 후 직접 등록할 리뷰: %s (캡처: %s)", pending_path, capture_dir)
    if report_path:
        log.info("처리내역: %s", report_path)


def _process(site, account, rules, settings, pending, report, capture_dir, known, stats, posted) -> int:
    """미답변 리뷰 분류 → 자동답글 / 확인후등록(캡처 + 답글 초안, 등록은 담당자가 직접)."""
    for review in site.iter_unanswered():
        decision = classify(review, rules)
        if decision.kind == AUTO:
            if posted >= settings.max_replies:
                continue
            tpl, body = build_reply(review, rules)
            if settings.dry_run:
                result = "초안(미등록)"
                stats["draft"] += 1
            elif site.post_reply(review.key, body):
                result = "등록완료"
                stats["auto"] += 1
                posted += 1
            else:
                result = "등록실패"
                stats["fail"] += 1
            report.add(review, decision.kind, decision.reason, tpl, body, result)
            site.pause()
        else:
            if review.key in known:
                continue  # 이미 확인대기에 올라간 리뷰
            n = len(list(capture_dir.glob("*.png"))) + 1 if capture_dir.exists() else 1
            where = _safe(review.store or account.name)
            shot = capture_dir / f"{n:02d}_{where}_{review.rating or '?'}점_{_safe(review.author)}.png"
            captured = site.capture(review.key, shot)
            draft = build_manual_draft(decision.category, rules)
            pending.add(review, decision.reason, str(shot) if captured else "캡처 실패", draft)
            known.add(review.key)
            stats["manual"] += 1
            report.add(review, decision.kind, decision.reason, decision.category or "", draft, "검수대기")
    return posted


def manual_login(settings: Settings, account_name: str | None = None) -> None:
    """문자 인증 등 사람이 직접 로그인해야 할 때. 로그인 상태는 data/sessions 에 저장된다."""
    selectors = load_yaml("selectors.yaml")
    with sync_playwright() as p:
        for account in settings.find_accounts(account_name):
            ctx = _open_context(p, account, headless=False, channel=settings.browser_channel)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            site = ReviewSite(page, account, selectors[account.platform], settings.delay_range)
            print(f"\n▶ {account.label} 로그인 창을 엽니다.")
            try:
                if site.ensure_logged_in(account.credentials()):
                    print("  이미 로그인되어 있습니다.")
                    continue
                print(f"  자동 접속이 안 되면 브라우저 주소창에 직접 입력하세요: {site.sel['login']['url']}")
                input("  브라우저에서 로그인/문자 인증을 마친 뒤 여기서 Enter 를 누르세요...")
                print("  ✅ 확인 완료" if site.is_review_page(5000) else "  ⚠️ 리뷰 화면이 확인되지 않았습니다 (selectors 점검 필요)")
            except Exception as e:
                log.exception("%s 로그인 중 오류", account.label)
                print(f"  ❌ 오류로 이 계정은 건너뜁니다: {str(e).splitlines()[0]}")
            finally:
                ctx.close()


def dump_pages(settings: Settings, account_name: str | None = None) -> None:
    """실제 화면을 저장해 selectors.yaml 을 맞출 때 사용. 답글창은 열기만 하고 등록하지 않는다."""
    selectors = load_yaml("selectors.yaml")
    out = DATA_DIR / "dump" / datetime.now().strftime("%Y%m%d_%H%M")
    out.mkdir(parents=True, exist_ok=True)

    def save(page, name: str) -> None:
        base: Path = out / name
        base.with_suffix(".html").write_text(page.content(), encoding="utf-8")
        page.screenshot(path=str(base.with_suffix(".png")), full_page=True)
        print(f"  저장: {base.name}.html / .png")

    with sync_playwright() as p:
        for account in settings.find_accounts(account_name):
            print(f"\n▶ {account.label}")
            ctx = _open_context(p, account, headless=False, channel=settings.browser_channel)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            site = ReviewSite(page, account, selectors[account.platform], settings.delay_range)
            prefix = account.env_prefix.lower()
            try:
                if not site.ensure_logged_in(account.credentials()):
                    input("  브라우저에서 로그인 후 리뷰 화면까지 직접 이동한 뒤 Enter...")
                page.wait_for_timeout(3000)
                save(page, prefix)
                if not site.is_review_page(3000):
                    print("  ⚠️ 리뷰 화면으로 인식되지 않았습니다.")
                    continue
                site.open_reviews()
                save(page, f"{prefix}_미답변")
                for review in site.iter_unanswered(max_steps=20):
                    card = site.find_card(review.key)
                    if card is not None:
                        site.open_reply_box(card)
                        page.wait_for_timeout(2000)
                        save(page, f"{prefix}_답글창")
                        print("  (답글창만 열었고 등록하지 않았습니다)")
                    break
                else:
                    print("  미답변 리뷰가 없어 답글창은 확인하지 못했습니다.")
            except Exception as e:
                log.exception("%s 화면 저장 중 오류", account.label)
                print(f"  ❌ 건너뜀: {str(e).splitlines()[0]}")
                try:
                    save(page, f"{prefix}_오류")
                except Exception:
                    pass
            finally:
                ctx.close()
    print(f"\n저장 폴더: {out}")
