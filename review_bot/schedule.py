"""윈도우 작업 스케줄러 등록 및 연차/반차용 날짜별 시간 변경."""
from __future__ import annotations

import json
import platform
import re
import subprocess
from datetime import date, datetime

from .config import DATA_DIR, ROOT, Settings, save_schedule_time

TASK_DAILY = "NamsanReviewBot"
TASK_ONCE_PREFIX = "NamsanReviewBot_"
OVERRIDES = DATA_DIR / "schedule_overrides.json"
SKIP = "skip"


def parse_time(value: str) -> str:
    m = re.fullmatch(r"\s*(\d{1,2})\s*[:시]\s*(\d{1,2})?\s*분?\s*", value or "")
    if not m:
        raise ValueError(f"시간 형식이 올바르지 않습니다: {value!r} (예: 08:30)")
    h, mi = int(m.group(1)), int(m.group(2) or 0)
    if not (0 <= h < 24 and 0 <= mi < 60):
        raise ValueError(f"없는 시간입니다: {value!r}")
    return f"{h:02d}:{mi:02d}"


def parse_date(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return date.today().isoformat()
    d = datetime.strptime(value.replace(".", "-").replace("/", "-"), "%Y-%m-%d").date()
    if d < date.today():
        raise ValueError("지난 날짜는 설정할 수 없습니다.")
    return d.isoformat()


# ---------- 날짜별 예외 (연차/반차) ----------
def load_overrides() -> dict[str, str]:
    if not OVERRIDES.exists():
        return {}
    data = json.loads(OVERRIDES.read_text(encoding="utf-8"))
    today = date.today().isoformat()
    return {d: v for d, v in data.items() if d >= today}  # 지난 날짜는 정리


def save_overrides(data: dict[str, str]) -> None:
    OVERRIDES.parent.mkdir(parents=True, exist_ok=True)
    OVERRIDES.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def regular_run_skipped(today: str | None = None) -> bool:
    """오늘 날짜에 예외가 있으면 매일 정기 실행은 건너뛴다 (예외 시간에 따로 실행)."""
    return (today or date.today().isoformat()) in load_overrides()


# ---------- 작업 스케줄러 ----------
def _powershell(script: str) -> bool:
    if platform.system() != "Windows":
        print("[윈도우가 아니라서 작업 스케줄러 등록을 건너뜁니다]\n" + script)
        return False
    res = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        print("작업 스케줄러 등록 실패:\n" + (res.stderr or res.stdout))
        return False
    return True


def _register(task: str, bat: str, trigger: str) -> bool:
    bat_path = ROOT / "scripts" / bat
    script = f"""
$a = New-ScheduledTaskAction -Execute '"{bat_path}"' -WorkingDirectory '{ROOT}'
$t = {trigger}
$s = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName '{task}' -Action $a -Trigger $t -Settings $s -Force | Out-Null
"""
    return _powershell(script)


def install_daily(hhmm: str) -> bool:
    return _register(TASK_DAILY, "run_scheduled.bat", f"New-ScheduledTaskTrigger -Daily -At '{hhmm}'")


def set_daily(hhmm: str) -> None:
    hhmm = parse_time(hhmm)
    save_schedule_time(hhmm)
    ok = install_daily(hhmm)
    print(f"✅ 매일 실행 시간을 {hhmm} 으로 저장했습니다." + ("" if ok else " (작업 스케줄러 미반영)"))


def set_for_date(day: str, value: str) -> None:
    day = parse_date(day)
    overrides = load_overrides()
    task = f"{TASK_ONCE_PREFIX}{day}"
    _powershell(f"Unregister-ScheduledTask -TaskName '{task}' -Confirm:$false -ErrorAction SilentlyContinue")

    if value.strip() in ("쉼", "건너뛰기", "skip", "0"):
        overrides[day] = SKIP
        save_overrides(overrides)
        print(f"✅ {day} 은(는) 자동 실행을 쉽니다. 리뷰는 다음 실행 때 한꺼번에 처리됩니다.")
        return

    hhmm = parse_time(value)
    if day == date.today().isoformat() and hhmm <= datetime.now().strftime("%H:%M"):
        raise ValueError("오늘은 지금보다 늦은 시간만 설정할 수 있습니다.")
    overrides[day] = hhmm
    save_overrides(overrides)
    _register(task, "run_override.bat", f"New-ScheduledTaskTrigger -Once -At '{day} {hhmm}'")
    print(f"✅ {day} 에는 {hhmm} 에 실행합니다. (그날 정기 {Settings.load().schedule_time} 실행은 건너뜀)")


def cancel_date(day: str) -> None:
    day = parse_date(day)
    overrides = load_overrides()
    overrides.pop(day, None)
    save_overrides(overrides)
    _powershell(f"Unregister-ScheduledTask -TaskName '{TASK_ONCE_PREFIX}{day}' -Confirm:$false -ErrorAction SilentlyContinue")
    print(f"✅ {day} 예외를 취소했습니다. 평소 시간에 실행됩니다.")


def show() -> None:
    print(f"매일 실행 시간: {Settings.load().schedule_time}")
    overrides = load_overrides()
    if not overrides:
        print("날짜별 예외: 없음")
    for d, v in sorted(overrides.items()):
        print(f"  {d}: {'쉼' if v == SKIP else v + ' 실행'}")
