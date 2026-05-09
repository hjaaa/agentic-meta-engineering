"""workflow 命令派发入口（F-005）。

CLI 用法：
    python3 scripts/lib/workflow_command_dispatcher.py <cmd> [<args>...]

9 个命令：run / continue / save / status / list / approve / reject / rollback / cancel

每命令在执行副作用前先做 §1.3 状态机矩阵校验（见 run_state.WORKFLOW_CMD_ALLOWED_STATES），
状态不满足直接 exit 1 + stderr 错误文案（错误码 E-WF-STATE-001）。
"""
from __future__ import annotations

import sys
from pathlib import Path

# scripts/lib 在 sys.path 里（调用方注入）
_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from common import WorkflowError  # noqa: E402

# 9 个命令 → 对应模块入口
_CMD_MAP: dict[str, str] = {
    "run": "workflow_run",
    "continue": "workflow_continue",
    "save": "workflow_save",
    "status": "workflow_status",
    "list": "workflow_list",
    "approve": "workflow_approve",
    "reject": "workflow_reject",
    "rollback": "workflow_rollback_cmd",
    "cancel": "workflow_cancel",
}

_VALID_CMDS = set(_CMD_MAP.keys())


def dispatch(cmd: str, args: list[str]) -> int:
    """派发到对应命令模块的 main(args) 函数，返回 exit code。

    参数：
        cmd  — 命令名（9 选 1）
        args — 命令剩余参数列表

    返回：
        0  — 成功
        1  — 业务错误（状态不满足 / 参数错误 / run 不存在等）
        2  — 鉴别拦截（approve/reject 非 tty / hook BLOCKED）
    """
    if cmd not in _VALID_CMDS:
        print(
            f"ERROR: 未知命令 {cmd!r}；可用命令：{', '.join(sorted(_VALID_CMDS))}",
            file=sys.stderr,
        )
        return 1

    module_name = _CMD_MAP[cmd]
    try:
        import importlib
        mod = importlib.import_module(module_name)
        return mod.main(args)
    except ModuleNotFoundError as exc:
        # 命令模块缺失（_CMD_MAP 配置错误 / 模块文件未落地）→ 友好错误，不暴露 traceback
        print(f"ERROR: 命令模块未实现 ({module_name}): {exc}", file=sys.stderr)
        return 1
    except WorkflowError as exc:
        print(f"WorkflowError: {exc}", file=sys.stderr)
        return 1
    except SystemExit as exc:
        # 命令内部调用 sys.exit(n) → 透传 exit code
        code = exc.code if isinstance(exc.code, int) else 1
        return code


def main() -> None:
    """CLI 入口。"""
    argv = sys.argv[1:]
    if not argv:
        print(
            f"用法：python3 workflow_command_dispatcher.py <cmd> [<args>...]\n"
            f"可用命令：{', '.join(sorted(_VALID_CMDS))}",
            file=sys.stderr,
        )
        sys.exit(1)

    cmd = argv[0]
    args = argv[1:]
    rc = dispatch(cmd, args)
    sys.exit(rc)


if __name__ == "__main__":
    main()
