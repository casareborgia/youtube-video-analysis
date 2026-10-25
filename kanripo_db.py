"""칸리포(漢籍リポジトリ) 구절 DB — Shiji Files 파일럿 P-2 (작업계획서_ShijiFiles_파일럿3편 4장).

표점본(tls 브랜치)을 얕게 받아 마크업을 걷어내고 문장 단위로 SQLite 에 넣는다. 원문은 고치지 않는다(이체자 그대로).

tls 원문 구조(2026-10-26 확인):
- `# src: SHIJI 85.2.1 2506; …` 줄은 **다음 문단**의 출전이다. 새 출전이 나올 때까지 이어진다(장 제목 앞의 출전은 첫 문단 몫).
  사기는 출전 줄이 없는 편이 많고, 그대로 두면 앞 편의 출전이 넘어온다(孟嘗君列傳이 73권 출전을 물려받음) —
  그래서 장 번호는 출전이 아니라 편 제목에서 정하고, 새 편에서는 새로 읽은 출전이 없으면 출전을 비운다.
- 문단은 빈 줄로 끝나고, 한 문단이 여러 줄(끝에 ¶)로 쪼개져 있다. `<pb:…>` 쪽 표시는 줄 중간에도 온다.
- 장 제목: `** 172 荊宣王問群臣`, `** 1 《計篇》`. 사기는 `** 5 傳`(부) 아래 `5.25《呂不韋列傳第二十五》`(편) — 권 번호 = 부 앞 권 수 + 편 번호.
  사기 출전 줄의 권 번호는 전통 권 번호와 어긋나는 곳이 있다(扁鵲倉公列傳 = 105권인데 `SHIJI 106`) — 출전은 참고로만 남긴다.
  12권 孝武本紀는 tls 에 없다. 表의 `|` 표 줄과 TLS 독음 주석(`@fú`)·`#` 은 본문에서 뺀다(`〓` 결자 표시는 남김).

받은 원본과 DB 는 data/kanripo/(gitignore) 에만 둔다 — 커밋 금지. 라이선스: 원문은 퍼블릭 도메인, 칸리포 전사·표점은 CC BY-SA 4.0.

사용: python -m kanripo_db fetch | build | search 此奇貨可居 [--repo KR2a0001]
"""

import os
import re
import sqlite3
import subprocess
import sys
from typing import Callable, Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
KANRIPO_DIR = os.path.join(BASE_DIR, "data", "kanripo")
SRC_DIR = os.path.join(KANRIPO_DIR, "src")
DB_PATH = os.path.join(KANRIPO_DIR, "passages.db")
REPO_URL = "https://github.com/kanripo/{repo}.git"
CREDIT = "Original text: Kanseki Repository (Kanripo), CC BY-SA 4.0"

BOOKS: Dict[str, dict] = {
    "KR2a0001": {"zh": "史記", "en": "Shiji", "cite": "Shiji, ch. {n}"},
    "KR2e0003": {"zh": "戰國策", "en": "Zhanguo ce", "cite": "Zhanguo ce, §{n}"},
    "KR3c0005": {"zh": "韓非子", "en": "Han Feizi", "cite": "Han Feizi, ch. {n}"},
    "KR3b0003": {"zh": "孫子", "en": "Sunzi", "cite": "Sunzi, ch. {n}"},
}
SHIJI = "KR2a0001"
# 사기 부(部)마다 앞선 권 수: 本紀 1–12 · 表 13–22 · 書 23–30 · 世家 31–60 · 列傳 61–130
SHIJI_PART_OFFSET = {1: 0, 2: 12, 3: 22, 4: 30, 5: 60}

_PB = re.compile(r"<pb:[^>]*>")
_SRC = re.compile(r"^#\s*src:\s*(.*)$")
_SRC_REF = re.compile(r"([A-Z]+)[ ,]+(\d+)([\d.:]*)")
_HEADING = re.compile(r"^\*+\s+(\d+)\s+(.+)$")
_SHIJI_TITLE = re.compile(r"^\**\s*(\d+)\.(\d+)\s*《(.+?)》[\s|]*$")   # 表는 `*** 2.1　《三代世表》` 형식(전각 공백, 끝에 | 붙기도)
_READING = re.compile(r"@[A-Za-z\u00C0-\u024F]+\d?")   # TLS 독음 주석 `夫@fú`
_SUB_LABEL = re.compile(r"^\d+(?:\.\d+)+\S{0,6}$")    # 韓非子 48편 소제목 줄 `48.7類柄` — 다음 줄이 `*` 로 시작
_SENTENCE = re.compile(r".+?[。！？][」』”’）)]*|.+$")
_NOT_WORD = re.compile(r"[\W_]+")


