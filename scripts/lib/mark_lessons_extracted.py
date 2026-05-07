"""mark_lessons_extracted —— 把 meta.yaml.lessons_extracted 翻为 true。

唯一目的：让 `meta.yaml.lessons_extracted` 字段的写入走脚本而非 AI 自觉的
Edit/Write 工具调用。`/knowledge:extract-experience` Skill 在沉淀完成后必须
调用本脚本作为收尾，否则 archive_runner 的 R-ARCHIVE-LESSONS-NOT-EXTRACTED
预检会拦下 archive。

行为：
  1. 读 meta.yaml；不存在 → exit 1（错误码 R-MARK-NO-META）
  2. lessons_extracted 已为 true → exit 0（幂等，不报错）
  3. 否则改为 true，原子写（先 .tmp 再 os.replace）
  4. stdout 打印：marked req=<id> lessons_extracted=true

退出码：
  0 —— 翻为 true 成功 / 已是 true
  1 —— 任何错误（meta 不存在 / yaml 解析失败 / 写入失败）

不接受 --force / --revert 参数：本脚本只允许 false → true 单向迁移。
若需重置，应通过 git revert 撤销当次 archive 元数据 commit。
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

import yaml

# 复用 common 提供的仓库根定位
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import REPO_ROOT  # noqa: E402

REQUIREMENTS_DIR = REPO_ROOT / "requirements"


def _meta_path(req_id: str) -> Path:
    return REQUIREMENTS_DIR / req_id / "meta.yaml"


def _abort(code: str, message: str) -> None:
    print(f"❌ {code}: {message}", file=sys.stderr)
    sys.exit(1)


def mark_lessons_extracted(req_id: str) -> bool:
    """把 meta.yaml.lessons_extracted 翻为 true。

    Returns:
        True  —— 实际改写了文件
        False —— 已是 true，无变更（幂等路径）
    """
    if not req_id:
        _abort("R-MARK-REQ-ID", "req_id 为空")

    meta_file = _meta_path(req_id)
    if not meta_file.exists():
        _abort("R-MARK-NO-META", f"meta.yaml 不存在：{meta_file}")

    try:
        with meta_file.open("r", encoding="utf-8") as f:
            meta = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        _abort("R-MARK-YAML", f"meta.yaml 解析失败：{exc}")

    if meta.get("lessons_extracted") is True:
        return False

    meta["lessons_extracted"] = True

    # 原子写：写 .tmp → os.replace（与 archive_runner._atomic_write_meta 同模式）
    tmp = tempfile.NamedTemporaryFile(
        "w",
        delete=False,
        dir=meta_file.parent,
        prefix=meta_file.name + ".",
        suffix=".tmp",
        encoding="utf-8",
    )
    try:
        yaml.safe_dump(meta, tmp, allow_unicode=True, sort_keys=False)
        tmp.close()
        os.replace(tmp.name, meta_file)
    except OSError as exc:
        # 清理临时文件，不掩盖原始错误
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        _abort("R-MARK-WRITE", f"meta.yaml 写入失败：{exc}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(
        description="mark meta.yaml.lessons_extracted=true（幂等；只允许 false → true）"
    )
    parser.add_argument("req_id", help="REQ-YYYY-NNN")
    args = parser.parse_args()

    changed = mark_lessons_extracted(args.req_id)
    if changed:
        print(f"marked req={args.req_id} lessons_extracted=true")
    else:
        print(f"already-true req={args.req_id}（idempotent skip）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
