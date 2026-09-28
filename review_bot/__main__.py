from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

from . import schedule
from .config import LOG_DIR, Settings, load_env


def setup_logging() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fmt = "%(asctime)s %(levelname)s %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        datefmt="%H:%M:%S",
        handlers=[
            logging.FileHandler(LOG_DIR / f"{datetime.now():%Y-%m-%d}.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="review_bot", description="남산돈까스 리뷰 답글 자동화")
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="리뷰 답글 작업 실행")
    r.add_argument("--account", help="특정 계정만 (settings.yaml 의 name)")
    r.add_argument("--scheduled", action="store_true", help="매일 정기 실행 (날짜별 예외가 있으면 건너뜀)")
    r.add_argument("--approved-only", action="store_true", help="확인대기.xlsx 답글만 등록")

    for name, help_ in [("login", "직접 로그인/문자 인증"), ("dump", "리뷰 화면 저장(점검용)")]:
        sp = sub.add_parser(name, help=help_)
        sp.add_argument("--account")

    s = sub.add_parser("schedule", help="실행 시간 관리")
    ssub = s.add_subparsers(dest="action", required=True)
    ssub.add_parser("show")
    ssub.add_parser("install", help="settings.yaml 의 시간으로 작업 스케줄러 등록")
    d = ssub.add_parser("daily", help="매일 실행 시간 변경")
    d.add_argument("--time")
    o = ssub.add_parser("date", help="특정 날짜만 시간 변경/쉬기 (연차·반차)")
    o.add_argument("--date")
    o.add_argument("--time", help="HH:MM 또는 '쉼'")
    c = ssub.add_parser("cancel", help="특정 날짜 예외 취소")
    c.add_argument("--date")

    args = ap.parse_args(argv)
    load_env()
    settings = Settings.load()

    if args.cmd == "schedule":
        try:
            if args.action == "show":
                schedule.show()
            elif args.action == "install":
                schedule.set_daily(settings.schedule_time)
            elif args.action == "daily":
                schedule.show()
                schedule.set_daily(args.time or input("\n새 매일 실행 시간 (예: 09:00): "))
            elif args.action == "date":
                schedule.show()
                day = args.date if args.date is not None else input("\n날짜 (예: 2026-10-02, 엔터=오늘): ")
                value = args.time or input("그날 실행할 시간 (예: 13:30, 하루 쉬려면 '쉼'): ")
                schedule.set_for_date(day, value)
            elif args.action == "cancel":
                schedule.cancel_date(args.date if args.date is not None else input("취소할 날짜 (엔터=오늘): "))
        except ValueError as e:
            print(f"❌ {e}")
            sys.exit(1)
        return

    setup_logging()
    log = logging.getLogger("review_bot")

    if args.cmd == "run":
        if args.scheduled and schedule.regular_run_skipped():
            log.info("오늘은 날짜별 예외가 있어 정기 실행을 건너뜁니다.")
            return
        if settings.dry_run and not args.approved_only:
            log.info("[시험 운영] dry_run=true → 템플릿 답글은 등록하지 않고 초안만 기록합니다.")
        from .runner import run

        run(settings, args.account, approved_only=args.approved_only)
    elif args.cmd == "login":
        from .runner import manual_login

        manual_login(settings, args.account)
    elif args.cmd == "dump":
        from .runner import dump_pages

        dump_pages(settings, args.account)


if __name__ == "__main__":
    main()
