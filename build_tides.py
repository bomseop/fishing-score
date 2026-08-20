#!/usr/bin/env python3
"""
build_tides.py — 조석예보 연간 선계산

프론트엔드가 읽는 data/tide-<YEAR>.json 을 생성한다.
연 1회만 돌리면 되고, 이미 완성된 연도는 --force 없이는 다시 만들지 않는다.

  python build_tides.py                  # 올해분, 없으면 생성
  python build_tides.py --year 2027      # 특정 연도
  python build_tides.py --force          # 강제 재생성
  python build_tides.py --budget 1200    # 이번 실행에서 1200회만 호출하고 중단
  python build_tides.py --stations DT_0001,DT_0018
  python build_tides.py --scan           # 지점표 재스캔 (khoa_api.STATIONS 갱신용)

환경변수:
  DATA_GO_KR_KEY   공공데이터포털 일반 인증키
                   https://www.data.go.kr/data/15156018/openapi.do 에서 활용신청

호출량 주의:
  지점 × 날짜 단위 호출이라 46개소 × 365일 = 약 16,800건.
  개발계정 일일 한도가 10,000 이라 한 번에 못 받는다. --budget 으로 쪼개 받고
  체크포인트를 .cache/ 에 남겨 다음 실행이 이어받는다.
  Actions 에서 하루 4회 × 2,400회면 이틀이면 한 해가 완성된다.
  속도가 아니라 일일 한도가 병목이다 — 2,400회는 1분 남짓이면 끝난다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from khoa_api import EP_TIDE_FCST, STATIONS, get, items, log, scan_stations, service_key

OUT_DIR = Path("data")
CKPT_DIR = Path(".cache")
# 이 API 에는 일일 한도(10,000)와 별개로 **초당 요청 제한**이 있다.
# 넘기면 429 가 돌아오고, 재시도가 일일 한도를 대신 태운다 — 가장 나쁜 낭비다.
# 실측: 1워커 13.7/s, 2워커 27.4/s, 3워커 41.9/s 까지 429 없음.
# 8워커(+대기 0.05)는 429 폭탄에 처리량은 4/s 로 오히려 떨어졌다.
# 3워커에 약간의 여유를 둬 33/s 근처를 목표로 한다.
RATE_SLEEP = 0.02          # 초 / 호출 (워커마다 적용)
WORKERS = 3                # 동시 요청 수

# 비우면 khoa_api.STATIONS 전체를 사용한다.
STATION_WHITELIST: list[str] = []


def parse_events(rows: list[dict]) -> list[list]:
    """조석예보 응답 → [["2026-08-20T01:59", 238], ...]

    `predcTdlvVl` 은 cm. 고/저조 구분(`extrSe`)은 버린다 — 프론트가 값의
    대소로 판단하고, 사인 보간은 이웃 두 극값만 있으면 성립한다.
    """
    out = []
    for r in rows:
        t = r.get("predcDt")            # "2026-08-20 01:59"
        h = r.get("predcTdlvVl")        # 238.0
        if not t or h is None:
            continue
        try:
            ts = dt.datetime.strptime(str(t).strip()[:16], "%Y-%m-%d %H:%M")
            lvl = int(round(float(h)))
        except (TypeError, ValueError):
            continue
        out.append([ts.strftime("%Y-%m-%dT%H:%M"), lvl])
    return out


def build(year: int, key: str, force: bool, budget: int = 0, workers: int = WORKERS) -> int:
    """반환값: 0 완료 / 2 예산 소진(이어서 받아야 함)"""
    OUT_DIR.mkdir(exist_ok=True)
    CKPT_DIR.mkdir(exist_ok=True)
    out_path = OUT_DIR / f"tide-{year}.json"
    ckpt_path = CKPT_DIR / f"tide-{year}.partial.json"

    if out_path.exists() and not force:
        log(f"{out_path} 이미 존재. --force 없이는 건너뜀.")
        return 0

    codes = [c for c in STATIONS if not STATION_WHITELIST or c in STATION_WHITELIST]
    stations = {c: {"name": STATIONS[c][0], "lat": STATIONS[c][1], "lon": STATIONS[c][2]}
                for c in codes}
    if not stations:
        sys.exit("대상 지점이 없습니다. --stations 값을 확인하세요.")
    log(f"조석예보 지점 {len(stations)}개소")

    # 체크포인트 복구
    events: dict[str, list] = {}
    done: set[str] = set()
    if ckpt_path.exists():
        ck = json.loads(ckpt_path.read_text(encoding="utf-8"))
        events = ck.get("events", {})
        done = set(ck.get("done", []))
        log(f"체크포인트 복구: {len(done)}건 완료 상태에서 재개")

    start = dt.date(year, 1, 1)
    end = dt.date(year, 12, 31)
    total = len(stations) * ((end - start).days + 1)
    spent = 0
    exhausted = False

    def save_ckpt() -> None:
        ckpt_path.write_text(
            json.dumps({"events": events, "done": sorted(done)}, ensure_ascii=False),
            encoding="utf-8")

    # 남은 작업을 먼저 펼친 뒤 예산만큼 잘라 병렬로 던진다.
    todo = []
    for code in codes:
        events.setdefault(code, [])
        day = start
        while day <= end:
            tag = f"{code}:{day:%Y%m%d}"
            if tag not in done:
                todo.append((code, f"{day:%Y%m%d}", tag))
            day += dt.timedelta(days=1)

    if budget and len(todo) > budget:
        todo, exhausted = todo[:budget], True
    if not todo:
        log("받을 것이 없습니다.")

    def fetch(item):
        """워커 스레드. 실패는 예외로 올리지 않고 표시만 한다 —
        한 건 때문에 전체가 멈추면 재개 비용이 크다."""
        code, ymd, tag = item
        try:
            rows = items(get(EP_TIDE_FCST, key, {
                "obsCode": code, "reqDate": ymd, "type": "json", "numOfRows": "100",
            }))
            time.sleep(RATE_SLEEP)
            return code, tag, parse_events(rows), True
        except Exception:
            return code, tag, [], False

    failed = 0
    t0 = time.time()
    try:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            # 결과 소비는 메인 스레드에서만 하므로 events/done 에 락이 필요 없다.
            for code, tag, evs, ok in ex.map(fetch, todo):
                if not ok:
                    failed += 1
                    continue          # done 에 넣지 않는다. 다음 실행이 다시 받는다.
                events[code].extend(evs)
                done.add(tag)
                spent += 1
                if spent % 500 == 0:
                    rate = spent / max(time.time() - t0, 1e-6)
                    left = (len(todo) - spent) / max(rate, 1e-6)
                    log(f"  {len(done)}/{total} ({len(done)/total:.1%})  "
                        f"{rate:.0f}건/초  남은 {left/60:.1f}분")
                    save_ckpt()
    except KeyboardInterrupt:
        save_ckpt()
        log("중단됨. 체크포인트 저장 완료 — 같은 명령으로 재실행하면 이어받습니다.")
        sys.exit(1)

    if failed:
        log(f"실패 {failed}건 (다음 실행에서 재시도)")
        exhausted = True

    if exhausted:
        save_ckpt()
        log(f"예산 {budget}회 소진. 진행률 {len(done)/total:.1%} ({len(done)}/{total})")
        log("다음 실행에서 이어서 받습니다.")
        return 2

    # 정렬 · 중복 제거
    for code in events:
        seen, uniq = set(), []
        for e in sorted(events[code], key=lambda x: x[0]):
            if e[0] in seen:
                continue
            seen.add(e[0])
            uniq.append(e)
        events[code] = uniq

    # 빈 지점은 내보내지 않는다. 프론트의 최근접 탐색이 빈 지점을 고르면
    # 물때 팩터가 통째로 죽는다 — 차라리 다음 지점으로 넘어가게 둔다.
    empty = [c for c, ev in events.items() if len(ev) < 2]
    for c in empty:
        events.pop(c)
        stations.pop(c, None)
    if empty:
        log(f"이벤트가 없어 제외한 지점 {len(empty)}개: {', '.join(empty)}")

    # 관측소별 정규화 상수를 미리 계산해 프론트 부팅을 가볍게 만든다.
    max_rate, max_range = {}, {}
    for code, ev in events.items():
        mr = mR = 0.0
        for i in range(1, len(ev)):
            dh = abs(ev[i][1] - ev[i - 1][1])
            dt_h = (dt.datetime.fromisoformat(ev[i][0])
                    - dt.datetime.fromisoformat(ev[i - 1][0])).total_seconds() / 3600
            if dt_h > 0:
                mr = max(mr, dh / 2 * 3.14159265 / dt_h)
                mR = max(mR, dh)
        max_rate[code] = round(mr, 2)
        max_range[code] = round(mR, 2)

    payload = {
        "year": year,
        "generated": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": "data.go.kr 1192136 tideFcstHghLw",
        "unit": {"level": "cm", "rate": "cm/h"},
        "stations": stations,
        "events": events,
        "maxRate": max_rate,
        "maxRange": max_range,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")
    ckpt_path.unlink(missing_ok=True)
    size = out_path.stat().st_size / 1e6
    log(f"완료 → {out_path} ({size:.1f} MB, {sum(len(v) for v in events.values())} events)")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=dt.date.today().year)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--budget", type=int, default=0,
                    help="이번 실행의 최대 API 호출 수 (0=무제한)")
    ap.add_argument("--stations", type=str, default="")
    ap.add_argument("--workers", type=int, default=WORKERS,
                    help=f"동시 요청 수 (기본 {WORKERS})")
    ap.add_argument("--scan", action="store_true",
                    help="지점표를 다시 스캔해 출력한다 (khoa_api.STATIONS 갱신용)")
    args = ap.parse_args()

    key = service_key()

    if args.scan:
        found = scan_stations(key)
        log(f"{len(found)}개소 발견")
        for c, (n, la, lo) in sorted(found.items()):
            print(f'    "{c}": ("{n}", {la:.5f}, {lo:.5f}),')
        sys.exit(0)

    if args.stations:
        STATION_WHITELIST.extend(s.strip() for s in args.stations.split(",") if s.strip())

    sys.exit(build(args.year, key, args.force, args.budget, args.workers))


if __name__ == "__main__":
    main()
