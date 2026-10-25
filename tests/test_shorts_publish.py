"""P-5 S-3 유튜브 발행 — 파일럿 범위 (작업계획서_ShijiFiles_파일럿3편 4장 P-5)."""

import os
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

import app as app_module
import shorts_engine
import shorts_publish
import uploader

try:   # unittest discover -s tests 로 돌 때는 같은 모듈을 다시 import 하지 않도록 최상위 이름을 먼저 쓴다
    from test_shorts_engine import ShortsS2Base
except ImportError:
    from tests.test_shorts_engine import ShortsS2Base

SHIJI = "UC0o0PWB665I9q7ZTmLOcBwQ"
LUNA = "UCowTfbpKpXDBF3Mc50H4iGQ"


class PublishBase(ShortsS2Base):
    def make_job(self, concept="shorts_shiji", ready=True, seal_source="Shiji, ch. 85", language="english"):
        sid = "shorts_pub_1"
        d = shorts_engine.job_dir(sid, create=True)
        f = os.path.join(d, shorts_engine.FINAL_NAME)
        with open(f, "wb") as fh:
            fh.write(b"mp4")
        job = {
            "shorts_id": sid, "concept_key": concept, "narration_language": language, "status": "qc_passed" if ready else "rendered",
            "storyboard": {"hook_text": "A merchant bought an empire", "scenes": [
                {"scene_num": 1, "kind": "image", "seconds": 5, "narration": "x"},
                {"scene_num": 2, "kind": "seal", "seconds": 5, "hanzi": "此奇貨可居", "translation": "Rare goods.", "source": seal_source},
                {"scene_num": 3, "kind": "seal", "seconds": 5, "hanzi": "此奇貨可居", "translation": "Rare goods.", "source": seal_source},
            ]},
            "render": {"file": f},
            "qc": {"passed": ready},
            "review": {"needs_review": False, "findings": [], "override": None},
            "metadata": {"youtube": {"title": "The Merchant Who Bought an Empire #Shorts",
                                     "description": "How a merchant turned a hostage prince into a king.", "tags": ["Shorts"]}},
            "publish": {"youtube": {"video_id": None, "publish_at": None}},
        }
        shorts_engine.save_job(job)
        return job

    def fake_upload(self, **ret):
        m = MagicMock(return_value={"video_id": "vid123", "url": "https://youtu.be/vid123", "warnings": [], **ret})
        p = patch.object(uploader, "upload_video", m)
        p.start()
        self.addCleanup(p.stop)
        return m


class MetadataTests(PublishBase):
    def test_shiji_description_has_sources_and_credit(self):
        meta = shorts_publish.build_youtube_metadata(self.make_job())
        desc = meta["description"]
        self.assertTrue(desc.startswith("How a merchant turned a hostage prince into a king."))
        self.assertEqual(desc.count("📜 Source: Shiji, ch. 85"), 1)   # 같은 출전은 한 번
        self.assertIn("Original text: Kanseki Repository (Kanripo), CC BY-SA 4.0", desc)
        self.assertIn("Translation: Shiji Files", desc)
        self.assertIn("#ancientchina", desc)
        self.assertEqual((meta["category_id"], meta["default_language"], meta["audio_language"]), ("27", "en", "en"))
        self.assertEqual(meta["title"], "The Merchant Who Bought an Empire #Shorts")

    def test_title_override_and_length(self):
        meta = shorts_publish.build_youtube_metadata(self.make_job(), title="x" * 150)
        self.assertEqual(len(meta["title"]), 100)

    def test_generic_job_is_korean_without_kanripo_credit(self):
        job = self.make_job(concept="shorts_info", language="korean")
        for s in job["storyboard"]["scenes"]:
            s["kind"] = "image"
        meta = shorts_publish.build_youtube_metadata(job)
        self.assertNotIn("Kanripo", meta["description"])
        self.assertEqual(meta["default_language"], "ko")


