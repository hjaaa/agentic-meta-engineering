"""GATE-BASH-WRITE-PROTECT：拦截 Bash 命令对 reviews/*.json 的直接写入（H5）。

设计来源：requirements/REQ-2026-002/artifacts/detailed-design.md §3.3（行 306-379）。

职责：
  - 仅在 pre-tool-use trigger + tool_name=Bash 时生效
  - 识别 8+ 类 shell 写法（>、>>、tee、tee -a、mv、cp、python -c open（'w'/'a'/'wb'/'ab'）、
    heredoc、printf >、dd of=）对 requirements/<req>/reviews/<file>.json 的直接写入
  - 双轨白名单：
      1) 父进程链含 save-review.sh（通过 SAVE_REVIEW_PID env 优先比对 / fallback 完整 comm 匹配）
      2) 显式 env：CLAUDE_GATES_BYPASS=1 + CLAUDE_GATES_BYPASS_REASON=<原因> → PASS
  - 其他情况一律 FAIL（code=BASH-WRITE）

precheck：tool_name 非 Bash → Skip。

外部依赖：
  - subprocess（仅用于 ps -o comm=,ppid= / 子用例必须 mock；timeout=1 防止僵尸进程阻塞）
  - os.getppid（仅用于父进程链识别）

best-effort 性质（F-007 round-2 标注）：
  - 容器场景下 claude 作为 PID=1 entrypoint 时，向上追溯 ppid 链全为 init，
    白名单 1 实质失效 → 必须依赖 SAVE_REVIEW_PID env 或白名单 2（CLAUDE_GATES_BYPASS）
  - PID 复用 TOCTOU：识别 ppid 到放行命令之间，save-review.sh 可能已退出且 PID 被复用，
    本设计接受此理论风险；进一步加固需要进程 stat 的 starttime 比对（F-004 评估）
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from typing import Iterator, Optional

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
    # 5) python 写入：open(...,'w'|'a'|'wb'|'ab') 全模式（F-006 round-2 补 'a'/'ab'/'wb'）
    rf"python3?\s+-c\s+['\"].*open\(.*?{_PATH}.*?['\"](?:w|a|wb|ab)['\"]",
    # 6) heredoc：cat <<EOF > / cat <<-EOF >>
    rf"cat\s+<<-?\s*['\"]?\w+['\"]?\s+>>?\s*['\"]?[^|;&]*?{_PATH}",
    # 7) printf 重定向
    rf"printf\s+.*?>\s*['\"]?[^|;&]*?{_PATH}",
    # 8) dd of=
    rf"dd\s+.*?of=['\"]?[^|;&]*?{_PATH}",
)

RE_WRITE_OPS = re.compile("(" + "|".join(_ALTS) + ")")

# ps 调用超时（F-024 round-2）：避免僵尸进程 / proc 异常下 pre-tool-use 路径挂死
_PS_TIMEOUT_SEC = 1


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
            return Skip("非 Bash 工具，跳过本 gate")
        return None

    def run(self, ctx: GateContext) -> Report:
        """检查 Bash 命令是否在写 reviews/*.json，并应用双轨白名单。

        参数：ctx.extra["command"] — Bash 命令字符串；
              ctx.env["CLAUDE_GATES_BYPASS"] / ["CLAUDE_GATES_BYPASS_REASON"] —
              env 白名单双轨；
              ctx.env["SAVE_REVIEW_PID"] — save-review.sh 启动时导出的 PID（白名单 1 优先源）。
        返回：PASS / FAIL（code=BASH-WRITE 或 BYPASS-NO-REASON）。
        """
        cmd = ctx.extra.get("command", "") or ""
        if not RE_WRITE_OPS.search(cmd):
            return Report(gate_id=self.id, decision=Decision.PASS)

        # 白名单 1：父进程链含 save-review.sh（SAVE_REVIEW_PID env 优先 / fallback comm 完整匹配）
        if self._caller_is_save_review_sh(ctx):
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
                # F-031：把"没设 BYPASS"和"设了 BYPASS 但缺 REASON"两种情况说清楚
                return Report(
                    gate_id=self.id,
                    decision=Decision.FAIL,
                    code="BYPASS-NO-REASON",
                    message=(
                        "已设置 CLAUDE_GATES_BYPASS=1 但 CLAUDE_GATES_BYPASS_REASON 为空；"
                        "为保证 audit 可追溯，必须同时给出非空 reason"
                    ),
                    fix_hint=(
                        "在调用方设置 CLAUDE_GATES_BYPASS_REASON=<具体原因> 后重试；"
                        "如本意是走 save-review.sh 通道，请检查父进程链是否断裂（容器场景白名单 1 失效）"
                    ),
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

    def _caller_is_save_review_sh(self, ctx: GateContext) -> bool:
        """父进程链识别：判断当前调用者是否为 save-review.sh。

        优先级（F-005/F-007/F-028 round-2 加固）：
          1. SAVE_REVIEW_PID env 比对：save-review.sh 启动时 export SAVE_REVIEW_PID=$$，
             若 ppid 链中任一层 == 该 PID，立即放行（最快、不易伪造）
          2. fallback 完整 comm 匹配：要求 comm 严格 == "save-review.sh"（防止
             evil-save-review.sh / xsave-review.sh 等命名伪造）

        实现细节（F-024/F-028 round-2）：
          - subprocess.check_output(timeout=1)：避免僵尸进程下挂死
          - 单次 ps -o comm=,ppid= 同时取两字段，从 5×2 次降到 5 次 ps 调用
          - _walk_ppid_chain 生成器把链遍历逻辑抽出，便于读和测

        异常路径（F-030 round-2）：
          - 任意 OSError/CalledProcessError/TimeoutExpired/ValueError → 打 WARNING
            log 后保守拒绝（return False），让用户能区分"白名单识别故障"vs"真不在白名单"
          - 容器场景（PPID=1）下白名单 1 必然 false，需走白名单 2 或 SAVE_REVIEW_PID
        """
        target_pid_str = ctx.env.get("SAVE_REVIEW_PID")
        target_pid = int(target_pid_str) if (target_pid_str and target_pid_str.isdigit()) else None
        try:
            for comm, ppid in _walk_ppid_chain(os.getppid(), max_depth=5):
                # 优先：SAVE_REVIEW_PID env 比对
                if target_pid is not None and ppid == target_pid:
                    return True
                # fallback：完整 comm 匹配（防止 endswith 命名伪造）
                if comm == "save-review.sh":
                    return True
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError, OSError) as exc:
            print(
                f"WARNING bash_write_protect 父进程链识别异常 ppid={os.getppid()}: {exc}",
                file=sys.stderr,
            )
            return False
        return False


def _walk_ppid_chain(start_pid: int, max_depth: int = 5) -> Iterator[tuple[str, int]]:
    """向上遍历父进程链，每步 yield (comm, ppid)。

    实现：单次 ps -o comm=,ppid= 同时取两字段（F-028 round-2，子进程数减半）；
    timeout=1 防止僵尸/proc 异常阻塞；ppid<=1 提前结束（PID 1 之上没有父）。
    """
    pid = start_pid
    for _ in range(max_depth):
        # ps 输出形如 "save-review.sh   12345"（comm 字段 macOS 可能截断）
        out = subprocess.check_output(
            ["ps", "-p", str(pid), "-o", "comm=,ppid="],
            timeout=_PS_TIMEOUT_SEC,
        ).decode().strip()
        if not out:
            return
        # rsplit(maxsplit=1)：comm 可能含空格，ppid 必为最后一字段
        parts = out.rsplit(None, 1)
        if len(parts) != 2:
            return
        comm_full, ppid_str = parts[0].strip(), parts[1].strip()
        # 取 comm 的 basename（macOS ps 可能输出完整路径）
        comm = os.path.basename(comm_full)
        ppid = int(ppid_str)
        yield comm, ppid
        if ppid <= 1:
            return
        pid = ppid


# 模块级导出（registry S2 校验入口）
GATE_CLASS = BashWriteProtectGate
