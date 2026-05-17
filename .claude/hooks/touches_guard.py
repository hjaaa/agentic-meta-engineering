#!/usr/bin/env python3
"""touches_guard.py — F-005 touches 越界软拦截 hook（PreToolUse Edit/Write/MultiEdit）。

职责：
  - 读取当前 feature 的 touches 列表（gitignore glob 风格）
  - 对即将写入的 file_path 检查是否在 touches 范围内
  - 越界 → append 违规记录到 tasks/<feature_id>.receipt.json 的 touches_violations[]
  - 始终 exit 0（fail-open 哲学）

fail-open 理由：
  本 hook 是"软拦截"，目的是记录越界行为供后续 GATE-TOUCHES-VIOLATION 硬拦截使用。
  如果 hook 本身出错导致 exit 非 0，会阻断所有 Edit/Write/MultiEdit 操作，
  造成开发链路死锁。因此顶层 try/except 兜底，始终 exit 0。

两条仓库根判定路径（D-011，来源：requirements/REQ-2026-013/plan.md）：
- `_REPO_ROOT`：file-driven，给 `_is_in_touches` 用（既有行为，不动）
- `_get_worktree_toplevel()`：cwd-driven，给 `_is_out_of_repo` 用（D-006 worktree 语义）
两源在主 repo cwd 下表现一致；仅 worktree edge case 不同。禁止互替。

关键约束（detail-design §3.4 / plan.md ADR D-012）：
  - 仅使用 dispatch_state.read_state()（L2 单读）读取 current_feature
  - 禁止 write_state / flock_state_file with 块（TOCTOU 风险，§3.2）
  - receipt.json RMW 通过 _flock_receipt_file LOCK_EX 序列化（仿 dispatch_state.flock_state_file
    模式：5s timeout + 50ms 轮询；truncate+write+flush+fsync 原地写）
    —— 修复 review-001 F-4 RMW 锁分层盲点（detail-design §3.4 仅覆盖 .dispatch-state.json）

过程产物白名单（hotfix REQ-2026-008 + REQ-2026-010）：
  以下 8 类路径在当前 req_dir 范围内不计为 touches 越界（避免 SOP 必经写入被硬挡）：
    1. <req_dir>/artifacts/tasks/<fid>.receipt.json — dispatch 回执（subagent 写）
    2. <req_dir>/artifacts/tasks/<fid>.md           — task.md 自指（主 Agent status 翻转）
    3. <req_dir>/plan.md                            — req-level 过程产物（ADR / 决策）
    4. <req_dir>/notes.md                           — req-level 过程产物（笔记）
    5. <req_dir>/meta.yaml                          — req-level 元数据（phase / signoff）
    6. <req_dir>/process.txt                        — req-level 时间线（progress logger）
    7. <req_dir>/artifacts/review-*.md              — code-review-report 嵌入模式审查报告
    8. <req_dir>/.dispatch-state.json               — dispatch lock 自身（acquire / release / cleanup）
  仅当前 req_dir 命中；跨需求的同名文件不豁免（白名单不过宽）。

依赖：
  - pathspec（GitIgnoreSpec，仓库已用）
  - dispatch_state.read_state（L2 API）
  - CLAUDE_DISPATCH_TEST_REQ_DIR_OVERRIDE env 后门（仅测试用）
"""
from __future__ import annotations

import fcntl
import json
import logging
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Iterator, Optional

# ---- 路径 / sys.path 初始化 ----
# .claude/hooks/touches_guard.py → repo root = ../../
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_LIB = _REPO_ROOT / "scripts" / "lib"
if str(_SCRIPTS_LIB) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_LIB))

# yaml 懒导入（与 dispatch_precheck.py 风格一致）
try:
    import yaml as _yaml
    _YAML_AVAILABLE = True
except ImportError:
    _yaml = None  # type: ignore[assignment]
    _YAML_AVAILABLE = False

# pathspec 懒导入
try:
    import pathspec as _pathspec
    _PATHSPEC_AVAILABLE = True
except ImportError:
    _pathspec = None  # type: ignore[assignment]
    _PATHSPEC_AVAILABLE = False

# dispatch_state 懒导入（F-001 产出，§3.4 L2 read_state）
try:
    import dispatch_state as _dispatch_state
    _DISPATCH_STATE_AVAILABLE = True
except ImportError:
    _dispatch_state = None  # type: ignore[assignment]
    _DISPATCH_STATE_AVAILABLE = False

