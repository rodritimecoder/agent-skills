#!/usr/bin/env python3
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.dirname(__file__))

import zoom_download as zd


class TestZoomRecorder(unittest.TestCase):

    def test_unwrap_protected_url(self):
        direct = "https://utsmeet.zoom.us/rec/share/12345"
        self.assertEqual(zd.unwrap_protected_url(direct), direct)

        safelink = "https://aus01.safelinks.protection.outlook.com/?url=https%3A%2F%2Futsmeet.zoom.us%2Frec%2Fshare%2F12345&data=05"
        self.assertEqual(zd.unwrap_protected_url(safelink), direct)

        mimecast = "https://protect-au.mimecastprotect.com/s/xyz?domain=https://utsmeet.zoom.us/rec/share/12345"
        self.assertEqual(zd.unwrap_protected_url(mimecast), direct)

        nested = "https://protect-au.mimecastprotect.com/s/xyz?domain=https%3A%2F%2Faus01.safelinks.protection.outlook.com%2F%3Furl%3Dhttps%253A%252F%252Futsmeet.zoom.us%252Frec%252Fshare%252F12345"
        self.assertEqual(zd.unwrap_protected_url(nested), direct)

    def test_time_conversions(self):
        self.assertEqual(zd.parse_time_str("01:23.456"), 83.456)
        self.assertEqual(zd.parse_time_str("01:02:03.500"), 3723.5)
        self.assertEqual(zd.format_seconds(83.4), "01:23")
        self.assertEqual(zd.format_seconds(3723.5), "01:02:04")
        self.assertEqual(zd.format_duration(45), "45s")
        self.assertEqual(zd.format_duration(125), "2m 5s")
        self.assertEqual(zd.format_duration(3665), "1h 1m 5s")

    def test_parse_vtt_cues(self):
        vtt = """WEBVTT

1
00:00:01.000 --> 00:00:05.000
<v Dr. Smith>Good morning class, welcome to Tutorial 5.</v>

2
00:00:05.500 --> 00:00:10.000
Dr. Smith: Today we study operational amplifiers.

3
00:00:12.000 --> 00:00:18.000
Alice: Is this going to be on the midterm?
"""
        cues = zd.parse_vtt_cues(vtt)
        self.assertEqual(len(cues), 3)
        self.assertEqual(cues[0]["speaker"], "Dr. Smith")
        self.assertEqual(cues[0]["text"], "Good morning class, welcome to Tutorial 5.")
        self.assertEqual(cues[1]["speaker"], "Dr. Smith")
        self.assertEqual(cues[2]["speaker"], "Alice")
        self.assertEqual(cues[2]["text"], "Is this going to be on the midterm?")

    def test_build_vtt_outline(self):
        vtt = """WEBVTT

1
00:00:00.000 --> 00:00:05.000
Speaker 1: Welcome to the session.

2
00:00:05.000 --> 00:00:10.000
Speaker 1: Here is our first topic on CMOS circuitry.

3
00:00:40.000 --> 00:00:50.000
Speaker 2: Can you clarify the threshold voltage?
"""
        cues = zd.parse_vtt_cues(vtt)
        outline = zd.build_vtt_outline(cues, pause_threshold=15.0)

        self.assertIn("entries", outline)
        self.assertEqual(len(outline["entries"]), 2)
        self.assertEqual(outline["entries"][0]["speaker"], "Speaker 1")
        self.assertEqual(outline["entries"][1]["speaker"], "Speaker 2")
        self.assertIn("Speaker 1", outline["speakers"])
        self.assertIn("Speaker 2", outline["speakers"])
        self.assertGreater(outline["total_words"], 0)

    def test_render_table_and_projection(self):
        rows = [
            {"time": "00:01", "speaker": "Alice", "words": 15, "preview": "Hello"},
            {"time": "00:05", "speaker": "Bob", "words": 20, "preview": "Hi there"},
        ]
        table_output = zd.render_table(rows, ["time", "speaker", "words"])
        self.assertIn("| Time  | Speaker | Words |", table_output)
        self.assertIn("| 00:01 | Alice   | 15    |", table_output)

        kv_output = zd.render_kv_table({"topic": "48520 Tut", "duration": "50m"})
        self.assertIn("| Topic    | 48520 Tut |", kv_output)
        self.assertIn("| Duration | 50m       |", kv_output)

    @patch("zoom_download.ZoomRecorderClient.get_recording_info")
    def test_cli_info_only(self, mock_info):
        mock_info.return_value = {
            "topic": "Electronics Tutorial 10",
            "duration": 3600,
            "duration_str": "1h",
            "file_id": "998877",
            "has_transcript": True,
            "transcript_url": "https://example.com/transcript.vtt",
            "video_url": "https://example.com/video.mp4",
        }

        with patch("sys.argv", ["zoom_download.py", "--url", "https://utsmeet.zoom.us/rec/share/test", "--info-only", "--json", "--project", "topic,duration"]):
            with patch("sys.stdout.write") as mock_stdout:
                zd.main()
                # Ensure JSON printed with projected fields
                called_text = "".join(call[0][0] for call in mock_stdout.call_args_list)
                data = json.loads(called_text)
                self.assertEqual(data["topic"], "Electronics Tutorial 10")
                self.assertEqual(data["duration"], "1h")
                self.assertNotIn("file_id", data)

    @patch("zoom_download.ZoomRecorderClient.fetch_transcript")
    @patch("zoom_download.ZoomRecorderClient.get_recording_info")
    def test_cli_outline_table(self, mock_info, mock_fetch):
        mock_info.return_value = {
            "topic": "Electronics Tutorial 10",
            "duration": 180,
            "duration_str": "3m",
            "file_id": "998877",
            "has_transcript": True,
            "transcript_url": "https://example.com/transcript.vtt",
            "video_url": None,
        }
        mock_fetch.return_value = """WEBVTT
1
00:00:00.000 --> 00:00:30.000
Lecturer: Welcome everyone.

2
00:01:00.000 --> 00:02:00.000
Student: Question here.
"""
        with patch("sys.argv", ["zoom_download.py", "--url", "https://utsmeet.zoom.us/rec/share/test", "--outline"]):
            with patch("sys.stdout.write") as mock_stdout:
                zd.main()
                called_text = "".join(call[0][0] for call in mock_stdout.call_args_list)
                self.assertIn("### Outline: Electronics Tutorial 10", called_text)
                self.assertIn("| Time", called_text)
                self.assertIn("Lecturer", called_text)
                self.assertIn("Student", called_text)


if __name__ == "__main__":
    unittest.main()
