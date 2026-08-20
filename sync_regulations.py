#!/usr/bin/env python3
"""
sync_regulations.py — 금어기 · 금지체장 현행 법령 동기화

「수산자원관리법 시행령」 별표 1(금어기) · 별표 2(금지체장)를
국가법령정보센터 OPEN API 로 받아 data/regulations.json 을 만든다.

  python sync_regulations.py              # 변경 있으면 갱신
  python sync_regulations.py --check      # 시행일만 확인하고 종료 (exit 1 = 변경됨)
  python sync_regulations.py --dry-run    # 파싱 결과만 출력

환경변수:
  LAW_OC   국가법령정보센터 OPEN API 신청 ID (이메일 @ 앞부분)
           https://open.law.go.kr 에서 신청. 무료, 승인 즉시 사용 가능.

왜 스크립트로 받는가:
  law.go.kr 은 CORS 를 열지 않고 robots 로 자동수집도 막는다. OPEN API 는
  별개 경로로 허용된다. 법령은 자주 안 바뀌지만 바뀌면 즉시 반영돼야 하므로
  주 1회 --check 로 시행일만 보고, 달라졌을 때만 전체를 다시 받는다.

한계:
  · 시·도 조례에 따른 지역별 예외(참문어 금어기 등)는 이 API 에 없다.
  · TAC 대상 어종의 한시적 유예는 중앙수산조정위원회 고시로 나가므로 별도다.
  · 따라서 결과 JSON 에는 항상 "조례 확인 필요" 플래그가 붙는다.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import urlopen
from urllib.error import HTTPError, URLError

LAW_BASE = "http://www.law.go.kr/DRF"
EP_SERVICE = f"{LAW_BASE}/lawService.do"
EP_SEARCH = f"{LAW_BASE}/lawSearch.do"

LAW_NAME = "수산자원관리법 시행령"
OUT = Path("data/regulations.json")

# 앱의 어종 id ↔ 별표에 쓰이는 법령상 표준명
# 별표는 표준명으로만 적혀 있어서(광어→넙치, 우럭→조피볼락) 매핑이 필요하다.
SPECIES_MAP = {
    "flounder":  "넙치",
    "seabass":   "농어",
    "rockfish":  "조피볼락",
    "rockbream": "볼락",
    "porgy":     "감성돔",
    "spanish":   "삼치",
    "squid":     "흰꼴뚜기",
    "flatfish":  "문치가자미",
    "croaker":   "보구치",
    "horsemack": "전갱이",
    "hairtail":  "갈치",
    "marbled":   "쏨뱅이",
    "greenling": "쥐노래미",
    "cuttlefish": "갑오징어",
    "webfoot":   "주꾸미",
    "octopus":   "문어",
    "whiting":   "청보리멸",
    "redsea":    "참돔",
    "beakfish":  "돌돔",
    "conger":    "붕장어",
    "nibbler":   "벵에돔",
    "halfbeak":  "학공치",
}

# 별표에 체장이 아닌 기준으로 적히는 어종
MEASURE_HINT = {"갈치": "항문장", "갑오징어": "외투장", "흰꼴뚜기": "외투장", "살오징어": "외투장"}


def log(m: str) -> None:
    print(f"[{dt.datetime.now():%H:%M:%S}] {m}", flush=True)


def api(url: str, params: dict) -> str | None:
    try:
        with urlopen(f"{url}?{urlencode(params)}", timeout=25) as r:
            return r.read().decode("utf-8", "replace")
    except (HTTPError, URLError, TimeoutError) as e:
        log(f"  요청 실패: {e}")
        return None


def find_law(oc: str) -> dict | None:
    """현행 시행령의 MST(법령일련번호)와 시행일자를 찾는다."""
    raw = api(EP_SEARCH, {"OC": oc, "target": "law", "type": "JSON",
                          "query": LAW_NAME, "display": 20})
    if not raw:
        return None
    try:
        js = json.loads(raw)
    except json.JSONDecodeError:
        log("  검색 응답이 JSON 이 아닙니다. OC 값이 올바른지 확인하세요.")
        return None

    items = js.get("LawSearch", {}).get("law", [])
    if isinstance(items, dict):
        items = [items]
    for it in items:
        if it.get("법령명한글", "").strip() == LAW_NAME:
            return {"mst": it.get("법령일련번호") or it.get("법령ID"),
                    "effective": it.get("시행일자", ""),
                    "promulgated": it.get("공포일자", ""),
                    "revision": it.get("제개정구분명", "")}
    log(f"  '{LAW_NAME}' 를 검색 결과에서 찾지 못했습니다.")
    return None


def fetch_byltable(oc: str, mst: str) -> str | None:
    """법령 본문(별표 포함)을 텍스트로 받는다."""
    return api(EP_SERVICE, {"OC": oc, "target": "law", "type": "HTML", "MST": mst})


def strip_tags(html: str) -> str:
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</tr>|</div>", "\n", html)
    html = re.sub(r"(?i)</td>|</th>", "\t", html)
    html = re.sub(r"<[^>]+>", "", html)
    html = html.replace("&nbsp;", " ").replace("&amp;", "&")
    html = re.sub(r"[ \t]+", " ", html)
    return "\n".join(l.strip() for l in html.split("\n") if l.strip())


DATE_RE = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일")
LEN_RE = re.compile(r"(?:전장|체장|항문장|외투장|두동장)?\s*(\d+(?:\.\d+)?)\s*(?:센티미터|cm)")
WT_RE = re.compile(r"(\d+(?:,\d{3})*)\s*(?:그램|g)")


def parse_species(text: str, name: str) -> dict:
    """
    별표 텍스트에서 해당 어종 줄을 찾아 금어기 · 금지체장을 뽑는다.
    별표 서식이 개정마다 조금씩 달라지므로 줄 단위 휴리스틱으로 처리하고,
    확신이 없으면 unsure 를 세워 UI 에 경고가 뜨게 한다.
    """
    out: dict = {"legal": name}
    hits = [l for l in text.split("\n") if name in l]
    if not hits:
        out["unsure"] = True
        out["parseNote"] = "별표에서 해당 어종 줄을 찾지 못함"
        return out

    blob = " ".join(hits)

    # 금어기 — "5월 1일부터 5월 31일까지" 형태
    dates = DATE_RE.findall(blob)
    if len(dates) >= 2:
        closed = []
        for i in range(0, len(dates) - 1, 2):
            a = f"{int(dates[i][0]):02d}-{int(dates[i][1]):02d}"
            b = f"{int(dates[i+1][0]):02d}-{int(dates[i+1][1]):02d}"
            closed.append([a, b])
        out["closed"] = closed

    # 금지체장 / 금지체중
    m = LEN_RE.search(blob)
    if m:
        out["len"] = float(m.group(1))
        if out["len"] == int(out["len"]):
            out["len"] = int(out["len"])
        if name in MEASURE_HINT:
            out["measure"] = MEASURE_HINT[name]
    w = WT_RE.search(blob)
    if w:
        out["wt"] = int(w.group(1).replace(",", ""))

    if not any(k in out for k in ("len", "wt", "closed")):
        out["parseNote"] = "규정 없음 또는 파싱 실패"
        out["unsure"] = True

    if len(hits) > 3:
        out["unsure"] = True
        out["parseNote"] = f"동일 어종명이 {len(hits)}줄에 등장 — 어업 종류별 예외가 있을 수 있음"

    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="시행일만 확인 (변경 시 exit 1)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    oc = os.environ.get("LAW_OC", "").strip()
    if not oc:
        sys.exit("LAW_OC 환경변수가 없습니다. https://open.law.go.kr 에서 신청하세요.")

    info = find_law(oc)
    if not info or not info.get("mst"):
        sys.exit("법령 정보를 받지 못했습니다.")
    log(f"현행: 시행 {info['effective']} / 공포 {info['promulgated']} / {info['revision']}")

    if args.check:
        cur = ""
        if OUT.exists():
            cur = json.loads(OUT.read_text(encoding="utf-8")).get("effectiveRaw", "")
        if cur == info["effective"]:
            log("변경 없음")
            sys.exit(0)
        log(f"시행일 변경 감지: {cur or '없음'} → {info['effective']}")
        sys.exit(1)

    html = fetch_byltable(oc, info["mst"])
    if not html:
        sys.exit("본문을 받지 못했습니다.")
    text = strip_tags(html)
    log(f"본문 {len(text):,}자 수신")

    species = {}
    unsure = []
    for sid, name in SPECIES_MAP.items():
        r = parse_species(text, name)
        species[sid] = r
        if r.get("unsure"):
            unsure.append(f"{name}({sid})")

    eff = info["effective"]
    eff_iso = f"{eff[:4]}-{eff[4:6]}-{eff[6:8]}" if len(eff) == 8 else eff

    payload = {
        "basis": "수산자원관리법 시행령 별표1·별표2",
        "effective": eff_iso,
        "effectiveRaw": eff,
        "promulgated": info["promulgated"],
        "revision": info["revision"],
        "fetched": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "source": "국가법령정보센터 OPEN API",
        "localOrdinanceWarning": True,
        "species": species,
    }

    if args.dry_run:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    log(f"완료 → {OUT}")
    if unsure:
        log(f"검증 필요 {len(unsure)}종: {', '.join(unsure)}")
        log("  해당 항목은 UI 에 '미검증' 으로 표시됩니다. 별표 원문과 대조하세요.")


if __name__ == "__main__":
    main()
