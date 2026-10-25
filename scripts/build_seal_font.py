#!/usr/bin/env python3
"""
원문 인장(seal) 씬 글꼴 만들기 — Noto Serif TC(OFL) 가변 폰트를 굵기 900 하나로 고정하고,
칸리포 구절 DB(kanripo_db)에 실제로 쓰인 글자 + 문장부호만 남겨 remotion/public/fonts 에 woff2 로 둔다.
같은 폴더에 남긴 글자 목록(NotoSerifTC-Seal.chars.txt)은 shorts_review 가 "인장 글자가 글꼴에 있는가"를 검사할 때 쓴다.

fonttools 는 저장소 .venv 에 없다 — 별도 가상환경에서 실행한다.
    python3 -m venv /tmp/fontvenv && /tmp/fontvenv/bin/pip install "fonttools[woff]==4.60.1"
    curl -L -o /tmp/NotoSerifTC.ttf "https://raw.githubusercontent.com/google/fonts/main/ofl/notoseriftc/NotoSerifTC%5Bwght%5D.ttf"
    /tmp/fontvenv/bin/python scripts/build_seal_font.py /tmp/NotoSerifTC.ttf

구절 DB 에 새 책을 넣으면 다시 돌린다(없는 글자는 린트가 P0 로 막는다).
"""

import os
import sqlite3
import sys

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONTS_DIR = os.path.join(BASE_DIR, "remotion", "public", "fonts")
OUT_FONT = os.path.join(FONTS_DIR, "NotoSerifTC-Seal.woff2")
OUT_CHARS = os.path.join(FONTS_DIR, "NotoSerifTC-Seal.chars.txt")
DB_PATH = os.path.join(BASE_DIR, "data", "kanripo", "passages.db")
WEIGHT = 900
# 인장·출전 카드에 쓰는 문장부호와 기본 라틴(출전 'Shiji, ch. 85' 등)
EXTRA = "，。、；：！？「」『』（）《》〈〉…—·〓 " + "".join(chr(c) for c in range(0x20, 0x7F))


def charset(db_path: str = DB_PATH) -> str:
    con = sqlite3.connect(db_path)
    try:
        chars = set()
        for (text,) in con.execute("SELECT text FROM passages"):
            chars.update(text)
    finally:
        con.close()
    chars.update(EXTRA)
    return "".join(sorted(c for c in chars if c.isprintable()))


def build(src_ttf: str, db_path: str = DB_PATH) -> dict:
    font = TTFont(src_ttf)
    font = instancer.instantiateVariableFont(font, {"wght": WEIGHT})
    chars = charset(db_path)
    opts = subset.Options()
    opts.flavor = "woff2"
    opts.layout_features = ["*"]
    opts.name_IDs = ["*"]
    opts.notdef_outline = True
    sub = subset.Subsetter(opts)
    sub.populate(text=chars)
    sub.subset(font)
    cmap = font.getBestCmap()
    covered = "".join(c for c in chars if ord(c) in cmap)
    os.makedirs(FONTS_DIR, exist_ok=True)
    font.flavor = "woff2"
    font.save(OUT_FONT)
    with open(OUT_CHARS, "w", encoding="utf-8") as f:
        f.write(covered)
    return {"requested": len(chars), "covered": len(covered), "bytes": os.path.getsize(OUT_FONT),
            "missing": "".join(c for c in chars if ord(c) not in cmap)}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    print(build(sys.argv[1]))
