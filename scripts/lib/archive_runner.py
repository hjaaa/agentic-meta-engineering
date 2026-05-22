"""archive 子动作 runner —— /requirement:archive 的实现入口。

设计契约（detailed-design §3.1 / §3.5，已 frozen）：

    archive_requirement(req_id, *, force, keep_branch, no_experience,
                        yes_experience, yes_local_branch, yes_remote_branch,
                        prompts_callback) -> ArchiveResult

行为流程：
  1. 5 项预检（phase / dirty / pr_number / pr-merged / lessons_extracted）
     任一失败 → SystemExit(1)
  2. 原子写 meta.yaml（phase=completed + archived_at）
  3. 追加 process.txt `[archived]` 事件（幂等：已有则跳过）
  4. 经验沉淀（可选；交互通道决议见 §3.5.5）
  5. 删本地分支 + 删远程分支（可选；同上）
  6. 终端反馈 6 行（spec §5.3：标题 + phase + archived_at + experience + 本地 + 远程）

副作用动作（3 / 4 / 5 步）失败均降级到 ArchiveResult.error_messages，
archive 命令始终 exit 0（除非 5 项预检挂）。

预检 5（lessons_extracted）由 `_precheck_lessons_extracted` 实现：要求
`meta.yaml.lessons_extracted is True`，否则 SystemExit(1)
错误码 `R-ARCHIVE-LESSONS-NOT-EXTRACTED`。该字段的写入只允许走
`scripts/lib/mark_lessons_extracted.py`，不允许 AI Edit/Write 工具直接编辑。
`--force` flag 仅豁免预检 4（PR-merged），不豁免预检 5（用户反馈 2026-05-07）。

为什么把交互通道做成 callback + yes_* flag 双轨：
  - 主对话场景：Skill 不能直接读 stdin，由伞形 Skill 装配 callback 串行问；
  - CLI 自动化：传 yes_* flag 跳问，等价用户答 y；
  - 二者同传时 yes_* 优先（避免歧义）；二者皆缺时按 N 处理（保守不删/不沉淀）。

时间戳遵循 context/team/engineering-spec/time-format.md：
  archived_at 字段使用 `YYYY-MM-DD HH:MM:SS`（Asia/Shanghai 不带 offset），
  与 phase-rules.md「archived_at 字段语义」示例值对齐（F-002 已交付契约）。
"""
from __future__ import annotations

import json
import logging
import os
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal, NoReturn, Optional

import yaml

# 复用 common 提供的仓库根定位（与 check_meta / list_requirements 同模块风格）
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import REPO_ROOT  # noqa: E402
import worktree_manager  # noqa: E402

REQUIREMENTS_DIR = REPO_ROOT / "requirements"

# Asia/Shanghai 时区常量（time-format.md：所有写入文件的时间戳统一 UTC+8）
_CST = timezone(timedelta(hours=8))

# 子进程超时（秒）——与 ahead_of_origin 同档，保留快速失败语义
_SUBPROC_TIMEOUT_SEC = 30

# 受保护的长寿命分支白名单（本地+远程对称）——任何情况下都不允许 archive 删除
# 即便 meta.base_branch 为空 / 漂移，命中本集合也直接 fail-closed（codex round-5 P1 F-10）
_PROTECTED_BRANCHES = frozenset({"main", "master", "develop"})

# 合法 git 分支名正向白名单（F-001 review R3 F-02）：
# 仅允许 [a-zA-Z0-9_./-]，且必须以字母/数字/下划线开头，禁止任何 git refspec 元字符
# （'-' 前缀、':' refspec、'@{...}' reflog、'~' / '^' 祖先记号、'..' range 等）
_VALID_BRANCH_RE = re.compile(r"^[a-zA-Z0-9_][a-zA-Z0-9_./-]*$")


def _check_branch_name_safe(branch: str) -> tuple[bool, str]:
    """字符集合法性校验：branch 仅含 [a-zA-Z0-9_./-] 且非 '-' 开头（防 git 命令注入）。

    与 _check_branch_safe_for_remote_op 不同：只校验字符串安全，**不**检查
    protected / base_branch 语义。供 `git switch <base_branch>` 等
    "切换到任意已知分支"的场景调用，避免 protected 检查把合法 base 误拒。

    额外禁止 `..`（git refname 规则禁止 double-dot，且 git 把 `a..b` 当 range 语法）。
    """
    if not branch:
        return True, "branch 为空"
    if not _VALID_BRANCH_RE.fullmatch(branch):
        return (
            True,
            f"branch={branch!r} 含非法字符（仅允许 [a-zA-Z0-9_./-]，"
            f"必须以字母/数字/下划线开头）",
        )
    if ".." in branch:
        return True, f"branch={branch!r} 含 '..'（git refname 规则禁止 double-dot）"
    return False, ""


def _check_branch_safe_for_remote_op(branch: str, base_branch: str) -> tuple[bool, str]:
    """判定 branch 是否安全用于远程 git 写操作（push / push --delete / branch -d）。

    防御四类风险（F-001 review F-05）：
      - 空 branch：早期防御，避免向 origin 推空 refspec
      - git refspec 元字符注入：由 _check_branch_name_safe 用正向白名单
        re.fullmatch(r'^[a-zA-Z0-9_][a-zA-Z0-9_./-]*$') 一次性拦下
        '-' 前缀 / ':' refspec / '@{' reflog / '~' / '^' / '..' 等
      - 受保护分支：命中 _PROTECTED_BRANCHES（meta 漂移兜底）
      - base_branch 漂移：branch == base_branch 也拒绝（防误删 base）

    返回 (is_invalid, reason)。调用方按各自 fail 策略处置：
      - _push_feat_branch：fail-closed → _abort(R-ARCHIVE-PUSH-FAILED)
      - _delete_local_branch / _delete_remote_branch：fail-soft → result.X=failed
    """
    is_invalid, reason = _check_branch_name_safe(branch)
    if is_invalid:
        return True, reason
    if branch in _PROTECTED_BRANCHES:
        return (
            True,
            f"branch={branch!r} 命中受保护分支白名单 {sorted(_PROTECTED_BRANCHES)}",
        )
    if base_branch and branch == base_branch:
        return True, f"branch={branch!r} == base_branch={base_branch!r}（meta.branch 漂移）"
    return False, ""


# archive commit message 幂等检测正则工厂（模块级命名，便于测试 mock）
# 用法：ARCHIVE_COMMIT_RE(req_id).match(subject)
def ARCHIVE_COMMIT_RE(req_id: str) -> re.Pattern:  # noqa: N802 — 保持大写以便 mock
    """返回匹配 `archive(<req_id>): metadata` 的编译正则。"""
    return re.compile(rf"^archive\({re.escape(req_id)}\): metadata$")


logger = logging.getLogger(__name__)


@dataclass
class ArchivePrompt:
    """三问串行的单条问句契约（A 案 callback 入参）。

    F-003 扩展：新增 "finalize" kind，用于 finalize 阶段的合并问询 +
    `--force` 二次确认。
    """

    kind: Literal["experience", "local_branch", "remote_branch", "finalize"]
    question: str
    default: bool = False  # 默认 N


@dataclass
class ArchiveResult:
    """archive 命令终态汇总（含每个副作用动作的 outcome）。

    F-003 扩展两字段：
      - worktree_removed：finalize 阶段 _cleanup_worktree_before_archive 的 outcome
      - manual_recovery_commands：legacy_resurrect / worktree 失败路径追加的人工恢复命令
    """

    req_id: str
    phase: str = "completed"
    archived_at: str = ""
    experience: Literal["yes", "no", "skipped", "failed"] = "skipped"
    local_branch: Literal["deleted", "kept", "skipped", "failed"] = "skipped"
    remote_branch: Literal[
        "deleted", "kept", "skipped", "already-deleted", "failed"
    ] = "skipped"
    error_messages: list[str] = field(default_factory=list)
    archive_pr_number: int = 0
    archive_pr_url: str = ""
    archive_pr_action: Literal["created", "reused", "skipped"] = "skipped"
    worktree_removed: Literal["removed", "kept", "skipped", "failed"] = "skipped"
    manual_recovery_commands: list[str] = field(default_factory=list)


# ---------- 内部工具 ----------


def _now_cst_str() -> str:
    """archived_at / process.txt 行首时间戳的统一来源。

    格式 `YYYY-MM-DD HH:MM:SS`（不带 offset；事实源 time-format.md）。
    """
    return datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S")


def _meta_path(req_id: str) -> Path:
    return REQUIREMENTS_DIR / req_id / "meta.yaml"


def _process_path(req_id: str) -> Path:
    return REQUIREMENTS_DIR / req_id / "process.txt"


def _load_meta(req_id: str) -> dict[str, Any]:
    """加载 meta.yaml；失败时抛 SystemExit(1) 让调用方走预检失败路径。"""
    path = _meta_path(req_id)
    if not path.exists():
        _abort("R-ARCHIVE-META-MISSING", f"meta.yaml 不存在: {path}", req_id)
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        _abort("R-ARCHIVE-META-PARSE", f"meta.yaml 解析失败: {exc}", req_id)
    if not isinstance(data, dict):
        _abort("R-ARCHIVE-META-PARSE", "meta.yaml 顶层不是 mapping", req_id)
    return data


def _abort(code: str, message: str, req_id: str) -> NoReturn:
    """预检失败统一出口：stderr 输出错误码 + 业务主键，并 exit 1。

    返回类型 NoReturn 让静态类型检查器知道本函数永不正常返回，
    使得调用 _abort 的分支不会被推断为"隐式 return None"
    （特别是 _run_or_abort 的 except 分支，避免与声明返回类型
    subprocess.CompletedProcess 矛盾——F-001 review R3 F-03）。
    """
    print(f"❌ {code} req={req_id}: {message}", file=sys.stderr)
    raise SystemExit(1)


def _run(cmd: list[str], *, cwd: Optional[Path] = None) -> subprocess.CompletedProcess:
    """统一的 subprocess 包装：超时 + 文本输出 + 不抛非零退出。"""
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=False,
        timeout=_SUBPROC_TIMEOUT_SEC,
        cwd=cwd,
    )


def _run_or_abort(
    cmd: list[str],
    *,
    cwd: Optional[Path] = None,
    error_code: str,
    req_id: str,
    label: str,
) -> subprocess.CompletedProcess:
    """fail-closed 包装：TimeoutExpired / FileNotFoundError / OSError → _abort。

    返回值仍是 CompletedProcess，调用方继续按 returncode 检查业务语义；
    本 helper 只把"进程都没起来"或"超时"这三类底层异常映射到结构化错误码，
    避免裸 Python traceback 绕过 R-ARCHIVE-* 错误码契约（F-001 review F-17）。
    """
    try:
        return _run(cmd, cwd=cwd)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        _abort(error_code, f"{label} 调用失败: {exc}", req_id)


