#!/usr/bin/env python3
"""
khoa_api.py — 공공데이터포털 국립해양조사원 API 공용 계층

**구 바다누리 OpenAPI(`khoa.go.kr/api/oceangrid`)는 2026-04-01 자로 종료됐다.**
현재 살아 있는 건 공공데이터포털(data.go.kr)에 등재된 기관코드 1192136 API 다.
`build_tides.py` 와 `collect_sst.py` 가 이 모듈을 공유한다.

| 용도 | data.go.kr | Base URL |
|---|---|---|
| 조석예보 고·저조 | 15156018 | `apis.data.go.kr/1192136/tideFcstHghLw` |
| 조위관측소 최신 관측 | 15155508 | `apis.data.go.kr/1192136/dtRecent` |

둘 다 **개발단계 자동승인**, 개발계정 10,000회/일. 인증키는 계정당 하나이므로
두 API(그리고 NIFS 등 다른 포털 API)가 같은 값을 쓴다.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import quote

# ── 엔드포인트 ────────────────────────────────────────────────
PORTAL = "https://apis.data.go.kr/1192136"
EP_TIDE_FCST = f"{PORTAL}/tideFcstHghLw/GetTideFcstHghLwApiService"
EP_DT_RECENT = f"{PORTAL}/dtRecent/GetDTRecentApiService"

MAX_RETRY = 3
TIMEOUT = 20

# ── 조석예보 지점 ─────────────────────────────────────────────
# 목록 API 가 따로 없어서 DT_0001..DT_0099 를 스캔해 확정했다 (2026-08-20).
# 응답에 위경도가 함께 오므로 스캔 결과가 곧 정본이다.
# 갱신주기가 연 1회이므로 사실상 바뀌지 않는다.
# 다시 만들려면: python build_tides.py --scan
STATIONS: dict[str, tuple[str, float, float]] = {
    "DT_0001": ("인천", 37.45194, 126.59222),
    "DT_0002": ("평택", 36.96694, 126.82277),
    "DT_0003": ("영광", 35.42611, 126.42055),
    "DT_0004": ("제주", 33.52750, 126.54305),
    "DT_0005": ("부산", 35.09638, 129.03527),
    "DT_0006": ("묵호", 37.55027, 129.11638),
    "DT_0007": ("목포", 34.77972, 126.37555),
    "DT_0008": ("안산", 37.19222, 126.64722),
    "DT_0010": ("서귀포", 33.24000, 126.56166),
    "DT_0011": ("후포", 36.67750, 129.45305),
    "DT_0012": ("속초", 38.20722, 128.59416),
    "DT_0013": ("울릉도", 37.49138, 130.91361),
    "DT_0014": ("통영", 34.82777, 128.43472),
    "DT_0016": ("여수", 34.74722, 127.76555),
    "DT_0017": ("대산", 37.00750, 126.35277),
    "DT_0018": ("군산", 35.97555, 126.56305),
    "DT_0020": ("울산", 35.50194, 129.38722),
    "DT_0021": ("추자도", 33.96194, 126.30027),
    "DT_0022": ("성산포", 33.47472, 126.92777),
    "DT_0023": ("모슬포", 33.21444, 126.25111),
    "DT_0024": ("장항", 36.00694, 126.68750),
    "DT_0025": ("보령", 36.40638, 126.48611),
    "DT_0026": ("고흥발포", 34.48111, 127.34277),
    "DT_0027": ("완도", 34.31555, 126.75972),
    "DT_0028": ("진도", 34.37777, 126.30861),
    "DT_0029": ("거제도", 34.80138, 128.69916),
    "DT_0031": ("거문도", 34.02833, 127.30888),
    "DT_0032": ("강화대교", 37.73194, 126.52222),
    "DT_0035": ("흑산도", 34.68416, 125.43555),
    "DT_0036": ("대청도", 37.82522, 124.71805),
    "DT_0037": ("어청도", 36.11722, 125.98472),
    "DT_0038": ("굴업도", 37.19444, 125.99500),
    "DT_0039": ("왕돌초", 36.71916, 129.73250),
    "DT_0041": ("복사초", 34.09833, 126.16833),
    "DT_0042": ("교본초", 34.70472, 128.30638),
    "DT_0043": ("영흥도", 37.23861, 126.42861),
    "DT_0044": ("영종대교", 37.54555, 126.58444),
    "DT_0046": ("쌍정초", 37.55616, 130.93921),
    "DT_0047": ("도농탄", 33.15805, 126.27472),
    "DT_0048": ("속초등표", 38.19947, 128.61308),
    "DT_0049": ("광양", 34.90367, 127.75483),
    "DT_0050": ("태안", 36.91305, 126.23888),
    "DT_0051": ("서천마량", 36.12888, 126.49527),
    "DT_0052": ("인천송도", 37.33805, 126.58611),
    "DT_0054": ("진해", 35.14722, 128.64305),
    "DT_0056": ("부산항신항", 35.07750, 128.78472),
}


def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


def service_key() -> str:
    """공공데이터포털 인증키. 인코딩·디코딩 어느 쪽을 넣어도 동작한다.

    포털은 '일반 인증키'를 인코딩본(`%2F`, `%3D` 포함)과 디코딩본 두 가지로 보여준다.
    인코딩본을 다시 인코딩하면 `%2F` → `%252F` 가 되어 조용히 인증에 실패하므로,
    이미 인코딩된 값인지 판별해서 그대로 쓴다.
    """
    for name in ("DATA_GO_KR_KEY", "KHOA_KEY", "NIFS_KEY"):
        key = os.environ.get(name, "").strip()
        if key:
            if name != "DATA_GO_KR_KEY":
                log(f"{name} 를 사용합니다 (DATA_GO_KR_KEY 로 옮기는 것을 권장)")
            return key if "%" in key else quote(key, safe="")
    sys.exit(
        "DATA_GO_KR_KEY 환경변수가 없습니다.\n"
        "  공공데이터포털(data.go.kr) 마이페이지 > 오픈API > 개발계정 의 일반 인증키"
    )


# 일부 공공기관 서버가 오래된 인증서 체인을 쓴다. 이 API 는 공개 데이터라
# 비밀이 오가지 않으므로 검증 실패로 수집이 멈추지 않게 한다.
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def get(endpoint: str, key: str, params: dict) -> dict | None:
    """포털 API 호출. serviceKey 는 이미 인코딩돼 있으므로 직접 이어 붙인다."""
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{endpoint}?serviceKey={key}&{qs}"
    for attempt in range(1, MAX_RETRY + 1):
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=TIMEOUT, context=_CTX) as r:
                body = r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "replace")
            if "SERVICE_KEY_IS_NOT_REGISTERED" in body:
                # 재시도해도 소용없다. 해당 API 활용신청이 안 된 것이다.
                log(f"  인증키가 이 API 에 등록되지 않았습니다: {endpoint}")
                log("  data.go.kr 에서 해당 오픈API '활용신청' 을 먼저 하세요.")
                return None
            if attempt == MAX_RETRY:
                log(f"  실패 HTTP {e.code}: {body[:160]}")
                return None
        except Exception as e:  # URLError, timeout, ssl 등
            if attempt == MAX_RETRY:
                log(f"  실패: {type(e).__name__} {e}")
                return None
            time.sleep(2 ** attempt)
            continue
        else:
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                if attempt == MAX_RETRY:
                    log(f"  JSON 아님: {body[:160]}")
                    return None
        time.sleep(2 ** attempt)
    return None


def items(js: dict | None) -> list[dict]:
    """`body.items.item` 을 항상 리스트로 돌려준다 (1건이면 dict 로 온다)."""
    if not js:
        return []
    if js.get("header", {}).get("resultCode") not in ("00", "0", None):
        return []
    body = js.get("body") or {}
    it = (body.get("items") or {}).get("item") or []
    if isinstance(it, dict):
        return [it]
    return it if isinstance(it, list) else []


def scan_stations(key: str, hi: int = 99) -> dict[str, tuple[str, float, float]]:
    """DT_0001..DT_00{hi} 를 훑어 조석예보 지점표를 다시 만든다.

    STATIONS 를 갱신해야 할 때만 쓴다. 평시에는 호출량 낭비다.
    """
    today = f"{dt.date.today():%Y%m%d}"
    found: dict[str, tuple[str, float, float]] = {}
    for n in range(1, hi + 1):
        code = f"DT_{n:04d}"
        rows = items(get(EP_TIDE_FCST, key,
                         {"obsCode": code, "reqDate": today, "type": "json", "numOfRows": "10"}))
        if rows:
            r = rows[0]
            found[code] = (r.get("obsvtrNm"), float(r["lat"]), float(r["lot"]))
            log(f"  {code} {r.get('obsvtrNm')}")
        time.sleep(0.1)
    return found