# ---------- 常量 ----------

_RECEIPT_SCHEMA_VERSION = "1.0"

# receipt.json LOCK_EX 等待上限；与 dispatch_state.LOCK_TIMEOUT_S 一致
_RECEIPT_LOCK_TIMEOUT_S: float = 5.0
# LOCK_EX 轮询间隔；与 dispatch_state.POLL_INTERVAL_S 一致
_RECEIPT_POLL_INTERVAL_S: float = 0.05

# 模块级 logger；hook fail-open 哲学下仅做 audit，不抛
logger = logging.getLogger("touches_guard")


# ---------- receipt.json 锁层（修复 review-001 F-4 / 仿 dispatch_state.flock_state_file 模式） ----------


@contextmanager
def _flock_receipt_file(receipt_path: Path) -> Iterator[IO[str]]:
    """receipt.json 的 LOCK_EX 上下文管理器（与 dispatch_state.flock_state_file 同模式）。

    用法（_record_violation 单锁原子，杜绝 RMW 覆盖）::

        with _flock_receipt_file(receipt_path) as f:
            data = _read_receipt_from_fd(f, feature_id)
            data["touches_violations"].append(entry)
            _write_receipt_to_fd(f, data)

    实现：
      - 模式 'r+'：read+write 复用同一 fd，read/write 都在锁内
      - 文件不存在 → 先建空骨架 "{}"（'r+' 要求文件预先存在；read 仍走骨架补齐）
      - LOCK_EX + LOCK_NB 轮询；5s timeout + 50ms 间隔
      - write 路径用 truncate+write+flush+fsync 原地写（rename 会换 inode 致 fd 失效）

    异常：
      - TimeoutError：5s 内未取到锁（调用方 fail-open 兜底）
      - OSError：磁盘 / 权限错误
    """
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    if not receipt_path.exists():
        receipt_path.write_text("{}", encoding="utf-8")

    f = receipt_path.open("r+", encoding="utf-8")
    try:
        deadline = time.monotonic() + _RECEIPT_LOCK_TIMEOUT_S
        while True:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise TimeoutError(
                        f"flock receipt timeout {_RECEIPT_LOCK_TIMEOUT_S}s: {receipt_path}"
                    )
                time.sleep(_RECEIPT_POLL_INTERVAL_S)
        try:
            yield f
        finally:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
    finally:
        f.close()


def _read_receipt_from_fd(f: IO[str], feature_id: str) -> dict:
    """从已持锁的 fd 读 receipt.json；不存在 / 格式错 → 建骨架。

    merge 语义：保留已有字段（subagent 完整 receipt 字段），仅补齐 3 个骨架字段。
    骨架结构（detail-design §3.4 / receipt-schema.yaml 基准 3 字段）：
      { feature_id, schema_version, touches_violations }
    """
    f.seek(0)
    text = f.read()
    if not text.strip():
        data: dict = {}
    else:
        try:
            data = json.loads(text)
            if not isinstance(data, dict):
                data = {}
        except json.JSONDecodeError:
            data = {}

    data.setdefault("feature_id", feature_id)
    data.setdefault("schema_version", _RECEIPT_SCHEMA_VERSION)
    data.setdefault("touches_violations", [])
    if not isinstance(data.get("touches_violations"), list):
        data["touches_violations"] = []
    return data


def _write_receipt_to_fd(f: IO[str], data: dict) -> None:
    """truncate + write + flush + fsync 原地写（仿 dispatch_state.StateFileHandle.write）。

    LOCK_EX 持锁期内 truncate 瞬间无并发观测窗口；与 atomic rename 不同，
    rename 会换 inode 致 with 块内 fd 后续操作作用于旧 inode（plan.md ADR D-010 同模式）。
    """
    text = json.dumps(data, ensure_ascii=False, indent=2)
    f.seek(0)
    f.truncate(0)
    f.write(text)
    f.flush()
    try:
        os.fsync(f.fileno())
    except OSError:
        # 某些 fs（tmpfs / 测试环境）不支持 fsync；忽略（与 dispatch_state 同处理）
        pass


# ---------- 辅助函数 ----------