# ---------- 4 项预检 ----------


def _precheck_phase(meta: dict[str, Any], req_id: str) -> None:
    """预检 1：phase 必须 ∈ {testing} 或 (completed AND archive_pr_number=0)。

    设计动机（F-001 e5caaab）：archive_pr_number=0 允许半完成重跑——兼容历史
    meta（无 archive_pr_number 字段视同 0）+ F-001 双阶段拆分中的中间状态
    （phase 已置 completed 但归档 PR 尚未创建）。archive_pr_number>0 说明已归档
    PR 已存在，拒绝二次归档防数据覆盖。

    任一条件不满足 → abort R-ARCHIVE-PHASE。
    """
    phase = meta.get("phase", "")
    if phase == "testing":
        return
    if phase == "completed":
        # 半完成重跑：archive_pr_number=0 视为允许（兼容历史 + 半完成场景）
        try:
            archive_pr_number = int(meta.get("archive_pr_number") or 0)
        except (TypeError, ValueError):
            archive_pr_number = 0
        if archive_pr_number == 0:
            return
        _abort(
            "R-ARCHIVE-PHASE",
            f"phase=completed 且 archive_pr_number={archive_pr_number}（>0），已完成归档；不允许重跑",
            req_id,
        )
    _abort(
        "R-ARCHIVE-PHASE",
        f"当前 phase={phase!r}，期望 testing 或 (completed AND archive_pr_number=0)",
        req_id,
    )


def _filter_dirty_lines_by_whitelist(lines: list[str], req_id: str) -> list[str]:
    """从 git status --porcelain 输出行中过滤出非白名单 dirty 路径。

    白名单：
      - requirements/<req_id>/ 前缀（idempotent 重跑必备）
      - context/team/experience/（含子目录）
      - context/project/<*>/experience/（子串匹配 /experience/）
      - context/INDEX.md
      - context/team/experience/INDEX.md

    返回剩余非白名单 dirty 路径列表；调用方决定是否 abort。
    """
    non_whitelisted: list[str] = []
    for line in lines:
        if not line:
            continue
        # porcelain 格式：XY SP SP path 或 rename 形式 XY SP SP old_path -> new_path
        raw_path = line[3:].strip()
        # rename 形式（R  old -> new）取 new
        if " -> " in raw_path:
            raw_path = raw_path.split(" -> ")[-1].strip()
        if _is_whitelist_path(raw_path, req_id):
            continue
        non_whitelisted.append(raw_path)
    return non_whitelisted


def _is_whitelist_path(path: str, req_id: str) -> bool:
    """判断 path 是否属于 dirty 白名单。"""
    req_prefix = f"requirements/{req_id}/"
    if path.startswith(req_prefix) or path == f"requirements/{req_id}":
        return True
    if path.startswith("context/team/experience/"):
        return True
    if "/experience/" in path and path.startswith("context/"):
        return True
    if path == "context/INDEX.md":
        return True
    if path == "context/team/experience/INDEX.md":
        return True
    return False


def _check_git_status_clean(cwd: Path, req_id: str, label: str) -> None:
    """在指定 cwd 跑 `git status --porcelain`，非白名单 dirty → SystemExit(1) + 标签化错误信息。"""
    try:
        result = _run(["git", "status", "--porcelain"], cwd=cwd)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        _abort("R-ARCHIVE-DIRTY", f"git status 调用失败 ({label} {cwd}): {exc}", req_id)
    if result.returncode != 0:
        _abort(
            "R-ARCHIVE-DIRTY",
            f"git status 返回非零 ({label} {cwd}): "
            f"{result.stderr.strip() or result.stdout.strip()}",
            req_id,
        )
    raw = (result.stdout or "").strip()
    if not raw:
        return
    lines = raw.splitlines()
    non_whitelisted = _filter_dirty_lines_by_whitelist(lines, req_id)
    if non_whitelisted:
        _abort(
            "R-ARCHIVE-DIRTY",
            f"{label} 有未提交改动 ({cwd})；先 commit 再 archive（首条: {non_whitelisted[0]}）",
            req_id,
        )


def _precheck_dirty(meta: dict[str, Any], req_id: str) -> None:
    """检查主仓 + owned linked worktree 双仓干净状态（codex P1 F-4 / F-6）。

    场景覆盖：
      - 主仓 cwd 启动 archive，meta.worktree.path 指向 owned 但 dirty 的 linked
        worktree：主仓 clean → 单点检查会漏 → cleanup `git worktree remove` 因
        dirty 失败但 fail-soft → meta 已 mark completed（codex round-5 F-6）
      - linked worktree cwd 启动 archive，主仓 clean 但 worktree dirty：rebind 后
        REPO_ROOT 已切主仓 → 单点检查只看 clean 主仓（codex round-3 F-4）

    设计：先主仓，再 owned worktree（只在 owner=workflow 时检查；external / legacy
    不强制——它们不归 workflow 管，dirty 也不会被 cleanup_worktree_if_owned 触动）。
    requirements/<req_id>/ 与 context/ 经验类路径在白名单内，允许 dirty（idempotent 重跑）。
    """
    _check_git_status_clean(REPO_ROOT, req_id, "主仓")

    worktree_meta = meta.get("worktree") or {}
    if not isinstance(worktree_meta, dict):
        return
    if worktree_meta.get("owner") != "workflow":
        return
    raw_path = (worktree_meta.get("path") or "").strip()
    if not raw_path:
        return
    worktree_path = (REPO_ROOT / Path(raw_path)).resolve()
    if not worktree_path.exists():
        # worktree 已被外部清理：cleanup 阶段会按 git worktree prune 处理，本步无需阻塞
        return
    _check_git_status_clean(worktree_path, req_id, "linked worktree")


def _precheck_pr_number(meta: dict[str, Any], req_id: str) -> int:
    """预检 3：meta.pr_number 必须 > 0；返回该数值供 _precheck_pr_merged 使用。

    pr_number ≤ 0（含缺失 / 非整数 / 0）→ abort R-ARCHIVE-NO-PR
    （提示用户先跑 /requirement:submit 写入 pr_number）。
    """
    raw = meta.get("pr_number", 0)
    try:
        pr_number = int(raw or 0)
    except (TypeError, ValueError):
        pr_number = 0
    if pr_number <= 0:
        _abort(
            "R-ARCHIVE-NO-PR",
            "meta.pr_number 缺失；先跑 /requirement:submit",
            req_id,
        )
    return pr_number


