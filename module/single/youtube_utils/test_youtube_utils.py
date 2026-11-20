import unittest

from module.single.youtube_utils import youtube_utils

class VideoIdValidationTests(unittest.TestCase):
    """YouTube動画IDの形式検証テスト。"""

    def test_valid_video_id(self):
        self.assertTrue(
            youtube_utils.is_valid_video_id("dQw4w9WgXcQ")
        )

    def test_valid_video_id_with_hyphen_and_underscore(self):
        self.assertTrue(
            youtube_utils.is_valid_video_id("abcde_f-gh1")
        )

    def test_invalid_video_id_length(self):
        invalid_ids = [
            "",
            "dQw4w9WgXc",
            "dQw4w9WgXcQ1",
        ]

        for video_id in invalid_ids:
            with self.subTest(video_id=video_id):
                self.assertFalse(
                    youtube_utils.is_valid_video_id(video_id)
                )

    def test_invalid_video_id_characters(self):
        invalid_ids = [
            "dQw4w9WgXc!",
            "dQw4w9WgXc/",
            "dQw4w9WgXc ",
        ]

        for video_id in invalid_ids:
            with self.subTest(video_id=video_id):
                self.assertFalse(
                    youtube_utils.is_valid_video_id(video_id)
                )

    def test_non_string_video_id(self):
        invalid_values = [
            None,
            12345678901,
            [],
            {},
        ]

        for value in invalid_values:
            with self.subTest(value=value):
                self.assertFalse(
                    youtube_utils.is_valid_video_id(value)
                )


class ExtractVideoIdTests(unittest.TestCase):
    """YouTube URLからの動画ID抽出テスト。"""

    VIDEO_ID = "dQw4w9WgXcQ"

    def test_standard_watch_url(self):
        url = f"https://www.youtube.com/watch?v={self.VIDEO_ID}"

        self.assertEqual(
            youtube_utils.extract_video_id(url),
            self.VIDEO_ID,
        )

    def test_short_url(self):
        url = f"https://youtu.be/{self.VIDEO_ID}"

        self.assertEqual(
            youtube_utils.extract_video_id(url),
            self.VIDEO_ID,
        )

    def test_embed_url(self):
        url = f"https://www.youtube.com/embed/{self.VIDEO_ID}"

        self.assertEqual(
            youtube_utils.extract_video_id(url),
            self.VIDEO_ID,
        )

    def test_shorts_url(self):
        url = f"https://www.youtube.com/shorts/{self.VIDEO_ID}"

        self.assertEqual(
            youtube_utils.extract_video_id(url),
            self.VIDEO_ID,
        )

    def test_live_url(self):
        url = f"https://www.youtube.com/live/{self.VIDEO_ID}"

        self.assertEqual(
            youtube_utils.extract_video_id(url),
            self.VIDEO_ID,
        )

    def test_mobile_url(self):
        url = f"https://m.youtube.com/watch?v={self.VIDEO_ID}"

        self.assertEqual(
            youtube_utils.extract_video_id(url),
            self.VIDEO_ID,
        )

    def test_youtube_music_url(self):
        url = f"https://music.youtube.com/watch?v={self.VIDEO_ID}"

        self.assertEqual(
            youtube_utils.extract_video_id(url),
            self.VIDEO_ID,
        )

    def test_watch_url_with_additional_query_parameters(self):
        url = (
            f"https://www.youtube.com/watch"
            f"?list=PL1234567890&v={self.VIDEO_ID}&index=1"
        )

        self.assertEqual(
            youtube_utils.extract_video_id(url),
            self.VIDEO_ID,
        )

    def test_watch_url_with_reversed_query_parameter_order(self):
        url = (
            f"https://www.youtube.com/watch"
            f"?t=120&v={self.VIDEO_ID}"
        )

        self.assertEqual(
            youtube_utils.extract_video_id(url),
            self.VIDEO_ID,
        )

    def test_url_without_scheme(self):
        url = f"www.youtube.com/watch?v={self.VIDEO_ID}"

        self.assertEqual(
            youtube_utils.extract_video_id(url),
            self.VIDEO_ID,
        )

    def test_url_with_surrounding_whitespace(self):
        url = f"  https://youtu.be/{self.VIDEO_ID}  "

        self.assertEqual(
            youtube_utils.extract_video_id(url),
            self.VIDEO_ID,
        )

    def test_invalid_urls(self):
        invalid_urls = [
            "",
            "https://www.google.com/watch?v=dQw4w9WgXcQ",
            f"https://youtube.com.evil.example/watch?v={self.VIDEO_ID}",
            f"https://youtube-nocookie.com/embed/{self.VIDEO_ID}",
            "https://www.youtube.com/watch",
            "https://www.youtube.com/playlist?list=PL1234567890",
            f"https://www.youtube.com/channel/{self.VIDEO_ID}",
            f"https://www.youtube.com/shorts/{self.VIDEO_ID}/extra",
            f"https://youtu.be/{self.VIDEO_ID}/extra",
            f"ftp://www.youtube.com/watch?v={self.VIDEO_ID}",
            f"https://user@www.youtube.com/watch?v={self.VIDEO_ID}",
            f"https://www.youtube.com:443/watch?v={self.VIDEO_ID}",
            f"https://youtu.be//{self.VIDEO_ID}",
            f"https://youtu.be/{self.VIDEO_ID}////",
            f"https://www.youtube.com/embed//{self.VIDEO_ID}",
            f"https://www.youtube.com/shorts//{self.VIDEO_ID}",
        ]

        for url in invalid_urls:
            with self.subTest(url=url):
                self.assertIsNone(
                    youtube_utils.extract_video_id(url)
                )

    def test_invalid_video_id_in_url(self):
        invalid_ids = [
            "short",
            "dQw4w9WgXc!",
            "dQw4w9WgXcQ1",
        ]

        for video_id in invalid_ids:
            with self.subTest(video_id=video_id):
                url = f"https://www.youtube.com/watch?v={video_id}"

                self.assertIsNone(
                    youtube_utils.extract_video_id(url)
                )

    def test_duplicate_video_id_query_parameters(self):
        url = (
            f"https://www.youtube.com/watch"
            f"?v={self.VIDEO_ID}&v={self.VIDEO_ID}"
        )

        self.assertIsNone(
            youtube_utils.extract_video_id(url)
        )

    def test_non_string_url(self):
        invalid_values = [
            None,
            123,
            [],
            {},
        ]

        for value in invalid_values:
            with self.subTest(value=value):
                self.assertIsNone(
                    youtube_utils.extract_video_id(value)
                )

    def test_url_with_trailing_slash(self):
        urls = [
            f"https://youtu.be/{self.VIDEO_ID}/",
            f"https://www.youtube.com/embed/{self.VIDEO_ID}/",
            f"https://www.youtube.com/shorts/{self.VIDEO_ID}/",
            f"https://www.youtube.com/live/{self.VIDEO_ID}/",
        ]

        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(
                    youtube_utils.extract_video_id(url),
                    self.VIDEO_ID,
                )


if __name__ == "__main__":
    unittest.main()
