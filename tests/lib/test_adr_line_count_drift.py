"""ADR 行数漂移检测测试（F-012 rev6 Minor 1+2 元信息脚本化）。

防止 plan.md D-017 ADR 中声明的文件行数与实际行数漂移（F-17/F-18 历史债务终结）。
  - 解析 plan.md D-017 ADR 文本，正则抽出 save_review.py / signoff.py / save_review_validation.py 行数
  - 与实测 wc -l 比对，超 ±5 行容差则 fail

来源：REQ-2026-009 rev5 F-17+F-18（D-017 ADR 数字过时）；F-012 rev6 元信息脚本化落地。
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN_MD = REPO_ROOT / "requirements" / "REQ-2026-009" / "plan.md"

# 容差：±5 行（允许每次微调 helper docstring 而不必同步 ADR）
_LINE_COUNT_TOLERANCE = 5

# 被监控的文件列表
_MONITORED_FILES = [
    "save_review.py",
    "signoff.py",
    "save_review_validation.py",
]


def _get_actual_line_count(filename: str) -> int | None:
    """获取 scripts/lib/<filename> 的实际行数；文件不存在返回 None。"""
    path = REPO_ROOT / "scripts" / "lib" / filename
    if not path.exists():
        return None
    return sum(1 for _ in path.open(encoding="utf-8"))


def _extract_adr_line_counts(plan_text: str) -> dict[str, int]:
    """从 D-017 ADR Decision 段中正则抽取文件行数声明。

    匹配模式示例：
      save_review.py 492 行 / signoff.py 434 行 / save_review_validation.py 47 行
    返回 {filename: claimed_count}。
    """
    # 找 D-017 块（从标题到下一个 ### 之间）
    d017_match = re.search(r"### D-017.*?(?=###|\Z)", plan_text, re.DOTALL)
    if not d017_match:
        return {}
    d017_text = d017_match.group(0)

    result: dict[str, int] = {}
    for filename in _MONITORED_FILES:
        # 匹配 "save_review.py 492 行" 或 "save_review.py 缩到 423 行（"
        pattern = rf"{re.escape(filename)}\s+(?:缩到\s+)?(\d+)\s+行"
        match = re.search(pattern, d017_text)
        if match:
            result[filename] = int(match.group(1))
    return result


def test_adr_line_count_drift_should_be_within_tolerance():
    """plan.md D-017 ADR 声明的行数与实际行数差距必须 ≤ 5 行。

    防止 ADR 数字过时（F-17 save_review.py / F-18 signoff.py / save_review_validation.py）。
    容差 5 行允许 helper docstring 微调，但如果重大重构后忘记更新 ADR 则 fail。
    """
    assert PLAN_MD.exists(), f"plan.md not found: {PLAN_MD}"
    plan_text = PLAN_MD.read_text(encoding="utf-8")

    claimed_counts = _extract_adr_line_counts(plan_text)
    assert claimed_counts, (
        "无法从 plan.md D-017 ADR 解析到任何文件行数声明——请检查格式是否匹配 '<file.py> NNN 行'"
    )

    drifts = []
    for filename, claimed in claimed_counts.items():
        actual = _get_actual_line_count(filename)
        if actual is None:
            # 文件不存在（可能被删除），只在 ADR 仍声明时告警
            drifts.append(f"{filename}: ADR 声明 {claimed} 行但文件不存在")
            continue
        diff = abs(actual - claimed)
        if diff > _LINE_COUNT_TOLERANCE:
            drifts.append(
                f"ADR line count drift: plan.md says {filename} {claimed} 行, actual {actual} 行 (diff={diff} > tolerance={_LINE_COUNT_TOLERANCE})"
            )

    assert not drifts, "\n".join(drifts)
