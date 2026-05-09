"""
workflow-launcher 核心匹配模块。

职责：
  - 定义 20 条关键词（6 类）及其匹配方式
  - 实现三步仲裁逻辑（state tiebreaker → 最长匹配 → 等长冲突 ask）
  - 提取命令附加参数（reject reason / new title）

本模块仅做意图翻译，不执行命令，不修改 RunState。
外部调用者只需导入 `match_keyword` 与 `ConflictReason`。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


# ============================================================================
# 数据结构
# ============================================================================

@dataclass(frozen=True)
class Keyword:
    """单条关键词描述。

    字段：
    - category: 所属类别（continue/review/new/approve/reject/release）
    - text: 关键词字面量（含标点）
    - length: 字符长度（Python len(text)）
    - command: 映射的 /workflow:* 命令模板
    - match_kind: 匹配方式（ascii / chinese / punct_literal）
    """

    category: str
    text: str
    length: int
    command: str
    match_kind: str  # "ascii" | "chinese" | "punct_literal"

    def matches(self, user_input: str) -> bool:
        """判断用户输入是否命中本关键词。"""
        return _keyword_matches(user_input, self)


@dataclass
class ConflictReason:
    """等长冲突描述。

    字段：
    - reason: 冲突类型（目前固定为 "equal_length"）
    - candidates: 所有等长命中的 Keyword 列表
    """

    reason: str
    candidates: list[Keyword] = field(default_factory=list)


# ============================================================================
# 关键词表（20 条，6 类）
# ============================================================================

KEYWORDS: list[Keyword] = [
    # --- continue 类 ---
    Keyword(
        category="continue",
        text="继续之前的需求",
        length=7,
        command="/workflow:continue",
        match_kind="chinese",
    ),
    Keyword(
        category="continue",
        text="继续这个需求",
        length=6,
        command="/workflow:continue",
        match_kind="chinese",
    ),
    Keyword(
        category="continue",
        text="接着做",
        length=3,
        command="/workflow:continue",
        match_kind="chinese",
    ),
    Keyword(
        category="continue",
        text="继续",
        length=2,
        command="/workflow:continue",
        match_kind="chinese",
    ),
    # --- review 类 ---
    Keyword(
        category="review",
        text="code review",
        length=11,
        command="/workflow:run code-review-embedded",
        match_kind="ascii",
    ),
    Keyword(
        category="review",
        text="跑下代码评审",
        length=6,
        command="/workflow:run code-review-embedded",
        match_kind="chinese",
    ),
    Keyword(
        category="review",
        text="跑代码评审",
        length=5,
        command="/workflow:run code-review-embedded",
        match_kind="chinese",
    ),
    Keyword(
        category="review",
        text="审一下",
        length=3,
        command="/workflow:run code-review-embedded",
        match_kind="chinese",
    ),
    # --- new 类 ---
    Keyword(
        category="new",
        text="开个新需求",
        length=5,
        command='/workflow:new standard-8phase "<title>"',
        match_kind="chinese",
    ),
    Keyword(
        category="new",
        text="新建需求",
        length=4,
        command='/workflow:new standard-8phase "<title>"',
        match_kind="chinese",
    ),
    Keyword(
        category="new",
        text="创建需求",
        length=4,
        command='/workflow:new standard-8phase "<title>"',
        match_kind="chinese",
    ),
    # --- release 类（Post-MVP）---
    Keyword(
        category="release",
        text="release",
        length=7,
        command="/workflow:run release-cut",
        match_kind="ascii",
    ),
    Keyword(
        category="release",
        text="我要发版",
        length=4,
        command="/workflow:run release-cut",
        match_kind="chinese",
    ),
    Keyword(
        category="release",
        text="打版本",
        length=3,
        command="/workflow:run release-cut",
        match_kind="chinese",
    ),
    # --- approve 类 ---
    Keyword(
        category="approve",
        text="approve",
        length=7,
        command="/workflow:approve",
        match_kind="ascii",
    ),
    Keyword(
        category="approve",
        text="批准",
        length=2,
        command="/workflow:approve",
        match_kind="chinese",
    ),
    Keyword(
        category="approve",
        text="通过",
        length=2,
        command="/workflow:approve",
        match_kind="chinese",
    ),
    # --- reject 类 ---
    Keyword(
        category="reject",
        text="reject:",
        length=7,
        command="/workflow:reject <reason>",
        match_kind="punct_literal",
    ),
    Keyword(
        category="reject",
        text="不通过",
        length=3,
        command="/workflow:reject <reason>",
        match_kind="chinese",
    ),
    Keyword(
        category="reject",
        text="驳回",
        length=2,
        command="/workflow:reject <reason>",
        match_kind="chinese",
    ),
]

# 按长度降序缓存，避免每次重排
_KEYWORDS_DESC: list[Keyword] = sorted(KEYWORDS, key=lambda k: -k.length)


# ============================================================================
# 私有：匹配实现
# ============================================================================

def _keyword_matches(user_input: str, kw: Keyword) -> bool:
    """根据 match_kind 调用对应匹配策略。"""
    if kw.match_kind == "ascii":
        return _match_ascii(user_input, kw.text)
    elif kw.match_kind == "chinese":
        return _match_chinese(user_input, kw.text)
    elif kw.match_kind == "punct_literal":
        return _match_punct_literal(user_input, kw.text)
    else:
        raise ValueError(f"未知 match_kind: {kw.match_kind!r}（关键词：{kw.text!r}）")


def _match_ascii(user_input: str, keyword: str) -> bool:
    """ASCII 词边界匹配：防止 approved / releases 等假阳性。

    含空格的短语（如 code review）也用词边界，空格字面量匹配。
    """
    # 对 keyword 中的特殊正则字符转义（如若含 . / * 等）
    escaped = re.escape(keyword)
    pattern = r"\b" + escaped + r"\b"
    return bool(re.search(pattern, user_input, re.IGNORECASE))


def _match_chinese(user_input: str, keyword: str) -> bool:
    """中文 substring 匹配：直接判断是否包含关键词。"""
    return keyword in user_input


def _match_punct_literal(user_input: str, keyword: str) -> bool:
    """含标点的字面量匹配：substring 匹配（冒号必须出现）。

    例：reject: → "reject:理由太弱" 命中，"rejected" 不命中（无冒号）。
    """
    return keyword in user_input


# ============================================================================
# 私有：参数提取
# ============================================================================

def _extract_reject_reason(user_input: str) -> Optional[str]:
    """从用户输入中提取 reject 理由。

    优先从 reject: 冒号后取内容；
    不通过 / 驳回 后取剩余文本（简单空格切割）。
    """
    # 优先：冒号分割（兼容全角冒号）
    for separator in ("reject:", "reject："):
        if separator in user_input:
            after = user_input.split(separator, 1)[1].strip()
            return after if after else None

    # 次选：不通过 / 驳回 后的内容
    for prefix in ("不通过", "驳回"):
        if prefix in user_input:
            idx = user_input.index(prefix) + len(prefix)
            after = user_input[idx:].strip()
            return after if after else None

    return None


def _extract_new_title(user_input: str, kw: Keyword) -> Optional[str]:
    """从用户输入中提取新建需求的标题（去除关键词后的剩余文本）。"""
    # 找到关键词的位置，取其后内容
    idx = user_input.find(kw.text)
    if idx == -1:
        return None
    after = user_input[idx + len(kw.text):].strip()
    # 去掉常见连接词（冒号、中文冒号、破折号）
    after = after.lstrip("：:—- ")
    return after if after else None


# ============================================================================
# 公开 API：参数提取
# ============================================================================

def extract_args(user_input: str, kw: Keyword) -> Optional[str]:
    """根据关键词类别从用户输入中提取附加参数。

    返回：
    - reject 类：冒号后的 reason 字符串（无则 None）
    - new 类：标题文本（无则 None）
    - 其余类：None
    """
    if kw.category == "reject":
        return _extract_reject_reason(user_input)
    elif kw.category == "new":
        return _extract_new_title(user_input, kw)
    return None


# ============================================================================
# 公开 API：三步仲裁
# ============================================================================

def match_keyword(
    user_input: str,
    active_runs: list,
) -> tuple[Optional[str], Optional[str], Optional[ConflictReason]]:
    """三步仲裁：将用户自然语言输入翻译为 /workflow:* 命令。

    参数：
    - user_input: 用户原始输入
    - active_runs: 当前活跃 run 列表，duck typing——只读取 .state 属性

    返回：(command, args, conflict)
    - command: 匹配到的命令字符串（如 "/workflow:approve"）
    - args:    附加参数（如 reject reason / new title），无则 None
    - conflict: ConflictReason，等长冲突时非空
    - 三项均为 None 表示无命中，launcher 不接管
    """
    # Step 1：state tiebreaker
    # 若存在 approval_pending 状态的 run，优先匹配 approve/reject 类
    has_approval_pending = any(
        getattr(r, "state", None) == "approval_pending" for r in active_runs
    )
    if has_approval_pending:
        for kw in KEYWORDS:
            if kw.category in ("approve", "reject") and kw.matches(user_input):
                return kw.command, extract_args(user_input, kw), None

    # Step 2：最长匹配（降序扫描，取所有命中）
    hits = [kw for kw in _KEYWORDS_DESC if kw.matches(user_input)]

    # Step 3：等长冲突兜底
    if len(hits) >= 2 and hits[0].length == hits[1].length:
        equal_top = [h for h in hits if h.length == hits[0].length]
        return None, None, ConflictReason("equal_length", equal_top)

    # Step 4：有命中或无命中
    if hits:
        return hits[0].command, extract_args(user_input, hits[0]), None

    # 无命中：launcher 不接管
    return None, None, None
