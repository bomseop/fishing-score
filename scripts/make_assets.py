#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""아이콘 · 스플래시 원본 PNG 를 만든다.

@capacitor/assets 가 이 원본을 받아 안드로이드 밀도별 리소스를 생성한다.
모티프는 이 앱의 시그니처인 **사운딩 컬럼** — 팩터별 가로 막대에서
트랙 길이가 가중치, 채움이 현재값을 뜻하는 그 도형이다.

외부 이미지 라이브러리 없이 순수 파이썬으로 PNG 를 쓴다.
색은 CLAUDE.md 6절 디자인 언어를 그대로 따른다.

    py scripts/make_assets.py
"""
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets"

# ── 해도 팔레트 (CLAUDE.md 6절) ──────────────────────────────
ABYSS = (0x07, 0x1A, 0x21, 255)
DEEP = (0x0D, 0x2A, 0x33, 255)
SHELF = (0x14, 0x42, 0x4C, 255)
SHOAL = (0x1E, 0x64, 0x70, 255)
AQUA = (0x46, 0xE0, 0xC8, 255)
AMBER = (0xFF, 0xB2, 0x3D, 255)
MAGENTA = (0xFF, 0x2E, 0x6E, 255)
CLEAR = (0, 0, 0, 0)


class Canvas:
    """RGBA 픽셀 버퍼. 필요한 영역만 칠하므로 큰 캔버스도 빠르다."""

    def __init__(self, w, h, bg=CLEAR):
        self.w, self.h = w, h
        self.rows = [bytearray(bytes(bg) * w) for _ in range(h)]

    def rect(self, x0, y0, x1, y1, color):
        x0, y0 = max(0, int(x0)), max(0, int(y0))
        x1, y1 = min(self.w, int(x1)), min(self.h, int(y1))
        if x1 <= x0 or y1 <= y0:
            return
        span = bytes(color) * (x1 - x0)
        for y in range(y0, y1):
            self.rows[y][x0 * 4:x1 * 4] = span

    def save(self, path):
        raw = b"".join(b"\x00" + bytes(r) for r in self.rows)

        def chunk(tag, data):
            return (struct.pack(">I", len(data)) + tag + data
                    + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

        png = (b"\x89PNG\r\n\x1a\n"
               + chunk(b"IHDR", struct.pack(">IIBBBBB", self.w, self.h, 8, 6, 0, 0, 0))
               + chunk(b"IDAT", zlib.compress(raw, 9))
               + chunk(b"IEND", b""))
        path.write_bytes(png)
        print(f"  {path.relative_to(ROOT)}  {self.w}x{self.h}  {len(png)//1024}KB")


def sounding(cv, cx, cy, size):
    """사운딩 컬럼 — 트랙 길이 = 가중치, 채움 = 현재값.

    막대 5개. (트랙 비율, 채움 비율, 채움색) 이 곧 곱셈 구조의 시각화다.
    """
    bars = [
        (1.00, 0.72, AQUA),
        (0.78, 0.55, AQUA),
        (0.58, 0.50, AMBER),
        (0.42, 0.16, MAGENTA),
        (0.28, 0.24, SHOAL),
    ]
    bar_h = size * 0.108
    gap = size * 0.062
    total = len(bars) * bar_h + (len(bars) - 1) * gap
    x0 = cx - size / 2
    y = cy - total / 2

    for track, fill, color in bars:
        w = size * track
        cv.rect(x0, y, x0 + w, y + bar_h, SHELF)          # 트랙 = 가중치
        cv.rect(x0, y, x0 + w * fill, y + bar_h, color)   # 채움 = 현재값
        y += bar_h + gap

    # 기준선 — 해도의 수심 기선
    cv.rect(x0 - size * 0.055, cy - total / 2 - size * 0.075,
            x0 - size * 0.030, cy + total / 2 + size * 0.075, SHOAL)


def depth_bg(cv, top=(0x04, 0x12, 0x1A), bottom=ABYSS, bands=48):
    """심해색 그라데이션. 밴드로 나눠 칠해 큰 캔버스에서도 빠르다."""
    for i in range(bands):
        t = i / (bands - 1)
        c = tuple(round(top[k] + (bottom[k] - top[k]) * t) for k in range(3)) + (255,)
        cv.rect(0, cv.h * i / bands, cv.w, cv.h * (i + 1) / bands + 1, c)


def main():
    OUT.mkdir(exist_ok=True)
    print("아이콘 · 스플래시 원본 생성")

    # 런처 아이콘 (정사각 풀블리드)
    # @capacitor/assets 는 icon-only.png 를 찾는다. logo.png 는 이름 규칙이
    # 바뀌었을 때를 대비한 폴백 원본이다 (있으면 전부 여기서 생성한다).
    icon = Canvas(1024, 1024, ABYSS)
    depth_bg(icon)
    icon.rect(0, 0, 1024, 8, DEEP)
    sounding(icon, 512, 512, 560)
    icon.save(OUT / "icon-only.png")
    icon.save(OUT / "logo.png")

    # 어댑티브 아이콘 — 전경은 배경 위에 얹히고 가장자리가 잘린다.
    # 안전영역이 66% 라 로고를 더 안쪽으로 넣는다.
    fg = Canvas(1024, 1024, CLEAR)
    sounding(fg, 512, 512, 440)
    fg.save(OUT / "icon-foreground.png")

    bg = Canvas(1024, 1024, ABYSS)
    depth_bg(bg)
    bg.save(OUT / "icon-background.png")

    # 스플래시 — @capacitor/assets 는 2732x2732 이상을 요구한다
    for name in ("splash.png", "splash-dark.png"):
        sp = Canvas(2732, 2732, ABYSS)
        depth_bg(sp)
        sounding(sp, 1366, 1366, 880)
        sp.save(OUT / name)

    print("완료. 다음: npx @capacitor/assets generate --android")


if __name__ == "__main__":
    main()