def _get_worktree_toplevel() -> Optional[Path]:
    """调 `git rev-parse --show-toplevel` 返回 cwd 所在仓库根；非 git 目录返回 None。

    缓存策略：函数局部不缓存（单次 hook 调用内被 _is_out_of_repo 复用一次，无需 lru_cache）。
    """
    import subprocess
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if result.returncode != 0:
            return None
        return Path(result.stdout.strip()).resolve()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _is_out_of_repo(file_path: str, toplevel: Optional[Path]) -> bool:
    """判断 file_path 是否在 toplevel 子树之外。toplevel 为 None（非 git 目录）时返回 False（fail-open）。

    Args:
        file_path: 来自 tool_input 的原始 file_path（可能是绝对路径或相对路径）
        toplevel: _get_worktree_toplevel() 返回值

    Returns:
        True 表示文件在仓库外，调用方应短路跳过 violation 记录；
        False 表示文件在仓库内或 toplevel 不可用（fail-open）。
    """
    if toplevel is None:
        return False  # fail-open：非 git 目录走原 in-touches 路径
    try:
        resolved = Path(file_path).resolve()
    except (OSError, ValueError):
        return False  # fail-open：路径解析失败
    try:
        resolved.relative_to(toplevel)
        return False  # 在 toplevel 子树内
    except ValueError:
        return True  # 在 toplevel 子树外 → out-of-repo


def _locate_req_dir() -> Optional[Path]:
    """定位当前需求根目录。

    优先读 CLAUDE_DISPATCH_TEST_REQ_DIR_OVERRIDE（测试后门），
    否则复用 dispatch_precheck.locate_req_dir_by_branch 模式，
    但以独立实现避免直接 import（F-004 文件禁止触碰）。

    返回 Path 或 None（fail-open）。
    """
    # 测试后门（仅 bats sandbox 使用；生产环境不应出现）
    test_override = os.environ.get("CLAUDE_DISPATCH_TEST_REQ_DIR_OVERRIDE")
    if test_override:
        p = Path(test_override)
        if p.exists() and p.is_dir():
            return p
        return None

    if not _YAML_AVAILABLE:
        return None

    # 通过 git 分支匹配 meta.yaml.branch 找到 req_dir
    branch = _current_branch()
    if not branch:
        return None

    requirements_dir = _REPO_ROOT / "requirements"
    if not requirements_dir.exists():
        return None

    for meta_path in requirements_dir.glob("*/meta.yaml"):
        try:
            with meta_path.open("r", encoding="utf-8") as f:
                meta = _yaml.safe_load(f)
            if isinstance(meta, dict) and meta.get("branch") == branch:
                return meta_path.parent
        except (OSError, _yaml.YAMLError):
            continue
    return None


def _current_branch() -> Optional[str]:
    """git rev-parse --abbrev-ref HEAD；失败返回 None。"""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=2.0,
            cwd=_REPO_ROOT,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip() or None
    except (subprocess.TimeoutExpired, OSError):
        return None


def _read_current_feature(req_dir: Path) -> Optional[str]:
    """通过 dispatch_state.read_state()（L2 单读）获取 current_feature。

    约束：仅调用 read_state，禁止 write_state 或 with flock_state_file（§3.4）。
    返回 feature_id 字符串或 None（未激活 / dispatch_state 不可用 / 状态为空 / 锁竞争超时）。

    异常分流（修复 review-001 F-6 / plan.md ADR D-012）：
      - TimeoutError：单独 logger.warning，audit 区分锁竞争 vs 冷启动；fail-open return None
      - 其他异常：合流 return None（fail-open，避免阻断写操作）
    """
    if not _DISPATCH_STATE_AVAILABLE:
        return None
    try:
        state = _dispatch_state.read_state(req_dir)
        if state is None:
            return None
        # DispatchState 是 TypedDict（运行时为普通 dict），用 .get() 访问字段
        fid = state.get("current_feature")
        return fid if isinstance(fid, str) else None
    except TimeoutError as exc:
        # 锁竞争：与"state 不存在（冷启动）"语义不同，事后 audit 应可区分
        logger.warning(
            "touches_guard: dispatch_state read timeout (lock contention), fail-open: %s",
            exc,
        )
        return None
    except Exception as exc:
        logger.debug("_read_current_feature failed (non-timeout): %s", exc)
        return None


