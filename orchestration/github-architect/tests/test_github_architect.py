import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Import modules under test
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import github_architect
import git_sync
import publication_guard


class TestGitHubArchitect(unittest.TestCase):
    def test_render_table(self):
        rows = [
            {"repository": "repo-a", "branch": "main", "worktree": "Clean", "remote_sync": "Up to date"},
            {"repository": "repo-b", "branch": "dev", "worktree": "2 dirty", "remote_sync": "Ahead (1)"},
        ]
        table = github_architect.render_table(rows, ["repository", "branch", "worktree"])
        self.assertIn("| Repository | Branch | Worktree |", table)
        self.assertIn("| repo-a     | main   | Clean    |", table)
        self.assertIn("| repo-b     | dev    | 2 dirty  |", table)

    def test_render_table_empty(self):
        table = github_architect.render_table([])
        self.assertEqual(table, "*(no records)*\n")

    def test_get_fleet_status_records(self):
        fleet = [
            {"name": "test-repo", "path": Path("/fake/path"), "description": "Fake repo"}
        ]

        def fake_run_cmd(cmd, cwd=None, check=True):
            cmd_str = " ".join(cmd) if isinstance(cmd, list) else cmd
            mock = MagicMock()
            mock.returncode = 0
            if "rev-parse" in cmd_str:
                mock.stdout = "main\n"
            elif "status --porcelain" in cmd_str:
                mock.stdout = ""
            elif "rev-list" in cmd_str:
                mock.stdout = "0 0\n"
            elif "log -1" in cmd_str:
                mock.stdout = "abc1234 (1 day ago) - feat: test commit\n"
            else:
                mock.stdout = ""
            return mock

        with patch.object(github_architect, "run_cmd", side_effect=fake_run_cmd):
            records = github_architect.get_fleet_status_records(fleet)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["repository"], "test-repo")
            self.assertEqual(records[0]["branch"], "main")
            self.assertEqual(records[0]["worktree"], "Clean")
            self.assertEqual(records[0]["remote_sync"], "Up to date")
            self.assertIn("abc1234", records[0]["last_commit"])

    def test_cmd_status_all_json_and_projection(self):
        fleet = [
            {"name": "repo-1", "path": Path("/tmp/r1"), "description": "desc 1"},
            {"name": "repo-2", "path": Path("/tmp/r2"), "description": "desc 2"},
        ]
        records = [
            {"repository": "repo-1", "branch": "main", "worktree": "Clean", "remote_sync": "Up to date", "last_commit": "c1", "path": "/tmp/r1"},
            {"repository": "repo-2", "branch": "feat", "worktree": "1 dirty", "remote_sync": "Ahead (1)", "last_commit": "c2", "path": "/tmp/r2"},
        ]

        with patch.object(github_architect, "discover_fleet_repos", return_value=fleet), \
             patch.object(github_architect, "get_fleet_status_records", return_value=records):
            
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                github_architect.cmd_status_all(as_json=True, project_keys=["repository", "branch"], limit=1)
            
            output = buf.getvalue().strip()
            data = json.loads(output)
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0], {"repository": "repo-1", "branch": "main"})

    def test_cmd_status_all_table(self):
        fleet = [{"name": "repo-1", "path": Path("/tmp/r1"), "description": "desc 1"}]
        records = [{"repository": "repo-1", "branch": "main", "worktree": "Clean", "remote_sync": "Up to date", "last_commit": "c1", "path": "/tmp/r1"}]

        with patch.object(github_architect, "discover_fleet_repos", return_value=fleet), \
             patch.object(github_architect, "get_fleet_status_records", return_value=records):
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                github_architect.cmd_status_all(as_table=True)
            output = buf.getvalue()
            self.assertIn("### Workstation Fleet Status", output)
            self.assertIn("| Repository | Branch | Worktree |", output)
            self.assertIn("| repo-1     | main   | Clean    |", output)

    def test_cmd_audit_table_and_json(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)
            (tmppath / "README.md").write_text("# Test\n", encoding="utf-8")

            # Test JSON mode
            buf = io.StringIO()
            with patch("sys.stdout", buf), \
                 patch.object(github_architect, "check_gh_status", return_value=(True, "testuser")), \
                 patch.object(github_architect, "run_cmd", return_value=MagicMock(stdout="", returncode=0)):
                github_architect.cmd_audit(tmppath, as_json=True)
            output = buf.getvalue().strip()
            data = json.loads(output)
            self.assertIn("checks", data)
            items = {c["item"]: c["status"] for c in data["checks"]}
            self.assertEqual(items.get("README.md"), "Yes")
            self.assertEqual(items.get(".gitignore"), "Missing")

            # Test Table mode
            buf = io.StringIO()
            with patch("sys.stdout", buf), \
                 patch.object(github_architect, "check_gh_status", return_value=(True, "testuser")), \
                 patch.object(github_architect, "run_cmd", return_value=MagicMock(stdout="", returncode=0)):
                github_architect.cmd_audit(tmppath, as_table=True)
            table_out = buf.getvalue()
            self.assertIn("### Repository Audit:", table_out)
            self.assertIn("| Audit Check", table_out)
            self.assertIn("| README.md", table_out)


