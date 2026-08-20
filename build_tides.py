#!/usr/bin/env python3
"""
build_tides.py — KHOA 조석예보 연간 선계산

프론트엔드가 읽는 data/tide-<YEAR>.json 을 생성한다.
연 1회만 돌리면 되고, 이미 완성된 연도는 --force 없이는 다시 만들지 않는다.

  python build_tides.py                  # 올해분, 없으면 생성
  python build_tides.py --year 2027      # 특정 연도
  python build_tides.py --force          # 강제 재생성
  python build_tides.py --budget 3000    # 이번 실행에서 3000회만 호출하고 중단
  python build_tides.py --stations DT_0001,DT_0002

환경변수:
  KHOA_KEY   바다누리 해양정보 서비스 인증키
             https://www.khoa.go.kr/oceangrid/khoa/koofs.do 에서 발급

호출량 주의:
  일자 × 관측소 단위 호출이라 40개소 × 365일 = 14,600건.
  개발계정 일일 한도(보통 10,000)를 넘으므로 --budget 으로 쪼개 받는다.
  체크포인트가 .cache/ 에 남으므로 여러 번에 나눠 실행하면 이어서 받는다.
  GitHub Actions 에서는 하루 한 번 --budget 3000 으로 돌리면 5일 만에 완성된다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
from urllib.error import HTTPError, URLError

KHOA_BASE = "http://www.khoa.go.kr/api/oceangrid"
EP_STATIONS = f"{KHOA_BASE}/ObsServiceObj/search.do"      # 관측소 목록
EP_TIDE_PRE = f"{KHOA_BASE}/tideObsPreTab/search.do"      # 조석예보(고·저조)

OUT_DIR = Path("data")
CKPT_DIR = Path(".cache")
RATE_SLEEP = 0.12          # 초 / 호출
MAX_RETRY = 3

# 워킹 포인트가 붙어 있는 연안 조위관측소만 추린다.
# 비우면 ObsServiceObj 응답의 조위관측소 전체를 사용.
STATION_WHITELIST: list[str] = []


def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def api_get(url: str, params: dict) -> dict:
    q = urlencode(params)
    for attempt in range(1, MAX_RETRY + 1):
        try:
            with urlopen(f"{url}?{q}", timeout=20) as r:
                return json.loads(r.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as e:
            if attempt == MAX_RETRY:
                raise
            wait = 2 ** attempt
            log(f"  재시도 {attempt}/{MAX_RETRY} ({e}) — {wait}s 대기")
            time.sleep(wait)
    raise RuntimeError("unreachable")


def fetch_stations(key: str) -> dict[str, dict]:
    """조위관측소 목록. 반환 스키마는 프론트가 그대로 쓴다."""
    log("관측소 목록 조회")
    js = api_get(EP_STATIONS, {"ServiceKey": key, "ServiceType": "json"})
    rows = js.get("result", {}).get("data", [])
    out: dict[str, dict] = {}
    for r in rows:
        code = r.get("obs_post_id") or r.get("obs_code")
        name = r.get("obs_post_name") or r.get("obs_object")
        lat, lon = r.get("obs_lat"), r.get("obs_lon")
        if not (code and lat and lon):
            continue
        # 조위관측소(DT_) 만. 부이(TW_/KG_) 등은 조석예보가 없다.
        if not str(code).startswith("DT_"):
            continue
        if STATION_WHITELIST and code not in STATION_WHITELIST:
            continue
        out[code] = {"name": name, "lat": round(float(lat), 5), "lon": round(float(lon), 5)}
    log(f"  조위관측소 {len(out)}개소")
    return out


def parse_events(js: dict) -> list[list]:
    """
    tideObsPreTab 응답 → [["2026-08-20T03:12", 912], ...]
    수위 단위는 cm. 고/저조 구분은 값의 대소로 프론트가 알아서 판단하므로 버린다.
    """
    rows = js.get("result", {}).get("data", [])
    out = []
    for r in rows:
        t = r.get("tph_time")          # "2026-08-20 03:12:00"
        h = r.get("tph_level")         # "912"
        if not t or h is None:
            continue
        try:
            ts = dt.datetime.strptime(t.strip()[:16], "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        try:
            lvl = int(round(float(h)))
        except (TypeError, ValueError):
            continue
        out.append([ts.strftime("%Y-%m-%dT%H:%M"), lvl])
    return out


def build(year: int, key: str, force: bool, budget: int = 0) -> int:
    """반환값: 0 완료 / 2 예산 소진(이어서 받아야 함)"""
    OUT_DIR.mkdir(exist_ok=True)
    CKPT_DIR.mkdir(exist_ok=True)
    out_path = OUT_DIR / f"tide-{year}.json"
    ckpt_path = CKPT_DIR / f"tide-{year}.partial.json"

    if out_path.exists() and not force:
        log(f"{out_path} 이미 존재. --force 없이는 건너뜀.")
        return 0

    stations = fetch_stations(key)
    if not stations:
        sys.exit("관측소를 하나도 못 받았습니다. 인증키와 응답 필드명을 확인하세요.")

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
    n = 0
    spent = 0
    exhausted = False

    def save_ckpt() -> None:
        ckpt_path.write_text(
            json.dumps({"events": events, "done": sorted(done)}, ensure_ascii=False),
            encoding="utf-8")

    try:
        for code in stations:
            if exhausted:
                break
            events.setdefault(code, [])
            day = start
            while day <= end:
                tag = f"{code}:{day:%Y%m%d}"
                n += 1
                if tag in done:
                    day += dt.timedelta(days=1)
                    continue
                if budget and spent >= budget:
                    exhausted = True
                    break
                js = api_get(EP_TIDE_PRE, {
                    "ServiceKey": key,
                    "ObsCode": code,
                    "Date": f"{day:%Y%m%d}",
                    "ResultType": "json",
                })
                events[code].extend(parse_events(js))
                done.add(tag)
                spent += 1
                if spent % 200 == 0:
                    log(f"  {len(done)}/{total}  ({len(done)/total:.1%})  이번 실행 {spent}회")
                    save_ckpt()
                time.sleep(RATE_SLEEP)
                day += dt.timedelta(days=1)
    except Exception as e:
        save_ckpt()
        log(f"중단: {e}")
        log("체크포인트 저장 완료. 같은 명령으로 재실행하면 이어서 받습니다.")
        sys.exit(1)

    if exhausted:
        save_ckpt()
        pct = len(done) / total
        log(f"예산 {budget}회 소진. 진행률 {pct:.1%} ({len(done)}/{total})")
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

    # 관측소별 정규화 상수를 여기서 미리 계산해 프론트 부팅을 가볍게 만든다.
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
        "source": "KHOA tideObsPreTab",
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
    args = ap.parse_args()

    if args.stations:
        STATION_WHITELIST.extend(s.strip() for s in args.stations.split(",") if s.strip())

    key = os.environ.get("KHOA_KEY", "").strip()
    if not key:
        sys.exit("KHOA_KEY 환경변수가 없습니다.")

    sys.exit(build(args.year, key, args.force, args.budget))


if __name__ == "__main__":
    main()