def _read_touches(req_dir: Path, feature_id: str) -> Optional[list[str]]:
    """读 tasks/<feature_id>.md frontmatter 中的 touches 字段。

    返回 glob 字符串列表；失败返回 None（fail-open）。
    """
    if not _YAML_AVAILABLE:
        return None
    task_md = req_dir / "artifacts" / "tasks" / f"{feature_id}.md"
    if not task_md.exists():
        return None
    try:
        content = task_md.read_text(encoding="utf-8")
    except OSError:
        return None

    # 提取 frontmatter（首对 ---...--- 之间的 YAML）
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return None

    fm_text = "\n".join(lines[1:end_idx])
    try:
        fm = _yaml.safe_load(fm_text)
    except _yaml.YAMLError:
        return None

    if not isinstance(fm, dict):
        return None
    touches = fm.get("touches", [])
    if not isinstance(touches, list):
        return None
    return [str(t) for t in touches]


def _is_in_touches(file_path: str, touches: list[str]) -> bool:
    """用 pathspec.GitIgnoreSpec 检查 file_path 是否命中 touches 列表。

    file_path 需转为相对于 repo root 的路径（pathspec 用相对路径匹配）。
    """
    if not _PATHSPEC_AVAILABLE:
        # pathspec 不可用时 fail-open（允许写入）
        return True
    if not touches:
        # touches 为空 → 不限制（fail-open）
        return True

    spec = _pathspec.PathSpec.from_lines("gitwildmatch", touches)
    # 统一用 POSIX 路径做匹配（pathspec 不接受 Windows 反斜杠）
    posix_path = Path(file_path).as_posix()
    # 去掉前缀 /（绝对路径 → 相对路径，与 repo root 对齐）
    if posix_path.startswith("/"):
        try:
            rel = Path(file_path).relative_to(_REPO_ROOT)
            posix_path = rel.as_posix()
        except ValueError:
            # 不在 repo 内 → 不在 touches 内，视为越界
            return False
    return spec.match_file(posix_path)


def _extract_file_paths(tool_name: str, tool_input: dict) -> list[str]:
    """从 tool_input 提取所有受影响的 file_path。

    Edit/Write/MultiEdit 都使用顶层 tool_input.file_path（指向单个文件）。
    MultiEdit 的 edits[] 只携带 (old_string, new_string) 对，不含 file_path
    ——和 pre-tool-use-guard.sh 的 jq '.tool_input.file_path' 读法保持一致。
    """
    paths: list[str] = []
    if tool_name in ("Edit", "Write", "MultiEdit"):
        fp = tool_input.get("file_path")
        if isinstance(fp, str) and fp:
            paths.append(fp)
    return paths


def _is_process_artifact(fp: str, req_dir: Path, feature_id: str) -> bool:
    """判断 fp 是否落在当前 req_dir 范围内的"过程产物白名单"中（hotfix REQ-2026-008 + REQ-2026-010）。

    覆盖 8 类（见模块 docstring）：
      1. <req_dir>/artifacts/tasks/<fid>.receipt.json
      2. <req_dir>/artifacts/tasks/<fid>.md
      3. <req_dir>/plan.md
      4. <req_dir>/notes.md
      5. <req_dir>/meta.yaml
      6. <req_dir>/process.txt
      7. <req_dir>/artifacts/review-*.md  ← code-review-report Skill 嵌入模式产物
      8. <req_dir>/.dispatch-state.json   ← dispatch lock 自身（acquire / release / cleanup 写入）

    前 6 + 第 8 类按 resolve 后绝对路径精确匹配；第 7 类为 pattern（parent ==
    <req_dir>/artifacts 且 name 形如 `review-*.md`），不依赖 IO（避免 glob 副作用）。

    仅当 fp 解析后命中"当前 req_dir 内"任一条目才返回 True；
    跨需求同名文件（如 <other_req_dir>/plan.md、<other_req_dir>/.dispatch-state.json）不豁免。

    任何 resolve 异常 → 返回 False（fail-open 回原行为：当作越界记录）。
    """
    try:
        fp_resolved = Path(fp).resolve()
    except Exception:
        return False

    try:
        req_resolved = req_dir.resolve()
    except Exception:
        return False

    candidates = [
        req_resolved / "artifacts" / "tasks" / f"{feature_id}.receipt.json",
        req_resolved / "artifacts" / "tasks" / f"{feature_id}.md",
        req_resolved / "plan.md",
        req_resolved / "notes.md",
        req_resolved / "meta.yaml",
        req_resolved / "process.txt",
        req_resolved / ".dispatch-state.json",
    ]
    for cand in candidates:
        try:
            # cand 可能尚不存在；Path.resolve(strict=False) 在不存在时返回规范化绝对路径
            if fp_resolved == cand.resolve():
                return True
        except Exception:
            continue

    # 第 7 类（pattern）：<req_dir>/artifacts/review-*.md
    # code-review-report Skill 嵌入模式写盘到 artifacts/review-YYYYMMDD-HHMMSS.md，
    # 是 SOP 必经路径；用 parent + name 模式判定避免 glob/IO，跨需求自然不命中。
    try:
        artifacts_dir = (req_resolved / "artifacts").resolve()
        if (
            fp_resolved.parent == artifacts_dir
            and fp_resolved.name.startswith("review-")
            and fp_resolved.suffix == ".md"
        ):
            return True
    except Exception:
        pass

    return False


