#!/usr/bin/env python3
"""
collect_sst.py — 연안 실측 수온 수집

data/sst-latest.json 을 갱신한다. 3시간 주기 cron 을 상정.
프론트는 포인트에서 35km 이내에 관측점이 있으면 이 값을,
없으면 Open-Meteo 격자 SST 를 쓴다.

  python collect_sst.py                 # KHOA 조위관측소 수온
  python collect_sst.py --with-nifs     # + 국립수산과학원 어장정보

환경변수:
  KHOA_KEY    바다누리 인증키 (build_tides.py 와 동일)
  NIFS_KEY    공공데이터포털 국립수산과학원 서비스키 (--with-nifs 일 때만)

설계 메모:
  KHOA 조위관측소는 40여 개소뿐이지만 결측이 적고 인증키가 조석과 공용이라
  기본 소스로 쓴다. NIFS 어장정보는 관측점이 촘촘한 대신 결측·지연이 잦아
  보조로 얹는다. 같은 위치에 둘 다 있으면 NIFS 를 우선한다 —
  어장정보 관측점이 실제 연안에 더 가깝게 설치돼 있기 때문.
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
EP_STATIONS = f"{KHOA_BASE}/ObsServiceObj/search.do"
EP_RECENT = f"{KHOA_BASE}/tideObsRecent/search.do"      # 실시간 조위관측(수온 포함)

# 국립수산과학원 실시간 어장정보. 포털 상세 페이지의 요청주소로 교체해서 쓴다.
# https://www.data.go.kr 에서 "국립수산과학원 실시간 해양환경" 검색
NIFS_ENDPOINT = os.environ.get(
    "NIFS_ENDPOINT",
    "http://apis.data.go.kr/1192000/RealtimeObsService/getRealtimeObsList",
)

OUT = Path("data/sst-latest.json")
STALE_HOURS = 6          # 이보다 오래된 관측은 버린다
MAX_RETRY = 3
RATE_SLEEP = 0.15


def log(m: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {m}", flush=True)


def api_get(url: str, params: dict) -> dict | None:
    q = urlencode(params)
    for a in range(1, MAX_RETRY + 1):
        try:
            with urlopen(f"{url}?{q}", timeout=15) as r:
                return json.loads(r.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as e:
            if a == MAX_RETRY:
                log(f"  실패: {e}")
                return None
            time.sleep(2 ** a)
    return None


def fresh(ts: str | None) -> bool:
    if not ts:
        return False
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y%m%d%H%M"):
        try:
            t = dt.datetime.strptime(ts.strip()[:19], fmt)
            return (dt.datetime.now() - t).total_seconds() < STALE_HOURS * 3600
        except ValueError:
            continue
    return False


def collect_khoa(key: str) -> list[dict]:
    log("KHOA 조위관측소 목록")
    js = api_get(EP_STATIONS, {"ServiceKey": key, "ServiceType": "json"})
    if not js:
        return []
    codes = []
    for r in js.get("result", {}).get("data", []):
        c = r.get("obs_post_id") or r.get("obs_code")
        n = r.get("obs_post_name") or r.get("obs_object")
        lat, lon = r.get("obs_lat"), r.get("obs_lon")
        if c and lat and lon and str(c).startswith("DT_"):
            codes.append((c, n, float(lat), float(lon)))

    log(f"  {len(codes)}개소 관측값 수집")
    out = []
    for c, n, lat, lon in codes:
        js = api_get(EP_RECENT, {"ServiceKey": key, "ObsCode": c, "ResultType": "json"})
        time.sleep(RATE_SLEEP)
        if not js:
            continue
        d = js.get("result", {}).get("data", {})
        if isinstance(d, list):
            d = d[0] if d else {}
        temp = d.get("water_temp")
        obs_t = d.get("record_time") or d.get("obs_time")
        if temp in (None, "", "-") or not fresh(obs_t):
            continue
        try:
            t = float(temp)
        except ValueError:
            continue
        if not (-3 <= t <= 35):        # 센서 이상값 제거
            continue
        out.append({"name": n, "lat": round(lat, 5), "lon": round(lon, 5),
                    "temp": round(t, 1), "agency": "KHOA", "obs": obs_t})
    log(f"  유효 {len(out)}건")
    return out


def collect_nifs(key: str) -> list[dict]:
    log("NIFS 실시간 어장정보")
    js = api_get(NIFS_ENDPOINT, {
        "serviceKey": key, "numOfRows": 500, "pageNo": 1,
        "resultType": "json", "dataType": "JSON",
    })
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
    """5km 이내 중복은 NIFS 우선."""
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

    khoa_key = os.environ.get("KHOA_KEY", "").strip()
    if not khoa_key:
        sys.exit("KHOA_KEY 환경변수가 없습니다.")

    stations = collect_khoa(khoa_key)

    if args.with_nifs:
        nifs_key = os.environ.get("NIFS_KEY", "").strip()
        if nifs_key:
            stations = merge(stations, collect_nifs(nifs_key))
        else:
            log("NIFS_KEY 없음 — KHOA 만 사용")

    if not stations:
        # 빈 파일로 덮어쓰면 프론트가 Open-Meteo 로 폴백하지 못하고
        # 오래된 값을 계속 쓸 수 있으므로, 실패 시엔 기존 파일을 보존한다.
        log("유효 관측 0건 — 기존 파일 유지하고 종료")
        sys.exit(1)

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({
        "generated": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "staleHours": STALE_HOURS,
        "count": len(stations),
        "stations": stations,
    }, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"완료 → {OUT} ({len(stations)} stations)")


if __name__ == "__main__":
    main()
