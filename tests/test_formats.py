import unittest

from formats import collect_options, info_payload, pick_fid


class FormatClassificationTest(unittest.TestCase):
    def setUp(self):
        self.info = {
            "title": "sample",
            "formats": [
                {"format_id": "137", "url": "https://cdn/video-1080.mp4", "ext": "mp4",
                 "protocol": "https", "vcodec": "avc1", "acodec": "none", "height": 1080,
                 "tbr": 2500},
                # Some extractors return null/empty codec values instead of "none".
                {"format_id": "140", "url": "https://cdn/audio.m4a", "ext": "m4a",
                 "protocol": "https", "vcodec": None, "acodec": "mp4a.40.2", "abr": 129},
                {"format_id": "22", "url": "https://cdn/video-720.mp4", "ext": "mp4",
                 "protocol": "https", "vcodec": "avc1", "acodec": "mp4a.40.2", "height": 720,
                 "tbr": 1000},
            ],
        }

    def test_audio_with_null_video_codec_is_exposed(self):
        video, audio = collect_options(self.info)
        self.assertEqual([o["fid"] for o in video], ["137", "22"])
        self.assertEqual([o["fid"] for o in audio], ["140"])
        self.assertFalse(audio[0]["has_video"])
        self.assertTrue(audio[0]["has_audio"])

    def test_audio_selection_and_quality_selection_are_correct(self):
        self.assertEqual(pick_fid(self.info, "audio", None), "140")
        self.assertEqual(pick_fid(self.info, "video", "720"), "22")

    def test_payload_keeps_video_and_audio_separate(self):
        payload = info_payload(self.info)
        self.assertEqual(payload["format_count"], 3)
        self.assertEqual(len(payload["audio"]), 1)


if __name__ == "__main__":
    unittest.main()