def plain(text: str) -> str:
    """검색용 — 문장부호·공백을 뺀 글자만."""
    return _NOT_WORD.sub("", text or "")


def _src_ref(raw: str) -> str:
    """'SHIJI 85.2.1 2506; …' → 'SHIJI 85.2.1', 'ZGC,14.3.1, tr. …' → 'ZGC 14.3.1'."""
    m = _SRC_REF.search(raw.split(";")[0])
    return f"{m.group(1)} {m.group(2)}{m.group(3)}" if m else ""


def _clean_line(line: str) -> str:
    line = _READING.sub("", _PB.sub("", line)).replace("¶", "").replace("#", "").strip()
    return line[1:].strip() if line.startswith("*") else line


def parse_text(text: str, repo: str) -> List[dict]:
    """tls 파일 하나 → 문장 행 목록. 행: src_ref·chapter·section_no·section_title·para_no·sent_no·text·paragraph.
    chapter 는 출전 표기에 쓰는 번호(사기 = 권, 전국책 = 항목 번호, 그 밖 = 편 번호)."""
    if repo not in BOOKS:
        raise ValueError(f"모르는 칸리포 저장소입니다: {repo}. 가능: {', '.join(BOOKS)}")
    rows: List[dict] = []
    state = {"src_ref": "", "chapter": "", "section_no": "", "section_title": ""}
    buf: List[str] = []
    para_no = 0
    src_fresh = False   # 마지막 문단 뒤에 새로 읽은 출전이 있는가 — 제목 앞의 출전은 그 편의 첫 문단 몫

    def new_section():
        if not src_fresh:
            state["src_ref"] = ""   # 앞 편 출전을 물려받지 않는다

    def flush():
        nonlocal para_no, src_fresh
        paragraph = "".join(buf)
        buf.clear()
        if not paragraph:
            return
        para_no += 1
        src_fresh = False
        for i, s in enumerate((x.strip() for x in _SENTENCE.findall(paragraph)), 1):
            if s:
                rows.append({**state, "repo": repo, "para_no": para_no, "sent_no": i, "text": s, "paragraph": paragraph})

    for raw in text.splitlines():
        line = raw.strip()
        src = _SRC.match(line)
        if src:
            flush()
            state["src_ref"] = _src_ref(src.group(1))
            src_fresh = True
            continue
        if line.startswith("#"):
            flush()   # # dating·#+TITLE 같은 메타 줄은 본문이 아니다
            continue
        head = _HEADING.match(line)
        if head:
            flush()
            new_section()
            state["section_no"], state["section_title"] = head.group(1), head.group(2).strip().strip("《》").strip()
            state["chapter"] = "" if repo == SHIJI else head.group(1)   # 사기의 ** 줄은 부(部)라 권 번호가 아니다
            continue
        title = _SHIJI_TITLE.match(_clean_line(line)) if repo == SHIJI else None
        if title:
            flush()
            new_section()
            part, n = int(title.group(1)), int(title.group(2))
            state["section_title"] = title.group(3)
            state["chapter"] = str(SHIJI_PART_OFFSET[part] + n) if part in SHIJI_PART_OFFSET else ""
            continue
        if "|" in line:
            continue   # 表의 칸 나눔 줄 — 이야기 본문이 아니다
        body = _clean_line(line)
        if _SUB_LABEL.match(body):
            flush()
            continue
        if body:
            buf.append(body)
        elif not _PB.search(line):
            flush()   # 빈 줄이 문단 끝 — 쪽 표시만 있는 줄은 문단을 끊지 않는다
    flush()
    return rows


