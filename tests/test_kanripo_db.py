"""P-2 칸리포 구절 DB (작업계획서_ShijiFiles_파일럿3편 4장 P-2)."""

import os
import shutil
import tempfile
import unittest

import kanripo_db

SHIJI = """# -*- mode: mandoku-view -*-
#+TITLE: 史記
#+PROPERTY: ID KR2a0001
<pb:KR2a0001_tls_500-1a>¶
** 5 傳

# src: SHIJI 85.1.1 2505; Wang Liqi 1937 ; Takigawa 2; tr. Watson 1993, Qin, p.159
# dating: 6220
<pb:KR2a0001_tls_500-687a>¶
5.25《呂不韋列傳第二十五》

<pb:KR2a0001_tls_500-688a>¶
呂不韋者，¶
陽翟大賈人也。¶
往來販賤賣貴，¶
家累千金。

# src: SHIJI 85.2.1 2506; Wang Liqi 1937 ; Takigawa 3
# dating: 6220
呂不韋賈邯鄲，¶
見而憐之，¶
曰¶「此奇貨可居」。¶

<pb:KR2a0001_tls_201-1a>¶
** 2 表
*** 2.1　《三代世表》　　　　

太史公曰：¶
五帝、三代之記，尚矣。¶
*** 公元前|206高祖元年|楚|¶

<pb:KR2a0001_tls_500-700a>¶
5.15《孟嘗君列傳第十五》

最下坐有能為狗盜者，¶
曰：「臣能得狐白裘。」¶
"""

ZGC = """#+TITLE: 戰國策
#+PROPERTY: ID KR2e0003

# src: ZGC,14.3.1, tr. Crump no,176, ed. Sha4ngha3igu3jí p. 4i1
# dating: 8110
<pb:KR2e0003_tls_172-1a>¶
** 172 荊宣王問群臣

荊宣王問群臣曰：¶
「吾聞北方之畏昭奚恤也，¶
果誠何如？」¶
群臣莫對。¶
江一對曰：¶
「虎求百獸而食之，¶
得狐。¶
"""

HF = """#+TITLE: 韓非子
#+PROPERTY: ID KR3c0005

# src: HF 12.01:01; jiaoshi 268; jishi 221
# dating: 8110
<pb:KR3c0005_tls_012-1a>¶
** 12 說難第十二

凡說之難：¶
在知所說之心，〓#夫@fú¶
可以吾說當之。<pb:KR3c0005_tls_012-2a>¶

48.7類柄<pb:KR3c0005_tls_048-14a>¶
*官之重也，¶
毋法也。¶
"""

SUNZI = """#+TITLE: 孫子
#+PROPERTY: ID KR3b0003
<pb:KR3b0003_tls_001-1a>¶
** 1 《計篇》

孫子曰：¶
兵者，¶
國之大事也；¶
不可不察也。

# dating: 8110
故經之以五事，¶
校之以計
而索其情：¶
一曰道。¶
"""


