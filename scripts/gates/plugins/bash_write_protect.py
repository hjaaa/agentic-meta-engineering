"""GATE-BASH-WRITE-PROTECT：拦截 Bash 命令对 reviews/*.json 的直接写入（H5）。

设计来源：requirements/REQ-2026-002/artifacts/detailed-design.md §3.3（行 306-379）。

职责：
  - 仅在 pre-tool-use trigger + tool_name=Bash 时生效
  - 识别 8+ 类 shell 写法（>、>>、tee、tee -a、mv、cp、python -c open、heredoc、
    printf >、dd of=）对 requirements/<req>/reviews/<file>.json 的直接写入
  - 双轨白名单：
      1) 父进程链含 save-review.sh（向上追溯最多 5 层）→ PASS
      2) 显式 env：CLAUDE_GATES_BYPASS=1 + CLAUDE_GATES_BYPASS_REASON=<原因> → PASS
  - 其他情况一律 FAIL（code=BASH-WRITE）

precheck：tool_name 非 Bash → Skip。

外部依赖：
  - subprocess（仅用于 ps -o comm= / ps -o ppid=，子用例必须 mock）
  - os.getppid（仅用于父进程链识别）
"""
from __future__ import annotations

import os
import re
import subprocess
from typing import Optional

from .base import Decision, Gate, GateContext, Report, Severity, Skip

# 受保护路径（与 detailed-design.md §3.3 锁定的字面量保持一致）
_PATH = r"requirements/[^/]+/reviews/[^/]+\.json"

# 8 类 shell 写法的正则替代项 —— 每条单独一行，便于审阅与新增
# 安全写法约束：用 tuple + "|".join() 构造，禁止多行 raw 字符串拼接 + 行间注释
_ALTS = (
    # 1) 重定向：> / >>
    rf">>?\s*['\"]?[^|;&]*?{_PATH}",
    # 2) tee / tee -a
    rf"tee\s+(?:-a\s+)?['\"]?[^|;&]*?{_PATH}",
    # 3) mv（任意源 → reviews/*.json）
    rf"mv\s+\S+\s+['\"]?[^|;&]*?{_PATH}",
    # 4) cp（任意源 → reviews/*.json）
    rf"cp\s+\S+\s+['\"]?[^|;&]*?{_PATH}",
    # 5) python -c "open(...,'w')"
    rf"python3?\s+-c\s+['\"].*open\(.*?{_PATH}.*?['\"]w['\"]",
    # 6) heredoc：cat <<EOF > / cat <<-EOF >>
    rf"cat\s+<<-?\s*['\"]?\w+['\"]?\s+>>?\s*['\"]?[^|;&]*?{_PATH}",
    # 7) printf 重定向
    rf"printf\s+.*?>\s*['\"]?[^|;&]*?{_PATH}",
    # 8) dd of=
    rf"dd\s+.*?of=['\"]?[^|;&]*?{_PATH}",
)

RE_WRITE_OPS = re.compile("(" + "|".join(_ALTS) + ")")


class BashWriteProtectGate(Gate):
    """Bash 写 reviews/*.json 拦截 gate。"""

    id = "GATE-BASH-WRITE-PROTECT"
    severity = Severity.ERROR
    triggers = {"pre-tool-use"}
    side_effects = "none"

    def precheck(self, ctx: GateContext) -> Optional[Skip]:
        """非 Bash 工具直接 Skip（registry 已限定 trigger，此处再做 defense-in-depth）。

        参数：ctx.extra["tool_name"] — 当前工具名。
        返回：Skip（非 Bash）或 None（继续 run）。
        """
        if ctx.trigger != "pre-tool-use":
            return Skip(f"trigger={ctx.trigger!r} 非 pre-tool-use；跳过 bash-write-protect")
        if ctx.extra.get("tool_name") != "Bash":
            return Skip("not Bash tool")
        return None

    def run(self, ctx: GateContext) -> Report:
        """检查 Bash 命令是否在写 reviews/*.json，并应用双轨白名单。

        参数：ctx.extra["command"] — Bash 命令字符串；
              ctx.env["CLAUDE_GATES_BYPASS"] / ["CLAUDE_GATES_BYPASS_REASON"] —
              env 白名单双轨。
        返回：PASS / FAIL（code=BASH-WRITE 或 BYPASS-NO-REASON）。
        """
        cmd = ctx.extra.get("command", "") or ""
        if not RE_WRITE_OPS.search(cmd):
            return Report(gate_id=self.id, decision=Decision.PASS)

        # 白名单 1：父进程链含 save-review.sh
        if self._caller_is_save_review_sh():
            return Report(
                gate_id=self.id,
                decision=Decision.PASS,
                vars={"whitelisted": "save-review.sh"},
            )

        # 白名单 2：env 双轨（必须同时给 reason，避免无审计绕过）
        # F-15 约束：env 必须从 ctx.env 读取，禁止 plugin 直接读 os.environ
        if ctx.env.get("CLAUDE_GATES_BYPASS") == "1":
            reason = (ctx.env.get("CLAUDE_GATES_BYPASS_REASON") or "").strip()
            if not reason:
                return Report(
                    gate_id=self.id,
                    decision=Decision.FAIL,
                    code="BYPASS-NO-REASON",
                    message="CLAUDE_GATES_BYPASS=1 必须同时设置 CLAUDE_GATES_BYPASS_REASON",
                    fix_hint="在调用方设置 CLAUDE_GATES_BYPASS_REASON=<原因> 后重试",
                )
            return Report(
                gate_id=self.id,
                decision=Decision.PASS,
                vars={"whitelisted": "env-bypass", "reason": reason},
            )

        return Report(
            gate_id=self.id,
            decision=Decision.FAIL,
            code="BASH-WRITE",
            message="Bash 试图写 reviews/*.json，但调用方不在白名单",
            fix_hint=(
                "reviews/*.json 由 save-review.sh 唯一写入通道维护；"
                "如需修订评审，请让 reviewer Agent 重审（supersedes 链）"
            ),
            vars={"command": cmd[:200]},
        )

    def _caller_is_save_review_sh(self) -> bool:
        """父进程链识别：向上追溯最多 5 层 ppid，任一层 comm 以 save-review.sh 结尾即放行。

        注：macOS 下 ps -o comm= 字段可能被截断（详见 tech-feasibility.md §1.3），
        因此使用 endswith 而非完全匹配；任何异常都视为不在白名单（保守拒绝）。
        """
        try:
            ppid = os.getppid()
            for _ in range(5):
                comm = subprocess.check_output(
                    ["ps", "-p", str(ppid), "-o", "comm="]
                ).decode().strip()
                if comm.endswith("save-review.sh"):
                    return True
                ppid_out = subprocess.check_output(
                    ["ps", "-p", str(ppid), "-o", "ppid="]
                ).decode().strip()
                ppid = int(ppid_out)
                if ppid <= 1:
                    break
        except (subprocess.CalledProcessError, ValueError, OSError):
            return False
        return False


# 模块级导出（registry S2 校验入口）
GATE_CLASS = BashWriteProtectGate
