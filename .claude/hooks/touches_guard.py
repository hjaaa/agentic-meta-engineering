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

关键约束（detail-design §3.4）：
  - 仅使用 dispatch_state.read_state()（L2 单读）读取 current_feature
  - 禁止 write_state / flock_state_file with 块（TOCTOU 风险，§3.2）
  - receipt.json 写入用 atomic rename（tmp file + os.replace），并发安全

依赖：
  - pathspec（GitIgnoreSpec，仓库已用）
  - dispatch_state.read_state（L2 API）
  - CLAUDE_DISPATCH_TEST_REQ_DIR_OVERRIDE env 后门（仅测试用）
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

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

# ---------- 骨架常量 ----------

_RECEIPT_SCHEMA_VERSION = "1.0"

# ---------- 辅助函数 ----------


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
    返回 feature_id 字符串或 None（未激活 / dispatch_state 不可用 / 状态为空）。
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
    except Exception:
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

    Edit/Write：tool_input.file_path（单个）
    MultiEdit：tool_input.edits[].file_path（多个）
    """
    paths: list[str] = []
    if tool_name in ("Edit", "Write"):
        fp = tool_input.get("file_path")
        if isinstance(fp, str) and fp:
            paths.append(fp)
    elif tool_name == "MultiEdit":
        edits = tool_input.get("edits", [])
        for edit in edits:
            if isinstance(edit, dict):
                fp = edit.get("file_path")
                if isinstance(fp, str) and fp:
                    paths.append(fp)
    return paths


def _load_or_init_receipt(receipt_path: Path, feature_id: str) -> dict:
    """加载已有 receipt.json，若不存在则建空骨架（3 字段）。

    merge 语义：仅当文件不存在时建骨架；存在则全量加载，保留已有字段。
    骨架结构（detail-design §3.4 / receipt-schema.yaml 基准 3 字段）：
      { feature_id, schema_version, touches_violations }
    """
    if receipt_path.exists():
        try:
            with receipt_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                data = {}
        except (OSError, json.JSONDecodeError):
            data = {}
    else:
        # 文件不存在 → 建最小骨架（不设其他必填字段，由 subagent 完整写入）
        data = {}

    # 确保三个骨架字段存在（merge 语义：不覆盖已有值）
    data.setdefault("feature_id", feature_id)
    data.setdefault("schema_version", _RECEIPT_SCHEMA_VERSION)
    data.setdefault("touches_violations", [])

    # touches_violations 必须是 list
    if not isinstance(data.get("touches_violations"), list):
        data["touches_violations"] = []

    return data


def _atomic_write_receipt(receipt_path: Path, data: dict) -> None:
    """用 atomic rename（tmp + os.replace）安全写入 receipt.json。

    atomic rename 保证：
    1. 写入中途崩溃不会留下半写文件
    2. 读取方要么看到旧版本，要么看到新版本，不会看到中间态
    """
    receipt_path.parent.mkdir(parents=True, exist_ok=True)
    # 在同一目录下建临时文件，确保 os.replace 是同设备 rename
    fd, tmp_path_str = tempfile.mkstemp(
        dir=receipt_path.parent,
        prefix=f".{receipt_path.name}.tmp.",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path_str, receipt_path)
    except Exception:
        # 清理临时文件；忽略清理失败
        try:
            os.unlink(tmp_path_str)
        except OSError:
            pass
        raise


def _record_violation(
    receipt_path: Path,
    feature_id: str,
    file_path: str,
    tool_name: str,
) -> None:
    """将越界记录 append 到 receipt.json 的 touches_violations[]。

    使用读-改-写 + atomic rename：
    1. 加载（或初始化）receipt
    2. 追加 violation 条目
    3. atomic rename 写回
    """
    data = _load_or_init_receipt(receipt_path, feature_id)

    # 构造 violation 条目
    entry = {
        "path": file_path,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "tool": tool_name,
    }
    data["touches_violations"].append(entry)

    _atomic_write_receipt(receipt_path, data)


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
    receipt_path = req_dir / "artifacts" / "tasks" / f"{feature_id}.receipt.json"
    for fp in file_paths:
        if not _is_in_touches(fp, touches):
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
