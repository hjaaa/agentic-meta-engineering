#!/usr/bin/env python3
"""派发前置 PreToolUse hook（F-004 / detail-design §2）。

触发：guard.sh Agent case 透传 stdin JSON
契约（detail-design §2.1）：
  exit 0 → 放行（含所有 fail-open 分支）
  exit 2 → 阻断；stderr 输出 BLOCKED 消息

校验链时序（detail-design §2.4）：
  [1] 解析 stdin JSON          → 失败 fail-open
  [2] tool_name == "Agent"      → 否则 fail-open（场景 1，D-007 实采样）
  [3] tool_input.prompt 取值    → 缺失 fail-open
  [4] parse_feature_id(prompt)  → 失败 fail-open
  [5] locate_req_dir_by_branch  → git 分支 → 匹配 meta.yaml.branch
  [6] 读 features.json          → 解析 / 不存在 fail-open
  [7] feature_id ∈ features     → 否则 fail-open
  [8] with flock_state_file:    ← **同一把锁内**完成读+三校验+写（TOCTOU 修复）
        [8a] state = fh.read()
        [8b] B-1: tasks/<fid>.md frontmatter.status == "pending"（**source of truth**）
        [8c] B-2: depends_on_features 全 done
        [8d] B-3: state["current_feature"] is None or == feature_id
        [8e] 三校验任一失败 → exit 2 + BLOCKED stderr
        [8f] 三校验全过 → fh.write(...)（current_feature=feature_id）
  [9] exit 0 + audit_log

防御性约束（用户指令）：
  - 顶层 try/except Exception 兜底 → sys.exit(0)（fail-open）
  - 严禁捕获 SystemExit（必须 raise）；只捕 Exception
  - 任何已知 fail-open 场景内部直接 return 0；未预期异常被顶层兜底
  - 为什么：本 hook 一旦 exit≠0/2 → PreToolUse 拦死整个 Agent 派发链 → 当前会话死锁

bypass 校验：guard.sh 入口已吃掉 CLAUDE_GATES_GLOBAL_BYPASS，本文件不重复实现。
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------- 路径 / 常量 ----------

# .claude/hooks/dispatch_precheck.py → repo root = ../../
_REPO_ROOT = Path(__file__).resolve().parents[2]

# audit 行 entry 字段（与 guard.sh 的 ENTRY="pre-tool-use-guard" 区分）
_ENTRY = "dispatch-precheck"

# feature_id 解析 regex（D-005 #3 / D-007）：必须独占一行
_FEATURE_ID_RE = re.compile(r"^feature_id:\s*(F-\d{3})\s*$", re.MULTILINE)

# parse_feature_id 仅扫 prompt 首部 5 行；超出则视同未声明
_PARSE_HEAD_LINES = 5

# yaml lazy import（F-7）：顶层一次，定义 _yaml 与 _YAML_AVAILABLE
try:
    import yaml as _yaml
    _YAML_AVAILABLE = True
except ImportError:
    _yaml = None  # type: ignore[assignment]
    _YAML_AVAILABLE = False


# ---------- audit 日志（与 guard.sh audit_log 行为等价） ----------

def _detect_audit_root() -> Path:
    """audit root：env 优先；回退到 _REPO_ROOT（与 guard.sh `_audit_root` 同语义）。"""
    env_root = os.environ.get("CLAUDE_GATES_AUDIT_ROOT")
    if env_root:
        return Path(env_root)
    return _REPO_ROOT


def audit_log(line: str) -> None:
    """写一行到 audit/.queue/<date>.log；任何失败 silently swallow。"""
    try:
        root = _detect_audit_root()
        queue_dir = root / "audit" / ".queue"
        queue_dir.mkdir(parents=True, exist_ok=True)
        # ISO8601 with offset；与 guard.sh `date -Iseconds` 接近
        ts = datetime.now().astimezone().isoformat(timespec="seconds")
        cwd = os.getcwd()
        log_line = f"{ts} {cwd} {line} @ entry={_ENTRY}\n"
        log_file = queue_dir / f"{date.today():%Y-%m-%d}.log"
        with log_file.open("a", encoding="utf-8") as f:
            f.write(log_line)
    except OSError:
        # silently swallow（与 guard.sh audit_log 行为一致）
        pass


# ---------- 解析 / 定位辅助函数 ----------

def parse_feature_id(prompt: str) -> Optional[str]:
    """从 prompt 文本前 5 行解析 `feature_id: F-xxx`（D-005 #3 / D-007）。

    硬约束：feature_id 必须独占一行，行首无前缀（regex `^feature_id:...$` MULTILINE）。
    返回 None 表示解析失败 → 调用方 fail-open。
    """
    if not isinstance(prompt, str) or not prompt:
        return None
    head = "\n".join(prompt.splitlines()[:_PARSE_HEAD_LINES])
    m = _FEATURE_ID_RE.search(head)
    if not m:
        return None
    return m.group(1)


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
        b = result.stdout.strip()
        return b or None
    except (subprocess.TimeoutExpired, OSError):
        return None


def _try_load_meta_branch(meta_path: Path) -> Optional[str]:
    """从单个 meta.yaml 读取 branch 字段（F-6：抽出嵌套层）。

    成功返回 branch 字符串；失败（IO/YAML 解析/类型错误）返回 None。
    """
    if not _YAML_AVAILABLE:
        return None
    try:
        with meta_path.open("r", encoding="utf-8") as f:
            meta = _yaml.safe_load(f)
    except (OSError, _yaml.YAMLError):
        return None
    if isinstance(meta, dict):
        branch = meta.get("branch")
        if isinstance(branch, str):
            return branch
    return None


def locate_req_dir_by_branch() -> Optional[Path]:
    """通过当前 git 分支匹配 meta.yaml.branch 找到对应 req_dir。

    扫 requirements/*/meta.yaml；branch 字段命中即返回。
    失败返回 None → 调用方 fail-open。

    测试后门（env CLAUDE_DISPATCH_TEST_REQ_DIR_OVERRIDE）：
      - 存在时直接返回 env 指向路径，绕过 git 分支匹配
      - 仅 bats 沙盒用例（TC-F4-3/4/5）使用，类比既有 CLAUDE_GATES_AUDIT_ROOT
      - 生产环境该变量不应出现；后续如需保护可加 CI/CLAUDE_DISPATCH_TEST_MODE 双重确认
      - 详见 plan.md ADR D-011
    """
    # 测试 backdoor：仅供 bats 用例隔离 sandbox req（避免污染真 git 分支）
    test_override = os.environ.get("CLAUDE_DISPATCH_TEST_REQ_DIR_OVERRIDE")
    if test_override:
        p = Path(test_override)
        if p.exists() and p.is_dir():
            return p
        return None

    if not _YAML_AVAILABLE:
        return None

    branch = _current_branch()
    if not branch:
        return None
    requirements_dir = _REPO_ROOT / "requirements"
    if not requirements_dir.exists():
        return None

    for meta_path in requirements_dir.glob("*/meta.yaml"):
        meta_branch = _try_load_meta_branch(meta_path)
        if meta_branch == branch:
            return meta_path.parent
    return None


