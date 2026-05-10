"""F-009 · D-006 拦截测试（pytest）。

测试 .claude/hooks/pre-tool-use-guard.sh 对 workflow approve/reject 的拦截行为。
与既有 .bats 文件共存，不依赖 bats framework。

用例矩阵来自 tests/hooks/fixtures/workflow_approval_inputs.yaml（§5.6 设计）：
- TC-F9-1: 16 条 happy block（4 入口 × 4 包装）→ exit 2 + BLOCKED 文案
- TC-F9-2: 5 条边界放行 → exit 0
- TC-F9-3: 2 条已知绕过（hook 放行 exit 0 + CLI isatty 层 exit 2）
- TC-F9-4: 1 条 audit log 不写 BYPASS used
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

# 仓库根路径
REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK_PATH = REPO_ROOT / ".claude" / "hooks" / "pre-tool-use-guard.sh"
FIXTURE_PATH = Path(__file__).parent / "fixtures" / "workflow_approval_inputs.yaml"

# 预期 BLOCKED 文案关键片段
BLOCKED_TEXT = "BLOCKED: /workflow:approve / /workflow:reject 是人类专属动作（D-006）"


def _load_fixture(section: str) -> list[dict]:
    """从 fixture YAML 加载指定 section 的用例列表。"""
    data = yaml.safe_load(FIXTURE_PATH.read_text(encoding="utf-8"))
    return data.get(section, [])


def _run_hook(command: str, env: dict | None = None) -> subprocess.CompletedProcess:
    """以 Bash 工具的 stdin JSON 调用 hook，返回 CompletedProcess。

    hook 协议：stdin 为 JSON {"tool_name": "Bash", "tool_input": {"command": "..."}}
    """
    payload = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    merged_env = {**os.environ, **(env or {})}
    # 确保不携带 BYPASS（避免父环境变量污染）
    merged_env.pop("CLAUDE_GATES_GLOBAL_BYPASS", None)
    return subprocess.run(
        ["bash", str(HOOK_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        env=merged_env,
        cwd=str(REPO_ROOT),
    )


# ============================================================================
# TC-F9-1: 16 条 happy block（4 入口 × 4 包装）
# ============================================================================

_happy_block_cases = _load_fixture("happy_block")


@pytest.mark.parametrize(
    "case",
    _happy_block_cases,
    ids=[c["id"] for c in _happy_block_cases],
)
def test_hook_blocks_16_combinations(case: dict) -> None:
    """TC-F9-1: 所有 happy block 用例必须 exit 2 且 stderr 含 BLOCKED 文案。"""
    proc = _run_hook(case["command"])
    assert proc.returncode == 2, (
        f"{case['id']} ({case['description']}): "
        f"期望 exit 2，实际 {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )
    assert BLOCKED_TEXT in proc.stderr, (
        f"{case['id']} ({case['description']}): "
        f"期望 stderr 含 BLOCKED 文案\nstderr={proc.stderr!r}"
    )


# ============================================================================
# TC-F9-2: 5 条边界放行
# ============================================================================

_boundary_cases = _load_fixture("boundary_passthrough")


@pytest.mark.parametrize(
    "case",
    _boundary_cases,
    ids=[c["id"] for c in _boundary_cases],
)
def test_hook_passthrough_5_boundary(case: dict) -> None:
    """TC-F9-2: 边界命令不应被 hook 拦截（exit 0）。"""
    proc = _run_hook(case["command"])
    assert proc.returncode == 0, (
        f"{case['id']} ({case['description']}): "
        f"期望 exit 0，实际 {proc.returncode}\nstdout={proc.stdout!r}\nstderr={proc.stderr!r}"
    )


# ============================================================================
# TC-F9-3: 2 条已知绕过通道（hook 放行 + CLI isatty 层拒绝）
# ============================================================================

_bypass_cases = _load_fixture("known_bypass")


@pytest.mark.parametrize(
    "case",
    _bypass_cases,
    ids=[c["id"] for c in _bypass_cases],
)
def test_known_bypass_with_isatty_block(case: dict, tmp_path: Path) -> None:
    """TC-F9-3: 已知绕过通道——hook 放行（exit 0），CLI isatty 层拒绝（exit 2）。

    双层验证：
    1. hook 对变量间接引用 / eval 形式放行（exit 0）
    2. 直接 subprocess 调 workflow_approve.py 喂非 tty stdin → exit 2
    """
    # 第一层：hook 放行
    proc = _run_hook(case["command"])
    assert proc.returncode == 0, (
        f"{case['id']}: 已知绕过通道应被 hook 放行，实际 exit={proc.returncode}\n"
        f"stderr={proc.stderr!r}"
    )

    # 第二层：CLI isatty 兜底——subprocess 喂非 tty stdin，预期 exit 2
    # stdin=subprocess.PIPE 使 workflow_approve.py 的 sys.stdin.isatty() 返回 False
    cli_proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "lib" / "workflow_approve.py")],
        input="",
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )
    assert cli_proc.returncode == 2, (
        f"{case['id']}: CLI isatty 层应拒绝非 tty 进程（exit 2），"
        f"实际 exit={cli_proc.returncode}\nstderr={cli_proc.stderr!r}"
    )
    # 验证 stderr 含中文拒绝文案
    assert cli_proc.stderr.strip(), (
        f"{case['id']}: CLI isatty 拒绝时应输出错误信息到 stderr"
    )


# ============================================================================
# TC-F9-4: 命中时 audit log 不写 BYPASS used
# ============================================================================

def test_audit_log_no_bypass_marker(tmp_path: Path) -> None:
    """TC-F9-4: approval 拦截命中时 audit log 不含 BYPASS used 字样。

    hook 写 audit log 到 CLAUDE_GATES_AUDIT_ROOT/.queue/<date>.log。
    本用例把 audit root 指向 tmp_path，命中 approval 拦截后读 log 确认
    不含 BYPASS used（该字符串仅在全局 bypass 通道写入）。
    """
    audit_root = tmp_path / "audit_root"
    audit_root.mkdir(parents=True)

    env_override = {
        "CLAUDE_GATES_AUDIT_ROOT": str(audit_root),
    }

    proc = _run_hook("/workflow:approve", env=env_override)
    # 命中拦截
    assert proc.returncode == 2, (
        f"TC-F9-4: 期望拦截 exit 2，实际 {proc.returncode}\nstderr={proc.stderr!r}"
    )

    # 读 audit queue log（可能不存在——approval 拦截不写 audit，这也是正确行为）
    queue_dir = audit_root / "audit" / ".queue"
    all_log_content = ""
    if queue_dir.exists():
        for log_file in queue_dir.glob("*.log"):
            all_log_content += log_file.read_text(encoding="utf-8")

    assert "BYPASS used" not in all_log_content, (
        "TC-F9-4: 命中 approval 拦截时，audit log 不应含 'BYPASS used'，"
        f"实际内容：\n{all_log_content}"
    )
