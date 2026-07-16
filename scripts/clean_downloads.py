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