def _record_violation(
    receipt_path: Path,
    feature_id: str,
    file_path: str,
    tool_name: str,
) -> None:
    """将越界记录 append 到 receipt.json 的 touches_violations[]。

    锁内 RMW（修复 review-001 F-4 / plan.md ADR D-012）：
      with LOCK_EX：
        1. 读 fd → 加载或初始化骨架
        2. 追加 violation 条目
        3. truncate+write+flush+fsync 原地写

    并发安全：与 dispatch_state.flock_state_file 同模式。两个并发 hook 串行通过锁，
    避免各自 base 旧版后互相覆盖 violation entry。

    异常：
      - TimeoutError（5s 锁超时）/ OSError → 由调用方 fail-open 兜底
    """
    entry = {
        "path": file_path,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool": tool_name,
    }
    with _flock_receipt_file(receipt_path) as f:
        data = _read_receipt_from_fd(f, feature_id)
        data["touches_violations"].append(entry)
        _write_receipt_to_fd(f, data)


def _main_inner(stdin_data: str) -> None:
    """主逻辑：解析 stdin → 定位 req_dir → 读 current_feature → 检查 touches → 记录越界。

    所有失败路径均 fail-open（直接 return，不抛出）。
    """
    # 1. 解析 stdin JSON
    try:
        payload = json.loads(stdin_data)
    except (json.JSONDecodeError, ValueError):
        return  # fail-open：stdin 非法

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {})
    if not isinstance(tool_input, dict):
        tool_input = {}

    # 2. 仅处理 Edit/Write/MultiEdit
    if tool_name not in ("Edit", "Write", "MultiEdit"):
        return

    # 3. 提取 file_path 列表
    file_paths = _extract_file_paths(tool_name, tool_input)
    if not file_paths:
        return  # fail-open：无有效路径

    # 4. 定位 req_dir
    req_dir = _locate_req_dir()
    if req_dir is None:
        return  # fail-open：不在需求分支上

    # 5. 读 current_feature（L2 单读，§3.4）
    feature_id = _read_current_feature(req_dir)
    if not feature_id:
        return  # fail-open：无活跃 feature

    # 6. 读 touches
    touches = _read_touches(req_dir, feature_id)
    if touches is None:
        return  # fail-open：无法读取 touches

    # 7. 检查每个 file_path，记录越界
    #    过程产物白名单（hotfix REQ-2026-008 + REQ-2026-010）：8 类路径在当前
    #    req_dir 范围内豁免，避免 SOP 必经写入（receipt.json 自指 / task.md status
    #    翻转 / plan.md ADR 落地 / notes.md 笔记 / meta.yaml signoff / process.txt
    #    进度 / artifacts/review-*.md 审查报告 / .dispatch-state.json lock 自身）
    #    被记为越界硬挡 GATE-TOUCHES-VIOLATION。详见 _is_process_artifact docstring。
    receipt_path = req_dir / "artifacts" / "tasks" / f"{feature_id}.receipt.json"
    toplevel = _get_worktree_toplevel()  # 新增：单次 hook 调用内只取一次
    for fp in file_paths:
        if _is_out_of_repo(fp, toplevel):
            continue  # 新增：out-of-repo 短路（D-006 + D-011）
        if not _is_in_touches(fp, touches):
            if _is_process_artifact(fp, req_dir, feature_id):
                continue
            try:
                _record_violation(receipt_path, feature_id, fp, tool_name)
            except Exception:
                # 记录失败 fail-open（不阻断写操作）
                pass


def main() -> None:
    """入口：读 stdin → 调 _main_inner → 始终 exit 0。"""
    try:
        stdin_data = sys.stdin.read()
        _main_inner(stdin_data)
    except Exception:
        # 顶层兜底：任何未预期异常 fail-open
        pass
    sys.exit(0)


if __name__ == "__main__":
    main()
