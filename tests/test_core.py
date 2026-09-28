import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from file_integrity_timeline import core


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.first = self.base / "first"
        self.second = self.base / "second"
        self.first.mkdir()
        self.second.mkdir()
        self.project = self.base / "archive.fit"

    def make_project(self):
        core.create_project(self.project, [("First", str(self.first)), ("Second", str(self.second))])

    def test_full_hash_detects_change_even_with_same_size_and_mtime(self):
        file = self.first / "photo.txt"
        file.write_bytes(b"AAAA")
        self.make_project()
        baseline = core.scan_project(self.project)
        original = file.stat()
        file.write_bytes(b"BBBB")
        import os

        os.utime(file, ns=(original.st_atime_ns, original.st_mtime_ns))
        result = core.scan_project(self.project)
        self.assertEqual((result["added"], result["missing"], result["changed"]), (0, 0, 1))
        self.assertEqual(core.current_baseline_id(self.project), baseline["id"])
        self.assertEqual(core.list_changes(self.project, result["id"])[0]["change"], "changed")

    def test_add_missing_and_unchanged_across_roots(self):
        (self.first / "gone.txt").write_text("gone")
        (self.second / "same.txt").write_text("same")
        self.make_project()
        core.scan_project(self.project)
        (self.first / "gone.txt").unlink()
        (self.first / "new.txt").write_text("new")
        result = core.scan_project(self.project)
        self.assertEqual((result["added"], result["missing"], result["changed"]), (1, 1, 0))
        self.assertEqual(len(core.list_changes(self.project, result["id"])), 2)
        self.assertEqual((self.second / "same.txt").read_text(), "same")

    def test_read_error_never_produces_missing_verdict(self):
        file = self.first / "unreadable.txt"
        file.write_text("original")
        self.make_project()
        core.scan_project(self.project)
        original_hash = core._hash_stable

        def fail_one(path, cancel):
            if path.name == "unreadable.txt":
                raise PermissionError("permission denied")
            return original_hash(path, cancel)

        with patch.object(core, "_hash_stable", side_effect=fail_one):
            result = core.scan_project(self.project)
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(result["missing"], 0)
        self.assertEqual(result["error_count"], 1)
        report = core.export_html(self.project, result["id"], self.base / "report.html")
        self.assertIn("No missing-file or integrity verdict", report.read_text(encoding="utf-8"))

    def test_cancelled_scan_cannot_be_trusted(self):
        (self.first / "file.txt").write_text("data")
        self.make_project()
        baseline = core.scan_project(self.project)
        stop = threading.Event()
        stop.set()
        result = core.scan_project(self.project, cancel=stop)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(core.current_baseline_id(self.project), baseline["id"])
        with self.assertRaises(ValueError):
            core.trust_scan(self.project, result["id"])

    def test_remap_preserves_relative_comparison(self):
        (self.first / "same.txt").write_text("bytes")
        self.make_project()
        core.scan_project(self.project)
        moved = self.base / "moved"
        self.first.rename(moved)
        core.remap_root(self.project, 1, moved)
        result = core.scan_project(self.project)
        self.assertEqual((result["added"], result["missing"], result["changed"]), (0, 0, 0))

    def test_trust_is_explicit_and_history_remains(self):
        file = self.first / "file.txt"
        file.write_text("one")
        self.make_project()
        first = core.scan_project(self.project)
        file.write_text("two")
        second = core.scan_project(self.project)
        self.assertEqual(second["changed"], 1)
        core.trust_scan(self.project, second["id"])
        third = core.scan_project(self.project)
        self.assertEqual(third["changed"], 0)
        self.assertEqual(core.current_baseline_id(self.project), second["id"])
        old_change = core.list_changes(self.project, second["id"])[0]
        self.assertNotEqual(old_change["before_hash"], old_change["after_hash"])
        self.assertEqual(core.list_scans(self.project)[-1]["id"], first["id"])

    def test_paths_are_escaped_and_reports_stay_outside_roots(self):
        self.make_project()
        core.scan_project(self.project)
        (self.first / "&unsafe.txt").write_text("safe")
        result = core.scan_project(self.project)
        with self.assertRaises(ValueError):
            core.export_html(self.project, result["id"], self.first / "report.html")
        report = core.export_html(self.project, result["id"], self.base / "report.html")
        contents = report.read_text(encoding="utf-8")
        self.assertIn("&amp;unsafe.txt", contents)
        self.assertNotIn("<td><code>&unsafe.txt", contents)

    def test_rejects_project_inside_root_and_overlapping_roots(self):
        with self.assertRaises(ValueError):
            core.create_project(self.first / "inside.fit", [("First", str(self.first))])
        nested = self.first / "nested"
        nested.mkdir()
        with self.assertRaises(ValueError):
            core.create_project(self.project, [("First", str(self.first)), ("Nested", str(nested))])


if __name__ == "__main__":
    unittest.main()
