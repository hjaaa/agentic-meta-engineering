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
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Optional

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

logger = logging.getLogger(__name__)


@dataclass
class ArchivePrompt:
    """三问串行的单条问句契约（A 案 callback 入参）。"""

    kind: Literal["experience", "local_branch", "remote_branch"]
    question: str
    default: bool = False  # 默认 N


@dataclass
class ArchiveResult:
    """archive 命令终态汇总（含每个副作用动作的 outcome）。"""

    req_id: str
    phase: str = "completed"
    archived_at: str = ""
    experience: Literal["yes", "no", "skipped", "failed"] = "skipped"
    local_branch: Literal["deleted", "kept", "skipped", "failed"] = "skipped"
    remote_branch: Literal[
        "deleted", "kept", "skipped", "already-deleted", "failed"
    ] = "skipped"
    error_messages: list[str] = field(default_factory=list)


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


def _abort(code: str, message: str, req_id: str) -> None:
    """预检失败统一出口：stderr 输出错误码 + 业务主键，并 exit 1。"""
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


# ---------- 4 项预检 ----------


def _precheck_phase(meta: dict[str, Any], req_id: str) -> None:
    phase = meta.get("phase", "")
    if phase not in {"testing", "completed"}:
        _abort(
            "R-ARCHIVE-PHASE",
            f"当前 phase={phase!r}，期望 testing 或 completed",
            req_id,
        )


def _precheck_dirty(req_id: str) -> None:
    try:
        result = _run(["git", "status", "--porcelain"], cwd=REPO_ROOT)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        _abort("R-ARCHIVE-DIRTY", f"git status 调用失败: {exc}", req_id)
    if result.returncode != 0:
        _abort(
            "R-ARCHIVE-DIRTY",
            f"git status 返回非零: {result.stderr.strip() or result.stdout.strip()}",
            req_id,
        )
    if (result.stdout or "").strip():
        _abort(
            "R-ARCHIVE-DIRTY",
            "工作目录有未提交改动；先 commit 再 archive",
            req_id,
        )


def _precheck_pr_number(meta: dict[str, Any], req_id: str) -> int:
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


def _delete_local_branch(
    branch: str,
    base_branch: str,
    *,
    keep_branch: bool,
    yes_local: bool,
    callback: Optional[Callable[[ArchivePrompt], bool]],
    result: ArchiveResult,
) -> None:
    """删本地分支第 4 步前半。-d safe delete，不允许 -D 强删（D-014）。"""
    if keep_branch:
        result.local_branch = "skipped"
        return
    if not branch:
        result.local_branch = "skipped"
        result.error_messages.append("local_branch: meta.branch 为空，跳过删除")
        return
    # 防止误删 base_branch（develop / main / master 不可作为 feature 分支被删）；
    # 即便 base_branch 为空 / 漂移，命中保护分支白名单也直接 fail-closed（F-10 对称）
    if branch == base_branch or branch in _PROTECTED_BRANCHES:
        result.local_branch = "failed"
        msg = (
            f"local_branch: 拒绝删除受保护分支 {branch!r}"
            f"（base_branch={base_branch!r}，meta.branch 可能漂移）"
        )
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
            result.local_branch = "failed"
            result.error_messages.append(msg)
            print(f"⚠️  {msg}", file=sys.stderr)
            return
        try:
            switch_proc = _run(
                ["git", "switch", base_branch], cwd=REPO_ROOT,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            result.local_branch = "failed"
            result.error_messages.append(
                f"local_branch: 自动切 {base_branch!r} 失败（{exc}）；"
                f"请手动 `git switch {base_branch}` 再重跑 archive"
            )
            return
        if switch_proc.returncode != 0:
            err = (switch_proc.stderr or switch_proc.stdout or "").strip() or f"exit={switch_proc.returncode}"
            result.local_branch = "failed"
            result.error_messages.append(
                f"local_branch: 自动切 {base_branch!r} 失败：{err}；"
                f"请手动 `git switch {base_branch}` 再重跑 archive"
            )
            return

    try:
        proc = _run(["git", "branch", "-d", branch], cwd=REPO_ROOT)
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        result.local_branch = "failed"
        result.error_messages.append(f"local_branch: {exc}")
        return
    if proc.returncode != 0:
        # 透传 git 原始错误（squash merge 后会被判 not fully merged，由用户决策）
        msg = (proc.stderr or proc.stdout or "").strip() or f"exit={proc.returncode}"
        result.local_branch = "failed"
        result.error_messages.append(f"local_branch: {msg}")
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
) -> None:
    """删远程分支第 4 步后半。`remote ref does not exist` → already-deleted。

    F-8（codex round-4 P1）：与本地删除路径对称，先把 base_branch 拦下——
    `meta.branch` 误配成 `develop` / `main` / `master` 时，搭配 `--yes-remote-branch`
    或 `y` callback 可能在仓库权限够的情况下删掉关键长寿命分支，必须 fail-closed。
    """
    if keep_branch:
        result.remote_branch = "skipped"
        return
    if not branch:
        result.remote_branch = "skipped"
        return
    # 防止误删 base_branch 远程引用（与 _delete_local_branch 对称）；
    # base_branch 漂移 / 缺失时仍要兜住保护分支白名单（F-10 远程对称兜底）
    if branch == base_branch or branch in _PROTECTED_BRANCHES:
        result.remote_branch = "failed"
        msg = (
            f"remote_branch: 拒绝删除受保护远程分支 {branch!r}"
            f"（base_branch={base_branch!r}，meta.branch 可能漂移）"
        )
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
        return
    if proc.returncode == 0:
        result.remote_branch = "deleted"
        return
    msg = (proc.stderr or proc.stdout or "").strip() or f"exit={proc.returncode}"
    # GitHub「Automatically delete head branches」勾选后 PR merge 即删远程分支；
    # 此处把这种 noisy fail 折叠为正常态，避免误导用户
    if "remote ref does not exist" in msg.lower():
        result.remote_branch = "already-deleted"
        return
    result.remote_branch = "failed"
    result.error_messages.append(f"remote_branch: {msg}")