class TestGitSync(unittest.TestCase):
    def test_git_sync_render_table(self):
        rows = [
            {"step": "Branch", "status": "main", "details": "origin/main"},
            {"step": "Push", "status": "Success", "details": "Pushed upstream"},
        ]
        table = git_sync.render_table(rows, ["step", "status", "details"])
        self.assertIn("| Step   | Status  | Details         |", table)
        self.assertIn("| Branch | main    | origin/main     |", table)

    def test_help_lists_subcommands(self):
        proc = subprocess.run(
            [sys.executable, str(HERE.parent / "scripts" / "git_sync.py"), "--help"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for sub in ("guarded-commit", "check-messages", "install-hook"):
            self.assertIn(sub, proc.stdout)

    def test_guarded_commit_help_lists_options(self):
        proc = subprocess.run(
            [sys.executable, str(HERE.parent / "scripts" / "git_sync.py"), "guarded-commit", "--help"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for opt in ("--repo", "--include", "--exclude", "--message", "--json"):
            self.assertIn(opt, proc.stdout)

    def test_bare_dry_run_json_works_without_subcommand(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        repo = tmp / "repo"
        repo.mkdir()
        subprocess.run(["git", "-C", str(repo), "init", "-b", "main"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True, capture_output=True)
        (repo / "README.md").write_text("hi\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "init"], check=True, capture_output=True)

        proc = subprocess.run(
            [sys.executable, str(HERE.parent / "scripts" / "git_sync.py"), "--dry-run", "--json"],
            cwd=str(repo), capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, f"{proc.stdout}\n{proc.stderr}")
        payload = json.loads(proc.stdout)
        self.assertEqual(payload.get("status"), "clean")


class TestStage2GuardRepo(unittest.TestCase):
    """Wave 1: stage2_guard must scan files relative to an explicit repo,
    not the process CWD, and must leave placeholder credentials alone."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = self.tmp / "outside-repo"
        self.repo.mkdir()

    def test_untracked_secret_outside_cwd_is_blocked(self):
        (self.repo / "leak.txt").write_text(TestPublicationGuard.FAKE_PAT + "\n", encoding="utf-8")
        safe, blocked = git_sync.stage2_guard(["leak.txt"], repo=str(self.repo))
        self.assertEqual(safe, [])
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0][0], "leak.txt")

    def test_placeholder_credential_is_allowed(self):
        (self.repo / "doc.md").write_text(
            'api_key = "YOUR_API_KEY_HERE"\n', encoding="utf-8"
        )
        safe, blocked = git_sync.stage2_guard(["doc.md"], repo=str(self.repo))
        self.assertEqual(blocked, [])
        self.assertEqual(safe, ["doc.md"])


class TestPublicationGuard(unittest.TestCase):
    # Built at runtime, never written as a literal: a PAT-shaped string in
    # this file would be published to the public spokes and the gate would
    # (correctly) block the bundle.
    FAKE_PAT = "ghp_" + "A" * 36

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _skill(self, name="skill", frontmatter="---\nname: s\ndescription: d\n---\n\nbody\n"):
        d = self.tmp / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "SKILL.md").write_text(frontmatter, encoding="utf-8")
        return d

    def test_clean_skill_passes(self):
        d = self._skill()
        findings = publication_guard.scan_source(d, "t")
        self.assertEqual([f for f in findings if f["severity"] == "block"], [])

    def test_archived_without_status_marker_is_blocked(self):
        d = self._skill()
        findings = publication_guard.scan_status_marker(d, "archived/s", "t")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["kind"], "missing-status-marker")

    def test_archived_with_status_marker_passes(self):
        d = self._skill(frontmatter="---\nname: s\nstatus: archived\n---\n\nbody\n")
        findings = publication_guard.scan_status_marker(d, "archived/s", "t")
        self.assertEqual(findings, [])

    def test_non_archived_path_needs_no_marker(self):
        d = self._skill()
        self.assertEqual(publication_guard.scan_status_marker(d, "skill", "t"), [])

    def test_secret_filename_is_blocked(self):
        d = self._skill()
        (d / ".env").write_text("TOKEN=x\n", encoding="utf-8")
        findings = publication_guard.scan_source(d, "t")
        self.assertEqual([f["kind"] for f in findings], ["secret-filename"])

    def test_env_example_is_allowed(self):
        d = self._skill()
        (d / ".env.example").write_text("TOKEN=x\n", encoding="utf-8")
        findings = publication_guard.scan_source(d, "t")
        self.assertEqual([f for f in findings if f["severity"] == "block"], [])

    def test_secret_content_is_blocked_and_masked(self):
        d = self._skill()
        (d / "leak.txt").write_text(self.FAKE_PAT + "\n", encoding="utf-8")
        findings = publication_guard.scan_source(d, "t")
        self.assertEqual(len(findings), 1)
        self.assertNotIn(self.FAKE_PAT, findings[0]["detail"])

    def test_placeholder_credential_is_allowed(self):
        d = self._skill()
        (d / "doc.md").write_text('api_key = "YOUR_API_KEY_HERE"\n', encoding="utf-8")
        findings = publication_guard.scan_source(d, "t")
        self.assertEqual([f for f in findings if f["severity"] == "block"], [])

    def test_excluded_paths_are_not_scanned(self):
        d = self._skill()
        (d / ".env").write_text("TOKEN=x\n", encoding="utf-8")
        findings = publication_guard.scan_source(d, "t", excludes=[".env"])
        self.assertEqual([f for f in findings if f["severity"] == "block"], [])

    def test_trailing_slash_exclude_matches_contents_not_the_dir_itself(self):
        # rsync-style: "foo/" excludes entries inside foo, but the directory
        # entry Path("foo") itself is not considered excluded.
        self.assertFalse(publication_guard.is_excluded(Path("foo"), ["foo/"]))
        self.assertTrue(publication_guard.is_excluded(Path("foo") / "notes.md", ["foo/"]))
        self.assertFalse(publication_guard.is_excluded(Path("bar") / "other.md", ["foo/"]))

    def test_ssh_private_keys_are_blocked_but_public_key_is_allowed(self):
        for name in ("id_ed25519", "id_ed25519_work"):
            with self.subTest(name=name):
                key = self.tmp / name
                key.write_text("not a real key\n", encoding="utf-8")
                findings = publication_guard.scan_file(key, "t")
                self.assertEqual(len(findings), 1)
                self.assertEqual(findings[0]["kind"], "secret-filename")
                self.assertEqual(findings[0]["severity"], "block")
        pub = self.tmp / "id_ed25519.pub"
        pub.write_text("ssh-ed25519 AAAAcomment\n", encoding="utf-8")
        self.assertEqual(publication_guard.scan_file(pub, "t"), [])

    def test_reap_removes_only_stale_managed_dirs(self):
        (self.tmp / "old").mkdir()
        (self.tmp / "old" / "f.txt").write_text("x", encoding="utf-8")
        (self.tmp / "keep").mkdir()
        (self.tmp / "keep" / "f.txt").write_text("x", encoding="utf-8")
        managed = self.tmp / ".bundle-managed.json"
        managed.write_text(json.dumps({"managed": ["old", "keep"]}), encoding="utf-8")
        result = publication_guard.reap(self.tmp, managed, ["keep"])
        self.assertEqual(result["removed"], ["old"])
        self.assertFalse((self.tmp / "old").exists())
        self.assertTrue((self.tmp / "keep").exists())

    def test_reap_is_idempotent(self):
        managed = self.tmp / ".bundle-managed.json"
        managed.write_text(json.dumps({"managed": ["gone"]}), encoding="utf-8")
        first = publication_guard.reap(self.tmp, managed, [])
        second = publication_guard.reap(self.tmp, managed, [])
        self.assertEqual(first["removed"], ["gone"])
        self.assertEqual(second["removed"], [])


class TestGuardedCommit(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        run = lambda *a: subprocess.run(["git", "-C", str(self.repo)] + list(a),
                                        capture_output=True, text=True, check=True)
        run("init", "-b", "main")
        run("config", "user.email", "t@t")
        run("config", "user.name", "t")
        (self.repo / "keep.txt").write_text("fine\n", encoding="utf-8")
        run("add", "keep.txt")
        run("commit", "-m", "init")

    def test_clean_change_commits(self):
        (self.repo / "new.txt").write_text("hello\n", encoding="utf-8")
        result = git_sync.guarded_commit(str(self.repo), "sync: test")
        self.assertEqual(result["blocked"], [])
        self.assertEqual(len(result["committed"]), 1)
        self.assertIn("new.txt", subprocess.run(
            ["git", "-C", str(self.repo), "show", "--name-only", "--format=", "HEAD"],
            capture_output=True, text=True).stdout)

    def test_untracked_file_with_secret_is_blocked(self):
        (self.repo / "leak.txt").write_text(TestPublicationGuard.FAKE_PAT + "\n", encoding="utf-8")
        result = git_sync.guarded_commit(str(self.repo), "sync: test")
        self.assertEqual(len(result["blocked"]), 1)
        self.assertEqual(result["committed"], [])
        # Nothing may reach the index.
        staged = subprocess.run(["git", "-C", str(self.repo), "diff", "--cached", "--name-only"],
                                capture_output=True, text=True).stdout
        self.assertEqual(staged.strip(), "")

    def test_modified_file_with_secret_is_blocked(self):
        (self.repo / "keep.txt").write_text(TestPublicationGuard.FAKE_PAT + "\n", encoding="utf-8")
        result = git_sync.guarded_commit(str(self.repo), "sync: test")
        self.assertEqual(len(result["blocked"]), 1)
        self.assertEqual(result["committed"], [])

    def test_deletion_is_allowed(self):
        (self.repo / "keep.txt").unlink()
        result = git_sync.guarded_commit(str(self.repo), "sync: test")
        self.assertEqual(result["blocked"], [])
        self.assertEqual(len(result["committed"]), 1)

    def test_exclude_keeps_a_path_out_of_the_commit(self):
        (self.repo / "new.txt").write_text("hello\n", encoding="utf-8")
        (self.repo / "draft.md").write_text("wip\n", encoding="utf-8")
        result = git_sync.guarded_commit(str(self.repo), "sync: test", excludes=["*.md"])
        self.assertEqual(result["blocked"], [])
        committed = subprocess.run(
            ["git", "-C", str(self.repo), "show", "--name-only", "--format=", "HEAD"],
            capture_output=True, text=True).stdout
        self.assertIn("new.txt", committed)
        self.assertNotIn("draft.md", committed)

    def _seed_two_dirs(self):
        (self.repo / "foo").mkdir()
        (self.repo / "bar").mkdir()
        (self.repo / "foo" / "notes.md").write_text("foo notes\n", encoding="utf-8")
        (self.repo / "bar" / "other.md").write_text("bar notes\n", encoding="utf-8")

    def _committed_names(self):
        return subprocess.run(
            ["git", "-C", str(self.repo), "show", "--name-only", "--format=", "HEAD"],
            capture_output=True, text=True).stdout

    def test_include_with_trailing_slash_stages_only_that_directory(self):
        self._seed_two_dirs()
        result = git_sync.guarded_commit(str(self.repo), "sync: include", includes=["foo/"])
        self.assertEqual(result["blocked"], [])
        committed = self._committed_names()
        self.assertIn("foo/notes.md", committed)
        self.assertNotIn("bar/other.md", committed)
        # The un-included file is left dirty in the working tree.
        self.assertIn("bar/other.md", git_sync.changed_files_in(str(self.repo)))

    def test_exclude_with_trailing_slash_skips_that_directory(self):
        self._seed_two_dirs()
        result = git_sync.guarded_commit(str(self.repo), "sync: exclude", excludes=["foo/"])
        self.assertEqual(result["blocked"], [])
        committed = self._committed_names()
        self.assertNotIn("foo/notes.md", committed)
        self.assertIn("bar/other.md", committed)

    def test_changed_files_includes_untracked(self):
        (self.repo / "brand_new.txt").write_text("x\n", encoding="utf-8")
        files = git_sync.changed_files_in(str(self.repo))
        self.assertIn("brand_new.txt", files)


class TestCommitMessage(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self.run = lambda *a: subprocess.run(["git", "-C", str(self.repo)] + list(a),
                                             capture_output=True, text=True, check=True)
        self.run("init", "-b", "main")
        self.run("config", "user.email", "t@t")
        self.run("config", "user.name", "t")

    def write(self, rel, text="x\n"):
        target = self.repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    def test_subject_names_scope_and_file(self):
        self.write("glitch-cat/kem-thought/SKILL.md")
        self.run("add", "-A")
        subject = git_sync.staged_subject(str(self.repo))
        self.assertEqual(subject, "chore(kem-thought): SKILL.md (+1/-0)")

    def test_multiple_scopes_appear_in_subject(self):
        self.write("academic/academic-pipeline-v2/SKILL.md")
        self.write("academic/canvas-cli/scripts/gates.py")
        self.write("github-architect/scripts/git_sync.py")
        self.run("add", "-A")
        subject = git_sync.staged_subject(str(self.repo))
        self.assertIn("(academic-pipeline-v2, canvas-cli +1)", subject)
        self.assertIn("3 files", subject)

    def test_no_prose_gets_a_manifest_below_the_subject(self):
        self.write("glitch-cat/kem-thought/SKILL.md")
        self.write("glitch-cat/kem-thought/principles/code-decides.md")
        self.run("add", "-A")
        message = git_sync.compose_message(str(self.repo), None)
        subject, manifest = message.split("\n\n")
        self.assertEqual(subject, git_sync.staged_subject(str(self.repo)))
        self.assertIn("- glitch-cat/kem-thought/SKILL.md (+1/-0)", manifest)
        self.assertIn("- glitch-cat/kem-thought/principles/code-decides.md (+1/-0)", manifest)

    def test_prose_is_the_body_and_needs_no_manifest(self):
        self.write("glitch-cat/kem-thought/SKILL.md")
        self.write("glitch-cat/kem-thought/principles/code-decides.md")
        self.run("add", "-A")
        message = git_sync.compose_message(str(self.repo), "Say why this moved.")
        subject, prose = message.split("\n\n")
        self.assertEqual(subject, git_sync.staged_subject(str(self.repo)))
        self.assertEqual(prose, "Say why this moved.")
        self.assertNotIn("code-decides.md", message)

    def test_subject_stays_within_the_console_width(self):
        for i in range(6):
            self.write(f"hardware/super-long-skill-name-number-{i}/scripts/x.py")
        self.run("add", "-A")
        subject = git_sync.staged_subject(str(self.repo))
        self.assertLessEqual(len(subject), git_sync.MAX_SUBJECT)

    def test_no_staged_changes_falls_back(self):
        self.assertEqual(
            git_sync.staged_subject(str(self.repo)),
            "chore: sync working tree",
        )

    def test_root_files_are_not_labelled_by_a_filename(self):
        self.write("a.txt")
        self.write("pyproject.toml")
        self.run("add", "-A")
        subject = git_sync.staged_subject(str(self.repo))
        self.assertEqual(subject, "chore(root): 2 files (+2/-0)")

    def test_root_scope_is_named_not_parenthesised_twice(self):
        self.write("a.txt")
        self.write("b.txt")
        self.run("add", "-A")
        subject = git_sync.staged_subject(str(self.repo))
        self.assertEqual(subject, "chore(root): 2 files (+2/-0)")

    def test_guarded_commit_derives_when_message_is_omitted(self):
        self.write("glitch-cat/kem-thought/SKILL.md")
        git_sync.guarded_commit(str(self.repo), None)
        subject = self.run("log", "-1", "--format=%s").stdout.strip()
        self.assertEqual(subject, "chore(kem-thought): SKILL.md (+1/-0)")

    def test_plain_prose_becomes_the_body_under_the_auto_subject(self):
        self.write("glitch-cat/kem-thought/SKILL.md")
        git_sync.guarded_commit(str(self.repo), "State the convention so a reader can find it.")
        subject = self.run("log", "-1", "--format=%s").stdout.strip()
        body = self.run("log", "-1", "--format=%b").stdout.strip()
        self.assertEqual(subject, "chore(kem-thought): SKILL.md (+1/-0)")
        self.assertEqual(body, "State the convention so a reader can find it.")

    def test_conventional_message_is_the_commit_verbatim(self):
        self.write("glitch-cat/kem-thought/SKILL.md")
        self.write("glitch-cat/kem-thought/principles/code-decides.md")
        message = (
            "docs(kem-thought,canvas-cli): state the convention\n"
            "\n"
            "Name the principle in the skill body so the gate can cite it."
        )
        git_sync.guarded_commit(str(self.repo), message)
        subject = self.run("log", "-1", "--format=%s").stdout.strip()
        body = self.run("log", "-1", "--format=%b").stdout.strip()
        self.assertEqual(subject, "docs(kem-thought,canvas-cli): state the convention")
        self.assertEqual(body, "Name the principle in the skill body so the gate can cite it.")
        self.assertNotIn("code-decides.md", body)

    def test_body_is_the_prose_and_nothing_else(self):
        self.write("glitch-cat/kem-thought/SKILL.md")
        self.write("glitch-cat/kem-thought/principles/code-decides.md")
        git_sync.guarded_commit(str(self.repo), "State the convention that code decides.")
        body = self.run("log", "-1", "--format=%b").stdout.strip()
        self.assertEqual(body, "State the convention that code decides.")

    def test_secret_in_a_new_directory_is_blocked(self):
        self.write("academic/new-skill/scripts/config.py", TestPublicationGuard.FAKE_PAT + "\n")
        result = git_sync.guarded_commit(str(self.repo), None)
        self.assertEqual(len(result["blocked"]), 1)
        self.assertEqual(result["committed"], [])

    def test_blocked_commit_exits_nonzero(self):
        self.write("academic/new-skill/scripts/config.py", TestPublicationGuard.FAKE_PAT + "\n")
        proc = subprocess.run(
            [sys.executable, str(HERE.parent / "scripts" / "git_sync.py"),
             "guarded-commit", "--repo", str(self.repo)],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 2)
        # The guard actually ran: a secret was reported (and the script was
        # found), rather than Python exiting 2 on a missing file.
        self.assertTrue(
            "Blocked files from staging" in proc.stderr
            or "blocked; nothing committed" in proc.stdout,
            f"guard did not report a blocked file: {proc.stdout!r} {proc.stderr!r}",
        )
        self.assertNotIn("No such file", proc.stderr)


class TestCommitMessageAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        self.run = lambda *a: subprocess.run(["git", "-C", str(self.repo)] + list(a),
                                             capture_output=True, text=True, check=True)
        self.run("init", "-b", "main")
        self.run("config", "user.email", "t@t")
        self.run("config", "user.name", "t")

    def write(self, rel, text="x\n"):
        target = self.repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")

    @staticmethod
    def _record(subject, body, *, files=4, added=20, removed=10, sha="abc1234", is_merge=False):
        return {"sha": sha, "subject": subject, "body": body, "files": files,
                "added": added, "removed": removed, "is_merge": is_merge}

    @staticmethod
    def _block_rules(findings):
        return {f["rule"] for f in findings if f["severity"] == "block"}

    def test_n1_hard_wrapped_body_is_blocked(self):
        body = (
            "Add a centralized find_first_available_in helper to the claw protocol module\n"
            "and reuse it across the overlay character selector and the What's New dialog\n"
            "so every caller agrees on which characters are free."
        )
        rec = self._record("fix(palette): share the free-character lookup helper", body)
        self.assertIn("hard-wrapped", self._block_rules(git_sync.audit_commit_messages([rec])))

    def test_n2_internal_jargon_is_blocked(self):
        body = "Track the pending palette refactor so reviewers can see the current state."
        rec = self._record("chore(palette): wip tweaks to internals", body)
        self.assertIn("internal-jargon", self._block_rules(git_sync.audit_commit_messages([rec])))

    def test_n3_nonconventional_untyped_title_is_blocked(self):
        body = "Describe the dialog resize behaviour people see when opening the window."
        rec = self._record("Fixed the dialog resize thing", body)
        rules = self._block_rules(git_sync.audit_commit_messages([rec]))
        self.assertIn("title-not-conventional", rules)
        self.assertIn("scope-missing", rules)

    def test_n3b_conventional_title_without_scope_is_blocked(self):
        body = "Keep the guard closed while the palette rebuilds its index."
        rec = self._record("fix: keep the guard closed", body)
        self.assertIn("scope-missing", self._block_rules(git_sync.audit_commit_messages([rec])))

    def test_n4_long_message_for_tiny_diff_is_blocked(self):
        body = "\n\n".join([
            "The command palette now normalizes the query before matching entries so that a "
            "user who types without punctuation still finds the right command. Apostrophes "
            "are stripped and hyphens, underscores and dots are treated as spaces in the "
            "normalized form.",
            "This keeps the search index small because normalization happens once when "
            "entries are registered rather than on every keystroke in the palette input. "
            "The same normalized form is used for the ranking step and for the highlight "
            "step.",
            "We also cache the normalized query for the duration of a single palette session "
            "so repeated edits do not re-normalize the full entry set. The cache is "
            "invalidated whenever the entry registry changes on disk.",
            "Finally, the empty-query state now shows the most recently used commands "
            "instead of an alphabetical dump. That list is persisted across sessions and "
            "respects the same scope filters as the regular search results.",
        ])
        self.assertGreater(len(body), 600)
        rec = self._record("docs(protocol): explain the query normalization", body,
                           files=1, added=1, removed=0)
        self.assertIn("message-too-long-for-change",
                      self._block_rules(git_sync.audit_commit_messages([rec])))

    def test_n5_bulleted_manifest_in_author_body_is_blocked(self):
        body = (
            "The files touched by this change are listed below.\n"
            "- glitch-cat/kem-thought/SKILL.md (+1/-0)\n"
            "- glitch-cat/kem-thought/scripts/gates.py (+4/-2)"
        )
        rec = self._record("chore(kem-thought): record the touched files", body)
        rules = self._block_rules(git_sync.audit_commit_messages([rec]))
        self.assertIn("body-has-bullets", rules)
        self.assertIn("body-is-manifest", rules)

    def test_n6_missing_body_is_blocked(self):
        rec = self._record("chore(palette): tidy the palette state", "")
        self.assertIn("body-missing", self._block_rules(git_sync.audit_commit_messages([rec])))

    def test_p1_full_width_example_passes(self):
        rec = self._record(
            "fix(window,terminal,command-palette): guard the palette against a stale index",
            'Strip apostrophes and treat hyphens, underscores and dots as spaces while '
            'normalizing queries, so typing "whats new" matches "What\'s New".',
            files=4, added=40, removed=12,
        )
        self.assertEqual(self._block_rules(git_sync.audit_commit_messages([rec])), set())

    def test_cli_strict_check_exits_nonzero_on_violating_commit(self):
        self.write("palette.py", "x = 1\n")
        self.run("add", "-A")
        self.run("commit", "-m", "chore(palette): wip tweaks to internals",
                 "-m", "Track the pending palette refactor so reviewers can see the state.")
        proc = subprocess.run(
            [sys.executable, str(HERE.parent / "scripts" / "git_sync.py"),
             "check-messages", "--repo", str(self.repo), "--strict"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 1)

    def test_mode2_generated_manifest_is_a_warning_and_passes(self):
        rec = self._record("fix(guard): keep guard closed", "- a/b.py (+1/-0)")
        findings = git_sync.audit_commit_messages([rec])
        manifest = [f for f in findings if f["rule"] == "generated-manifest"]
        self.assertEqual(len(manifest), 1)
        self.assertEqual(manifest[0]["severity"], "warning")
        self.assertEqual([f for f in findings if f["severity"] == "block"], [])
        self.assertTrue(
            git_sync.audit_report([rec], repo=str(self.repo), strict=True)["passed"]
        )

    def test_cli_strict_check_accepts_mode2_warning_only_commit(self):
        self.write("palette.py", "x = 1\n")
        self.run("add", "-A")
        self.run("commit", "-m", "fix(guard): keep guard closed",
                 "-m", "- a/b.py (+1/-0)")
        proc = subprocess.run(
            [sys.executable, str(HERE.parent / "scripts" / "git_sync.py"),
             "check-messages", "--repo", str(self.repo), "--strict"],
            capture_output=True, text=True,
        )
        self.assertEqual(proc.returncode, 0, f"{proc.stdout}\n{proc.stderr}")

    def test_normal_english_words_are_not_internal_jargon(self):
        rec = self._record(
            "docs(guard): describe the changes and updates",
            "Cover the cleanup of temp files so reviewers understand the work.",
        )
        rules = self._block_rules(git_sync.audit_commit_messages([rec]))
        self.assertNotIn("internal-jargon", rules)
        self.assertEqual(rules, set())

    def test_jargon_words_are_still_blocked(self):
        for word in ("wip", "todo", "asdf"):
            with self.subTest(word=word):
                rec = self._record(
                    f"chore(guard): {word} tweaks",
                    "Describe the work so reviewers can follow along.",
                )
                self.assertIn(
                    "internal-jargon", self._block_rules(git_sync.audit_commit_messages([rec]))
                )

    def _audit_json(self, subject, body):
        self.write("note.txt", "x = 1\n")
        self.run("add", "-A")
        self.run("commit", "-m", subject, "-m", body)
        buf = io.StringIO()
        with patch("sys.stdout", buf), \
             patch.object(github_architect, "check_gh_status", return_value=(True, "testuser")):
            ok = github_architect.cmd_audit(
                self.repo, check_commits=True, strict=True, as_json=True
            )
        data = json.loads(buf.getvalue())
        return ok, data

    def test_cmd_audit_fails_on_block_commit(self):
        ok, data = self._audit_json(
            "chore(guard): wip tweaks",
            "Track the pending palette refactor so reviewers can see the state.",
        )
        self.assertFalse(ok)
        self.assertFalse(data["commits"]["passed"])
        expected = git_sync.audit_report(
            git_sync.read_commit_records(str(self.repo)),
            repo=str(self.repo), strict=True,
        )
        self.assertEqual(data["commits"], expected)

    def test_cmd_audit_passes_on_mode2_warning_commit(self):
        ok, data = self._audit_json(
            "fix(guard): keep guard closed", "- a/b.py (+1/-0)"
        )
        self.assertTrue(ok)
        self.assertTrue(data["commits"]["passed"])
        expected = git_sync.audit_report(
            git_sync.read_commit_records(str(self.repo)),
            repo=str(self.repo), strict=True,
        )
        self.assertEqual(data["commits"], expected)


class TestGate(unittest.TestCase):
    def test_gate_runs_on_a_python_project_without_crashing(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "pyproject.toml").write_text("[tool.pytest.ini_options]\n", encoding="utf-8")
        previous = Path.cwd()
        os.chdir(tmp)
        self.addCleanup(os.chdir, previous)
        self.assertEqual(git_sync.stage4_gate(), [])


class TestProtectedPush(unittest.TestCase):
    def test_refuses_a_protected_branch_without_a_tty(self):
        with patch("sys.stdin") as fake_stdin:
            fake_stdin.isatty.return_value = False
            with self.assertRaises(SystemExit):
                git_sync.stage6_push("main", has_upstream=True, auto_yes=False)


class TestCommitComposition(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        run = lambda *a: subprocess.run(["git", "-C", str(self.repo)] + list(a),
                                        capture_output=True, text=True, check=True)
        run("init", "-b", "main")
        run("config", "user.email", "t@t")
        run("config", "user.name", "t")
        (self.repo / "glitch-cat" / "kem-thought").mkdir(parents=True)
        (self.repo / "glitch-cat" / "kem-thought" / "SKILL.md").write_text("x\n", encoding="utf-8")
        run("add", "-A")

    def test_single_file_prose_has_no_manifest(self):
        message = git_sync.compose_message(str(self.repo), "Say why this moved.")
        self.assertEqual(message, "chore(kem-thought): SKILL.md (+1/-0)\n\nSay why this moved.")

    def test_a_conventional_message_replaces_the_generated_subject(self):
        message = git_sync.compose_message(
            str(self.repo),
            "feat(kem-thought): say why this moved\n\nThe diff line would only repeat it.",
        )
        self.assertEqual(
            message,
            "feat(kem-thought): say why this moved\n\nThe diff line would only repeat it.",
        )

    def test_a_conventional_subject_without_a_body_gets_the_manifest(self):
        message = git_sync.compose_message(str(self.repo), "fix(github-architect): keep the guard closed")
        header, body = message.split("\n\n")
        self.assertEqual(header, "fix(github-architect): keep the guard closed")
        self.assertIn("glitch-cat/kem-thought/SKILL.md", body)

    def test_prose_that_only_mentions_a_colon_is_not_a_header(self):
        message = git_sync.compose_message(str(self.repo), "Note: the gate now runs first.")
        self.assertTrue(message.startswith("chore(kem-thought): SKILL.md (+1/-0)\n\n"))

    def test_single_file_without_prose_still_gets_a_body(self):
        message = git_sync.compose_message(str(self.repo), None)
        subject, body = message.split("\n\n")
        self.assertEqual(subject, git_sync.staged_subject(str(self.repo)))
        self.assertIn("glitch-cat/kem-thought/SKILL.md", body)

    def test_bodyless_commit_is_flagged_before_push(self):
        git_sync.run_git(["commit", "--allow-empty", "-m", "chore: no description here"], cwd=str(self.repo))
        missing = git_sync.commits_without_body(repo=str(self.repo))
        self.assertEqual([s for _, s in missing], ["chore: no description here"])

    def test_merge_commits_are_exempt_from_the_body_rule(self):
        git_sync.run_git(["commit", "--allow-empty", "-m", "Merge branch 'topic'"], cwd=str(self.repo))
        self.assertEqual(git_sync.commits_without_body(repo=str(self.repo)), [])


SCRIPT = HERE.parent / "scripts" / "github_architect.py"


class TestPublishGuard(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_cmd_publish_refuses_untracked_secret_in_fresh_dir(self):
        target = self.tmp / "fresh"
        target.mkdir()
        (target / "leak.txt").write_text(TestPublicationGuard.FAKE_PAT + "\n", encoding="utf-8")
        with patch.object(github_architect, "check_gh_status", return_value=(True, "testuser")), \
             patch.object(github_architect, "ensure_git_identity", return_value=("t", "t@t")):
            ok = github_architect.cmd_publish(target, "fresh-repo")
        self.assertFalse(ok)
        self.assertFalse((target / ".git" / "refs" / "heads" / "main").exists())
        staged = subprocess.run(
            ["git", "-C", str(target), "diff", "--cached", "--name-only"],
            capture_output=True, text=True,
        ).stdout
        self.assertEqual(staged.strip(), "")

    def test_publish_subprocess_exits_nonzero_on_untracked_secret(self):
        target = self.tmp / "fresh-cli"
        target.mkdir()
        (target / "leak.txt").write_text(TestPublicationGuard.FAKE_PAT + "\n", encoding="utf-8")
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "publish", str(target)],
            capture_output=True, text=True,
        )
        self.assertNotEqual(proc.returncode, 0, f"{proc.stdout}\n{proc.stderr}")


class TestArchitectCli(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.source = self.tmp / "source"
        self.source.mkdir()
        (self.source / ".env").write_text("TOKEN=x\n", encoding="utf-8")

    def _guard(self, *extra):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "guard", "--source", str(self.source), *extra],
            capture_output=True, text=True,
        )

    def test_guard_accepts_exclude_and_exits_zero_when_env_excluded(self):
        proc = self._guard("--exclude", ".env")
        self.assertEqual(proc.returncode, 0, f"{proc.stdout}\n{proc.stderr}")

    def test_guard_exits_two_without_exclude(self):
        proc = self._guard()
        self.assertEqual(proc.returncode, 2, f"{proc.stdout}\n{proc.stderr}")

    def test_insights_command_is_removed(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "insights"], capture_output=True, text=True
        )
        self.assertEqual(proc.returncode, 2)
        self.assertIn("invalid choice", proc.stderr)


class TestFleetConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_discover_fleet_repos_loads_existing_git_repos(self):
        repo = self.tmp / "real-repo"
        repo.mkdir()
        subprocess.run(["git", "-C", str(repo), "init", "-b", "main"],
                       capture_output=True, text=True, check=True)
        plain = self.tmp / "plain-dir"
        plain.mkdir()
        config = self.tmp / "fleet.json"
        config.write_text(json.dumps({"repos": [
            {"name": "real-repo", "path": str(repo), "description": "a git checkout"},
            {"name": "plain-dir", "path": str(plain)},
        ]}), encoding="utf-8")

        fleet = github_architect.discover_fleet_repos(config)
        self.assertEqual(len(fleet), 1)
        self.assertEqual(fleet[0]["name"], "real-repo")
        self.assertEqual(fleet[0]["path"], repo.resolve())
        self.assertEqual(fleet[0]["description"], "a git checkout")

    def test_discover_fleet_repos_empty_for_missing_config(self):
        self.assertEqual(github_architect.discover_fleet_repos(self.tmp / "missing.json"), [])


class TestScaffoldNonDestructive(unittest.TestCase):
    def test_scaffold_preserves_existing_readme_with_a_skill(self):
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        skill = tmp / "my-skill"
        skill.mkdir()
        (skill / "SKILL.md").write_text("---\nname: s\ndescription: d\n---\n\nbody\n", encoding="utf-8")
        readme = tmp / "README.md"
        custom = "# My own README\n\nHand written, do not overwrite.\n"
        readme.write_text(custom, encoding="utf-8")

        with patch.object(github_architect, "ensure_git_identity", return_value=("t", "t@t")):
            github_architect.cmd_scaffold(tmp, "repo")

        self.assertEqual(readme.read_text(encoding="utf-8"), custom)


if __name__ == "__main__":
    unittest.main()
