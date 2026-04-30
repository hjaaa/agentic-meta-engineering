"""旧版 verdict 干跑迁移脚本（v1.0 → v2.0 schema）。

背景：
  review-schema.yaml v2.0 将 conclusion 枚举从
  {approved, needs_revision, rejected} 升级为 {looks_clean, needs_attention, blocked}。
  本脚本负责扫描 requirements/*/reviews/*.json，找出仍使用旧枚举的 verdict，
  生成干跑报告（--dry-run）或执行字面量替换（--apply）。

用法：
  python3 scripts/lib/migrate_review_v2.py --dry-run   # 只看报告，不改文件
  python3 scripts/lib/migrate_review_v2.py --apply     # 执行替换（approved→looks_clean）+ 清空 human_signoff

安全约束（D-002 强制重签）：
  --apply 仅做字面量替换 + 清空 human_signoff；不会写入 decision=approved，
  不视旧 approved 为已签字通过——所有历史 verdict 均需重新人工 sign-off。

来源：requirements/REQ-2026-003/artifacts/detailed-design.md §F-001.4
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from common import REPO_ROOT, paint

# 旧版 conclusion 枚举集合（v1.0 schema）
OLD_CONCLUSIONS: frozenset[str] = frozenset({"approved", "needs_revision", "rejected"})

# conclusion 字面量平移映射（其余旧值保留原样，仅 approved 可直接平移到 looks_clean）
RENAME_MAP: dict[str, str] = {
    "approved": "looks_clean",
    # needs_revision / rejected 无直接对应，需人工重签判断后选择 needs_attention 或 blocked
}


@dataclass
class OldVerdict:
    """内存中一条旧版 verdict 记录。"""

    path: Path           # review JSON 的绝对路径
    conclusion: str      # verdict["conclusion"] 原始值
    data: dict           # read 后内存里的 verdict 全文（--apply 时回写）


def scan_old_verdicts(reviews_root: Path) -> list[OldVerdict]:
    """扫描 requirements/*/reviews/*.json，返回 conclusion ∈ 旧枚举的 verdict 列表。

    参数：
      reviews_root — requirements/ 目录的路径（通常 = REPO_ROOT / "requirements"）

    返回：
      OldVerdict 列表，按文件路径排序，便于幂等输出。
    """
    results: list[OldVerdict] = []
    for review_file in sorted(reviews_root.glob("*/reviews/*.json")):
        try:
            with review_file.open("r", encoding="utf-8") as f:
                data: dict = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            # 读取失败不中断扫描；打印 warning 后继续
            print(paint(f"⚠️  跳过 {review_file}：{exc}", "yellow"), file=sys.stderr)
            continue

        conclusion = data.get("conclusion", "")
        if conclusion in OLD_CONCLUSIONS:
            results.append(OldVerdict(path=review_file, conclusion=conclusion, data=data))

    return results


def render_dry_run_report(items: list[OldVerdict]) -> str:
    """生成多行干跑报告。

    每行格式：`<相对路径> :: <conclusion> :: <重签建议|可平移>`

    平移判断规则：
      - conclusion=approved  → 可平移（approved→looks_clean），但仍需重签
      - 其余（needs_revision / rejected）→ 建议重签，需人工选择新枚举值
    """
    if not items:
        return "✓ 未发现旧版 verdict，无需迁移。"

    lines = [f"发现 {len(items)} 条旧版 verdict：", ""]
    for item in items:
        # 计算相对路径，便于阅读
        try:
            rel_path = str(item.path.relative_to(REPO_ROOT))
        except ValueError:
            rel_path = str(item.path)

        if item.conclusion == "approved":
            advice = "可平移（approved→looks_clean），但仍需重签"
        else:
            advice = "建议重签（无直接平移映射，需人工选择 needs_attention 或 blocked）"

        lines.append(f"{rel_path} :: {item.conclusion} :: {advice}")

    lines.append("")
    lines.append("使用 --apply 执行字面量替换（approved→looks_clean）+ 清空 human_signoff。")
    lines.append("其余 conclusion 值保留，需人工编辑后重新提交 sign-off。")
    return "\n".join(lines)


def apply_rename(items: list[OldVerdict]) -> int:
    """执行迁移：字面量替换 + 清空 human_signoff。

    行为：
      - conclusion=approved → looks_clean（其余旧值原样保留，等待人工处理）
      - human_signoff 字段一律置为 null（强制重签，遵 D-002）
      - stale 字段不改（由 save-review.sh 重算覆盖）

    返回已修改的文件计数。

    安全约束：
      本函数不写入 decision=approved，不视旧 approved 为已签字通过。
    """
    count = 0
    for item in items:
        modified = False
        data = item.data

        # 字面量替换 approved → looks_clean
        if data.get("conclusion") == "approved":
            data["conclusion"] = "looks_clean"
            modified = True

        # 清空 human_signoff（强制重签）；键存在才处理，不存在则跳过
        if "human_signoff" in data:
            data["human_signoff"] = None
            modified = True

        if not modified:
            continue

        # 回写 JSON（保留原格式：2 空格缩进，UTF-8，末尾换行）
        try:
            with item.path.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.write("\n")
            count += 1
            try:
                rel_path = str(item.path.relative_to(REPO_ROOT))
            except ValueError:
                rel_path = str(item.path)
            print(paint(f"✓ 已迁移 {rel_path}", "green"))
        except OSError as exc:
            # 写入失败不吞没；打印 error 后继续处理剩余文件
            print(paint(f"❌ 写入失败 {item.path}：{exc}", "red"), file=sys.stderr)

    return count


def main() -> int:
    """CLI 入口。"""
    parser = argparse.ArgumentParser(
        description="旧版 verdict 干跑迁移工具（v1.0 conclusion → v2.0）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python3 scripts/lib/migrate_review_v2.py --dry-run   # 只看报告\n"
            "  python3 scripts/lib/migrate_review_v2.py --apply     # 执行替换\n"
        ),
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true", help="只打印报告，不修改文件")
    group.add_argument("--apply", action="store_true", help="执行字面量替换 + 清空 human_signoff")
    args = parser.parse_args()

    reviews_root = REPO_ROOT / "requirements"
    items = scan_old_verdicts(reviews_root)

    if args.dry_run:
        print(render_dry_run_report(items))
        return 0

    # --apply 路径
    if not items:
        print(paint("✓ 未发现旧版 verdict，无需迁移。", "green"))
        return 0

    print(f"准备迁移 {len(items)} 条旧版 verdict…")
    count = apply_rename(items)
    print(paint(f"\n完成：共重命名 {count} 个文件。", "cyan"))
    remaining = len(items) - count
    if remaining > 0:
        print(paint(f"⚠️  {remaining} 个文件写入失败，请查看上方错误信息。", "yellow"), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
