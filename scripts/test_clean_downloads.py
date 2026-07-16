import unittest
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

    def test_ac01_files_sorted_into_category_dirs(self):
        self.touch("a.jpg")
        self.touch("b.pdf")
        self.touch("c.zip")
        self.assertEqual(run(self.target), 0)
        self.assertTrue((self.target / "Images" / "a.jpg").is_file())
        self.assertTrue((self.target / "Documents" / "b.pdf").is_file())
        self.assertTrue((self.target / "Archives" / "c.zip").is_file())
        for name in ("a.jpg", "b.pdf", "c.zip"):
            self.assertFalse((self.target / name).exists())

    def test_ac02_unknown_and_no_extension_go_to_others(self):
        self.touch("README")
        self.touch("foo.xyz")
        self.assertEqual(run(self.target), 0)
        self.assertTrue((self.target / "Others" / "README").is_file())
        self.assertTrue((self.target / "Others" / "foo.xyz").is_file())

    def test_ac07_hidden_files_stay_put(self):
        self.touch(".secret")
        self.assertEqual(run(self.target), 0)
        self.assertTrue((self.target / ".secret").is_file())

    def test_ac03_name_clash_gets_suffix_1(self):
        self.touch("Documents/report.pdf", content="old")
        self.touch("report.pdf", content="new")
        self.assertEqual(run(self.target), 0)
        self.assertEqual((self.target / "Documents" / "report.pdf").read_text(), "old")
        self.assertEqual((self.target / "Documents" / "report_1.pdf").read_text(), "new")

    def test_ac04_suffix_increments_to_next_free_slot(self):
        self.touch("Documents/report.pdf")
        self.touch("Documents/report_1.pdf")
        self.touch("report.pdf", content="new")
        self.assertEqual(run(self.target), 0)
        self.assertEqual((self.target / "Documents" / "report_2.pdf").read_text(), "new")

    def test_batch_collision_reserved_slots_never_overwrite(self):
        self.touch("Documents/report.pdf", content="old")
        self.touch("report.pdf", content="a")
        self.touch("report_1.pdf", content="b")
        self.assertEqual(run(self.target), 0)
        docs = self.target / "Documents"
        self.assertEqual((docs / "report.pdf").read_text(), "old")
        contents = sorted(p.read_text() for p in docs.iterdir())
        self.assertEqual(contents, ["a", "b", "old"])
        self.assertEqual(len(list(docs.iterdir())), 3)


if __name__ == "__main__":
    unittest.main()