def _read_task_status(tasks_dir: Path, fid: str) -> Optional[str]:
    """从 tasks/<fid>.md frontmatter 读 status 字段（**source of truth**，detail-design §2.1.1）。

    返回值：
      - "pending" / "in-progress" / "done" 等字符串 → 实际值
      - None → 文件不存在 / parse 失败 / 缺 status 字段（调用方 fail-open 或 BLOCKED 视场景）
    """
    if not _YAML_AVAILABLE:
        return None
    task_path = tasks_dir / f"{fid}.md"
    if not task_path.exists():
        return None
    try:
        text = task_path.read_text(encoding="utf-8")
    except OSError:
        return None
    # 简易 frontmatter 解析：第一行 "---" 起，到下一个 "---" 止
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    fm_lines: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        fm_lines.append(line)
    else:
        # 没找到结束 ---
        return None
    try:
        fm = _yaml.safe_load("\n".join(fm_lines))
    except Exception:  # noqa: BLE001
        return None
    if not isinstance(fm, dict):
        return None
    status = fm.get("status")
    if not isinstance(status, str):
        return None
    return status


# ---------- 主流程辅助函数（F-1/F-2/F-5：_main_inner 拆分） ----------

def _format_blocked(message: str) -> None:
    """把 BLOCKED 消息写到 stderr（PreToolUse 协议会回传 Agent）。"""
    sys.stderr.write(message)
    if not message.endswith("\n"):
        sys.stderr.write("\n")
    sys.stderr.flush()


def _block_and_exit(msg: str, audit_tag: str) -> int:
    """B-1/B-2/B-3 共享：输出 BLOCKED 消息 + audit_log + return 2。"""
    _format_blocked(msg)
    audit_log(audit_tag)
    return 2


