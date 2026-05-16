"""workflow 命令派发入口（F-005）。

CLI 用法：
    python3 scripts/lib/workflow_command_dispatcher.py <cmd> [<args>...]

9 个命令：run / continue / save / status / list / approve / reject / rollback / cancel

每命令在执行副作用前先做 §1.3 状态机矩阵校验（见 run_state.WORKFLOW_CMD_ALLOWED_STATES），
状态不满足直接 exit 1 + stderr 错误文案（错误码 E-WF-STATE-001）。
"""
from __future__ import annotations

import difflib
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

# Fuzzy 匹配词典：分命令集与模板集两段，总长 ≥ 10（F-012 AC-09）
#
# 命令集：9 个合法命令名（含常见拼写变体）→ 拼写变体也含在内，先试命令集
_FUZZY_CMDS: list[str] = list(_VALID_CMDS) + [
    "stat",         # status 简写
    "lst",          # list 拼错
    "cancl",        # cancel 拼错
    "rol",          # rollback 缩写
]
# 模板别名词典：variant → canonical 名（acceptance #1/#2 覆盖）
# key = 用户可能输入的变体，value = 应该建议给用户的正式模板名
_FUZZY_TEMPLATE_ALIASES: dict[str, str] = {
    "standar-8phase": "standard-8phase",       # 编辑距离 1 拼写错（acceptance #1）
    "standard8phase": "standard-8phase",       # 缺连字符变体
    "std-8phase": "standard-8phase",           # 缩写变体
    "review-emb": "code-review-embedded",      # 短名（acceptance #2）
    "review-embedded": "code-review-embedded", # 缺 code- 前缀
    "req-bootstrap": "requirement-bootstrap",  # 缩写
    "requirement-boot": "requirement-bootstrap",
    "feature-development": "feature-dev",      # 全写变体
}
# 公开给测试用的合并词典（acceptance #3 验证 ≥ 10 词）
_FUZZY_TEMPLATES: list[str] = list(_FUZZY_TEMPLATE_ALIASES.keys())


def _fuzzy_match(cmd: str) -> tuple[str | None, bool]:
    """对 cmd 做 fuzzy 匹配，返回 (canonical_name, is_command)。

    优先尝试命令集（is_command=True），未命中再试模板别名集（is_command=False）。
    两者均不命中返回 (None, False)。

    cutoff 双档说明（IB-40）：
      - 主路径（命令集 / 模板别名集首次匹配）cutoff=0.6——features.json F-012 description
        约定的标准阈值，与 acceptance #1 编辑距离 ≤ 2 自洽。
      - 二阶段（拼写变体 → canonical 命令名兜底）cutoff=0.5——'rol' / 'cancl' 等拼写变体
        SequenceMatcher ratio 落在 0.46~0.50 区间，必须降阈才能回归到 'rollback' / 'cancel'。
        本档仅作用于 _FUZZY_CMDS 已经一阶段命中后的命令名归一化，输入空间受限不扩张攻击面。
    """
    # 1. 命令集：优先匹配（一阶段 cutoff=0.6）
    hits = difflib.get_close_matches(cmd, _FUZZY_CMDS, n=1, cutoff=0.6)
    if hits:
        matched = hits[0]
        if matched in _VALID_CMDS:
            return matched, True
        # 命中了拼写变体（如 "cancl"）→ 找最接近的正式命令名（二阶段 cutoff=0.5）
        canonical = difflib.get_close_matches(matched, list(_VALID_CMDS), n=1, cutoff=0.5)
        if canonical:
            return canonical[0], True

    # 2. 模板别名集：fuzzy 查 key，返回对应 canonical value（一阶段 cutoff=0.6）
    template_hits = difflib.get_close_matches(cmd, list(_FUZZY_TEMPLATE_ALIASES.keys()), n=1, cutoff=0.6)
    if template_hits:
        canonical_template = _FUZZY_TEMPLATE_ALIASES[template_hits[0]]
        return canonical_template, False

    return None, False


def _handle_unknown_cmd(cmd: str) -> tuple[str | None, int]:
    """处理 _VALID_CMDS 未覆盖的输入：fuzzy 三路分支（IB-37）。

    Args:
        cmd: 用户输入但不在 _VALID_CMDS 的原始命令名。

    Returns:
        (normalized_cmd, 0)：fuzzy 命中合法命令名，调用方应改用 normalized_cmd 继续 dispatch。
        (None, 1)：未命中或命中模板别名集，已落 stderr 错误/提示，调用方应直接 return 1。
    """
    matched, is_command = _fuzzy_match(cmd)
    if matched and is_command:
        print(
            f"NOTE: 已 fuzzy 匹配 {cmd!r} → {matched!r}",
            file=sys.stderr,
        )
        return matched, 0
    if matched:  # is_command == False → 命中模板别名
        print(
            f"NOTE: {cmd!r} 看起来像 workflow 模板名 {matched!r}；"
            f"您可能想 `/workflow:run {matched}`?",
            file=sys.stderr,
        )
        return None, 1
    suggestion = difflib.get_close_matches(cmd, list(_VALID_CMDS), n=1, cutoff=0.5)
    hint = f"；您是不是想输入 {suggestion[0]!r}?" if suggestion else ""
    print(
        f"ERROR: 未知命令 {cmd!r}；可用命令：{', '.join(sorted(_VALID_CMDS))}{hint}",
        file=sys.stderr,
    )
    return None, 1


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
        normalized, rc = _handle_unknown_cmd(cmd)
        if normalized is None:
            return rc
        cmd = normalized

    module_name = _CMD_MAP[cmd]
    try:
        import importlib
        mod = importlib.import_module(module_name)
        return mod.main(args)
    except ModuleNotFoundError as exc:
        # 命令模块缺失（_CMD_MAP 配置错误 / 模块文件未落地）→ 友好错误，不暴露 traceback
        print(f"ERROR: 命令模块未实现 ({module_name}): {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        # 用户 Ctrl+C 中断 → 友好提示，不暴露 traceback，返回 130（Unix Ctrl+C 惯例）
        print("已中断", file=sys.stderr)
        return 130
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
