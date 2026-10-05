"""Integration checks against real temporary Git repositories."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / "versioning.py"


class VersioningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "-q")
        self.write("VERSION", "0.1.0\n")
        self.modules = [{"id": "chat", "path": "modules/chat"},
                        {"id": "memory", "path": "modules/memory"}]
        self.config()
        for module in self.modules:
            self.write(module["path"] + "/VERSION", "0.1.0\n")
            self.write(module["path"] + "/example.txt", "initial\n")
        self.write("README.md", "initial\n")
        self.commit()

    def write(self, path, text):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(text, encoding="utf-8")

    def config(self):
        self.write("MODULES.json", json.dumps({"schema_version": 1, "modules": self.modules}))

    def git(self, *args):
        return subprocess.run(["git", "-C", str(self.root), *args], check=True,
                              capture_output=True, text=True).stdout.strip()

    def commit(self):
        self.git("add", "-A")
        self.git("-c", "user.name=Version tests", "-c", "user.email=tests@example.invalid",
                 "commit", "-qm", "fixture")
        return self.git("rev-parse", "HEAD")

    def cli(self, *args, success=True):
        result = subprocess.run([sys.executable, str(SCRIPT), "--root", str(self.root), *args],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0 if success else 1, result.stdout + result.stderr)
        return json.loads(result.stdout) if success else result.stderr

    def test_document_change_requires_only_project_bump(self):
        self.write("README.md", "changed\n")
        self.assertIn("project", self.cli("check", success=False))
        result = self.cli("bump")
        self.assertEqual(result["project"]["version"], "0.1.1")
        self.assertEqual(result["chat"]["version"], "0.1.0")
        self.cli("check")

    def test_new_module_file_and_repeat_bump(self):
        self.write("modules/chat/new file.txt", "new\n")
        result = self.cli("bump")
        self.assertEqual(result["chat"]["version"], "0.1.1")
        self.assertEqual(result["memory"]["version"], "0.1.0")
        self.assertEqual(result, self.cli("bump"))
        self.cli("check")

    def test_staged_change_and_dependent_module(self):
        self.write("modules/chat/example.txt", "changed\n")
        self.git("add", "modules/chat/example.txt")
        result = self.cli("bump", "--module", "memory")
        self.assertEqual(result["chat"]["version"], "0.1.1")
        self.assertEqual(result["memory"]["version"], "0.1.1")
        self.cli("check")

    def test_deletion_requires_module_bump(self):
        (self.root / "modules/chat/example.txt").unlink()
        self.write("VERSION", "0.1.1\n")
        self.assertIn("chat", self.cli("check", success=False))
        self.cli("bump")
        self.cli("check")

    def test_move_bumps_source_and_destination(self):
        self.git("mv", "modules/chat/example.txt", "modules/memory/moved.txt")
        result = self.cli("bump")
        self.assertEqual(result["chat"]["version"], "0.1.1")
        self.assertEqual(result["memory"]["version"], "0.1.1")

    def test_new_module_keeps_initial_version(self):
        self.modules.append({"id": "documents", "path": "modules/documents"})
        self.config()
        self.write("modules/documents/VERSION", "0.1.0\n")
        self.write("modules/documents/example.txt", "new module\n")
        result = self.cli("bump")
        self.assertEqual(result["documents"]["version"], "0.1.0")
        self.cli("check")

    def test_unregister_requires_removing_files(self):
        self.modules.pop()
        self.config()
        self.assertIn("cannot unregister", self.cli("bump", success=False))
        shutil.rmtree(self.root / "modules/memory")
        self.cli("bump")
        self.cli("check")

    def test_invalid_and_decreasing_versions_do_not_write(self):
        for invalid in ("0.01.0", "v0.1.0", "0.0.9"):
            with self.subTest(version=invalid):
                self.write("modules/chat/VERSION", invalid)
                self.cli("bump", success=False)
                self.assertEqual((self.root / "VERSION").read_text(), "0.1.0\n")

    def test_invalid_registry_and_missing_version(self):
        self.modules[0]["path"] = "../outside"
        self.config()
        self.cli("show", success=False)
        self.modules[0]["path"] = "modules/chat"
        self.config()
        (self.root / "modules/chat/VERSION").unlink()
        self.cli("check", success=False)

    def test_each_commit_catches_unversioned_intermediate_commit(self):
        base = self.git("rev-parse", "HEAD")
        self.write("README.md", "changed\n")
        self.commit()
        self.write("VERSION", "0.1.1\n")
        target = self.commit()
        self.cli("check", "--base", base, "--target", target)
        self.cli("check", "--base", base, "--target", target, "--each-commit", success=False)

    def test_committed_target_ignores_working_changes(self):
        base = self.git("rev-parse", "HEAD")
        self.write("modules/chat/example.txt", "changed\n")
        self.cli("bump")
        target = self.commit()
        self.write("modules/memory/example.txt", "not committed\n")
        self.cli("check", "--base", base, "--target", target, "--each-commit")

    def test_show_works_without_git_and_handles_crlf(self):
        shutil.rmtree(self.root / ".git")
        (self.root / "VERSION").write_bytes(b"0.1.0\r\n")
        self.assertEqual(self.cli("show")["project"]["version"], "0.1.0")

    def test_bootstrap_after_unversioned_history(self):
        (self.root / "VERSION").unlink()
        (self.root / "MODULES.json").unlink()
        self.commit()
        self.write("VERSION", "0.1.1\n")
        self.config()
        self.cli("check")


if __name__ == "__main__":
    unittest.main()
