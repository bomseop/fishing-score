#!/usr/bin/env python3
"""
collect_sst.py — 연안 실측 수온 수집

프론트엔드가 읽는 data/sst-latest.json 을 생성한다.
격자 수온(Open-Meteo)은 동해 냉수대처럼 국지적인 현상을 8km 격자에서 뭉개므로
조위관측소 실측값을 최근접 보간용으로 따로 모은다.

  python collect_sst.py               # 조위관측소만
  python collect_sst.py --with-nifs   # 국립수산과학원 실시간 어장정보까지

환경변수:
  DATA_GO_KR_KEY   공공데이터포털 일반 인증키
                   https://www.data.go.kr/data/15155508/openapi.do 에서 활용신청
  NIFS_ENDPOINT    (선택) 국립수산과학원 API 요청주소 재정의

호출량:
  지점 46개소 × 1회 = 실행당 46회. 개발계정 10,000회/일 안에서 여유롭다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

from khoa_api import EP_DT_RECENT, STATIONS, get, items, log, service_key, write_atomic

# 국립수산과학원 실시간 어장정보. 포털 상세 페이지의 요청주소로 교체해서 쓴다.
NIFS_ENDPOINT = os.environ.get(
    "NIFS_ENDPOINT",
    "http://apis.data.go.kr/1192000/RealtimeObsService/getRealtimeObsList",
)

OUT = Path("data/sst-latest.json")
STALE_HOURS = 6          # 이보다 오래된 관측은 버린다
RATE_SLEEP = 0.15

# 관측시각은 KST 로 온다. Actions 러너는 UTC 라 그냥 비교하면 9시간 틀어져
# 멀쩡한 관측이 전부 '오래됨'으로 버려진다.
KST = dt.timezone(dt.timedelta(hours=9))


def now_kst() -> dt.datetime:
    return dt.datetime.now(tz=KST)


def parse_kst(ts: str | None) -> dt.datetime | None:
    if not ts:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y%m%d%H%M"):
        try:
            return dt.datetime.strptime(str(ts).strip()[:19], fmt).replace(tzinfo=KST)
        except ValueError:
            continue
    return None


def fresh(ts: str | None) -> bool:
    t = parse_kst(ts)
    return bool(t and (now_kst() - t).total_seconds() < STALE_HOURS * 3600)


def sensorless(wtem: float, saln) -> bool:
    """수온계가 없는 지점은 관측값 대신 0.0 을 돌려준다.

    태안·인천송도·광양 등은 `wtem: 0.0` 과 `slntQty: 0.0` 이 함께 온다.
    바닷물 염분이 0 psu 일 수는 없으므로 이 조합이 '센서 없음'의 지표다.
    (군산은 `wtem: 27.1, slntQty: 29.5` 처럼 둘 다 실측이 온다.)

    이걸 걸러내지 않으면 8월에 0℃ 가 최근접 관측소로 잡히고, 프론트의
    치사수온 게이트가 걸려 그 일대 전 어종이 조용히 0점이 된다.
    실제로 어는점 근처인 겨울 서해 천수만이라면 염분은 정상값이 오므로
    그 경우는 그대로 통과한다.
    """
    if abs(wtem) > 0.05:
        return False
    try:
        return saln is None or abs(float(saln)) < 0.05
    except (TypeError, ValueError):
        return True


def latest_wtem(rows: list[dict]) -> tuple[float, str] | None:
    """관측 행들 중 수온이 유효한 가장 최근 값. 없으면 None."""
    best = None
    for r in rows:
        v = r.get("wtem")
        if v in (None, "", "-"):
            continue
        try:
            t = float(v)
        except (TypeError, ValueError):
            continue
        if not (-3 <= t <= 35):        # 센서 이상값 제거
            continue
        if sensorless(t, r.get("slntQty")):
            continue
        when = parse_kst(r.get("obsrvnDt"))
        if not when:
            continue
        if best is None or when > best[2]:
            best = (t, r.get("obsrvnDt"), when)
    return (best[0], best[1]) if best else None


def collect_khoa(key: str) -> list[dict]:
    log(f"조위관측소 실측 수온 — {len(STATIONS)}개소")
    today = f"{now_kst():%Y%m%d}"
    yday = f"{now_kst() - dt.timedelta(days=1):%Y%m%d}"
    out: list[dict] = []
    denied = False
    no_sensor: list[str] = []

    for code, (name, lat, lon) in STATIONS.items():
        rows = items(get(EP_DT_RECENT, key, {
            "obsCode": code, "type": "json", "numOfRows": "300", "min": "60",
            "reqDate": today,
        }))
        # 자정 직후에는 오늘 자료가 거의 없다. 전날로 한 번 더 본다.
        if not rows:
            rows = items(get(EP_DT_RECENT, key, {
                "obsCode": code, "type": "json", "numOfRows": "300", "min": "60",
                "reqDate": yday,
            }))
            time.sleep(RATE_SLEEP)
        time.sleep(RATE_SLEEP)

        if not rows:
            denied = True          # 전 지점 실패면 대개 활용신청 누락이다
            continue
        denied = False
        pick = latest_wtem(rows)
        if not pick:
            no_sensor.append(name)
            continue
        if not fresh(pick[1]):
            continue
        out.append({"name": name, "lat": round(lat, 5), "lon": round(lon, 5),
                    "temp": round(pick[0], 1), "agency": "KHOA", "obs": pick[1]})

    if denied and not out:
        log("  전 지점 응답 없음 — data.go.kr 에서 '조위관측소 최신 관측데이터'(15155508)")
        log("  활용신청이 되어 있는지 확인하세요.")
    if no_sensor:
        # 여기가 갑자기 늘면 관측망이 바뀐 것이다. 조용히 넘어가면 안 된다.
        log(f"  수온계 없음 {len(no_sensor)}개소: {', '.join(no_sensor)}")
    log(f"  유효 {len(out)}건")
    return out


def collect_nifs(key: str) -> list[dict]:
    log("NIFS 실시간 어장정보")
    js = get(NIFS_ENDPOINT, key, {"numOfRows": "500", "pageNo": "1", "resultType": "json"})
    if not js:
        log("  응답 없음 — NIFS_ENDPOINT 를 포털의 실제 요청주소로 교체하세요.")
        return []

    # 포털 API 마다 래핑이 제각각이라 재귀로 레코드 배열을 찾는다.
    def find_items(o):
        if isinstance(o, list):
            return o if o and isinstance(o[0], dict) else None
        if isinstance(o, dict):
            for k in ("item", "items", "data", "row", "body", "response", "result"):
                if k in o:
                    r = find_items(o[k])
                    if r:
                        return r
            for v in o.values():
                r = find_items(v)
                if r:
                    return r
        return None

    rows = find_items(js) or []
    out = []
    for r in rows:
        lat = r.get("lat") or r.get("obs_lat") or r.get("latitude")
        lon = r.get("lon") or r.get("obs_lon") or r.get("longitude")
        temp = r.get("wtr_tmpr") or r.get("water_temp") or r.get("temp") or r.get("sst")
        name = r.get("obs_pst_nm") or r.get("sta_nm") or r.get("name") or "NIFS"
        obs_t = r.get("obs_dt") or r.get("obs_time") or r.get("record_time")
        if lat is None or lon is None or temp in (None, "", "-"):
            continue
        try:
            lat, lon, t = float(lat), float(lon), float(temp)
        except (TypeError, ValueError):
            continue
        if not (-3 <= t <= 35) or not (32 < lat < 39) or not (124 < lon < 132):
            continue
        if obs_t and not fresh(obs_t):
            continue
        out.append({"name": name, "lat": round(lat, 5), "lon": round(lon, 5),
                    "temp": round(t, 1), "agency": "NIFS", "obs": obs_t})
    log(f"  유효 {len(out)}건")
    return out


def merge(khoa: list[dict], nifs: list[dict]) -> list[dict]:
    """5km 이내 중복은 NIFS 우선 — 어장정보가 연안에 더 가깝다."""
    out = list(nifs)
    for k in khoa:
        dup = any(abs(n["lat"] - k["lat"]) * 111 < 5 and abs(n["lon"] - k["lon"]) * 89 < 5
                  for n in nifs)
        if not dup:
            out.append(k)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-nifs", action="store_true")
    args = ap.parse_args()

    key = service_key()
    stations = collect_khoa(key)

    if args.with_nifs:
        stations = merge(stations, collect_nifs(key))

    if not stations:
        # 빈 파일로 덮어쓰면 프론트가 Open-Meteo 로 폴백하지 못하고
        # 오래된 값을 계속 쓸 수 있으므로, 실패 시엔 기존 파일을 보존한다.
        log("유효 관측 0건 — 기존 파일 유지하고 종료")
        sys.exit(1)

    OUT.parent.mkdir(exist_ok=True)
    write_atomic(OUT, json.dumps({
        "generated": now_kst().isoformat(timespec="seconds"),
        "staleHours": STALE_HOURS,
        "count": len(stations),
        "stations": stations,
    }, ensure_ascii=False, separators=(",", ":")))
    log(f"완료 → {OUT} ({len(stations)} stations)")


if __name__ == "__main__":
    main()
