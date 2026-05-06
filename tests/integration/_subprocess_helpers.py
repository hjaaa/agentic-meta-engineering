"""integration 测试公共辅助：subprocess.run 超时兜底。

目的：避免 CI 慢机因 subprocess.TimeoutExpired 丢失诊断上下文。
每次调用超时时 pytest.fail 并附带 partial stdout/stderr，
保留所有断言信号。
"""
from __future__ import annotations

import subprocess

import pytest


def run_with_timeout(
    cmd: list,
    timeout: int,
    **kwargs,
) -> subprocess.CompletedProcess:
    """subprocess.run 包装：超时时 pytest.fail 并附带 partial stdout/stderr。

    入参：
        cmd      — 命令行列表
        timeout  — 秒数上限
        **kwargs — 透传给 subprocess.run（capture_output / text / env / cwd 等）

    超时时：pytest.fail（含 cmd / PARTIAL_STDOUT / PARTIAL_STDERR 后 4000 字符），
    不返回，测试立刻标为 FAILED，保留所有诊断信息。
    """
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    try:
        return subprocess.run(cmd, timeout=timeout, **kwargs)
    except subprocess.TimeoutExpired as exc:
        # exc.stdout / exc.stderr 可能是 bytes 也可能是 str（取决于 text= 参数）
        stdout = (
            exc.stdout
            if isinstance(exc.stdout, str)
            else (exc.stdout or b"").decode("utf-8", "replace")
        )
        stderr = (
            exc.stderr
            if isinstance(exc.stderr, str)
            else (exc.stderr or b"").decode("utf-8", "replace")
        )
        pytest.fail(
            f"subprocess timeout after {timeout}s\n"
            f"CMD: {cmd}\n"
            f"PARTIAL_STDOUT:\n{stdout[-4000:]}\n"
            f"PARTIAL_STDERR:\n{stderr[-4000:]}"
        )