def citation(row: dict) -> str:
    """영상·설명란에 쓰는 출전. 예: 'Shiji, ch. 85'. 장 번호를 모르면 책 이름만 — 틀린 번호를 붙이지 않는다."""
    book = BOOKS[row["repo"]]
    n = row.get("chapter")
    return book["cite"].format(n=n) if n else book["en"]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS paragraphs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT NOT NULL, file TEXT NOT NULL, para_no INTEGER NOT NULL,
    text TEXT NOT NULL, plain TEXT NOT NULL,
    UNIQUE(repo, file, para_no)
);
CREATE TABLE IF NOT EXISTS passages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT NOT NULL, file TEXT NOT NULL, para_no INTEGER NOT NULL, sent_no INTEGER NOT NULL,
    src_ref TEXT, chapter TEXT, section_no TEXT, section_title TEXT,
    text TEXT NOT NULL, plain TEXT NOT NULL, chars INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0,
    UNIQUE(repo, file, para_no, sent_no)
);
CREATE TABLE IF NOT EXISTS episode_passages (
    episode TEXT NOT NULL, passage_id INTEGER NOT NULL REFERENCES passages(id), role TEXT NOT NULL DEFAULT 'quote',
    PRIMARY KEY (episode, passage_id)
);
"""


def _connect(db_path: str) -> sqlite3.Connection:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    con.executescript(_SCHEMA)
    return con


def build_db(src_dir: str = SRC_DIR, db_path: str = DB_PATH) -> Dict[str, int]:
    """받아 둔 원본 → DB. 다시 돌려도 같은 결과(같은 자리 문장은 id 가 유지돼 에피소드 연결이 깨지지 않는다)."""
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    counts: Dict[str, int] = {}
    con = _connect(db_path)
    try:
        con.execute("CREATE TEMP TABLE seen (id INTEGER PRIMARY KEY)")
        con.execute("DELETE FROM paragraphs")   # 문단은 연결이 없으니 통째로 다시 만든다
        for repo in BOOKS:
            counts[repo] = 0
            d = os.path.join(src_dir, repo)
            if not os.path.isdir(d):
                continue
            for name in sorted(os.listdir(d)):
                if not (name.startswith(repo + "_") and name.endswith(".txt")):
                    continue   # Readme.org 등은 본문이 아니다
                with open(os.path.join(d, name), encoding="utf-8") as f:
                    rows = parse_text(f.read(), repo)
                for r in rows:
                    if r["sent_no"] == 1:
                        con.execute("INSERT INTO paragraphs (repo, file, para_no, text, plain) VALUES (?,?,?,?,?)",
                                    (repo, name, r["para_no"], r["paragraph"], plain(r["paragraph"])))
                    con.execute(
                        """INSERT INTO passages (repo, file, para_no, sent_no, src_ref, chapter, section_no, section_title,
                                                 text, plain, chars)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?)
                           ON CONFLICT(repo, file, para_no, sent_no) DO UPDATE SET
                             src_ref=excluded.src_ref, chapter=excluded.chapter, section_no=excluded.section_no,
                             section_title=excluded.section_title, text=excluded.text, plain=excluded.plain,
                             chars=excluded.chars""",
                        (repo, name, r["para_no"], r["sent_no"], r["src_ref"], r["chapter"], r["section_no"],
                         r["section_title"], r["text"], plain(r["text"]), len(plain(r["text"]))))
                    rid = con.execute("SELECT id FROM passages WHERE repo=? AND file=? AND para_no=? AND sent_no=?",
                                      (repo, name, r["para_no"], r["sent_no"])).fetchone()[0]
                    con.execute("INSERT OR IGNORE INTO seen (id) VALUES (?)", (rid,))
                counts[repo] += len(rows)
        # 원본에서 사라진 문장은 지우되, 에피소드에 연결된 문장은 남긴다
        con.execute("""DELETE FROM passages WHERE id NOT IN (SELECT id FROM seen)
                       AND id NOT IN (SELECT passage_id FROM episode_passages)""")
        con.commit()
        con.execute("VACUUM")
    finally:
        con.close()
    return counts


_SELECT = """SELECT p.*, g.text AS paragraph FROM passages p
              LEFT JOIN paragraphs g ON g.repo = p.repo AND g.file = p.file AND g.para_no = p.para_no"""


def _hit(row: sqlite3.Row, match: str) -> dict:
    d = {k: row[k] for k in ("id", "repo", "chapter", "section_no", "section_title", "src_ref", "text", "paragraph")}
    d["book"] = BOOKS[row["repo"]]["en"]
    d["citation"] = citation(d)
    d["match"] = match
    return d


def search(keyword: str, db_path: str = DB_PATH, repo: Optional[str] = None, limit: int = 20) -> List[dict]:
    """문장부호를 무시하고 찾는다. 문장 안에 없으면 문단(문장 경계를 넘는 구절)에서 찾아 문단의 첫 문장을 돌려준다."""
    kp = plain(keyword)
    if not kp:
        return []
    if not os.path.exists(db_path):
        raise FileNotFoundError(f"구절 DB 가 없습니다: {db_path} — python -m kanripo_db fetch && python -m kanripo_db build")
    where, args = "", []
    if repo:
        where, args = " AND p.repo = ?", [repo]
    con = _connect(db_path)
    try:
        order = " ORDER BY p.repo, p.file, p.para_no, p.sent_no LIMIT ?"
        rows = con.execute(_SELECT + " WHERE p.plain LIKE ?" + where + order, [f"%{kp}%", *args, limit]).fetchall()
        if rows:
            return [_hit(r, "sentence") for r in rows]
        rows = con.execute(_SELECT + " WHERE g.plain LIKE ? AND p.sent_no = 1" + where + order,
                           [f"%{kp}%", *args, limit]).fetchall()
        return [_hit(r, "paragraph") for r in rows]
    finally:
        con.close()


def link_episode(episode: str, passage_id: int, role: str = "quote", db_path: str = DB_PATH) -> None:
    """에피소드에 쓰는 구절을 기록한다(같은 쌍은 한 줄, role 만 갱신)."""
    con = _connect(db_path)
    try:
        if not con.execute("SELECT 1 FROM passages WHERE id = ?", (passage_id,)).fetchone():
            raise ValueError(f"없는 구절 id 입니다: {passage_id}")
        con.execute("""INSERT INTO episode_passages (episode, passage_id, role) VALUES (?,?,?)
                       ON CONFLICT(episode, passage_id) DO UPDATE SET role=excluded.role""", (episode, passage_id, role))
        con.execute("UPDATE passages SET used = 1 WHERE id = ?", (passage_id,))
        con.commit()
    finally:
        con.close()


def episode_passages(episode: str, db_path: str = DB_PATH) -> List[dict]:
    con = _connect(db_path)
    try:
        rows = con.execute("""SELECT p.*, g.text AS paragraph, e.role FROM episode_passages e
                              JOIN passages p ON p.id = e.passage_id
                              LEFT JOIN paragraphs g ON g.repo = p.repo AND g.file = p.file AND g.para_no = p.para_no
                              WHERE e.episode = ? ORDER BY p.repo, p.file, p.para_no, p.sent_no""", (episode,)).fetchall()
        return [{**_hit(r, "linked"), "role": r["role"]} for r in rows]
    finally:
        con.close()


def fetch_sources(dest: str = SRC_DIR, runner: Callable = subprocess.run) -> List[str]:
    """BOOKS 의 tls 브랜치를 얕게(--depth 1) 받는다. 이미 받은 저장소는 건너뛴다. 반환: 받아 둔 저장소 목록."""
    os.makedirs(dest, exist_ok=True)
    done = []
    for repo in BOOKS:
        target = os.path.join(dest, repo)
        if not os.path.isdir(target):
            runner(["git", "clone", "--depth", "1", "--branch", "tls", REPO_URL.format(repo=repo), target],
                   check=True, capture_output=True)
        done.append(repo)
    return done


def main(argv: List[str]) -> int:
    if not argv or argv[0] not in ("fetch", "build", "search"):
        print(__doc__.strip().splitlines()[-1])
        return 2
    cmd = argv[0]
    if cmd == "fetch":
        print("받음:", ", ".join(fetch_sources()))
    elif cmd == "build":
        for repo, n in build_db().items():
            print(f"{repo} {BOOKS[repo]['zh']}: 문장 {n}")
    else:
        repo = argv[argv.index("--repo") + 1] if "--repo" in argv else None
        words = [a for a in argv[1:] if a != "--repo" and a != repo]
        for h in search(" ".join(words), repo=repo):
            print(f"[{h['citation']}] {h['src_ref']} {h['section_title']} — {h['text']}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
