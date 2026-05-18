"""requirement key 命名规则的单一入口。

D-013：新格式 YYYYMMDD-<slug>，目录名自解释。
D-014：legacy REQ-YYYY-NNN 仍兼容；本模块同时处理两类 key。
D-015：分支统一 feat/req-<key>。
本模块不引用 worktree_manager 与其他 lib（叶子节点；OD-1 默认锁死）。
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Iterable

# 正则：复用 workflow_run._REQ_ID_PATTERN 语义（来源：scripts/lib/workflow_run.py:31）
_LEGACY_REQUIREMENT_KEY_RE = re.compile(r"^REQ-(\d{4})-(\d{3})$")
_NEW_REQUIREMENT_KEY_RE = re.compile(r"^(\d{8})-([a-z0-9]+(?:-[a-z0-9]+)*)(?:-(\d{2}))?$")
_SLUG_CHARSET_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_SLUG_DERIVE_FROM_TITLE_RE = re.compile(r"^[\x20-\x7e]+$")  # 仅 ASCII 标题派生
_WHITESPACE_OR_UNDERSCORE_RE = re.compile(r"[\s_]+")  # normalize_slug 替换用
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")  # derive_slug_from_title 替换用


class SlugError(ValueError):
    """slug 非法（非 ASCII / 非法字符 / 长度超限）。CLI 层捕获后 fail-closed exit 1。"""


def normalize_slug(raw: str) -> str:
    """规范化 ASCII slug：lower + 空白/下划线 → 连字符 + 字符集校验。

    入参：任意字符串
    返回：合法 slug
    异常：SlugError（非 ASCII / 空串 / 全连字符 / 长度 > 64）
    """
    try:
        raw.encode("ascii")
    except UnicodeEncodeError as e:
        raise SlugError(f"slug 含非 ASCII 字符：{raw!r}") from e

    s = raw.lower()
    s = _WHITESPACE_OR_UNDERSCORE_RE.sub("-", s)

    if not s or s.strip("-") == "":
        raise SlugError(f"slug 规范化后为空或全连字符：{raw!r}")

    if not _SLUG_CHARSET_RE.match(s):
        raise SlugError(f"slug 含非法字符（仅允许 a-z 0-9 连字符）：{s!r}")

    if len(s) > 64:
        raise SlugError(f"slug 长度超限（{len(s)} > 64）：{s!r}")

    return s


def derive_slug_from_title(title: str) -> str | None:
    """从 ASCII 标题派生 slug；以下三种情况返回 None：
    (1) 标题含非 ASCII 字符（regex 不匹配）；
    (2) 替换非字母数字后 strip 结果为空；
    (3) 截断到 64 字符后字符集校验不通过。

    入参：任意字符串标题
    返回：合法 slug 字符串，或 None（三种情况见上）
    None 语义：CLI 层 fail-closed（来源：requirements/REQ-2026-014/artifacts/tech-feasibility.md:139 R2），
    要求用户显式 --slug。
    """
    if not _SLUG_DERIVE_FROM_TITLE_RE.match(title):
        return None

    s = title.lower()
    # 非字母数字的字符替换为连字符
    s = _NON_ALNUM_RE.sub("-", s)
    s = s.strip("-")

    if not s:
        return None

    # 截断到 64 字符
    if len(s) > 64:
        s = s[:64].rstrip("-")

    if not _SLUG_CHARSET_RE.match(s):
        return None

    return s


def generate_requirement_key(
    date_obj: date,
    slug: str,
    *,
    existing_keys: Iterable[str] = (),
) -> str:
    """生成 YYYYMMDD-<slug>；纯字符串函数，不读 / 不写文件系统。

    冲突回避：候选 key 在 existing_keys 中存在时尝试 -02 / -03 / ... 后缀，
    第一个未占用的即返回；超 -99 后缀抛 SlugError。
    本函数不调 mkdir / 不读 requirements/ 目录。
    """
    occupied = set(existing_keys)
    date_str = date_obj.strftime("%Y%m%d")
    candidate = f"{date_str}-{slug}"

    if candidate not in occupied:
        return candidate

    for suffix in range(2, 100):
        suffixed = f"{candidate}-{suffix:02d}"
        if suffixed not in occupied:
            return suffixed

    raise SlugError(f"同日 date={date_str!r} slug={slug!r} 后缀 -02~-99 均已占用，无法生成新 key")


def is_legacy_requirement_key(key: str) -> bool:
    """识别 REQ-YYYY-NNN 旧格式（D-014）。"""
    return bool(_LEGACY_REQUIREMENT_KEY_RE.match(key))


def branch_for_requirement_key(key: str) -> str:
    """两种 key 统一生成 feat/req-<key> 分支名。

    入参：requirement key 字符串（legacy REQ-YYYY-NNN 或新格式 YYYYMMDD-<slug>）
    返回：feat/req-<key>（legacy 格式去掉 REQ- 前缀，与 _strip_req_prefix 对齐）
    来源：scripts/lib/workflow_bootstrap.py:77
    """
    m = _LEGACY_REQUIREMENT_KEY_RE.match(key)
    if m:
        year = m.group(1)
        nnn = m.group(2)
        return f"feat/req-{year}-{nnn}"
    return f"feat/req-{key}"


def directory_for_requirement_key(key: str) -> Path:
    """两种 key 统一映射到需求目录路径（不执行 mkdir）。

    入参：requirement key 字符串（legacy REQ-YYYY-NNN 或新格式 YYYYMMDD-<slug>）
    返回：`Path('requirements/<key>')`（相对路径，与 key 字符串同构）
    """
    return Path("requirements") / key
