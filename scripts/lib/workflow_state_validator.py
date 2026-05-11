"""状态机矩阵校验（F-005 共享工具）。

详细设计 §1.3：命令×RunState 矩阵。每命令在执行副作用前调用 validate_state_for_cmd。

允许矩阵（True = 允许，False = 拒绝）：
- run:      (无 run)
- continue: running / paused / failed
- save:     running / paused / approval_pending / failed / completed
- status:   running / paused / approval_pending / cancel_requested / cancelled / failed / completed
- list:     任意（无需 run 上下文）
- approve:  approval_pending
- reject:   approval_pending
- rollback: running / paused / approval_pending / failed / completed
- cancel:   running / paused / approval_pending
"""
from __future__ import annotations

import sys
from pathlib import Path

_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from common import WorkflowError  # noqa: E402

# 每命令允许的 run state 集合
# None = 命令不需要 run 上下文（run / list）
CMD_ALLOWED_STATES: dict[str, set[str] | None] = {
    "run":      None,  # 无 run 场景；调用方自行保证
    "continue": {"running", "paused", "failed"},
    "save":     {"running", "paused", "approval_pending", "failed", "completed"},
    "status":   {"running", "paused", "approval_pending", "cancel_requested",
                 "cancelled", "failed", "completed"},
    "list":     None,  # 无需 run 上下文
    "approve":  {"approval_pending"},
    "reject":   {"approval_pending"},
    "rollback": {"running", "paused", "approval_pending", "failed", "completed"},
    "cancel":   {"running", "paused", "approval_pending"},
}


def validate_state_for_cmd(cmd: str, run_id: str, state: str) -> None:
    """校验当前 run state 是否允许执行 cmd。

    若不允许，抛 WorkflowError（调用方 catch 后 exit 1 + 错误文案）。

    参数：
        cmd    — 命令名（9 选 1）
        run_id — run 标识（用于错误上下文）
        state  — 当前 RunState.state 字符串

    异常：
        WorkflowError — state 不允许执行 cmd（错误码 E-WF-STATE-001）
    """
    allowed = CMD_ALLOWED_STATES.get(cmd)
    if allowed is None:
        # run / list 不做 state 校验
        return

    if state not in allowed:
        allowed_str = " / ".join(sorted(allowed))
        raise WorkflowError(
            f"E-WF-STATE-001: cmd={cmd!r} run_id={run_id!r} state={state!r}\n"
            f"当前状态 {state!r} 不允许执行 {cmd!r}\n"
            f"允许状态: {allowed_str}"
        )


def check_tty_for_approval(cmd: str) -> None:
    """approve / reject 的 tty 兜底校验（D-006 fail-closed）。

    若非 tty 终端，打印错误到 stderr 并 exit 2。
    测试时 mock sys.stdin.isatty() 即可控制路径。

    参数：
        cmd — 命令名（approve / reject）
    """
    if cmd not in ("approve", "reject"):
        return
    if not sys.stdin.isatty():
        print(
            f"ERROR [E-WF-TTY-001]: {cmd!r} 需要 tty 终端（人类专属动作）\n"
            f"AI Agent 禁止调用 approve / reject（D-006 双层校验）",
            file=sys.stderr,
        )
        sys.exit(2)