def _parse_payload(stdin_text: str) -> Optional[Tuple[str, str]]:
    """步骤 [1]-[4]：解析 stdin → 返回 (feature_id, prompt) 或 None（fail-open）。

    返回 None 表示 fail-open（已自行写 audit_log）。
    """
    if not stdin_text:
        audit_log("FAIL_OPEN: stdin empty")
        return None
    try:
        payload = json.loads(stdin_text)
    except json.JSONDecodeError:
        audit_log("FAIL_OPEN: stdin parse error")
        return None
    if not isinstance(payload, dict):
        audit_log("FAIL_OPEN: stdin payload not object")
        return None

    # [2] 断言 tool_name == "Agent"（D-007 实采样确认）
    if payload.get("tool_name") != "Agent":
        # 场景 1：非 Agent 调用 → 静默 fail-open（避免污染 audit）
        return None

    # [3] 取 tool_input.prompt
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        audit_log("FAIL_OPEN: tool_input not object")
        return None
    prompt = tool_input.get("prompt")
    if not isinstance(prompt, str) or not prompt:
        audit_log("FAIL_OPEN: prompt missing")
        return None

    # [4] parse_feature_id
    fid = parse_feature_id(prompt)
    if not fid:
        import hashlib
        head = "\n".join(prompt.splitlines()[:_PARSE_HEAD_LINES])
        digest = hashlib.sha256(head.encode("utf-8", errors="replace")).hexdigest()[:16]
        audit_log(f"FAIL_OPEN: feature_id unresolved | head_sha256={digest}")
        return None

    return fid, prompt


