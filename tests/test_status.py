import unittest

from moonpath.controller import is_hls_url, normalize_player_state


class NormalizePlayerStateTests(unittest.TestCase):
    def test_idle_after_stop_stays_idle(self) -> None:
        self.assertEqual(
            normalize_player_state(device_idle=False, player_state="IDLE", media_session_id=None),
            "IDLE",
        )

    def test_idle_with_active_session_becomes_buffering(self) -> None:
        self.assertEqual(
            normalize_player_state(device_idle=False, player_state="IDLE", media_session_id=1),
            "BUFFERING",
        )

    def test_unknown_with_active_session_becomes_buffering(self) -> None:
        self.assertEqual(
            normalize_player_state(device_idle=False, player_state="UNKNOWN", media_session_id=2),
            "BUFFERING",
        )

    def test_unknown_without_session_becomes_active(self) -> None:
        self.assertEqual(
            normalize_player_state(device_idle=False, player_state="UNKNOWN", media_session_id=None),
            "ACTIVE",
        )

    def test_device_idle_preserves_idle(self) -> None:
        self.assertEqual(
            normalize_player_state(device_idle=True, player_state="IDLE", media_session_id=1),
            "IDLE",
        )


class IsHlsUrlTests(unittest.TestCase):
    def test_detects_m3u8_extension(self) -> None:
        self.assertTrue(is_hls_url("http://host/film-hls/key/playlist.m3u8"))

    def test_detects_mpegurl_content_type(self) -> None:
        self.assertTrue(
            is_hls_url(
                "http://host/film-hls/key/playlist",
                "application/vnd.apple.mpegurl",
            ),
        )

    def test_rejects_direct_mkv(self) -> None:
        self.assertFalse(is_hls_url("http://host/stream?path=/film.mkv", "video/x-matroska"))


if __name__ == "__main__":
    unittest.main()
