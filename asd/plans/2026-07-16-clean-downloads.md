# clean_downloads 下载目录清理脚本 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 `scripts/clean_downloads.py`:对目标目录顶层文件按扩展名归档到英文类别目录,重名加 `_N` 序号,收尾自底向上删除空子目录。

**Architecture:** 单文件脚本,纯函数(categorize / unique_dest / plan_moves / remove_empty_dirs)+ 薄 `run()`/`main()`。测试直接调用 `run()` 在临时目录里做端到端验证,不起子进程。

**Tech Stack:** Python 3 标准库(pathlib / shutil / argparse / unittest / tempfile),零第三方依赖。

**Spec:** `asd/specs/2026-07-16-clean-downloads-design.md`

## Global Constraints

- 零第三方依赖,只用 Python 3 标准库。
- 类别目录名固定为英文:Images / Documents / Videos / Audio / Archives / Installers / Code / Others;未知与无扩展名归 Others。
- 重名序号格式固定 `name_1.ext`、`name_2.ext`…,绝不覆盖已有文件。
- 只处理目标目录顶层文件;隐藏文件(`.` 开头)跳过;子目录内容不动,仅删完全空的子目录(含嵌套空壳)。
- 目录参数缺省 `~/Downloads`;`--dry-run` 必须零改动。
- 测试文件放 `scripts/test_clean_downloads.py`(manifest 约定 `test_dir: scripts`),AC 测试命名 `def test_ac{nn}_<slug>`。
- 测试命令:`python3 -m unittest discover -s scripts -p "test_*.py"`。
- Commit message 用简体中文。
- 声称完成前必须 `bash asd/kernel/delivery/pipeline.sh asd/specs/2026-07-16-clean-downloads-design.md` 全绿。

---

### Task 1: 基础归档 — categorize + plan_moves + run(AC-01 / AC-02 / AC-07)

**Files:**
- Create: `scripts/clean_downloads.py`
- Test: `scripts/test_clean_downloads.py`

**Interfaces:**
- Consumes: 无(首个任务)。
- Produces:
  - `categorize(filename: str) -> str`:文件名 → 类别目录名(str)。
  - `plan_moves(target: Path) -> list[tuple[Path, Path]]`:纯规划,返回 (src, dst) 列表,不动文件系统。
  - `run(target: Path) -> int`:执行归档,返回退出码(Task 4 会扩展为 `run(target, dry_run=False)`)。
  - 测试基类 `CleanDownloadsTest`,含 `self.target`(临时目录 Path)、`touch(relpath, content="x")`、`tree()` 辅助方法。

- [ ] **Step 1: 写失败测试**

创建 `scripts/test_clean_downloads.py`:

```python
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


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest discover -s scripts -p "test_*.py" -v`
Expected: ERROR,`ModuleNotFoundError: No module named 'clean_downloads'`

- [ ] **Step 3: 写最小实现**

创建 `scripts/clean_downloads.py`:

```python
#!/usr/bin/env python3
"""Sort top-level files of a downloads directory into category folders by
extension, suffix duplicates with _N, then remove empty subdirectories."""

import shutil
from pathlib import Path

CATEGORIES = {
    "Images": {"jpg", "jpeg", "png", "gif", "webp", "heic", "svg", "bmp", "tiff"},
    "Documents": {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
                  "txt", "md", "csv", "rtf", "epub"},
    "Videos": {"mp4", "mov", "mkv", "avi", "wmv", "flv", "webm"},
    "Audio": {"mp3", "wav", "flac", "m4a", "aac", "ogg"},
    "Archives": {"zip", "rar", "7z", "tar", "gz", "bz2", "xz"},
    "Installers": {"dmg", "pkg", "exe", "msi", "apk", "deb", "rpm"},
    "Code": {"py", "js", "ts", "sh", "json", "yaml", "yml", "html", "css", "sql"},
}
DEFAULT_CATEGORY = "Others"


def categorize(filename):
    ext = Path(filename).suffix.lstrip(".").lower()
    if ext:
        for category, exts in CATEGORIES.items():
            if ext in exts:
                return category
    return DEFAULT_CATEGORY


def plan_moves(target):
    moves = []
    for entry in sorted(target.iterdir()):
        if entry.name.startswith(".") or (entry.is_dir() and not entry.is_symlink()):
            continue
        moves.append((entry, target / categorize(entry.name) / entry.name))
    return moves


def run(target):
    for src, dst in plan_moves(target):
        dst.parent.mkdir(exist_ok=True)
        shutil.move(str(src), str(dst))
        print(f"move {src.name} -> {dst.relative_to(target)}")
    return 0
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m unittest discover -s scripts -p "test_*.py" -v`
Expected: PASS,3 tests OK

- [ ] **Step 5: 提交**