def _precheck_pr_merged(pr_number: int, req_id: str, *, force: bool) -> None:
    """gh pr view 校验 state == MERGED；--force 时跳过。"""
    if force:
        return
    try:
        result = _run(
            ["gh", "pr", "view", str(pr_number), "--json", "state"],
            cwd=REPO_ROOT,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        _abort(
            "R-ARCHIVE-PR-NOT-MERGED",
            f"gh pr view 调用失败 pr=#{pr_number}: {exc}（可加 --force 跳过）",
            req_id,
        )
    if result.returncode != 0:
        _abort(
            "R-ARCHIVE-PR-NOT-MERGED",
            f"gh pr view 返回非零 pr=#{pr_number}: {result.stderr.strip()}",
            req_id,
        )
    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        _abort(
            "R-ARCHIVE-PR-NOT-MERGED",
            f"gh pr view 输出非合法 JSON pr=#{pr_number}: {exc}",
            req_id,
        )
    state = (data.get("state") or "").upper()
    if state != "MERGED":
        _abort(
            "R-ARCHIVE-PR-NOT-MERGED",
            f"PR #{pr_number} state={state!r}，未合并；等 merge 或加 --force",
            req_id,
        )


def _precheck_archive_pr_merged(
    meta: dict[str, Any], req_id: str, *, force: bool
) -> int:
    """finalize 阶段预检：归档 PR 必须 MERGED 才允许做后续清理。

    返回 archive_pr_number。`force=True` 时跳过三路径，返回
    meta.archive_pr_number 或 0（finalize_requirement 调用方负责打 force 警告）。

    三路径全 fail-closed（detailed-design §3.2）：

      R-FINALIZE-ARCHIVE-PR-MISSING
        meta.archive_pr_number ∈ {None, 0, ""}

      R-FINALIZE-ARCHIVE-PR-FETCH-FAILED
        gh pr view OSError / 非零退出 / JSON 解析失败

      R-FINALIZE-ARCHIVE-PR-NOT-MERGED
        gh state != "MERGED"

    与 _precheck_pr_merged 对称，只是错误码换成 R-FINALIZE-* 前缀，
    并多承担「archive_pr_number 缺失」这一独立预检。
    """
    raw = meta.get("archive_pr_number")
    try:
        archive_pr_number = int(raw or 0)
    except (TypeError, ValueError):
        archive_pr_number = 0

    if force:
        # --force 跳过三路径校验；返回 meta.archive_pr_number 或 0
        return archive_pr_number

    if archive_pr_number <= 0:
        _abort(
            "R-FINALIZE-ARCHIVE-PR-MISSING",
            (
                f"meta.archive_pr_number={raw!r} 缺失；"
                f"先跑 archive_runner {req_id}（无 --finalize）创建归档 PR"
            ),
            req_id,
        )

    try:
        result = _run(
            ["gh", "pr", "view", str(archive_pr_number), "--json", "state"],
            cwd=REPO_ROOT,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        _abort(
            "R-FINALIZE-ARCHIVE-PR-FETCH-FAILED",
            (
                f"gh pr view {archive_pr_number} 调用失败：{exc}；"
                f"检查网络 / gh auth；--force 可跳过此预检（高风险）"
            ),
            req_id,
        )
    if result.returncode != 0:
        _abort(
            "R-FINALIZE-ARCHIVE-PR-FETCH-FAILED",
            (
                f"gh pr view {archive_pr_number} 调用失败：{result.stderr.strip()}；"
                f"检查网络 / gh auth；--force 可跳过此预检（高风险）"
            ),
            req_id,
        )
    try:
        data = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        _abort(
            "R-FINALIZE-ARCHIVE-PR-FETCH-FAILED",
            (
                f"gh pr view {archive_pr_number} 调用失败：JSON 解析失败 {exc}；"
                f"检查网络 / gh auth；--force 可跳过此预检（高风险）"
            ),
            req_id,
        )
    state = (data.get("state") or "").upper()
    if state != "MERGED":
        _abort(
            "R-FINALIZE-ARCHIVE-PR-NOT-MERGED",
            (
                f"归档 PR #{archive_pr_number} state={state}，未 merged；"
                f"等 reviewer merge 后再跑 finalize"
            ),
            req_id,
        )
    return archive_pr_number


def _precheck_lessons_extracted(meta: dict[str, Any], req_id: str) -> None:
    """预检 5：meta.yaml.lessons_extracted 必须为 True。

    设计动机（用户反馈 2026-05-07）：归档时强制要求经验已沉淀，避免「跑完 archive
    才发现忘了沉淀经验」的常见漏洞。lessons_extracted 字段的写入必须走脚本
    （scripts/lib/mark_lessons_extracted.py）—— 不允许 AI Edit / 手工编辑 meta.yaml
    来翻这个字段。`/knowledge:extract-experience` Skill 完成沉淀后调用 mark
    脚本作为收尾。

    硬约束：--force 不豁免本预检。--force 仅设计用于「PR 未 merged 异常恢复」，
    不应被借用来绕过经验沉淀这一独立、强制的工程纪律。
    """
    if meta.get("lessons_extracted") is True:
        return
    _abort(
        "R-ARCHIVE-LESSONS-NOT-EXTRACTED",
        (
            f"meta.yaml.lessons_extracted={meta.get('lessons_extracted')!r}（期望 True）；"
            f"先跑 `claude /knowledge:extract-experience {req_id}` 沉淀经验，"
            f"Skill 收尾会调用 scripts/lib/mark_lessons_extracted.py 把字段翻为 True"
        ),
        req_id,
    )


# ---------- 5 步执行 ----------


def _atomic_write_meta(req_id: str, meta: dict[str, Any], *, outcome: str = "shipped") -> str:
    """原子写 meta.yaml：tmp + os.replace；返回最终的 archived_at 值。

    F-17（CI gate fail）：phase=completed 时 schema 强校验 outcome/completed_at 非空
    （context/team/engineering-spec/meta-schema.yaml conditional_required），
    必须同时写这两个字段。outcome 默认 shipped（archive 路径前置已校验 PR merged）；
    `--force` 路径可能 PR 未 merged，但 outcome 仍由调用方在 CLI 层显式给值。

    重跑安全：archived_at / completed_at / outcome 已非空时保留旧值（首次归档时间
    与结论不被覆盖）。
    """
    archived_at = (meta.get("archived_at") or "").strip()
    if not archived_at:
        archived_at = _now_cst_str()
    completed_at = (meta.get("completed_at") or "").strip()
    if not completed_at:
        completed_at = archived_at  # 同一动作内 phase 转 completed 与 archive 同步发生
    existing_outcome = (meta.get("outcome") or "").strip()
    final_outcome = existing_outcome or outcome

    meta["phase"] = "completed"
    meta["archived_at"] = archived_at
    meta["completed_at"] = completed_at
    meta["outcome"] = final_outcome

    path = _meta_path(req_id)
    tmp = path.with_suffix(".yaml.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        # allow_unicode 保中文标题；sort_keys=False 保字段顺序与既有风格一致
        yaml.safe_dump(meta, f, allow_unicode=True, sort_keys=False)
    os.replace(tmp, path)
    return archived_at


def _append_process_event(req_id: str, pr_number: int, archived_at: str) -> None:
    """追加 `[archived]` 事件；幂等——已存在则跳过。

    走 requirement-progress-logger 的格式约束：
      `YYYY-MM-DD HH:MM:SS [archived] (PR #N merged at <ts>)`
    时间戳取 append 那一刻的 now（保证行序与时序一致）。

    并发安全（codex round-2 P2 finding F-5）：check-then-append 必须在 LOCK_EX
    保护下做单原子段——否则两个并发 archive 都能观察到「未追加」并各自 append，
    破坏单条 `[archived]` 行的不变量。POSIX 平台用 fcntl.flock；Windows 不支持
    时退化为非原子（与历史行为一致），不抛异常。
    """
    path = _process_path(req_id)
    line = f"{_now_cst_str()} [archived] (PR #{pr_number} merged at {archived_at})\n"
    # 'a+'：文件不存在则创建（保留原 `path.open('a')` 兜底创建语义）
    # 同一句柄完成 read+write，避免双 open 间窗口
    with path.open("a+", encoding="utf-8") as f:
        _try_lock_exclusive(f)
        # 'a+' 默认 seek 到末尾；要读 content 必须先 seek(0)
        f.seek(0)
        content = f.read()
        if "[archived]" in content:
            return
        # 'a' 写入语义：内核保证每次 write 落在 EOF（即便有人在 lock 期间
        # 又往同一文件写——LOCK_EX 已排他，不会发生）
        f.write(line)


def _log_finalize_event(
    req_id: str, result: ArchiveResult, *, keep_flags: list[str]
) -> None:
    """追加 `[finalized]` 事件到 process.txt；幂等（末 10 行扫描）。

    格式（detailed-design §3.5）：
        YYYY-MM-DD HH:MM:SS [finalized] worktree=<...> local_branch=<...> remote_branch=<...> [archive PR #<N>] (--keep-...)

    - archive PR #<N> 段仅在 result.archive_pr_number > 0 时追加
    - 括号后缀仅含 keep_flags 中**启用**的 flag，空格分隔，全空则省略
    - idempotent：扫 process.txt 末 10 行含 `[finalized]` tag → 跳过追加

    与 _append_process_event 同样走 flock + a+ 写法：POSIX 平台用 fcntl.flock
    提供 best-effort 原子性；NFS 老内核 / Windows 不支持时 `_try_lock_exclusive`
    会静默退化为非原子追加（与 _append_process_event 一致）——并非强保证并发安全。
    """
    path = _process_path(req_id)
    suffix_parts: list[str] = [
        f"worktree={result.worktree_removed}",
        f"local_branch={result.local_branch}",
        f"remote_branch={result.remote_branch}",
    ]
    if result.archive_pr_number > 0:
        suffix_parts.append(f"[archive PR #{result.archive_pr_number}]")
    if keep_flags:
        suffix_parts.append(f"({' '.join(keep_flags)})")
    line = f"{_now_cst_str()} [finalized] {' '.join(suffix_parts)}\n"

    with path.open("a+", encoding="utf-8") as f:
        _try_lock_exclusive(f)
        f.seek(0)
        content = f.read()
        # idempotent：扫末 10 行（设计文档明确要求；避免历史 finalize 误判）
        tail = content.splitlines()[-10:]
        if any("[finalized]" in entry for entry in tail):
            return
        f.write(line)


def _try_lock_exclusive(file_obj: Any) -> None:
    """尝试取排他文件锁；失败时静默退化（与历史非原子行为兼容）。

    抽出独立函数：fcntl 仅 POSIX 可用，import 在函数体内做容错；
    单测可用 monkeypatch 替换该函数验证 fallback 路径。
    """
    try:
        import fcntl
    except ImportError:
        return  # 非 POSIX 平台
    try:
        fcntl.flock(file_obj.fileno(), fcntl.LOCK_EX)
    except OSError:
        # 部分 FS（如 NFS 老内核）可能不支持 flock；退化处理
        return


def _ask(
    prompt: ArchivePrompt,
    *,
    yes_flag: bool,
    callback: Optional[Callable[[ArchivePrompt], bool]],
) -> bool:
    """统一的三问决议：yes_flag → callback → 默认 N。"""
    if yes_flag:
        return True
    if callback is not None:
        try:
            return bool(callback(prompt))
        except Exception:  # noqa: BLE001 —— callback 异常视同回答 N，不抛
            return False
    return False


def _run_experience(
    req_id: str,
    *,
    no_experience: bool,
    yes_experience: bool,
    callback: Optional[Callable[[ArchivePrompt], bool]],
    result: ArchiveResult,
) -> None:
    """经验沉淀第 3 步。fail-soft：调用失败 → outcome=failed，不抛。"""
    if no_experience:
        result.experience = "skipped"
        return

    answer = _ask(
        ArchivePrompt(
            kind="experience",
            question=f"是否沉淀经验到 context/team/experience/（针对 {req_id}）？(y/N)",
            default=False,
        ),
        yes_flag=yes_experience,
        callback=callback,
    )
    if not answer:
        result.experience = "no"
        return

    # claude CLI 在沙盒/CI 里可能不存在；调用失败按降级矩阵走 outcome=failed
    try:
        proc = _run(["claude", "/knowledge:extract-experience", req_id])
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        result.experience = "failed"
        result.error_messages.append(f"experience: {exc}")
        print(f"⚠️  经验沉淀调用失败 req={req_id}: {exc}", file=sys.stderr)
        return
    if proc.returncode != 0:
        result.experience = "failed"
        msg = (proc.stderr or proc.stdout or "").strip() or f"exit={proc.returncode}"
        result.error_messages.append(f"experience: {msg}")
        print(f"⚠️  经验沉淀返回非零 req={req_id}: {msg}", file=sys.stderr)
        return
    result.experience = "yes"


def _render_archive_pr_body(req_id: str, pr_number: int, branch: str) -> str:
    """渲染 archive-pr-body.md.tmpl，返回替换后的 PR body 字符串。

    pr_number 是**需求 PR number**（meta["pr_number"]），不是归档 PR number。
    三占位符：__REQ_ID__ / __PR_NUMBER__ / __BRANCH__。
    """
    tmpl_path = (
        REPO_ROOT
        / ".claude/skills/managing-requirement-lifecycle/templates/archive-pr-body.md.tmpl"
    )
    content = tmpl_path.read_text(encoding="utf-8")
    return (
        content
        .replace("__REQ_ID__", req_id)
        .replace("__PR_NUMBER__", str(pr_number))
        .replace("__BRANCH__", branch)
    )


def _check_existing_archive_pr(
    branch: str, req_id: str
) -> Optional[dict[str, Any]]:
    """gh pr list 查当前归档 PR（state=all）；返回首条记录 dict 或 None（无匹配）。

    gh 调用失败 → abort R-ARCHIVE-PR-CREATE-FAILED。
    JSON 解析失败 → abort R-ARCHIVE-PR-CREATE-FAILED。
    """
    proc = _run_or_abort(
        [
            "gh", "pr", "list",
            "--head", branch,
            "--base", "develop",
            "--state", "all",
            "--json", "number,state,url",
            "--limit", "1",
        ],
        cwd=REPO_ROOT,
        error_code="R-ARCHIVE-PR-CREATE-FAILED",
        req_id=req_id,
        label="gh pr list",
    )
    if proc.returncode != 0:
        _abort(
            "R-ARCHIVE-PR-CREATE-FAILED",
            f"gh pr list 返回非零 req={req_id}: {proc.stderr.strip()}",
            req_id,
        )
    raw = (proc.stdout or "").strip()
    if not raw or raw == "[]":
        return None
    try:
        items = json.loads(raw)
    except json.JSONDecodeError as exc:
        _abort(
            "R-ARCHIVE-PR-CREATE-FAILED",
            f"gh pr list JSON 解析失败 req={req_id}: {exc}",
            req_id,
        )
    if not items:
        return None
    return items[0]


def _do_create_archive_pr(
    meta: dict[str, Any], req_id: str, branch: str, result: ArchiveResult
) -> int:
    """实际调用 gh pr create；返回新建 PR number。

    渲染模板 → 写临时文件 → gh pr create --body-file → unlink。
    失败 → abort R-ARCHIVE-PR-CREATE-FAILED。
    """
    pr_number = meta.get("pr_number", 0)
    try:
        pr_number = int(pr_number or 0)
    except (TypeError, ValueError):
        pr_number = 0

    body = _render_archive_pr_body(req_id, pr_number, branch)

    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".md")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as fh:
            fh.write(body)

        proc = _run_or_abort(
            [
                "gh", "pr", "create",
                "--base", "develop",
                "--head", branch,
                "--title", f"archive({req_id}): metadata + lessons",
                "--body-file", tmp_path,
            ],
            cwd=REPO_ROOT,
            error_code="R-ARCHIVE-PR-CREATE-FAILED",
            req_id=req_id,
            label="gh pr create",
        )
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    if proc.returncode != 0:
        _abort(
            "R-ARCHIVE-PR-CREATE-FAILED",
            f"gh pr create 失败 req={req_id}: {proc.stderr.strip() or proc.stdout.strip()}",
            req_id,
        )

    # gh pr create 成功时 stdout 为 PR URL，例如 "https://github.com/org/repo/pull/42\n"
    url = (proc.stdout or "").strip()
    # 从 URL 末段解出 number
    try:
        new_number = int(url.rstrip("/").split("/")[-1])
    except (ValueError, IndexError):
        _abort(
            "R-ARCHIVE-PR-CREATE-FAILED",
            f"gh pr create 输出无法解析 PR number req={req_id}: {url!r}",
            req_id,
        )

    result.archive_pr_number = new_number
    result.archive_pr_url = url
    result.archive_pr_action = "created"
    logger.info(
        "create_archive_pr: created pr=#%d url=%s req_id=%s", new_number, url, req_id
    )
    return new_number


def _handle_existing_pr_state(
    existing: dict[str, Any],
    meta: dict[str, Any],
    req_id: str,
    result: ArchiveResult,
) -> int:
    """阶段 1 step 8 helper：处理 _check_existing_archive_pr 返回的非 None 结果。

    - OPEN：复用，写 result.archive_pr_action="reused"，return number
    - MERGED：abort R-ARCHIVE-PR-ALREADY-MERGED（已被 _precheck_phase 保证 meta=0）
    - CLOSED：abort R-ARCHIVE-PR-CLOSED
    - 冲突：meta.archive_pr_number > 0 且 != gh number → R-ARCHIVE-PR-NUMBER-MISMATCH（C-3）

    设计来源：detailed-design.md §2.1（idempotent 三态分支 + C-3 冲突决策）
    """
    state = (existing.get("state") or "").upper()
    number = int(existing.get("number") or 0)
    url = (existing.get("url") or "").strip()

    if state == "MERGED":
        _abort(
            "R-ARCHIVE-PR-ALREADY-MERGED",
            (
                f"归档 PR #{number} 已 MERGED 但 archive_pr_number 未写入 "
                f"req={req_id}；请手工把 archive_pr_number: {number} 写入 meta.yaml 后重跑"
            ),
            req_id,
        )
    if state == "CLOSED":
        _abort(
            "R-ARCHIVE-PR-CLOSED",
            f"归档 PR #{number} 已 CLOSED req={req_id}；如需重开，请手工恢复后重跑",
            req_id,
        )

    # OPEN — 复用；先做冲突检查（C-3 决策）
    try:
        meta_pr = int(meta.get("archive_pr_number") or 0)
    except (TypeError, ValueError):
        meta_pr = 0
    if meta_pr > 0 and meta_pr != number:
        _abort(
            "R-ARCHIVE-PR-NUMBER-MISMATCH",
            (
                f"meta.archive_pr_number={meta_pr} 与 gh 返回 #{number} 不符 "
                f"req={req_id}；请手工核对后再重跑"
            ),
            req_id,
        )

    result.archive_pr_number = number
    result.archive_pr_url = url
    result.archive_pr_action = "reused"
    logger.info("create_archive_pr: reused pr=#%d req_id=%s", number, req_id)
    return number


def _create_archive_pr(
    meta: dict[str, Any], req_id: str, result: ArchiveResult
) -> int:
    """阶段 1 step 8：调 gh pr create 开归档 PR；返回 PR number。

    Idempotent：先 gh pr list 检查，委托 _handle_existing_pr_state 处理三态：
      - OPEN：复用；MERGED / CLOSED：abort。
    存在性检查后才 create。create 失败抛 R-ARCHIVE-PR-CREATE-FAILED。

    冲突检查：若 meta.archive_pr_number > 0 且 != gh 返回 number →
    fail-closed R-ARCHIVE-PR-NUMBER-MISMATCH（C-3 决策）。

    raises: SystemExit(1) — 任一异常路径
    returns: int — 新建或复用的 PR number
    """
    branch = (meta.get("branch") or "").strip()
    if not branch:
        _abort(
            "R-ARCHIVE-PR-CREATE-FAILED",
            f"meta.branch 为空，无法确定 head branch req={req_id}",
            req_id,
        )

    existing = _check_existing_archive_pr(branch, req_id)
    if existing is not None:
        return _handle_existing_pr_state(existing, meta, req_id, result)

    # 无已有 PR → 新建
    return _do_create_archive_pr(meta, req_id, branch, result)


def _write_archive_pr_number(
    req_id: str, meta: dict[str, Any], pr_number: int
) -> None:
    """阶段 1 step 9：把 archive_pr_number 落回 meta.yaml（tmp + os.replace）。

    Idempotent：meta.archive_pr_number == pr_number 时跳过写盘。
    只改 archive_pr_number 单字段，其余字段维持原状。
    """
    try:
        existing = int(meta.get("archive_pr_number") or 0)
    except (TypeError, ValueError):
        existing = 0

    if existing == pr_number:
        logger.info(
            "write_archive_pr_number: skipped (idempotent) pr_number=%d req_id=%s",
            pr_number, req_id,
        )
        return

    meta["archive_pr_number"] = pr_number

    path = _meta_path(req_id)
    tmp = path.with_suffix(".yaml.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        yaml.safe_dump(meta, f, allow_unicode=True, sort_keys=False)
    os.replace(tmp, path)
    logger.info(
        "write_archive_pr_number: wrote pr_number=%d req_id=%s", pr_number, req_id
    )


def _commit_and_push_archive_pr_number(
    meta: dict[str, Any], req_id: str, archive_pr_number: int
) -> None:
    """阶段 1 step 10：把 _write_archive_pr_number 写入的 meta 改动 commit + push。

    Codex Review P1 (PR #88)：原实现写完 archive_pr_number 后未 commit/push，导致归档 PR 的
    head commit 不含此字段，其他 clone 跑 finalize 会因 R-FINALIZE-ARCHIVE-PR-MISSING 失败。

    Idempotent：meta.yaml 无 dirty 改动时跳过（archive_pr_number 已等于目标值的场景）。
    commit message 使用 `archive(<req_id>): record archive_pr_number=#<N>`，与
    `ARCHIVE_COMMIT_RE` 的 `metadata` 字面正则区分，避免被 `_idempotent_skip_if_commit_exists`
    误识别（来源：scripts/lib/archive_runner.py:128 ARCHIVE_COMMIT_RE）。
    """
    branch = (meta.get("branch") or "").strip()
    if not branch:
        return  # 无分支可推；与 _push_feat_branch 缺 branch 一致地静默跳过
    meta_rel = f"requirements/{req_id}/meta.yaml"

    status_proc = _run_or_abort(
        ["git", "status", "--porcelain", "--", meta_rel],
        cwd=REPO_ROOT,
        error_code="R-ARCHIVE-COMMIT-FAILED",
        req_id=req_id,
        label="git status meta.yaml",
    )
    if status_proc.returncode != 0 or not status_proc.stdout.strip():
        logger.info(
            "commit_archive_pr_number: skipped (clean) req_id=%s pr=%d",
            req_id, archive_pr_number,
        )
        return

    _run_or_abort(
        ["git", "add", "--", meta_rel],
        cwd=REPO_ROOT,
        error_code="R-ARCHIVE-COMMIT-FAILED",
        req_id=req_id,
        label=f"git add {meta_rel}",
    )
    msg = f"archive({req_id}): record archive_pr_number=#{archive_pr_number}"
    commit_proc = _run_or_abort(
        ["git", "commit", "-m", msg],
        cwd=REPO_ROOT,
        error_code="R-ARCHIVE-COMMIT-FAILED",
        req_id=req_id,
        label="git commit archive_pr_number",
    )
    if commit_proc.returncode != 0:
        stderr = (commit_proc.stderr or commit_proc.stdout or "").strip()
        _abort(
            "R-ARCHIVE-COMMIT-FAILED",
            f"git commit archive_pr_number 失败：{stderr}",
            req_id,
        )

    _do_push_with_recovery_hint(
        branch, (meta.get("base_branch") or "").strip(), req_id
    )
    logger.info(
        "commit_archive_pr_number: committed + pushed req_id=%s pr=%d",
        req_id, archive_pr_number,
    )


def _idempotent_skip_if_commit_exists(req_id: str) -> bool:
    """幂等检测：HEAD commit subject 命中 ARCHIVE_COMMIT_RE(req_id) → 返回 True。

    git log 调用失败 → abort R-ARCHIVE-COMMIT-FAILED。
    """
    head_subject = _run_or_abort(
        ["git", "log", "-1", "--format=%s"],
        cwd=REPO_ROOT,
        error_code="R-ARCHIVE-COMMIT-FAILED",
        req_id=req_id,
        label="git log -1",
    )
    if head_subject.returncode == 0 and ARCHIVE_COMMIT_RE(req_id).match(
        (head_subject.stdout or "").strip()
    ):
        logger.info("commit_archive_metadata: skipped (idempotent) req_id=%s", req_id)
        return True
    return False


def _collect_paths_to_add(req_id: str) -> list[str]:
    """跑 git status --porcelain，校验无非白名单 dirty 后返回需 add 的白名单路径列表。

    非白名单 dirty / git status 调用失败 → abort R-ARCHIVE-CONTEXT-DIRTY。
    """
    status_result = _run_or_abort(
        ["git", "status", "--porcelain"],
        cwd=REPO_ROOT,
        error_code="R-ARCHIVE-CONTEXT-DIRTY",
        req_id=req_id,
        label="git status --porcelain",
    )
    if status_result.returncode != 0:
        _abort(
            "R-ARCHIVE-CONTEXT-DIRTY",
            f"git status 调用失败: {status_result.stderr.strip()}",
            req_id,
        )

    raw_lines = (status_result.stdout or "").splitlines()
    non_whitelisted = _filter_dirty_lines_by_whitelist(raw_lines, req_id)
    if non_whitelisted:
        _abort(
            "R-ARCHIVE-CONTEXT-DIRTY",
            f"存在非白名单 dirty 文件，请先 commit 再 archive（首条: {non_whitelisted[0]}）",
            req_id,
        )

    to_add: list[str] = []
    for line in raw_lines:
        if not line:
            continue
        raw_path = line[3:].strip()
        if " -> " in raw_path:
            raw_path = raw_path.split(" -> ")[-1].strip()
        if _is_whitelist_path(raw_path, req_id):
            to_add.append(raw_path)
    return to_add


def _stage_and_commit(req_id: str, to_add: list[str]) -> None:
    """对 to_add 列表执行 git add + git commit，失败 → abort R-ARCHIVE-COMMIT-FAILED。"""
    for path in to_add:
        add_proc = _run_or_abort(
            ["git", "add", path],
            cwd=REPO_ROOT,
            error_code="R-ARCHIVE-COMMIT-FAILED",
            req_id=req_id,
            label=f"git add {path!r}",
        )
        if add_proc.returncode != 0:
            _abort(
                "R-ARCHIVE-COMMIT-FAILED",
                f"git add {path!r} 失败: {add_proc.stderr.strip()}",
                req_id,
            )

    commit_msg = f"archive({req_id}): metadata"
    commit_proc = _run_or_abort(
        ["git", "commit", "-m", commit_msg],
        cwd=REPO_ROOT,
        error_code="R-ARCHIVE-COMMIT-FAILED",
        req_id=req_id,
        label="git commit",
    )
    if commit_proc.returncode != 0:
        _abort(
            "R-ARCHIVE-COMMIT-FAILED",
            f"git commit 失败: {commit_proc.stderr.strip() or commit_proc.stdout.strip()}",
            req_id,
        )
    logger.info("commit_archive_metadata: committed req_id=%s", req_id)


def _commit_archive_metadata(req_id: str, result: ArchiveResult) -> None:  # noqa: ARG001 — result 保留供 F-003 finalize_requirement 写 outcome；签名对称 _push_feat_branch
    """阶段 1 step 6：提交 requirements/<req_id>/ 及经验类白名单文件（幂等）。

    幂等检测：HEAD commit subject 命中 ARCHIVE_COMMIT_RE(req_id) → 跳过整步。
    非白名单 dirty 文件 → abort R-ARCHIVE-CONTEXT-DIRTY（fail-closed）。
    git commit 失败 → abort R-ARCHIVE-COMMIT-FAILED。
    """
    if _idempotent_skip_if_commit_exists(req_id):
        return
    to_add = _collect_paths_to_add(req_id)
    if not to_add:
        logger.info("commit_archive_metadata: nothing to add req_id=%s", req_id)
        return
    _stage_and_commit(req_id, to_add)


def _check_head_eq_remote(branch: str, req_id: str) -> bool:
    """跑 git rev-parse HEAD / origin/<branch>，相等返回 True（push 幂等跳过）。

    rev-parse HEAD 失败 → abort R-ARCHIVE-PUSH-FAILED。
    rev-parse origin/<branch> 失败（如远端无该分支）→ 返回 False，让 push 路径正常走。
    """
    local_sha_proc = _run_or_abort(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        error_code="R-ARCHIVE-PUSH-FAILED",
        req_id=req_id,
        label="git rev-parse HEAD",
    )
    if local_sha_proc.returncode != 0:
        _abort(
            "R-ARCHIVE-PUSH-FAILED",
            f"git rev-parse HEAD 失败: {local_sha_proc.stderr.strip()}",
            req_id,
        )
    local_sha = local_sha_proc.stdout.strip()

    remote_sha_proc = _run_or_abort(
        ["git", "rev-parse", f"origin/{branch}"],
        cwd=REPO_ROOT,
        error_code="R-ARCHIVE-PUSH-FAILED",
        req_id=req_id,
        label=f"git rev-parse origin/{branch}",
    )
    return remote_sha_proc.returncode == 0 and remote_sha_proc.stdout.strip() == local_sha


def _do_push_with_recovery_hint(branch: str, base_branch: str, req_id: str) -> None:
    """git push origin <branch>，失败 → abort R-ARCHIVE-PUSH-FAILED + 手工恢复指引。"""
    push_proc = _run_or_abort(
        ["git", "push", "origin", branch],
        cwd=REPO_ROOT,
        error_code="R-ARCHIVE-PUSH-FAILED",
        req_id=req_id,
        label=f"git push origin {branch}",
    )
    if push_proc.returncode != 0:
        stderr = (push_proc.stderr or push_proc.stdout or "").strip()
        _abort(
            "R-ARCHIVE-PUSH-FAILED",
            (
                f"git push origin {branch} 失败: {stderr}\n"
                f"（可手工 `git push origin {branch}` 重试，或 `gh pr create"
                f" --base {base_branch or 'develop'} --head {branch} --no-codex --skip-rebase` 创建归档 PR 后重跑 archive）"
            ),
            req_id,
        )
    logger.info("push_feat_branch: pushed origin/%s req_id=%s", branch, req_id)


def _push_feat_branch(meta: dict[str, Any], req_id: str, result: ArchiveResult) -> None:  # noqa: ARG001 — result 保留供 F-003 finalize_requirement 写 outcome；签名对称 _commit_archive_metadata
    """阶段 1 step 7：推送 feat 分支到 origin（幂等，不带 --force）。

    幂等检测：HEAD == origin/<branch> → 跳过。
    push 失败 → abort R-ARCHIVE-PUSH-FAILED。
    """
    branch = (meta.get("branch") or "").strip()
    base_branch = (meta.get("base_branch") or "").strip()
    # F-05：与 _delete_local_branch / _delete_remote_branch 对称——
    # refspec / 选项前缀 / 受保护分支三道防御，命中即 fail-closed
    is_invalid, reason = _check_branch_safe_for_remote_op(branch, base_branch)
    if is_invalid:
        _abort("R-ARCHIVE-PUSH-FAILED", f"拒绝推送：{reason}", req_id)

    if _check_head_eq_remote(branch, req_id):
        logger.info("push skipped: HEAD == origin/%s req_id=%s", branch, req_id)
        return

    _do_push_with_recovery_hint(branch, base_branch, req_id)


def _delete_local_branch(
    branch: str,
    base_branch: str,
    *,
    keep_branch: bool,
    yes_local: bool,
    callback: Optional[Callable[[ArchivePrompt], bool]],
    result: ArchiveResult,
    strict: bool = False,
) -> None:
    """删本地分支第 4 步前半。-d safe delete，不允许 -D 强删（D-014）。

    F-003 新增 `strict` 参数（detailed-design §3.3）：
      - strict=False（默认，archive 兼容路径）：所有失败路径维持现有 fail-soft 行为
      - strict=True（finalize 入口）：所有原本 fail-soft 的失败路径
        （switch base 失败 / git branch -d 失败 / safety check 失败 /
        base_branch 为空 / branch 为空）一律 SystemExit(1) + stderr 透传原错误

    注：archive 主流程不再调本函数，default 仍保 False 是为单测易读
    （detailed-design §3.3 已写明）。
    """
    if keep_branch:
        result.local_branch = "skipped"
        return
    if not branch:
        msg = "local_branch: meta.branch 为空，跳过删除"
        if strict:
            _abort("R-FINALIZE-LOCAL-BRANCH-FAILED", msg, result.req_id)
        result.local_branch = "skipped"
        result.error_messages.append(msg)
        return
    # 防止误删 base_branch / 受保护分支 + refspec/选项注入（F-05 远程对称）；
    # 即便 base_branch 为空 / 漂移，命中保护分支白名单也直接 fail-soft
    is_invalid, reason = _check_branch_safe_for_remote_op(branch, base_branch)
    if is_invalid:
        msg = f"local_branch: 拒绝删除——{reason}"
        if strict:
            _abort("R-FINALIZE-LOCAL-BRANCH-FAILED", msg, result.req_id)
        result.local_branch = "failed"
        result.error_messages.append(msg)
        print(f"⚠️  {msg}", file=sys.stderr)
        return

    answer = _ask(
        ArchivePrompt(
            kind="local_branch",
            question=f"是否删除本地分支 {branch}？(y/N)",
            default=False,
        ),
        yes_flag=yes_local,
        callback=callback,
    )
    if not answer:
        result.local_branch = "kept"
        return

    # 自动切走 base_branch 再删 feat（2026-05-12 spec 修订）：
    # 旧实现要求用户手动 `git switch <base>` 再重跑 archive，造成"二次跑命令"的奇怪
    # 用户体验。改为 archive_runner 内部检测 current==branch 时主动 `git switch
    # <base_branch>`，让删本地分支真正成为整个 archive 的最后一步（"所有归档操作在
    # 开发分支上进行，删除开发分支是最后操作"）。
    # 安全约束：base_branch 必须非空且能 switch 成功；任一失败 fail-soft，本地分支
    # outcome=failed，archive 整体仍 exit 0（与现有副作用降级矩阵一致）。
    current = _current_branch()
    if current == branch:
        if not base_branch:
            msg = (
                f"local_branch: 当前 HEAD 在 {branch!r} 但 base_branch 为空，"
                f"无法自动切走；请先 `git switch <base>` 再重跑 archive"
            )
            if strict:
                _abort("R-FINALIZE-LOCAL-BRANCH-FAILED", msg, result.req_id)
            result.local_branch = "failed"
            result.error_messages.append(msg)
            print(f"⚠️  {msg}", file=sys.stderr)
            return
        # F-001 review R3 F-01：base_branch 也走字符集校验，防止 meta.base_branch
        # 被污染为 '-f' / 'a:b' / '@{...}' 等触发 git switch 选项/refspec 注入
        base_invalid, base_reason = _check_branch_name_safe(base_branch)
        if base_invalid:
            msg = f"local_branch: 拒绝自动切——{base_reason}"
            if strict:
                _abort("R-FINALIZE-LOCAL-BRANCH-FAILED", msg, result.req_id)
            result.local_branch = "failed"
            result.error_messages.append(msg)
            print(f"⚠️  {msg}", file=sys.stderr)
            return
        try:
            switch_proc = _run(
                ["git", "switch", base_branch], cwd=REPO_ROOT,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            msg = (
                f"local_branch: 自动切 {base_branch!r} 失败（{exc}）；"
                f"请手动 `git switch {base_branch}` 再重跑 archive"
            )
            if strict:
                _abort("R-FINALIZE-LOCAL-BRANCH-FAILED", msg, result.req_id)
            result.local_branch = "failed"
            result.error_messages.append(msg)
            return
        if switch_proc.returncode != 0:
            err = (switch_proc.stderr or switch_proc.stdout or "").strip() or f"exit={switch_proc.returncode}"
            msg = (
                f"local_branch: 自动切 {base_branch!r} 失败：{err}；"
                f"请手动 `git switch {base_branch}` 再重跑 archive"
            )
            if strict:
                _abort("R-FINALIZE-LOCAL-BRANCH-FAILED", msg, result.req_id)
            result.local_branch = "failed"
            result.error_messages.append(msg)
            return

    try:
        proc = _run(["git", "branch", "-d", branch], cwd=REPO_ROOT)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        msg = f"local_branch: {exc}"
        if strict:
            _abort("R-FINALIZE-LOCAL-BRANCH-FAILED", msg, result.req_id)
        result.local_branch = "failed"
        result.error_messages.append(msg)
        return
    if proc.returncode != 0:
        # 透传 git 原始错误（squash merge 后会被判 not fully merged，由用户决策）
        err = (proc.stderr or proc.stdout or "").strip() or f"exit={proc.returncode}"
        msg = f"local_branch: {err}"
        if strict:
            _abort("R-FINALIZE-LOCAL-BRANCH-FAILED", msg, result.req_id)
        result.local_branch = "failed"
        result.error_messages.append(msg)
        return
    result.local_branch = "deleted"


def _current_branch() -> Optional[str]:
    """读 HEAD 当前分支名；detached 或读不到时返 None（视作"不在任何 branch"）。

    抽出独立函数：_run 在多数测试中已 mock，本函数在测试场景能被
    直接 monkeypatch 替换，避免给 _run plan 表加额外条目。
    """
    try:
        proc = _run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=REPO_ROOT,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if proc.returncode != 0:
        return None
    name = (proc.stdout or "").strip()
    if not name or name == "HEAD":
        return None
    return name


def _delete_remote_branch(
    branch: str,
    base_branch: str,
    *,
    keep_branch: bool,
    yes_remote: bool,
    callback: Optional[Callable[[ArchivePrompt], bool]],
    result: ArchiveResult,
    legacy_resurrect: bool = False,
) -> None:
    """删远程分支第 4 步后半。`remote ref does not exist` → already-deleted。

    F-8（codex round-4 P1）：与本地删除路径对称，先把 base_branch 拦下——
    `meta.branch` 误配成 `develop` / `main` / `master` 时，搭配 `--yes-remote-branch`
    或 `y` callback 可能在仓库权限够的情况下删掉关键长寿命分支，必须 fail-closed。

    F-003 新增 `legacy_resurrect` 参数（detailed-design §3.3 / F-007 兜底）：
      - legacy_resurrect=False（默认）：only `remote ref does not exist` 视作
        already-deleted，维持现有行为
      - legacy_resurrect=True：扩大识别集到 {remote ref does not exist, not found,
        unknown}；其他失败仍 fail-soft，但额外把 `git push origin --delete <branch>`
        塞入 result.manual_recovery_commands 供用户手工恢复
    """
    if keep_branch:
        result.remote_branch = "skipped"
        return
    if not branch:
        result.remote_branch = "skipped"
        return
    # 防止误删受保护远程分支 + refspec/选项注入（F-05 推送/本地三处对称）
    is_invalid, reason = _check_branch_safe_for_remote_op(branch, base_branch)
    if is_invalid:
        result.remote_branch = "failed"
        msg = f"remote_branch: 拒绝删除——{reason}"
        result.error_messages.append(msg)
        print(f"⚠️  {msg}", file=sys.stderr)
        return

    answer = _ask(
        ArchivePrompt(
            kind="remote_branch",
            question=f"是否删除远程分支 origin/{branch}？(y/N)",
            default=False,
        ),
        yes_flag=yes_remote,
        callback=callback,
    )
    if not answer:
        result.remote_branch = "kept"
        return

    try:
        proc = _run(
            ["git", "push", "origin", "--delete", branch],
            cwd=REPO_ROOT,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        result.remote_branch = "failed"
        result.error_messages.append(f"remote_branch: {exc}")
        if legacy_resurrect:
            # branch 已经过 _check_branch_safe_for_remote_op 校验（仅 [a-zA-Z0-9_./-]），
            # shlex.quote 对该字符集是 no-op；此处只为与 worktree 路径拼接保持风格一致。
            result.manual_recovery_commands.append(
                f"git push origin --delete {shlex.quote(branch)}"
            )
        return
    if proc.returncode == 0:
        result.remote_branch = "deleted"
        return
    msg = (proc.stderr or proc.stdout or "").strip() or f"exit={proc.returncode}"
    msg_lower = msg.lower()
    # 已删判定：默认仅 `remote ref does not exist`；legacy_resurrect 扩到三关键词
    already_keywords = ["remote ref does not exist"]
    if legacy_resurrect:
        already_keywords.extend(["not found", "unknown"])
    if any(kw in msg_lower for kw in already_keywords):
        result.remote_branch = "already-deleted"
        return
    result.remote_branch = "failed"
    result.error_messages.append(f"remote_branch: {msg}")
    if legacy_resurrect:
        # 与上方异常路径保持一致：branch 已校验，shlex.quote 仅为风格统一。
        result.manual_recovery_commands.append(
            f"git push origin --delete {shlex.quote(branch)}"
        )


def _render_summary(
    result: ArchiveResult, *, stage: Literal["archive", "finalize"] = "archive"
) -> str:
    """spec §5.3 第 5 步终端反馈格式。

    stage="archive"（默认，兼容旧行为）：6 行 + 可选 archive PR 行 + errors 段
      标题 + phase + archived_at + experience + 本地 + 远程

    stage="finalize"（F-003）：finalize 终态汇总
      标题 + worktree_removed + local_branch + remote_branch + manual_recovery 段
    """
    if stage == "finalize":
        return _render_summary_finalize(result)
    return _render_summary_archive(result)


def _render_summary_archive(result: ArchiveResult) -> str:
    """archive 阶段 6 行汇总（向后兼容；新增可选 archive PR 行不破坏既有断言）。"""
    icon = {
        "experience": {
            "yes": "✅", "no": "⏭", "skipped": "⏭",
            "failed": "❌",
        },
        "local_branch": {
            "deleted": "✅", "kept": "⏭", "skipped": "⏭",
            "failed": "❌",
        },
        "remote_branch": {
            "deleted": "✅", "kept": "⏭", "skipped": "⏭",
            "already-deleted": "✅", "failed": "❌",
        },
    }
    lines = [
        f"✅ {result.req_id} archived",
        f"   phase: {result.phase}",
        f"   archived_at: {result.archived_at}",
        f"   experience: {icon['experience'].get(result.experience, '?')} {result.experience}",
        f"   local branch:  {icon['local_branch'].get(result.local_branch, '?')} {result.local_branch}",
        f"   remote branch: {icon['remote_branch'].get(result.remote_branch, '?')} {result.remote_branch}",
    ]
    if result.archive_pr_number > 0:
        lines.append(f"   archive PR: #{result.archive_pr_number}")
    lines.append("")  # 空行分隔
    lines.append("🟢 archive 前请确认 ci gate exit 0：python3 scripts/gates/run.py --trigger=ci --strict")
    if result.error_messages:
        lines.append("   errors:")
        for msg in result.error_messages:
            lines.append(f"     - {msg}")
    return "\n".join(lines)


def _render_summary_finalize(result: ArchiveResult) -> str:
    """finalize 阶段汇总（detailed-design §3.3）。

    展示 worktree_removed / local_branch / remote_branch / errors /
    manual_recovery_commands 字段。
    """
    icon = {
        "worktree_removed": {
            "removed": "✅", "kept": "⏭", "skipped": "⏭", "failed": "❌",
        },
        "local_branch": {
            "deleted": "✅", "kept": "⏭", "skipped": "⏭", "failed": "❌",
        },
        "remote_branch": {
            "deleted": "✅", "kept": "⏭", "skipped": "⏭",
            "already-deleted": "✅", "failed": "❌",
        },
    }
    lines = [
        f"✅ {result.req_id} finalized",
        f"   worktree: {icon['worktree_removed'].get(result.worktree_removed, '?')} {result.worktree_removed}",
        f"   local branch:  {icon['local_branch'].get(result.local_branch, '?')} {result.local_branch}",
        f"   remote branch: {icon['remote_branch'].get(result.remote_branch, '?')} {result.remote_branch}",
    ]
    if result.archive_pr_number > 0:
        lines.append(f"   archive PR: #{result.archive_pr_number}")
    if result.error_messages:
        lines.append("   errors:")
        for msg in result.error_messages:
            lines.append(f"     - {msg}")
    if result.manual_recovery_commands:
        lines.append("   manual recovery:")
        for cmd in result.manual_recovery_commands:
            lines.append(f"     $ {cmd}")
    return "\n".join(lines)


# ---------- worktree cleanup（F-005）----------


def _rebind_to_main_repo(req_id: str) -> None:
    """archive 入口最早调用：把 module-level REPO_ROOT / REQUIREMENTS_DIR 锁定到主仓。

    问题（codex P1 F-1 / F-3）：archive 可能从 linked worktree 内被 invoke，此时
    Python 通过 cwd-relative sys.path 找到 worktree 副本里的 scripts/lib/，
    `__file__` → REPO_ROOT 都指向 worktree。后续 `_cleanup_worktree_before_archive`
    虽然 os.chdir 到主仓并删 worktree，但 module-level REPO_ROOT 不变 →
    `_meta_path` / `_process_path` 仍解析到已删的 worktree 副本 → 写盘失败 / 写入
    无人能读到的孤儿路径。

    本函数在所有 path-dependent 操作之前调用，把全局常量重绑到主仓。失败时不抛
    异常（caller 已显式 chdir cleanup 兜底），但保留 stderr warning 让问题可观察。
    """
    global REPO_ROOT, REQUIREMENTS_DIR
    try:
        main = worktree_manager.resolve_main_repo_root(Path.cwd())
    except worktree_manager.WorktreeBootstrapError as exc:
        logger.info(
            "rebind_to_main_repo: skipped req_id=%s reason=%s "
            "(可能 cwd 已在主仓或非 git 上下文)",
            req_id, getattr(exc, "reason", str(exc)),
        )
        return
    if main == REPO_ROOT:
        return
    REPO_ROOT = main
    REQUIREMENTS_DIR = main / "requirements"
    logger.info(
        "rebind_to_main_repo: REPO_ROOT %s → %s req_id=%s",
        REPO_ROOT, main, req_id,
    )


def _cleanup_worktree_before_archive(
    meta: dict[str, Any], req_id: str
) -> Literal["removed", "skipped", "failed"]:
    """预检全部通过后，atomic_write_meta 之前注入 worktree 清理（F-005 / P1-3 修复）。

    三步顺序硬约束（详见 detailed-design §3.5 / P1-3）：
      1. resolve_main_repo_root：从当前 cwd（可能是 worktree 内）解出主仓根
      2. os.chdir(main_repo_root)：保证后续 git 操作（含 archive 自身）在主仓根下
      3. cleanup_worktree_if_owned：owner=workflow → remove；其他 → skipped/aborted/failed

    OD-3 落点：不读 meta.worktree.cleanup.policy（占位字段，本期不消费）。
    设计来源：detailed-design.md:792-826（§3.5）。

    返回值（F-003 新增）：
      - "removed"：cleanup_worktree_if_owned action=removed
      - "skipped"：action=skipped 或 resolve_main_repo_root / chdir 异常
      - "failed"：action=aborted / failed

    archive 主流程不消费返回值（向后兼容）；finalize_requirement 据此置位
    result.worktree_removed。
    """
    try:
        main_repo_root = worktree_manager.resolve_main_repo_root(Path.cwd())
    except worktree_manager.WorktreeBootstrapError as exc:
        # resolve 规约只抛 WorktreeBootstrapError；非此类型向上传播（fail loud > silent）
        logger.error(
            "worktree cleanup skipped: resolve_main_repo_root failed req_id=%s reason=%s",
            req_id, getattr(exc, "reason", str(exc)),
        )
        return "skipped"

    # os.chdir 裸调在权限异常或 race 时会 crash archive 主流程，违反 D-009 fail-soft；
    # 用 OSError 兜住，让 cleanup 跳过而非整体 abort。
    try:
        os.chdir(main_repo_root)
    except OSError as exc:
        logger.error(
            "worktree cleanup skipped: chdir to %s failed req_id=%s: %s",
            main_repo_root, req_id, exc,
        )
        return "skipped"

    cleanup_result = worktree_manager.cleanup_worktree_if_owned(meta, main_repo_root)

    if cleanup_result.action == "removed":
        logger.info("worktree removed: %s", cleanup_result.removed_path)
        # 仅 removed 分支才 mutate meta，避免给 legacy meta 引入空 worktree 段
        meta.setdefault("worktree", {}).setdefault("cleanup", {})["removed_at"] = _now_cst_str()
        return "removed"
    if cleanup_result.action == "skipped":
        logger.info("worktree cleanup skipped: %s", cleanup_result.reason)
        return "skipped"
    # aborted / failed：记 error 但不阻塞 archive 主流程（D-009）
    logger.error(
        "worktree cleanup %s: %s", cleanup_result.action, cleanup_result.reason
    )
    return "failed"


# ---------- 主入口 ----------


def archive_requirement(
    req_id: str,
    *,
    force: bool = False,
    keep_branch: bool = False,
    no_experience: bool = False,
    yes_experience: bool = False,
    yes_local_branch: bool = False,
    yes_remote_branch: bool = False,
    outcome: str = "shipped",
    prompts_callback: Optional[Callable[[ArchivePrompt], bool]] = None,
) -> ArchiveResult:
    """archive 子动作入口；详见模块 docstring 与 detailed-design §3.5。

    outcome（F-17 新增）：写入 meta.outcome，satisfy GATE-META-SCHEMA conditional
    required（phase=completed 时 outcome / completed_at 必须非空）。默认 shipped；
    --force 路径（PR 未 merged）调用方应显式给值（abandoned / rolled-back）。
    """
    if not req_id:
        _abort("R-ARCHIVE-REQ-ID", "req_id 为空", req_id or "<empty>")
    if outcome not in {"shipped", "abandoned", "rolled-back"}:
        _abort(
            "R-ARCHIVE-OUTCOME",
            f"outcome 必须 ∈ {{shipped, abandoned, rolled-back}}，实际 {outcome!r}",
            req_id,
        )

    # —— 关键顺序约束（codex P1 round-1~5 F-1 / F-3 / F-4 / F-5 / F-6 累积修复 +
    # F-001 双阶段拆分）——
    #
    # 1. _rebind_to_main_repo 必须在 _load_meta / dirty / write_meta 之前：
    #    确保 path helper 一律解析到主仓（F-1 / F-3）。
    # 2. _load_meta 必须在 rebind 之后：从主仓加载 meta dict，避免 worktree stale
    #    副本覆盖主仓较新 metadata（F-5）。
    # 3. _precheck_dirty 必须同时检查主仓 + owned worktree（F-4 / F-6）：
    #      - 主仓 cwd 启动 + worktree dirty 场景（F-6）：rebind 不变 REPO_ROOT=主仓，
    #        仅看主仓会漏 dirty worktree
    #      - worktree cwd 启动 + worktree dirty 场景（F-4）：rebind 后 REPO_ROOT 切
    #        主仓，仅看主仓会漏 dirty worktree
    #    两种场景都需要显式检查 meta.worktree.path（owner=workflow 时）。
    # 4. F-001 双阶段拆分：worktree cleanup + 删本地/远程分支三件套已搬迁到 F-003
    #    finalize_requirement，archive 主流程不再调用。
    #
    # 综合顺序：
    #   rebind → load_meta (main) → 5 precheck → write_meta → process → experience
    #   → commit_metadata → push_feat_branch

    _rebind_to_main_repo(req_id)

    meta = _load_meta(req_id)

    # —— 预检（任一失败 → SystemExit(1)） ——
    _precheck_dirty(meta, req_id)
    _precheck_phase(meta, req_id)
    pr_number = _precheck_pr_number(meta, req_id)
    _precheck_pr_merged(pr_number, req_id, force=force)
    _precheck_lessons_extracted(meta, req_id)

    # —— 5 步执行 ——
    result = ArchiveResult(req_id=req_id)
    archived_at = _atomic_write_meta(req_id, meta, outcome=outcome)
    result.archived_at = archived_at
    result.phase = meta.get("phase", "completed")

    _append_process_event(req_id, pr_number, archived_at)

    _run_experience(
        req_id,
        no_experience=no_experience,
        yes_experience=yes_experience,
        callback=prompts_callback,
        result=result,
    )

    # —— 阶段 1 step 6/7：commit metadata + push feat branch ——
    # 三件套（_cleanup_worktree_before_archive / _delete_remote_branch /
    # _delete_local_branch）的调用已全部移除（detailed-design §1.1 1-H / §1.4）；
    # 函数定义保留供 F-003 finalize_requirement 复用。
    # keep_branch / yes_local_branch / yes_remote_branch 三 flag 保留参数签名（CLI
    # parser 仍有），在 F-003 接管后重新使用。
    _commit_archive_metadata(req_id, result)
    _push_feat_branch(meta, req_id, result)

    # —— 阶段 1 step 8/9/10：创建归档 PR + 落 archive_pr_number + 二次 commit/push ——
    # step 10（Codex P1-1）保证 archive_pr_number 跟随归档 PR head commit 一起进入 develop，
    # 避免其他 clone 跑 finalize 时因 meta.archive_pr_number=0 触发 R-FINALIZE-ARCHIVE-PR-MISSING。
    archive_pr_number = _create_archive_pr(meta, req_id, result)
    _write_archive_pr_number(req_id, meta, archive_pr_number)
    _commit_and_push_archive_pr_number(meta, req_id, archive_pr_number)

    print(_render_summary(result))
    return result


# ---------- finalize 子命令（F-003） ----------


# §3.4 警告文案常量（精确匹配；test_finalize TC-F3-5/6 会断言）
_FINALIZE_WARN_FORCE_ONLY = (
    "⚠️  finalize: --force 已启用——跳过 archive_pr_number 校验。"
    "即将无视归档 PR 状态删除 feat 分支与 worktree。Y/N？"
)
_FINALIZE_WARN_FORCE_AND_YES = (
    "⚠️  finalize: --force + --yes-finalize 同时启用——双重危险组合"
    "（跳过 PR 校验 + 跳过合并问询）。请确认你正在做异常恢复且已手工核对归档 PR 状态。"
    "继续执行。"
)


def _finalize_warn_force(
    req_id: str,
    *,
    force: bool,
    yes_finalize: bool,
    keep_flags: list[str],
    prompts_callback: Optional[Callable[[ArchivePrompt], bool]],
) -> Optional[ArchiveResult]:
    """§3.4 警告文案：在 _precheck_archive_pr_merged 之前打印。

    返回值语义：
      - None：继续 finalize 流程
      - ArchiveResult（experience="aborted by user"）：用户在 force-only 二次确认中
        答 N；调用方应直接 return 它并 exit 0

    分支（detailed-design §3.4 表 4 行）：
      - 无 force：什么都不做
      - force only：打印警告 + 二次确认；callback 答 N → 返回 aborted result
      - force + yes_finalize：打印警告，**不**问，直接继续（双重危险已确认）
      - force + keep_flags 非空：force-only 警告之后追加列出实际生效的 --keep-* flag，
        然后照常走二次确认（yes_finalize 路径已被 FORCE_AND_YES 覆盖，不嵌套加 keep）
    """
    if not force:
        return None
    if yes_finalize:
        print(_FINALIZE_WARN_FORCE_AND_YES, file=sys.stderr)
        return None
    print(_FINALIZE_WARN_FORCE_ONLY, file=sys.stderr)
    if keep_flags:
        print(
            f"（实际生效 keep flag：{' '.join(keep_flags)}）",
            file=sys.stderr,
        )
    answer = _ask(
        ArchivePrompt(
            kind="finalize",
            question=_FINALIZE_WARN_FORCE_ONLY,
            default=False,
        ),
        yes_flag=False,
        callback=prompts_callback,
    )
    if not answer:
        result = ArchiveResult(req_id=req_id)
        result.experience = "aborted by user"  # type: ignore[assignment]
        return result
    return None


def _finalize_chdir_main_repo(req_id: str) -> Path:
    """第 6 步：显式 chdir(main_repo_root)。OSError → fail-closed。

    返回 main_repo_root Path（供后续 pull / cleanup 复用）。
    """
    try:
        main_repo_root = worktree_manager.resolve_main_repo_root(Path.cwd())
    except worktree_manager.WorktreeBootstrapError as exc:
        _abort(
            "R-FINALIZE-CWD-FAILED",
            f"resolve_main_repo_root 失败：{getattr(exc, 'reason', str(exc))}",
            req_id,
        )
    try:
        os.chdir(main_repo_root)
    except OSError as exc:
        _abort(
            "R-FINALIZE-CWD-FAILED",
            f"chdir 到主仓根 {main_repo_root} 失败：{exc}",
            req_id,
        )
    return main_repo_root


def _finalize_pull_develop(req_id: str, main_repo_root: Path) -> None:
    """第 7 步：先 git switch develop 再 git pull --ff-only origin develop。fail-closed → R-FINALIZE-PULL-FAILED。

    Codex Review P1 (PR #88)：原实现直接在当前分支跑 pull，feat 分支被 squash-merged 进
    develop 后 HEAD 与 origin/develop non-fast-forward，pull 必失败。先切到 develop（已在
    develop 时 git switch 为 no-op）再 pull，从而把 develop 本地引用更新到 origin/develop。
    后续 _delete_local_branch(strict=True) 在 develop 上 `git branch -d feat/...` 才能
    安全识别已合并状态。
    """
    try:
        switch_proc = _run(["git", "switch", "develop"], cwd=main_repo_root)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        _abort(
            "R-FINALIZE-PULL-FAILED",
            f"git switch develop 调用失败：{exc}",
            req_id,
        )
    if switch_proc.returncode != 0:
        err = (switch_proc.stderr or switch_proc.stdout or "").strip() or f"exit={switch_proc.returncode}"
        _abort("R-FINALIZE-PULL-FAILED", f"git switch develop 失败：{err}", req_id)

    try:
        proc = _run(["git", "pull", "--ff-only", "origin", "develop"], cwd=main_repo_root)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        _abort("R-FINALIZE-PULL-FAILED", f"git pull --ff develop 调用失败：{exc}", req_id)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit={proc.returncode}"
        _abort("R-FINALIZE-PULL-FAILED", f"git pull --ff develop 失败：{err}", req_id)


def _finalize_collect_keep_flags(
    *, keep_worktree: bool, keep_local_branch: bool, keep_remote_branch: bool,
) -> list[str]:
    """收集启用的 --keep-* flag 名称（_log_finalize_event 用作括号后缀）。"""
    flags: list[str] = []
    if keep_worktree:
        flags.append("--keep-worktree")
    if keep_local_branch:
        flags.append("--keep-local-branch")
    if keep_remote_branch:
        flags.append("--keep-remote-branch")
    return flags


def _finalize_cleanup_worktree(
    meta: dict[str, Any],
    req_id: str,
    result: ArchiveResult,
    *,
    keep_worktree: bool,
) -> None:
    """第 8 步：worktree cleanup + 失败时追加 manual_recovery_commands。"""
    if keep_worktree:
        result.worktree_removed = "kept"
        return
    outcome = _cleanup_worktree_before_archive(meta, req_id)
    result.worktree_removed = outcome
    if outcome == "failed":
        raw_path = ((meta.get("worktree") or {}).get("path") or "").strip()
        if raw_path:
            # raw_path 来自 meta.worktree.path（worktree_manager 写入，理论受控），
            # 但若含空格 / shell 元字符，用户复制粘贴会被 shell 截断 → 视觉欺骗；
            # 经 shlex.quote 后保证整段命令在 shell 中按字面值传给 git。
            result.manual_recovery_commands.append(
                f"git worktree remove --force {shlex.quote(raw_path)}"
            )


def _finalize_post_run(
    req_id: str,
    meta: dict[str, Any],
    result: ArchiveResult,
    *,
    keep_worktree: bool,
    keep_local_branch: bool,
    keep_remote_branch: bool,
    legacy_resurrect_remote: bool,
    prompts_callback: Optional[Callable[[ArchivePrompt], bool]],
) -> None:
    """第 8/9/10/11 步合并：worktree cleanup → 删本地 → 删远程 → 写 process 事件。"""
    # step 8
    _finalize_cleanup_worktree(meta, req_id, result, keep_worktree=keep_worktree)

    # step 9: _delete_local_branch(strict=True)
    branch = (meta.get("branch") or "").strip()
    base_branch = (meta.get("base_branch") or "").strip()
    if keep_local_branch:
        result.local_branch = "skipped"
    else:
        _delete_local_branch(
            branch,
            base_branch,
            keep_branch=False,
            yes_local=True,  # finalize 阶段不再二次问询
            callback=prompts_callback,
            result=result,
            strict=True,
        )

    # step 10: _delete_remote_branch
    if keep_remote_branch:
        result.remote_branch = "skipped"
    else:
        _delete_remote_branch(
            branch,
            base_branch,
            keep_branch=False,
            yes_remote=True,
            callback=prompts_callback,
            result=result,
            legacy_resurrect=legacy_resurrect_remote,
        )

    # step 11: _log_finalize_event
    keep_flags = _finalize_collect_keep_flags(
        keep_worktree=keep_worktree,
        keep_local_branch=keep_local_branch,
        keep_remote_branch=keep_remote_branch,
    )
    _log_finalize_event(req_id, result, keep_flags=keep_flags)


def finalize_requirement(
    req_id: str,
    *,
    yes_finalize: bool = False,
    force: bool = False,
    keep_local_branch: bool = False,
    keep_remote_branch: bool = False,
    keep_worktree: bool = False,
    legacy_resurrect_remote: bool = False,
    prompts_callback: Optional[Callable[[ArchivePrompt], bool]] = None,
) -> ArchiveResult:
    """finalize 子命令入口（detailed-design §3.1，已 frozen）。

    12 步顺序：
      1. _rebind_to_main_repo
      2. _load_meta
      3. §3.4 警告文案（在 _precheck_archive_pr_merged 之前）
      4. _precheck_archive_pr_merged（--force 跳过）
      5. 合并问询 ArchivePrompt(kind="finalize")（--yes-finalize 跳过；N → exit 0）
      6. os.chdir(main_repo_root)（OSError → R-FINALIZE-CWD-FAILED）
      7. git pull --ff develop（fail-closed → R-FINALIZE-PULL-FAILED）
      8. _cleanup_worktree_before_archive（--keep-worktree 跳过）
      9. _delete_local_branch(strict=True)（--keep-local-branch 跳过）
     10. _delete_remote_branch(legacy_resurrect=...)（--keep-remote-branch 跳过）
     11. _log_finalize_event（写 process.txt [finalized]）
     12. print(_render_summary(result, stage="finalize")) + return

    返回 ArchiveResult；用户在第 3/5 步答 N → result.experience="aborted by user"。
    """
    if not req_id:
        _abort("R-FINALIZE-REQ-ID", "req_id 为空", req_id or "<empty>")

    # 1. rebind
    _rebind_to_main_repo(req_id)

    # 2. load meta
    meta = _load_meta(req_id)

    # 3. §3.4 警告文案（必须在 _precheck_archive_pr_merged 之前）
    # 先收集 keep_flags：force + keep-* 组合时要在警告里列出实际生效的 flag
    keep_flags = _finalize_collect_keep_flags(
        keep_worktree=keep_worktree,
        keep_local_branch=keep_local_branch,
        keep_remote_branch=keep_remote_branch,
    )
    aborted = _finalize_warn_force(
        req_id,
        force=force,
        yes_finalize=yes_finalize,
        keep_flags=keep_flags,
        prompts_callback=prompts_callback,
    )
    if aborted is not None:
        return aborted

    # 4. _precheck_archive_pr_merged
    archive_pr_number = _precheck_archive_pr_merged(meta, req_id, force=force)

    # 5. 合并问询
    if not yes_finalize:
        answer = _ask(
            ArchivePrompt(
                kind="finalize",
                question=(
                    f"即将 finalize {req_id}（删 worktree + feat 本地/远程分支）。"
                    f"确认继续？(y/N)"
                ),
                default=False,
            ),
            yes_flag=False,
            callback=prompts_callback,
        )
        if not answer:
            result = ArchiveResult(req_id=req_id)
            result.experience = "aborted by user"  # type: ignore[assignment]
            return result

    # 初始化 result
    result = ArchiveResult(req_id=req_id)
    result.phase = meta.get("phase", "completed")
    result.archived_at = (meta.get("archived_at") or "").strip()
    result.archive_pr_number = archive_pr_number

    # 6. chdir(main_repo_root)
    main_repo_root = _finalize_chdir_main_repo(req_id)

    # 7. git pull --ff develop
    _finalize_pull_develop(req_id, main_repo_root)

    # 8/9/10/11. cleanup + 删本地 + 删远程 + 写 process 事件
    _finalize_post_run(
        req_id,
        meta,
        result,
        keep_worktree=keep_worktree,
        keep_local_branch=keep_local_branch,
        keep_remote_branch=keep_remote_branch,
        legacy_resurrect_remote=legacy_resurrect_remote,
        prompts_callback=prompts_callback,
    )

    # 12. summary + return
    print(_render_summary(result, stage="finalize"))
    return result


# ---------- CLI 入口（命令直接调用时） ----------


def _build_parser():
    import argparse

    p = argparse.ArgumentParser(
        description="archive 子动作：phase=completed + archived_at + 三问串行；"
                    "--finalize 切换到 finalize 子命令（worktree + 分支清理）"
    )
    p.add_argument("req_id", help="REQ-YYYY-NNN")
    p.add_argument("--force", action="store_true",
                   help="跳过 PR merged 校验（异常恢复用；finalize 阶段同样适用）")
    p.add_argument("--keep-branch", action="store_true",
                   help="archive：跳过删本地+远程分支两问（已被 F-003 弃用）")
    p.add_argument("--no-experience", action="store_true",
                   help="跳过经验沉淀提示")
    p.add_argument("--yes-experience", action="store_true",
                   help="经验问跳问，等价用户答 y")
    p.add_argument("--yes-local-branch", action="store_true",
                   help="本地分支问跳问，等价用户答 y")
    p.add_argument("--yes-remote-branch", action="store_true",
                   help="远程分支问跳问，等价用户答 y")
    p.add_argument(
        "--outcome",
        choices=["shipped", "abandoned", "rolled-back"],
        default="shipped",
        help="meta.outcome 终态，默认 shipped；--force 路径下显式给值",
    )
    # ---- finalize 子命令 flag（F-003） ----
    p.add_argument("--finalize", action="store_true",
                   help="切换到 finalize 子命令：归档 PR merge 后清理 worktree + 分支")
    p.add_argument("--yes-finalize", action="store_true",
                   help="finalize 合并问询跳问，等价用户答 y")
    p.add_argument("--keep-local-branch", action="store_true",
                   help="finalize：跳过删本地分支")
    p.add_argument("--keep-remote-branch", action="store_true",
                   help="finalize：跳过删远程分支")
    p.add_argument("--keep-worktree", action="store_true",
                   help="finalize：跳过 worktree cleanup")
    p.add_argument("--legacy-resurrect-remote", action="store_true",
                   help="finalize：扩大 already-deleted 关键词集（F-007 兜底）")
    return p


def main() -> int:
    """CLI 入口：解析命令行参数；--finalize 切 finalize_requirement，否则 archive_requirement。"""
    args = _build_parser().parse_args()
    if args.finalize:
        finalize_requirement(
            args.req_id,
            yes_finalize=args.yes_finalize,
            force=args.force,
            keep_local_branch=args.keep_local_branch,
            keep_remote_branch=args.keep_remote_branch,
            keep_worktree=args.keep_worktree,
            legacy_resurrect_remote=args.legacy_resurrect_remote,
        )
        return 0
    archive_requirement(
        args.req_id,
        force=args.force,
        keep_branch=args.keep_branch,
        no_experience=args.no_experience,
        yes_experience=args.yes_experience,
        yes_local_branch=args.yes_local_branch,
        yes_remote_branch=args.yes_remote_branch,
        outcome=args.outcome,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