class ParseTests(unittest.TestCase):
    def test_shiji_src_precedes_paragraph_and_sets_chapter(self):
        rows = kanripo_db.parse_text(SHIJI, "KR2a0001")
        hit = [r for r in rows if "奇貨可居" in r["text"]]
        self.assertEqual(len(hit), 1)
        r = hit[0]
        self.assertEqual(r["src_ref"], "SHIJI 85.2.1")
        self.assertEqual(r["chapter"], "85")
        self.assertEqual(r["section_title"], "呂不韋列傳第二十五")
        self.assertEqual(r["text"], "呂不韋賈邯鄲，見而憐之，曰「此奇貨可居」。")   # ¶·줄바꿈 제거, 마침표까지 한 문장
        self.assertIn("呂不韋賈邯鄲", r["paragraph"])
        first = [x for x in rows if x["text"].startswith("呂不韋者")][0]
        self.assertEqual(first["src_ref"], "SHIJI 85.1.1")   # 제목 줄은 문단이 아니다 — 출전은 다음 문단까지 이어진다

    def test_shiji_chapter_from_title_not_inherited_src(self):
        # 출전 줄이 없는 편은 앞 편 출전을 물려받지 않고, 권 번호는 편 제목(列傳 15 → 75권)에서 정한다
        rows = kanripo_db.parse_text(SHIJI, "KR2a0001")
        r = [x for x in rows if "狗盜" in x["text"]][0]
        self.assertEqual(r["chapter"], "75")
        self.assertEqual(r["src_ref"], "")
        self.assertEqual(r["section_title"], "孟嘗君列傳第十五")

    def test_shiji_table_title_with_stars_and_fullwidth_spaces(self):
        rows = kanripo_db.parse_text(SHIJI, "KR2a0001")
        r = [x for x in rows if x["text"].startswith("太史公曰")][0]
        self.assertEqual(r["chapter"], "13")   # 表 1 → 13권
        self.assertEqual(r["section_title"], "三代世表")
        self.assertFalse(any("三代世表" in x["text"] for x in rows))   # 제목 줄이 본문으로 새지 않는다
        self.assertFalse(any("|" in x["text"] for x in rows))   # 표 칸 줄은 뺀다

    def test_markup_removed(self):
        for text, repo in ((SHIJI, "KR2a0001"), (ZGC, "KR2e0003"), (HF, "KR3c0005"), (SUNZI, "KR3b0003")):
            for r in kanripo_db.parse_text(text, repo):
                for bad in ("<pb", "¶", "#", "\n", "src:"):
                    self.assertNotIn(bad, r["text"], (repo, r["text"]))
                    self.assertNotIn(bad, r["paragraph"], (repo, r["paragraph"]))

    def test_sentences_split_on_full_stops(self):
        rows = kanripo_db.parse_text(ZGC, "KR2e0003")
        texts = [r["text"] for r in rows]
        self.assertEqual(texts[0], "荊宣王問群臣曰：「吾聞北方之畏昭奚恤也，果誠何如？」")
        self.assertIn("群臣莫對。", texts)
        self.assertEqual(rows[0]["section_no"], "172")
        self.assertEqual(rows[0]["chapter"], "172")
        self.assertEqual(rows[0]["src_ref"], "ZGC 14.3.1")   # 제목 앞 출전은 그 항목 첫 문단 몫
        self.assertEqual(rows[0]["section_title"], "荊宣王問群臣")

    def test_inline_page_tag_and_hf_chapter(self):
        rows = kanripo_db.parse_text(HF, "KR3c0005")
        self.assertEqual(rows[0]["text"], "凡說之難：在知所說之心，〓夫可以吾說當之。")   # 독음·# 제거, 결자 〓 유지
        self.assertEqual(rows[0]["chapter"], "12")
        self.assertEqual(rows[0]["src_ref"], "HF 12.01:01")
        self.assertEqual(rows[-1]["text"], "官之重也，毋法也。")   # 소제목 줄·앞 * 제거
        self.assertFalse(any("類柄" in r["text"] for r in rows))

    def test_line_without_pilcrow_joins_and_missing_src(self):
        rows = kanripo_db.parse_text(SUNZI, "KR3b0003")
        self.assertIn("故經之以五事，校之以計而索其情：一曰道。", [r["text"] for r in rows])
        self.assertEqual(rows[0]["src_ref"], "")
        self.assertEqual(rows[0]["section_no"], "1")
        self.assertEqual(rows[0]["chapter"], "1")
        self.assertEqual(rows[0]["section_title"], "計篇")

    def test_unknown_repo_rejected(self):
        with self.assertRaises(ValueError):
            kanripo_db.parse_text(SHIJI, "KR9z9999")


class CitationTests(unittest.TestCase):
    def test_citations_per_book(self):
        self.assertEqual(kanripo_db.citation({"repo": "KR2a0001", "chapter": "85", "section_no": "5"}), "Shiji, ch. 85")
        self.assertEqual(kanripo_db.citation({"repo": "KR2e0003", "chapter": "172"}), "Zhanguo ce, §172")
        self.assertEqual(kanripo_db.citation({"repo": "KR3c0005", "chapter": "12"}), "Han Feizi, ch. 12")
        self.assertEqual(kanripo_db.citation({"repo": "KR3b0003", "chapter": "1"}), "Sunzi, ch. 1")

    def test_citation_without_chapter_never_guesses(self):
        # 사기 부 번호(5)를 권 번호로 잘못 쓰지 않는다
        self.assertEqual(kanripo_db.citation({"repo": "KR2a0001", "chapter": "", "section_no": "5"}), "Shiji")

    def test_credit_line(self):
        self.assertEqual(kanripo_db.CREDIT, "Original text: Kanseki Repository (Kanripo), CC BY-SA 4.0")


class DbTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.src = os.path.join(self.tmp, "src")
        for repo, text in (("KR2a0001", SHIJI), ("KR2e0003", ZGC), ("KR3c0005", HF), ("KR3b0003", SUNZI)):
            d = os.path.join(self.src, repo)
            os.makedirs(d)
            with open(os.path.join(d, f"{repo}_001.txt"), "w", encoding="utf-8") as f:
                f.write(text)
            with open(os.path.join(d, "Readme.org"), "w", encoding="utf-8") as f:
                f.write("#+TITLE: x\n本文ではない。¶\n")
        self.db = os.path.join(self.tmp, "passages.db")

    def test_build_counts_and_rebuild_is_idempotent(self):
        c1 = kanripo_db.build_db(self.src, self.db)
        c2 = kanripo_db.build_db(self.src, self.db)
        self.assertEqual(c1, c2)
        self.assertGreater(c1["KR2a0001"], 0)
        self.assertEqual(set(c1), set(kanripo_db.BOOKS))

    def test_search_ignores_punctuation(self):
        kanripo_db.build_db(self.src, self.db)
        hits = kanripo_db.search("此奇貨可居", db_path=self.db)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["citation"], "Shiji, ch. 85")
        hits = kanripo_db.search("曰「此奇貨，可居」", db_path=self.db)   # 문장부호가 달라도 찾는다
        self.assertEqual(len(hits), 1)

    def test_search_across_sentences_falls_back_to_paragraph(self):
        kanripo_db.build_db(self.src, self.db)
        hits = kanripo_db.search("群臣莫對江一對曰", db_path=self.db)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["match"], "paragraph")

    def test_search_repo_filter_and_empty(self):
        kanripo_db.build_db(self.src, self.db)
        self.assertEqual(kanripo_db.search("說", db_path=self.db, repo="KR2a0001"), [])
        self.assertEqual(kanripo_db.search("", db_path=self.db), [])
        self.assertEqual(kanripo_db.search("說之難", db_path=self.db, repo="KR3c0005")[0]["repo"], "KR3c0005")

    def test_episode_links(self):
        kanripo_db.build_db(self.src, self.db)
        pid = kanripo_db.search("此奇貨可居", db_path=self.db)[0]["id"]
        kanripo_db.link_episode("ep04", pid, role="seal", db_path=self.db)
        kanripo_db.link_episode("ep04", pid, role="seal", db_path=self.db)   # 두 번 넣어도 한 줄
        rows = kanripo_db.episode_passages("ep04", db_path=self.db)
        self.assertEqual([(r["id"], r["role"]) for r in rows], [(pid, "seal")])
        with self.assertRaises(ValueError):
            kanripo_db.link_episode("ep04", 999999, db_path=self.db)


class FetchTests(unittest.TestCase):
    def test_fetch_clones_tls_branch_shallow_and_skips_existing(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        os.makedirs(os.path.join(tmp, "KR2a0001"))
        calls = []

        def runner(cmd, **kw):
            calls.append(cmd)
            os.makedirs(cmd[-1], exist_ok=True)

            class R:
                returncode = 0
            return R()

        done = kanripo_db.fetch_sources(dest=tmp, runner=runner)
        self.assertEqual(sorted(done), sorted(kanripo_db.BOOKS))
        cloned = [c[-1] for c in calls]
        self.assertNotIn(os.path.join(tmp, "KR2a0001"), cloned)   # 이미 있으면 다시 받지 않는다
        for c in calls:
            self.assertEqual(c[:6], ["git", "clone", "--depth", "1", "--branch", "tls"])
            self.assertTrue(c[6].startswith("https://github.com/kanripo/"))


REAL_DB = kanripo_db.DB_PATH


@unittest.skipUnless(os.path.exists(REAL_DB), "실데이터 DB 없음 — python -m kanripo_db fetch && build 후 실행")
class PilotQuotesTests(unittest.TestCase):
    """기획서 5장 에피소드 원문이 실제 DB 에서 맞는 권으로 찾아지는가."""
    CASES = [
        ("募民有能徙置北門者予十金", "KR2a0001", "68"),
        ("車裂商君以徇", "KR2a0001", "68"),   # 기획서의 "車裂以徇" 은 秦本紀(5권) 문장이었다 — 68권 원문으로 정정
        ("最下坐有能為狗盜者", "KR2a0001", "75"),   # 출전 줄이 없어 73권 출전을 물려받던 편
        ("臣請完璧歸趙", "KR2a0001", "81"),
        ("肉袒負荊", "KR2a0001", "81"),
        ("此奇貨可居", "KR2a0001", "85"),
        ("人主亦有逆鱗", "KR2a0001", "63"),
        ("李斯使人遺非藥", "KR2a0001", "63"),
        ("持鹿獻於二世曰馬也", "KR2a0001", "6"),
        ("項莊拔劍起舞", "KR2a0001", "7"),
        ("出胯下", "KR2a0001", "92"),
        ("狡兔死良狗亨", "KR2a0001", "92"),
        ("置膽於坐", "KR2a0001", "41"),
        ("將在軍君命有所不受", "KR2a0001", "65"),
        ("斬隊長二人", "KR2a0001", "65"),
    ]

    def test_pilot_quotes(self):
        for phrase, repo, chapter in self.CASES:
            with self.subTest(phrase=phrase):
                hits = kanripo_db.search(phrase, repo=repo)
                self.assertIn(chapter, [h["chapter"] for h in hits], hits[:3])


if __name__ == "__main__":
    unittest.main()