```bash
git add scripts/clean_downloads.py scripts/test_clean_downloads.py
git commit -m "feat(scripts): clean_downloads 基础归档(AC-01/02/07)"
```

---

### Task 2: 重名序号 — unique_dest(AC-03 / AC-04)

**Files:**
- Modify: `scripts/clean_downloads.py`(新增 `unique_dest`,改写 `plan_moves`)
- Test: `scripts/test_clean_downloads.py`

**Interfaces:**
- Consumes: Task 1 的 `plan_moves(target)`、`run(target)`、测试基类 `CleanDownloadsTest` 及 `touch()`。
- Produces: `unique_dest(dest_dir: Path, filename: str, reserved=frozenset()) -> Path` —
  返回 dest_dir 下第一个不与磁盘文件、也不与 reserved 集合冲突的路径(`name.ext` → `name_1.ext` → `name_2.ext`…)。

- [ ] **Step 1: 写失败测试**

在 `CleanDownloadsTest` 类中追加:

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest discover -s scripts -p "test_*.py" -v`
Expected: test_ac03 / test_ac04 FAIL(shutil.move 会把顶层 report.pdf 覆盖进 Documents/report.pdf,`read_text()` 断言不匹配)

- [ ] **Step 3: 写最小实现**

在 `categorize` 之后新增 `unique_dest`,并整体替换 `plan_moves`:

```python
def unique_dest(dest_dir, filename, reserved=frozenset()):
    stem, suffix = Path(filename).stem, Path(filename).suffix
    candidate = dest_dir / filename
    n = 0
    while candidate.exists() or candidate in reserved:
        n += 1
        candidate = dest_dir / f"{stem}_{n}{suffix}"
    return candidate


def plan_moves(target):
    moves = []
    reserved = set()
    for entry in sorted(target.iterdir()):
        if entry.name.startswith(".") or (entry.is_dir() and not entry.is_symlink()):
            continue
        dst = unique_dest(target / categorize(entry.name), entry.name, reserved)
        reserved.add(dst)
        moves.append((entry, dst))
    return moves
```

(`reserved` 防止同一批规划中两个 dst 撞到同一路径,规划期间文件尚未落盘,仅 `exists()` 判不出来。)

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m unittest discover -s scripts -p "test_*.py" -v`
Expected: PASS,5 tests OK

- [ ] **Step 5: 提交**

```bash
git add scripts/clean_downloads.py scripts/test_clean_downloads.py
git commit -m "feat(scripts): clean_downloads 重名序号避让(AC-03/04)"
```

---

### Task 3: 空目录清理 — remove_empty_dirs(AC-05 / AC-06)

**Files:**
- Modify: `scripts/clean_downloads.py`(新增 `remove_empty_dirs`,`run` 末尾调用)
- Test: `scripts/test_clean_downloads.py`

**Interfaces:**
- Consumes: Task 1 的 `run(target)`、测试基类。
- Produces: `remove_empty_dirs(target: Path, dry_run=False) -> list[Path]` —
  自底向上删除 target 内所有空子目录(含嵌套空壳),返回被删(或 dry-run 时将删)的目录列表;target 本身不删。

- [ ] **Step 1: 写失败测试**

在 `CleanDownloadsTest` 类中追加:

```python
    def test_ac05_empty_dirs_removed_including_nested(self):
        (self.target / "empty").mkdir()
        (self.target / "a" / "b").mkdir(parents=True)
        self.assertEqual(run(self.target), 0)
        self.assertFalse((self.target / "empty").exists())
        self.assertFalse((self.target / "a").exists())

    def test_ac06_nonempty_subdir_left_untouched(self):
        self.touch("keep/x.txt")
        self.assertEqual(run(self.target), 0)
        self.assertTrue((self.target / "keep" / "x.txt").is_file())
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest discover -s scripts -p "test_*.py" -v`
Expected: test_ac05 FAIL(空目录仍存在);test_ac06 PASS(现状本来就不动子目录,保留它作回归防护)

- [ ] **Step 3: 写最小实现**

新增 `remove_empty_dirs`,并在 `run` 的 move 循环之后调用:

```python
def remove_empty_dirs(target, dry_run=False):
    removed = []
    subdirs = [p for p in target.rglob("*") if p.is_dir() and not p.is_symlink()]
    for d in sorted(subdirs, key=lambda p: len(p.parts), reverse=True):
        children = [c for c in d.iterdir() if c not in removed]
        if children:
            continue
        removed.append(d)
        if not dry_run:
            d.rmdir()
    return removed
```

`run` 改为:

```python
def run(target):
    for src, dst in plan_moves(target):
        dst.parent.mkdir(exist_ok=True)
        shutil.move(str(src), str(dst))
        print(f"move {src.name} -> {dst.relative_to(target)}")
    for d in remove_empty_dirs(target):
        print(f"rmdir {d.relative_to(target)}/")
    return 0
```