class PublishTests(PublishBase):
    def test_uploads_private_with_ai_label_to_given_channel(self):
        up = self.fake_upload()
        job = shorts_publish.publish_youtube(self.make_job(), channel_id=SHIJI)
        kw = up.call_args.kwargs
        self.assertEqual(kw["privacy"], "private")
        self.assertEqual(kw["channel_id"], SHIJI)
        self.assertTrue(kw["contains_synthetic_media"])
        self.assertFalse(kw["made_for_kids"])
        self.assertEqual((kw["default_language"], kw["audio_language"], kw["category_id"]), ("en", "en", "27"))
        self.assertIsNone(kw.get("pinned_comment"))
        self.assertTrue(kw["video_path"].endswith(shorts_engine.FINAL_NAME))
        yt = job["publish"]["youtube"]
        self.assertEqual((yt["video_id"], yt["privacy"], yt["channel_id"]), ("vid123", "private", SHIJI))
        self.assertEqual(shorts_engine.load_job(job["shorts_id"])["publish"]["youtube"]["video_id"], "vid123")

    def test_channel_defaults_to_env(self):
        up = self.fake_upload()
        with patch.dict(os.environ, {"SHORTS_YOUTUBE_CHANNEL_ID": SHIJI}):
            shorts_publish.publish_youtube(self.make_job())
        self.assertEqual(up.call_args.kwargs["channel_id"], SHIJI)

    def test_no_channel_refused(self):
        up = self.fake_upload()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("SHORTS_YOUTUBE_CHANNEL_ID", None)
            with self.assertRaises(shorts_publish.PublishRefused):
                shorts_publish.publish_youtube(self.make_job())
        up.assert_not_called()

    def test_luna_channel_refused(self):
        up = self.fake_upload()
        with self.assertRaises(shorts_publish.PublishRefused) as cm:
            shorts_publish.publish_youtube(self.make_job(), channel_id=LUNA)
        self.assertIn("루나", str(cm.exception))
        up.assert_not_called()

    def test_publish_gate_refuses(self):
        up = self.fake_upload()
        job = self.make_job()
        job["review"] = {"needs_review": True, "override": None, "findings": [{"level": "P0", "message": "출전 없음"}]}
        with self.assertRaises(shorts_publish.PublishRefused) as cm:
            shorts_publish.publish_youtube(job, channel_id=SHIJI)
        self.assertIn("P0", str(cm.exception))
        up.assert_not_called()

    def test_not_qc_passed_refused(self):
        up = self.fake_upload()
        with self.assertRaises(shorts_publish.PublishRefused):
            shorts_publish.publish_youtube(self.make_job(ready=False), channel_id=SHIJI)
        up.assert_not_called()

    def test_second_upload_refused(self):
        self.fake_upload()
        job = shorts_publish.publish_youtube(self.make_job(), channel_id=SHIJI)
        with self.assertRaises(shorts_publish.PublishRefused) as cm:
            shorts_publish.publish_youtube(job, channel_id=SHIJI)
        self.assertIn("vid123", str(cm.exception))

    def test_schedule_passes_publish_at(self):
        up = self.fake_upload()
        shorts_publish.publish_youtube(self.make_job(), channel_id=SHIJI, publish_at="2026-11-02T09:00:00+09:00")
        self.assertEqual(up.call_args.kwargs["publish_at"], "2026-11-02T09:00:00+09:00")
        self.assertEqual(up.call_args.kwargs["privacy"], "private")

    def test_set_privacy_after_upload(self):
        self.fake_upload()
        job = shorts_publish.publish_youtube(self.make_job(), channel_id=SHIJI)
        with patch.object(uploader, "set_video_privacy", return_value={"privacy": "public"}) as sp:
            job = shorts_publish.set_youtube_privacy(job, "public")
        sp.assert_called_once_with("vid123", "public", channel_id=SHIJI)
        self.assertEqual(job["publish"]["youtube"]["privacy"], "public")
        with self.assertRaises(ValueError):
            shorts_publish.set_youtube_privacy(job, "everyone")

    def test_set_privacy_before_upload_refused(self):
        with self.assertRaises(shorts_publish.PublishRefused):
            shorts_publish.set_youtube_privacy(self.make_job(), "public")


