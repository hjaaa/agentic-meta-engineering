#!/usr/bin/env python3
"""Sort top-level files of a downloads directory into category folders by
extension, suffix duplicates with _N, then remove empty subdirectories."""

import argparse
import shutil
import sys
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