(按路径深度倒序遍历实现自底向上;`children` 过滤掉本轮已标记删除的子目录,使 dry-run 下嵌套空壳也能整体判空。)

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m unittest discover -s scripts -p "test_*.py" -v`
Expected: PASS,7 tests OK

- [ ] **Step 5: 提交**

```bash
git add scripts/clean_downloads.py scripts/test_clean_downloads.py
git commit -m "feat(scripts): clean_downloads 空目录自底向上清理(AC-05/06)"
```

---

### Task 4: CLI 收口 — dry-run、错误处理、main(AC-08 / AC-09)

**Files:**
- Modify: `scripts/clean_downloads.py`(重写 `run` 为最终形态,新增 `main` 与 `__main__` 入口)
- Test: `scripts/test_clean_downloads.py`

**Interfaces:**
- Consumes: Task 1-3 的 `plan_moves` / `remove_empty_dirs` / 测试基类。
- Produces:
  - `run(target: Path, dry_run: bool = False) -> int`:最终形态;target 非目录 → stderr 提示 + 返回 1;单文件移动失败 → stderr 警告、继续处理、最终返回 1;dry-run 只打印零改动。
  - `main(argv=None) -> int`:argparse 入口,位置参数 `target` 缺省 `~/Downloads`,开关 `--dry-run`。

- [ ] **Step 1: 写失败测试**

在测试文件顶部补充导入:

```python
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
```

在 `CleanDownloadsTest` 类中追加:

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m unittest discover -s scripts -p "test_*.py" -v`
Expected: test_ac08 ERROR(`run() got an unexpected keyword argument 'dry_run'`);test_ac09 ERROR(`FileNotFoundError`)

- [ ] **Step 3: 写最小实现**

`scripts/clean_downloads.py` 顶部补充导入:

```python
import argparse
import sys
```

整体替换 `run`,文件末尾新增 `main` 与入口:

```python
def run(target, dry_run=False):
    if not target.is_dir():
        print(f"error: not a directory: {target}", file=sys.stderr)
        return 1
    prefix = "[dry-run] " if dry_run else ""
    errors = 0
    for src, dst in plan_moves(target):
        if not dry_run:
            try:
                dst.parent.mkdir(exist_ok=True)
                shutil.move(str(src), str(dst))
            except OSError as e:
                print(f"warning: failed to move {src.name}: {e}", file=sys.stderr)
                errors += 1
                continue
        print(f"{prefix}move {src.name} -> {dst.relative_to(target)}")
    for d in remove_empty_dirs(target, dry_run=dry_run):
        print(f"{prefix}rmdir {d.relative_to(target)}/")
    return 1 if errors else 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Sort downloads into category folders by extension.")
    parser.add_argument("target", nargs="?", default="~/Downloads",
                        help="directory to organize (default: ~/Downloads)")
    parser.add_argument("--dry-run", action="store_true",
                        help="print planned actions without changing anything")
    args = parser.parse_args(argv)
    return run(Path(args.target).expanduser(), dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m unittest discover -s scripts -p "test_*.py" -v`
Expected: PASS,9 tests OK

- [ ] **Step 5: 提交**

```bash
git add scripts/clean_downloads.py scripts/test_clean_downloads.py
git commit -m "feat(scripts): clean_downloads dry-run 与 CLI 入口(AC-08/09)"
```

---

### Task 5: 全量验证 — CLI 冒烟 + ASD 管道全绿

**Files:**
- 无新增/修改(纯验证;若失败则修复后重跑)

**Interfaces:**
- Consumes: Task 1-4 的全部交付物。
- Produces: pipeline 全绿证据,可进入收尾流程。

- [ ] **Step 1: CLI 冒烟(真实命令行走一遍)**

```bash
smoke=$(mktemp -d)
touch "$smoke/photo.png" "$smoke/notes.txt" "$smoke/data"
mkdir -p "$smoke/empty/nested"
python3 scripts/clean_downloads.py "$smoke" --dry-run
python3 scripts/clean_downloads.py "$smoke"
find "$smoke" | sort
rm -r "$smoke"
```

Expected: dry-run 只打印计划;真实运行后 find 输出为 `Images/photo.png`、`Documents/notes.txt`、`Others/data`,`empty/` 已消失。

- [ ] **Step 2: 跑 ASD 交付管道**

Run: `bash asd/kernel/delivery/pipeline.sh asd/specs/2026-07-16-clean-downloads-design.md`
Expected: spec-lint / test / ac-coverage 三步依次通过,最后一行 `✓ [pipeline] 全部通过`

- [ ] **Step 3: 确认工作区干净**

Run: `git status`
Expected: clean(Task 1-4 已各自提交,本任务无遗留改动)
