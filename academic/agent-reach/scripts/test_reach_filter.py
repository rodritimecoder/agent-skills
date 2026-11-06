#!/usr/bin/env python3
import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import reach_filter as rf


class TestReachFilter(unittest.TestCase):

    def test_render_table(self):
        rows = [
            {"id": "1", "name": "Alice", "score": 100},
            {"id": "2", "name": "Bob", "score": 90},
        ]
        out = rf.render_table(rows, ["id", "name", "score"])
        self.assertIn("| Id | Name  | Score |", out)
        self.assertIn("| 1  | Alice | 100   |", out)
        self.assertIn("| 2  | Bob   | 90    |", out)

    def test_filter_v2ex(self):
        sample = [
            {
                "id": 1084201,
                "title": "Discussion on Python 3.14 async runtime",
                "replies": 35,
                "node": {"title": "Python", "name": "python"},
                "member": {"username": "guido"}
            }
        ]
        rows = rf.filter_v2ex(sample)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "1084201")
        self.assertEqual(rows[0]["node"], "Python")
        self.assertEqual(rows[0]["author"], "guido")
        self.assertEqual(rows[0]["replies"], 35)
        self.assertEqual(rows[0]["url"], "https://www.v2ex.com/t/1084201")

    def test_filter_twitter(self):
        sample = [
            {
                "id": "184000112233",
                "username": "karpathy",
                "text": "Deep thinking agents with verifiable reasoning are exciting.",
                "favorite_count": 4200,
                "retweet_count": 530
            }
        ]
        rows = rf.filter_twitter(sample)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["author"], "@karpathy")
        self.assertEqual(rows[0]["likes"], 4200)
        self.assertIn("Deep thinking", rows[0]["text"])

    def test_filter_reddit(self):
        sample = {
            "data": {
                "children": [
                    {
                        "data": {
                            "subreddit_name_prefixed": "r/LocalLLaMA",
                            "title": "Dual AMD Radeon GPU inference benchmarking with llama.cpp",
                            "score": 380,
                            "num_comments": 45,
                            "author": "localtester",
                            "permalink": "/r/LocalLLaMA/comments/123/dual_amd/"
                        }
                    }
                ]
            }
        }
        rows = rf.filter_reddit(sample)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["sub"], "r/LocalLLaMA")
        self.assertEqual(rows[0]["score"], 380)
        self.assertEqual(rows[0]["comments"], 45)
        self.assertEqual(rows[0]["url"], "https://reddit.com/r/LocalLLaMA/comments/123/dual_amd/")

    def test_filter_bilibili(self):
        sample = {
            "data": {
                "result": [
                    {
                        "bvid": "BV1xx411c7mD",
                        "title": "<em class=\"keyword\">PyTorch</em> 2.0 深度学习教学",
                        "author": "UP主",
                        "play": 150000,
                        "video_review": 3200
                    }
                ]
            }
        }
        rows = rf.filter_bilibili(sample)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["bvid"], "BV1xx411c7mD")
        self.assertEqual(rows[0]["title"], "PyTorch 2.0 深度学习教学")
        self.assertEqual(rows[0]["author"], "UP主")

    def test_filter_xhs(self):
        sample = {
            "data": {
                "items": [
                    {
                        "id": "670f123456",
                        "title": "Sydney UTS Library study spot recommendation",
                        "user": {"nickname": "StudySydney"},
                        "interact_info": {"liked_count": 890},
                        "xsec_token": "AB12CD"
                    }
                ]
            }
        }
        rows = rf.filter_xhs(sample)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "670f123456")
        self.assertEqual(rows[0]["author"], "StudySydney")
        self.assertEqual(rows[0]["likes"], 890)
        self.assertIn("xsec_token=AB12CD", rows[0]["url"])

    def test_auto_detect_platform(self):
        self.assertEqual(rf.auto_detect_platform([{"node": {}, "replies": 10}]), "v2ex")
        self.assertEqual(rf.auto_detect_platform([{"bvid": "BV123"}]), "bilibili")
        self.assertEqual(rf.auto_detect_platform({"data": {"children": []}}), "reddit")

    def test_cli_piped_execution_with_projection_and_limit(self):
        sample = [
            {"id": "1", "title": "Topic 1", "replies": 10, "node": {"title": "tech"}, "member": {"username": "u1"}},
            {"id": "2", "title": "Topic 2", "replies": 20, "node": {"title": "tech"}, "member": {"username": "u2"}},
            {"id": "3", "title": "Topic 3", "replies": 30, "node": {"title": "tech"}, "member": {"username": "u3"}},
        ]
        cmd = [sys.executable, os.path.join(os.path.dirname(__file__), "reach_filter.py"), "v2ex", "-p", "title,replies", "-n", "2"]
        res = subprocess.run(cmd, input=json.dumps(sample), capture_output=True, text=True)
        self.assertEqual(res.returncode, 0)
        self.assertIn("| Title", res.stdout)
        self.assertIn("| Replies |", res.stdout)
        self.assertNotIn("| Node |", res.stdout)
        # Should have header + separator + 2 data rows = 4 lines
        lines = [l for l in res.stdout.strip().splitlines() if l.startswith("|")]
        self.assertEqual(len(lines), 4)

    def test_cli_disk_buffering(self):
        sample = [{"id": "1", "title": "Topic 1", "replies": 10, "node": {"title": "tech"}, "member": {"username": "u1"}}]
        with tempfile.TemporaryDirectory() as tmp_dir:
            out_file = os.path.join(tmp_dir, "feed.json")
            cmd = [sys.executable, os.path.join(os.path.dirname(__file__), "reach_filter.py"), "v2ex", "-o", out_file]
            res = subprocess.run(cmd, input=json.dumps(sample), capture_output=True, text=True)
            self.assertEqual(res.returncode, 0)
            self.assertTrue(os.path.exists(out_file))
            self.assertIn(f"Buffered 1 v2ex records to `{out_file}`", res.stdout)


if __name__ == "__main__":
    unittest.main()