def _render_summary(result: ArchiveResult) -> str:
    """spec §5.3 第 5 步终端反馈格式（6 行：标题 + phase + archived_at + experience + 本地 + 远程；error_messages 非空时再追加 errors 段）。"""
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
    lines.append("")  # 空行分隔
    lines.append("🟢 archive 前请确认 ci gate exit 0：python3 scripts/gates/run.py --trigger=ci --strict")
    if result.error_messages:
        lines.append("   errors:")
        for msg in result.error_messages:
            lines.append(f"     - {msg}")
    return "\n".join(lines)


# ---------- worktree cleanup（F-005）----------


def _cleanup_worktree_before_archive(meta: dict[str, Any], req_id: str) -> None:
    """预检全部通过后，atomic_write_meta 之前注入 worktree 清理（F-005 / P1-3 修复）。

    三步顺序硬约束（详见 detailed-design §3.5 / P1-3）：
      1. resolve_main_repo_root：从当前 cwd（可能是 worktree 内）解出主仓根
      2. os.chdir(main_repo_root)：保证后续 git 操作（含 archive 自身）在主仓根下
      3. cleanup_worktree_if_owned：owner=workflow → remove；其他 → skipped/aborted/failed

    OD-3 落点：不读 meta.worktree.cleanup.policy（占位字段，本期不消费）。
    设计来源：detailed-design.md:792-826（§3.5）。
    """
    try:
        main_repo_root = worktree_manager.resolve_main_repo_root(Path.cwd())
    except worktree_manager.WorktreeBootstrapError as exc:
        # resolve 规约只抛 WorktreeBootstrapError；非此类型向上传播（fail loud > silent）
        logger.error(
            "worktree cleanup skipped: resolve_main_repo_root failed req_id=%s reason=%s",
            req_id, getattr(exc, "reason", str(exc)),
        )
        return

    # os.chdir 裸调在权限异常或 race 时会 crash archive 主流程，违反 D-009 fail-soft；
    # 用 OSError 兜住，让 cleanup 跳过而非整体 abort。
    try:
        os.chdir(main_repo_root)
    except OSError as exc:
        logger.error(
            "worktree cleanup skipped: chdir to %s failed req_id=%s: %s",
            main_repo_root, req_id, exc,
        )
        return

    cleanup_result = worktree_manager.cleanup_worktree_if_owned(meta, main_repo_root)

    if cleanup_result.action == "removed":
        logger.info("worktree removed: %s", cleanup_result.removed_path)
        # 仅 removed 分支才 mutate meta，避免给 legacy meta 引入空 worktree 段
        meta.setdefault("worktree", {}).setdefault("cleanup", {})["removed_at"] = _now_cst_str()
    elif cleanup_result.action == "skipped":
        logger.info("worktree cleanup skipped: %s", cleanup_result.reason)
    else:
        # aborted / failed：记 error 但不阻塞 archive 主流程（D-009）
        logger.error(
            "worktree cleanup %s: %s", cleanup_result.action, cleanup_result.reason
        )


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

    meta = _load_meta(req_id)

    # —— 1 ~ 5 项预检（任一失败 → SystemExit(1)） ——
    _precheck_phase(meta, req_id)
    _precheck_dirty(req_id)
    pr_number = _precheck_pr_number(meta, req_id)
    _precheck_pr_merged(pr_number, req_id, force=force)
    _precheck_lessons_extracted(meta, req_id)

    # —— worktree cleanup（P1-3 修复：不用 REPO_ROOT，archive 可能从 worktree 内运行）——
    # REPO_ROOT 在 import 时以 cwd 为基准定位，从 worktree 内调时 REPO_ROOT = worktree 根，
    # 直接用会触发 self-remove；必须先 resolve_main_repo_root 再 chdir。
    _cleanup_worktree_before_archive(meta, req_id)

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

    branch = (meta.get("branch") or "").strip()
    base_branch = (meta.get("base_branch") or "").strip()
    # 2026-05-12 spec 修订：删除顺序改 远程 → 本地，让"删本地分支"成为整个 archive 的
    # 最后操作（本地删需要先 git switch <base_branch>，远程删不需要切走）。这样
    # archive 所有 bookkeeping 操作都在原 feat 分支上进行，最后才离开 feat。
    _delete_remote_branch(
        branch,
        base_branch,
        keep_branch=keep_branch,
        yes_remote=yes_remote_branch,
        callback=prompts_callback,
        result=result,
    )
    _delete_local_branch(
        branch,
        base_branch,
        keep_branch=keep_branch,
        yes_local=yes_local_branch,
        callback=prompts_callback,
        result=result,
    )

    print(_render_summary(result))
    return result


# ---------- CLI 入口（命令直接调用时） ----------


def _build_parser():
    import argparse

    p = argparse.ArgumentParser(
        description="archive 子动作：phase=completed + archived_at + 三问串行"
    )
    p.add_argument("req_id", help="REQ-YYYY-NNN")
    p.add_argument("--force", action="store_true",
                   help="跳过 PR merged 校验（异常恢复用）")
    p.add_argument("--keep-branch", action="store_true",
                   help="跳过删本地+远程分支两问")
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
    return p


def main() -> int:
    """CLI 入口：解析命令行参数并调用 archive_requirement；成功返回 0。"""
    args = _build_parser().parse_args()
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