class UploaderFieldsTests(unittest.TestCase):
    def test_upload_body_language_and_synthetic(self):
        yt = MagicMock()
        req = MagicMock()
        req.next_chunk.return_value = (None, {"id": "v1"})
        yt.videos.return_value.insert.return_value = req
        tmp = __import__("tempfile").NamedTemporaryFile(suffix=".mp4", delete=False)
        tmp.write(b"x")
        tmp.close()
        self.addCleanup(os.remove, tmp.name)
        with patch.object(uploader, "_creds", return_value=object()), patch.object(uploader, "_service", return_value=yt), \
             patch("googleapiclient.http.MediaFileUpload", MagicMock()):
            uploader.upload_video(tmp.name, "T", "D", default_language="en", audio_language="en", contains_synthetic_media=True)
        body = yt.videos.return_value.insert.call_args.kwargs["body"]
        self.assertEqual(body["snippet"]["defaultLanguage"], "en")
        self.assertEqual(body["snippet"]["defaultAudioLanguage"], "en")
        self.assertTrue(body["status"]["containsSyntheticMedia"])

    def test_upload_defaults_unchanged(self):
        yt = MagicMock()
        req = MagicMock()
        req.next_chunk.return_value = (None, {"id": "v1"})
        yt.videos.return_value.insert.return_value = req
        tmp = __import__("tempfile").NamedTemporaryFile(suffix=".mp4", delete=False)
        tmp.write(b"x")
        tmp.close()
        self.addCleanup(os.remove, tmp.name)
        with patch.object(uploader, "_creds", return_value=object()), patch.object(uploader, "_service", return_value=yt), \
             patch("googleapiclient.http.MediaFileUpload", MagicMock()):
            uploader.upload_video(tmp.name, "T", "D")
        body = yt.videos.return_value.insert.call_args.kwargs["body"]
        self.assertEqual(body["snippet"]["defaultLanguage"], "ko")
        self.assertNotIn("defaultAudioLanguage", body["snippet"])
        self.assertNotIn("containsSyntheticMedia", body["status"])

    def test_set_video_privacy_keeps_other_status_fields(self):
        yt = MagicMock()
        yt.videos.return_value.list.return_value.execute.return_value = {"items": [{"status": {
            "privacyStatus": "private", "license": "youtube", "embeddable": True, "publicStatsViewable": True,
            "selfDeclaredMadeForKids": False, "madeForKids": False, "containsSyntheticMedia": True, "uploadStatus": "processed"}}]}
        yt.videos.return_value.update.return_value.execute.return_value = {"status": {"privacyStatus": "public"}}
        with patch.object(uploader, "_creds", return_value=object()), patch.object(uploader, "_service", return_value=yt):
            res = uploader.set_video_privacy("v1", "public", channel_id=SHIJI)
        body = yt.videos.return_value.update.call_args.kwargs["body"]
        self.assertEqual(body["status"]["privacyStatus"], "public")
        self.assertTrue(body["status"]["containsSyntheticMedia"])   # 다른 값이 지워지지 않게 합쳐 보낸다
        self.assertFalse(body["status"]["selfDeclaredMadeForKids"])
        self.assertNotIn("uploadStatus", body["status"])           # 읽기 전용 필드는 보내지 않는다
        self.assertNotIn("madeForKids", body["status"])
        self.assertEqual(res["privacy"], "public")


class PublishApiTests(PublishBase):
    def setUp(self):
        super().setUp()
        self.client = TestClient(app_module.app)
        app_module._shorts_building.clear()

    def test_publish_endpoint(self):
        self.fake_upload()
        job = self.make_job()
        r = self.client.post(f"/api/shorts/jobs/{job['shorts_id']}/publish/youtube", json={"channel_id": SHIJI})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["data"]["publish"]["youtube"]["video_id"], "vid123")

    def test_publish_endpoint_refusals(self):
        up = self.fake_upload()
        job = self.make_job()
        r = self.client.post(f"/api/shorts/jobs/{job['shorts_id']}/publish/youtube", json={"channel_id": LUNA})
        self.assertEqual(r.status_code, 409)
        app_module._shorts_building.add(job["shorts_id"])
        r = self.client.post(f"/api/shorts/jobs/{job['shorts_id']}/publish/youtube", json={"channel_id": SHIJI})
        self.assertEqual(r.status_code, 409)
        app_module._shorts_building.clear()
        up.assert_not_called()

    def test_privacy_endpoint(self):
        self.fake_upload()
        job = shorts_publish.publish_youtube(self.make_job(), channel_id=SHIJI)
        with patch.object(uploader, "set_video_privacy", return_value={"privacy": "public"}):
            r = self.client.post(f"/api/shorts/jobs/{job['shorts_id']}/publish/youtube/privacy", json={"privacy": "public"})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["data"]["publish"]["youtube"]["privacy"], "public")
        r = self.client.post(f"/api/shorts/jobs/{job['shorts_id']}/publish/youtube/privacy", json={"privacy": "everyone"})
        self.assertEqual(r.status_code, 400)


if __name__ == "__main__":
    unittest.main()
