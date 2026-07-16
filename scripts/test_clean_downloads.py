import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from clean_downloads import run


class CleanDownloadsTest(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.target = Path(tmp.name)

    def touch(self, relpath, content="x"):
        p = self.target / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return p

    def tree(self):
        return sorted(str(p.relative_to(self.target)) for p in self.target.rglob("*"))

    def run_silenced(self, *args, **kwargs):
        with redirect_stdout(StringIO()):
            return run(*args, **kwargs)

    def test_ac01_files_sorted_into_category_dirs(self):
        self.touch("a.jpg")
        self.touch("b.pdf")
        self.touch("c.zip")
        self.assertEqual(self.run_silenced(self.target), 0)
        self.assertTrue((self.target / "Images" / "a.jpg").is_file())
        self.assertTrue((self.target / "Documents" / "b.pdf").is_file())
        self.assertTrue((self.target / "Archives" / "c.zip").is_file())
        for name in ("a.jpg", "b.pdf", "c.zip"):
            self.assertFalse((self.target / name).exists())

    def test_ac02_unknown_and_no_extension_go_to_others(self):
        self.touch("README")
        self.touch("foo.xyz")
        self.assertEqual(self.run_silenced(self.target), 0)
        self.assertTrue((self.target / "Others" / "README").is_file())
        self.assertTrue((self.target / "Others" / "foo.xyz").is_file())

    def test_ac07_hidden_files_stay_put(self):
        self.touch(".secret")
        self.assertEqual(self.run_silenced(self.target), 0)
        self.assertTrue((self.target / ".secret").is_file())

    def test_ac03_name_clash_gets_suffix_1(self):
        self.touch("Documents/report.pdf", content="old")
        self.touch("report.pdf", content="new")
        self.assertEqual(self.run_silenced(self.target), 0)
        self.assertEqual((self.target / "Documents" / "report.pdf").read_text(), "old")
        self.assertEqual((self.target / "Documents" / "report_1.pdf").read_text(), "new")

    def test_ac04_suffix_increments_to_next_free_slot(self):
        self.touch("Documents/report.pdf")
        self.touch("Documents/report_1.pdf")
        self.touch("report.pdf", content="new")
        self.assertEqual(self.run_silenced(self.target), 0)
        self.assertEqual((self.target / "Documents" / "report_2.pdf").read_text(), "new")

    def test_batch_collision_reserved_slots_never_overwrite(self):
        self.touch("Documents/report.pdf", content="old")
        self.touch("report.pdf", content="a")
        self.touch("report_1.pdf", content="b")
        self.assertEqual(self.run_silenced(self.target), 0)
        docs = self.target / "Documents"
        self.assertEqual((docs / "report.pdf").read_text(), "old")
        contents = sorted(p.read_text() for p in docs.iterdir())
        self.assertEqual(contents, ["a", "b", "old"])
        self.assertEqual(len(list(docs.iterdir())), 3)

    def test_category_name_blocker_resolved_in_single_run(self):
        self.touch("Videos")  # 无扩展名普通文件,占住类别目录名
        self.touch("A.mp4")
        self.assertEqual(self.run_silenced(self.target), 0)
        self.assertTrue((self.target / "Videos").is_dir())
        self.assertTrue((self.target / "Videos" / "A.mp4").is_file())
        self.assertTrue((self.target / "Others" / "Videos").is_file())

    def test_self_category_blocker_converges(self):
        self.touch("Others")  # 归类目标恰为 Others/Others,自己堵自己
        self.assertEqual(self.run_silenced(self.target), 0)
        self.assertTrue((self.target / "Others" / "Others").is_file())

    def test_dangling_symlink_dest_slot_treated_as_occupied(self):
        docs = self.target / "Documents"
        docs.mkdir()
        (docs / "report.pdf").symlink_to(self.target / "gone.pdf")  # 悬空链接
        self.touch("report.pdf", content="new")
        self.assertEqual(self.run_silenced(self.target), 0)
        self.assertTrue((docs / "report.pdf").is_symlink())  # 原目录项未被替换
        self.assertEqual((docs / "report_1.pdf").read_text(), "new")

    def test_ac05_empty_dirs_removed_including_nested(self):
        (self.target / "empty").mkdir()
        (self.target / "a" / "b").mkdir(parents=True)
        self.assertEqual(self.run_silenced(self.target), 0)
        self.assertFalse((self.target / "empty").exists())
        self.assertFalse((self.target / "a").exists())

    def test_ac06_nonempty_subdir_left_untouched(self):
        self.touch("keep/x.txt")
        self.assertEqual(self.run_silenced(self.target), 0)
        self.assertTrue((self.target / "keep" / "x.txt").is_file())

    def test_ac08_dry_run_prints_plan_and_changes_nothing(self):
        self.touch("a.jpg")
        (self.target / "empty").mkdir()
        before = self.tree()
        out = StringIO()
        with redirect_stdout(out):
            rc = run(self.target, dry_run=True)
        self.assertEqual(rc, 0)
        self.assertEqual(self.tree(), before)
        lines = out.getvalue().splitlines()
        self.assertIn("[dry-run] move a.jpg -> Images/a.jpg", lines)
        self.assertIn("[dry-run] rmdir empty/", lines)

    def test_ac09_missing_target_errors_with_exit_1(self):
        err = StringIO()
        with redirect_stderr(err):
            rc = run(self.target / "nope")
        self.assertEqual(rc, 1)
        self.assertIn("not a directory", err.getvalue())

    def test_dry_run_keeps_planned_destination_dirs(self):
        (self.target / "Images").mkdir()
        self.touch("a.jpg")
        out = StringIO()
        with redirect_stdout(out):
            rc = run(self.target, dry_run=True)
        self.assertEqual(rc, 0)
        self.assertNotIn("rmdir Images/", out.getvalue())
        self.assertTrue((self.target / "Images").is_dir())

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0,
                     "root 不受权限位约束,chmod 000 无法制造不可读目录")
    def test_unreadable_subdir_warns_and_continues(self):
        locked = self.target / "locked"
        locked.mkdir()
        (self.target / "empty").mkdir()
        locked.chmod(0o000)
        self.addCleanup(lambda: locked.chmod(0o755))
        err = StringIO()
        with redirect_stderr(err):
            rc = self.run_silenced(self.target)
        self.assertEqual(rc, 1)
        self.assertIn("warning", err.getvalue())
        self.assertFalse((self.target / "empty").exists())


if __name__ == "__main__":
    unittest.main()