def _resolve_feature_context(
    fid: str,
    req_dir: Path,
) -> Optional[Tuple[Dict[str, Any], Path, str]]:
    """步骤 [5]-[7]：locate_req_dir + features.json 读取 + feature 查找。

    返回 (feature_dict, tasks_dir, req_id) 或 None（fail-open，已写 audit_log）。
    req_dir 由调用方传入（已做 locate_req_dir_by_branch）。
    """
    req_id = req_dir.name
    features_path = req_dir / "artifacts" / "features.json"
    if not features_path.exists():
        audit_log(f"FAIL_OPEN: features.json absent | req={req_id}")
        return None
    try:
        features_data = json.loads(features_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        audit_log(f"FAIL_OPEN: features.json parse error | req={req_id}")
        return None
    if not isinstance(features_data, dict):
        audit_log(f"FAIL_OPEN: features.json not object | req={req_id}")
        return None
    features_list = features_data.get("features")
    if not isinstance(features_list, list):
        audit_log(f"FAIL_OPEN: features.json missing features[] | req={req_id}")
        return None

    # [7] feature_id ∈ features
    feature_map: Dict[str, Dict[str, Any]] = {}
    for item in features_list:
        if isinstance(item, dict):
            iid = item.get("id")
            if isinstance(iid, str):
                feature_map[iid] = item
    if fid not in feature_map:
        audit_log(f"FAIL_OPEN: feature_id {fid} not found | req={req_id}")
        return None

    tasks_dir = req_dir / "artifacts" / "tasks"
    return feature_map[fid], tasks_dir, req_id


def _check_and_acquire(
    fh: Any,
    fid: str,
    feature: Dict[str, Any],
    tasks_dir: Path,
    req_id: str,
) -> int:
    """步骤 [8]：单 with 锁内三校验+写。返回 exit code（0=放行/2=阻断）。

    调用方必须在 flock_state_file with 块内调用此函数（fh 是 StateFileHandle）。
    """
    # [8a] 锁内读
    state = fh.read()

    # [8b] B-1: 当前 feature 状态必须 == "pending"（source of truth: tasks/<fid>.md）
    cur_status = _read_task_status(tasks_dir, fid)
    if cur_status is None:
        # task.md 不存在 / parse 失败 / 缺 status → 视同未派发过（fail-open）
        audit_log(f"FAIL_OPEN: task.md status missing | req={req_id} | fid={fid}")
        return 0
    if cur_status != "pending":
        return _block_and_exit(
            f"BLOCKED: {fid} 状态为 {cur_status}，期望 pending；"
            f"如要重派需先回退状态。\n"
            f"紧急绕过：CLAUDE_GATES_GLOBAL_BYPASS=\"<原因 ≥ 8 字符>\" 重新执行。",
            f"BLOCKED B-1: {fid} status={cur_status} | req={req_id}",
        )

    # [8c] B-2: depends_on_features 全 done
    depends_on: List[str] = feature.get("depends_on_features") or []
    if not isinstance(depends_on, list):
        depends_on = []
    unfinished: list[tuple[str, str]] = []
    for dep_fid in depends_on:
        if not isinstance(dep_fid, str):
            continue
        dep_status = _read_task_status(tasks_dir, dep_fid)
        if dep_status != "done":
            unfinished.append((dep_fid, dep_status or "missing"))
    if unfinished:
        deps_str = ",".join(f"{f}({s})" for f, s in unfinished)
        return _block_and_exit(
            f"BLOCKED: {fid} 依赖 [{deps_str}] 未全部 done。\n"
            f"修复：先完成上述依赖 feature；或紧急绕过 "
            f"CLAUDE_GATES_GLOBAL_BYPASS=\"<原因 ≥ 8 字符>\"。",
            f"BLOCKED B-2: {fid} deps={deps_str} | req={req_id}",
        )

    # [8d] B-3: state.current_feature 必须 None 或 == fid
    cur_fid = None
    cur_at = None
    if state and isinstance(state, dict):
        cur_fid = state.get("current_feature")
        cur_at = state.get("acquired_at")
    if cur_fid is not None and cur_fid != fid:
        return _block_and_exit(
            f"BLOCKED: 已有 {cur_fid} 派发中（acquired_at={cur_at}），"
            f"保守档串行约束禁止并发派 implementer。\n"
            f"修复：等 {cur_fid} 完成后再派 {fid}；或紧急绕过 "
            f"CLAUDE_GATES_GLOBAL_BYPASS=\"<原因 ≥ 8 字符>\"。",
            f"BLOCKED B-3: current={cur_fid} new={fid} | req={req_id}",
        )

    # [8f] 三校验全过 → 锁内写
    import scripts.lib.dispatch_state as _dispatch_state_mod
    now_iso = datetime.now().astimezone().isoformat(timespec="seconds")
    new_state: _dispatch_state_mod.DispatchState = {
        "schema_version": "1.0",
        "req_id": req_id,
        "current_feature": fid,
        "acquired_at": now_iso,
        "acquired_by_pid": os.getpid(),
    }
    try:
        fh.write(new_state)
    except OSError as exc:
        audit_log(f"FAIL_OPEN: state write failed | {exc}")
        return 0
    return 0


def _main_inner() -> int:
    """主流程编排层（~25 行）；任何已知 fail-open 场景内部直接 return 0；未预期异常由 main() 顶层兜底。

    禁止 raise SystemExit；只 return int。
    """
    # [1] 读 stdin
    try:
        raw = sys.stdin.read()
    except OSError:
        audit_log("FAIL_OPEN: stdin read error")
        return 0

    # [1]-[4] 解析 payload → (fid, prompt)
    parsed = _parse_payload(raw)
    if parsed is None:
        return 0
    fid, _prompt = parsed

    # [5] locate_req_dir_by_branch
    req_dir = locate_req_dir_by_branch()
    if not req_dir:
        audit_log(f"FAIL_OPEN: req_dir unresolved | feature_id={fid}")
        return 0
    req_id = req_dir.name

    # [6]-[7] features.json + feature 查找
    ctx = _resolve_feature_context(fid, req_dir)
    if ctx is None:
        return 0
    feature, tasks_dir, req_id = ctx

    # [8] with flock_state_file: 单锁内 read+三校验+write（TOCTOU 修复）
    # import 在这里以避免顶层失败拦死 hook：dispatch_state 缺失 → fail-open
    try:
        if str(_REPO_ROOT) not in sys.path:
            sys.path.insert(0, str(_REPO_ROOT))
        from scripts.lib import dispatch_state
    except ImportError as exc:
        audit_log(f"FAIL_OPEN: dispatch_state import error | {exc}")
        return 0

    try:
        with dispatch_state.flock_state_file(req_dir) as fh:
            rc = _check_and_acquire(fh, fid, feature, tasks_dir, req_id)
            if rc != 0:
                return rc
    except TimeoutError:
        audit_log(f"FAIL_OPEN: state lock timeout | req={req_id} | fid={fid}")
        return 0
    except ValueError as exc:
        audit_log(f"FAIL_OPEN: state json invalid | {exc}")
        return 0
    except OSError as exc:
        audit_log(f"FAIL_OPEN: state io error | {exc}")
        return 0

    # [9] 成功放行
    audit_log(f"DISPATCH_OK: {fid} | req={req_id}")
    return 0


def main() -> int:
    """顶层入口；catch-all `except Exception` 兜底转 0（fail-open）。

    禁止捕获 SystemExit（让 sys.exit(0) 正常退出）。
    """
    try:
        return _main_inner()
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        # 场景 10：任何未预期异常；audit 记录类型 + 截断的消息便于排查
        try:
            audit_log(f"FAIL_OPEN: unexpected | {type(exc).__name__}:{str(exc)[:200]}")
        except Exception:  # noqa: BLE001
            pass
        return 0


if __name__ == "__main__":
    sys.exit(main())
