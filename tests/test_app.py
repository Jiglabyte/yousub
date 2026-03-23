import unittest
from unittest.mock import patch

from app import (
    CaptionSegment,
    SubtitleError,
    app,
    build_document,
    extract_video_id,
    format_timestamp,
    to_preview_rows,
)


class AppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = app.test_client()

    def test_extract_video_id_from_watch_url(self) -> None:
        self.assertEqual(
            extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )

    def test_extract_video_id_rejects_invalid_input(self) -> None:
        with self.assertRaises(SubtitleError):
            extract_video_id("https://example.com/video")

    def test_format_timestamp_for_srt(self) -> None:
        self.assertEqual(format_timestamp(61.245, True), "00:01:01,245")

    def test_preview_rows(self) -> None:
        rows = to_preview_rows([CaptionSegment(start=1.5, duration=2.25, text="Hello world")])
        self.assertEqual(rows[0]["start"], "00:00:01.500")
        self.assertEqual(rows[0]["end"], "00:00:03.750")

    def test_build_document_csv(self) -> None:
        content, mimetype = build_document(
            [CaptionSegment(start=0, duration=1.2, text='Hello "world"')],
            "csv",
        )
        self.assertIn('"Hello ""world"""', content)
        self.assertEqual(mimetype, "text/csv; charset=utf-8")

    @patch("app.analyze_video")
    def test_analyze_endpoint(self, analyze_video_mock) -> None:
        analyze_video_mock.return_value = {
            "video_id": "abc123def45",
            "title": "Example",
            "author": "Channel",
            "length_seconds": 120,
            "thumbnail": "https://example.com/thumb.jpg",
            "tracks": [],
            "translation_languages": [],
        }
        response = self.client.post("/api/analyze", json={"url": "https://youtu.be/abc123def45"})
        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])

    @patch("app.fetch_caption_segments")
    def test_preview_endpoint(self, fetch_caption_segments_mock) -> None:
        fetch_caption_segments_mock.return_value = [
            CaptionSegment(start=0.0, duration=1.0, text="One"),
            CaptionSegment(start=1.0, duration=1.5, text="Two"),
        ]
        response = self.client.get("/api/preview?video_id=x&track_id=en::manual")
        payload = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["data"]["rows"]), 2)

    @patch("app.fetch_caption_segments")
    def test_caption_endpoint_error(self, fetch_caption_segments_mock) -> None:
        fetch_caption_segments_mock.side_effect = SubtitleError("Bad track")
        response = self.client.get("/api/captions?video_id=x&track_id=en::manual&format=srt")
        payload = response.get_json()
        self.assertEqual(response.status_code, 400)
        self.assertFalse(payload["ok"])


if __name__ == "__main__":
    unittest.main()
