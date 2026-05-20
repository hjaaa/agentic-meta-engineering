"""context_usage_applied — F-007 AppliedSignalClassifier 组件。

负责：
  - AppliedEvidence 数据载体 (frozen dataclass)
  - _ANY_H_RE 正则常量
  - _build_section_map / _section_line_range 辅助函数
  - AppliedSignalClassifier: 把 ReferenceEvidence 升级判定为 AppliedEvidence
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from markdown_links import mask_code_blocks  # noqa: E402


@dataclass(frozen=True)
class AppliedEvidence:
    """一条被判定为 applied 的引用证据。

    字段对应 detailed-design.md §AppliedEvidence（interfaces_frozen）。
    """

    reference: object  # ReferenceEvidence（避免循环 import 时用 object 类型注解）
    rule: Literal["window_hit", "explicit_upgrade"]
    matched_keyword: str
    section_heading: str | None


# 用于识别 ## 二级标题（H2，不多不少两个 # ）
_H2_RE = re.compile(r"^##\s+(.+?)\s*$")
# 用于识别任意标题（H1-H6），用于终止当前 H2 小节
_ANY_H_RE = re.compile(r"^(#{1,6})\s+")


def _build_section_map(lines: list[str]) -> dict[int, str | None]:
    """把 masked_text 的每一行映射到所属 ## 二级小节标题。

    规则（保守原则）：
    - 第一个 H2 之前的行（包括 H1 下方）→ None（不参与窗口同小节判定）
    - 位于某 H2 之内、下一个 H1/H2 之前的行 → 该 H2 标题文本
    - H1 重置当前小节为 None（H1 结束前一个 H2 的作用域）

    Args:
        lines: masked_text.splitlines() 的结果（行 index 0-based，行号 1-based = index+1）

    Returns:
        dict，key 为 1-based 行号，value 为所属 H2 标题文本（或 None）。
    """
    result: dict[int, str | None] = {}
    current_section: str | None = None

    for idx, line in enumerate(lines):
        lineno = idx + 1
        h_match = _ANY_H_RE.match(line)
        if h_match:
            level = len(h_match.group(1))
            if level == 1:
                current_section = None
            elif level == 2:
                h2_match = _H2_RE.match(line)
                current_section = h2_match.group(1) if h2_match else None
            # H3+ 不改变当前 H2 小节
        result[lineno] = current_section

    return result


def _section_line_range(
    section_map: dict[int, str | None], target_section: str, total_lines: int
) -> tuple[int, int]:
    """返回 target_section 对应的行范围 [start, end]（1-based inclusive）。

    线性扫描 section_map，找出连续属于 target_section 的最早 start 和最晚 end。
    若未找到则返回 (1, 0)（空范围）。
    """
    start: int | None = None
    end: int | None = None
    for ln in range(1, total_lines + 1):
        if section_map.get(ln) == target_section:
            if start is None:
                start = ln
            end = ln
    if start is None:
        return (1, 0)
    return (start, end)  # type: ignore[return-value]


class AppliedSignalClassifier:
    """把 ReferenceEvidence 升级判定为 AppliedEvidence。

    判定规则（来源：requirement.md + detailed-design.md §组件 4）：

    路径 A（复合窗口命中）：
      - 引用所在行在某 ## 二级小节内（section_heading 不为 None）
      - AND 前 5 行 + 后 10 行（16 行窗口，masked 文本）内出现关键字
      - 关键字不在 fenced/inline code 内（mask_code_blocks 已处理）
      - 关键字与引用行必须在同一 ## 小节

    路径 B（显式升级声明）：
      - 引用所在行的源文件全文（masked）出现任一 UPGRADE_PHRASES 短语
      - 子串匹配

    两路任一命中即为 applied；同一 reference 双路均命中时各产一条（不去重）。
    保守原则：宁可漏判，不可误判——窗口边界外不命中，不同 ## 小节不命中。
    """

    WINDOW_BEFORE: int = 5
    WINDOW_AFTER: int = 10
    APPLIED_KEYWORDS: tuple[str, ...] = tuple(sorted({
        "Decision", "决策", "应对", "风险", "验证"
    }))
    UPGRADE_PHRASES: tuple[str, ...] = tuple(sorted({
        "升级为 checklist", "升级为 SOP", "升级为测试", "升级为 gate",
        "升级为 hook", "来自该经验", "按该经验落 test", "按该经验落 gate",
    }))

    def __init__(self) -> None:
        self._warnings: list[str] = []

    def classify(
        self, evidences: list, file_cache: dict[Path, str]
    ) -> list[AppliedEvidence]:
        """对每条 ReferenceEvidence 判定是否构成 applied。

        Args:
            evidences:   来自 EvidenceScanner 的引用证据列表
            file_cache:  source 文件内容缓存，key 为绝对路径 Path，value 为文件全文

        Returns:
            list[AppliedEvidence]，只包含命中条目。同一 reference 双路命中时各产一条。

        不抛业务异常（fail-open 风格）。
        """
        results: list[AppliedEvidence] = []

        from collections import defaultdict
        by_source: dict[str, list] = defaultdict(list)
        for ev in evidences:
            by_source[ev.source].append(ev)

        cache_by_rel, cache_by_name = self._build_cache_indexes(file_cache)

        for source_rel, evs in by_source.items():
            raw_text = self._lookup_cache(source_rel, cache_by_rel, cache_by_name)
            if raw_text is None:
                continue

            try:
                masked_text = mask_code_blocks(raw_text)
                masked_lines = masked_text.splitlines()
                section_map = _build_section_map(masked_lines)
                total_lines = len(masked_lines)
            except Exception as exc:
                self._warnings.append(
                    f"WARN classify {source_rel}: {type(exc).__name__}"
                )
                continue

            for ev in evs:
                results.extend(
                    self._classify_single(ev, masked_lines, section_map, total_lines)
                )

        return results

    def _build_cache_indexes(
        self, file_cache: dict[Path, str]
    ) -> tuple[dict[str, str], dict[str, str]]:
        """预建 rel_path → text 和 basename → text 两个索引，避免 O(K) 重复扫描。"""
        cache_by_rel: dict[str, str] = {}
        cache_by_name: dict[str, str] = {}
        for cache_key, cache_text in file_cache.items():
            key_str = str(cache_key).replace("\\", "/")
            cache_by_rel[key_str] = cache_text
            cache_by_name[cache_key.name] = cache_text
        return cache_by_rel, cache_by_name

    def _lookup_cache(
        self,
        source_rel: str,
        cache_by_rel: dict[str, str],
        cache_by_name: dict[str, str],
    ) -> str | None:
        """在缓存中查找 source_rel 对应的文件内容，三级 fallback。"""
        normalized = source_rel.replace("\\", "/")
        raw_text = cache_by_rel.get(normalized)
        if raw_text is None:
            for ckey, ctext in cache_by_rel.items():
                if ckey == normalized or ckey.endswith("/" + normalized):
                    raw_text = ctext
                    break
        if raw_text is None:
            raw_text = cache_by_name.get(Path(normalized).name)
        return raw_text

    def _classify_single(
        self,
        ev: object,
        masked_lines: list[str],
        section_map: dict[int, str | None],
        total_lines: int,
    ) -> list[AppliedEvidence]:
        """对单条 ReferenceEvidence 执行路径 A + 路径 B 判定，返回命中结果列表。"""
        results: list[AppliedEvidence] = []
        ref_lineno = ev.line  # type: ignore[attr-defined]

        # --- 路径 B：显式升级声明（## 二级小节级匹配） ---
        ref_section_b = section_map.get(ref_lineno)
        if ref_section_b is not None:
            upgrade_hit = self._check_upgrade_in_section(
                ref_section_b, section_map, masked_lines, total_lines
            )
            if upgrade_hit is not None:
                results.append(AppliedEvidence(
                    reference=ev,
                    rule="explicit_upgrade",
                    matched_keyword=upgrade_hit,
                    section_heading=None,
                ))

        # --- 路径 A：复合窗口命中 ---
        ref_section = section_map.get(ref_lineno)
        if ref_section is not None:
            window_keyword = self._check_window_keyword(
                ref_lineno, ref_section, section_map, masked_lines, total_lines
            )
            if window_keyword is not None:
                results.append(AppliedEvidence(
                    reference=ev,
                    rule="window_hit",
                    matched_keyword=window_keyword,
                    section_heading=ref_section,
                ))

        return results

    def _check_upgrade_in_section(
        self,
        section: str,
        section_map: dict[int, str | None],
        masked_lines: list[str],
        total_lines: int,
    ) -> str | None:
        """检查指定 section 内是否包含任一 UPGRADE_PHRASES，命中则返回短语，否则 None。"""
        sec_start, sec_end = _section_line_range(section_map, section, total_lines)
        section_text = "\n".join(masked_lines[sec_start - 1 : sec_end])
        for phrase in self.UPGRADE_PHRASES:
            if phrase in section_text:
                return phrase
        return None

    def _check_window_keyword(
        self,
        ref_lineno: int,
        ref_section: str,
        section_map: dict[int, str | None],
        masked_lines: list[str],
        total_lines: int,
    ) -> str | None:
        """检查窗口内（同小节）是否含关键字，命中则返回关键字，否则 None。"""
        win_start = max(1, ref_lineno - self.WINDOW_BEFORE)
        win_end = min(total_lines, ref_lineno + self.WINDOW_AFTER)

        for lineno in range(win_start, win_end + 1):
            if section_map.get(lineno) != ref_section:
                continue
            line_text = masked_lines[lineno - 1]
            for kw in self.APPLIED_KEYWORDS:
                if kw in line_text:
                    return kw
        return None

    @property
    def warnings(self) -> list[str]:
        """累计的非致命告警。"""
        return list(self._warnings)
