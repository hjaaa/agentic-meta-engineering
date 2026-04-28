"""GATE-BASH-WRITE-PROTECT：拦截 Bash 命令对 reviews/*.json 的直接写入（H5）。

设计来源：requirements/REQ-2026-002/artifacts/detailed-design.md §3.3（行 306-379）。

职责：
  - 仅在 pre-tool-use trigger + tool_name=Bash 时生效
  - 识别 12 类 shell 写法（F-005 round-3 在 round-2 的 8 类基础上补 4 条）对
    requirements/<req>/reviews/<file>.json 的直接写入：
      1) > / >>            重定向
      2) tee / tee -a      管道写入
      3) mv                移动覆盖
      4) cp                复制覆盖
      5) python3 -c "...open(<path>, 'w'/'a'/'wb'/'ab')..."
      6) heredoc           cat <<EOF > / cat <<-EOF >>
      7) printf >          格式化重定向
      8) dd of=            块复制
      9) sponge            moreutils stdin 吸入后整体写入（绕过 noclobber）
     10) rsync             含 --inplace 覆盖写
     11) install           coreutils 默认 cp+chmod 覆盖
     12) python3 -c "...Path(<path>).write_text|write_bytes(...)..."  pathlib 通道（不走 open()）
  - 双轨白名单：
      1) 父进程链含 save-review.sh：**仅** 通过 SAVE_REVIEW_PID env 比对（唯一通道）。
         save-review.sh:18 启动时 export SAVE_REVIEW_PID=$$，:19 用 exec 替换为 python3
         进程，导致子进程 comm 不再是 save-review.sh，原 comm 字符串 fallback 永远到不了
         （F-012 round-3 删除死代码，简化为单一 PID 通道）。
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

# 12 类 shell 写法的正则替代项 —— 每条单独一行，便于审阅与新增
# 安全写法约束：用 tuple + "|".join() 构造，禁止多行 raw 字符串拼接 + 行间注释
# F-005 round-3 补 4 条 alt（sponge / rsync / install / pathlib.write_text|write_bytes），
# 关闭 F-003 H5 acceptance "至少 8 类" 在实测中遗漏的形态。
_ALTS = (
    # 1) 重定向：> / >>（含目标在引号中的常见变体）
    rf">>?\s*['\"]?[^|;&]*?{_PATH}",
    # 2) tee / tee -a（管道写入；-a 为追加，不带 -a 是覆盖，两种都拦）
    rf"tee\s+(?:-a\s+)?['\"]?[^|;&]*?{_PATH}",
    # 3) mv（任意源 → reviews/*.json）
    rf"mv\s+\S+\s+['\"]?[^|;&]*?{_PATH}",
    # 4) cp（任意源 → reviews/*.json）
    rf"cp\s+\S+\s+['\"]?[^|;&]*?{_PATH}",
    # 5) python 写入：open(...,'w'|'a'|'wb'|'ab') 全模式（F-006 round-2 补 'a'/'ab'/'wb'）
    rf"python3?\s+-c\s+['\"].*open\(.*?{_PATH}.*?['\"](?:w|a|wb|ab)['\"]",
    # 6) heredoc：cat <<EOF > / cat <<-EOF >>
    rf"cat\s+<<-?\s*['\"]?\w+['\"]?\s+>>?\s*['\"]?[^|;&]*?{_PATH}",
    # 7) printf 重定向（含 -- / 多 % 占位符的变体）
    rf"printf\s+.*?>\s*['\"]?[^|;&]*?{_PATH}",
    # 8) dd of=（块复制 / 二进制写入兜底）
    rf"dd\s+.*?of=['\"]?[^|;&]*?{_PATH}",
    # 9) sponge（moreutils；从 stdin 吸入后整体写入目标，绕过 > 直接重定向时的 -noclobber）
    rf"sponge\s+['\"]?[^|;&]*?{_PATH}",
    # 10) rsync（任意源 → reviews/*.json，含 --inplace 覆盖写）
    rf"rsync\s+(?:-\S+\s+)*\S+\s+['\"]?[^|;&]*?{_PATH}",
    # 11) install（coreutils install 命令默认是 cp + chmod，会覆盖目标）
    rf"install\s+(?:-\S+\s+)*\S+\s+['\"]?[^|;&]*?{_PATH}",
    # 12) pathlib.Path(...).write_text / write_bytes（Python 内建写入，不走 open()）
    #     形式：python3 -c "...Path('<path>').write_text(...)..."；
    #     _PATH 出现在 write_text/write_bytes 之前，正则按 .*write_text|write_bytes 锚后向前匹配
    rf"python3?\s+-c\s+['\"].*{_PATH}.*?\.write_(?:text|bytes)\(",
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

        通道（F-012 round-3 简化）：
          - **SAVE_REVIEW_PID env 比对（唯一通道）**：save-review.sh:18 启动时 export
            SAVE_REVIEW_PID=$$，本函数比对 ppid 链中任一层 PID 与该值是否相等。
          - **不再尝试 comm 字符串匹配**：save-review.sh:19 用 `exec python3 ...` 直接替换
            shell 进程，子进程 comm 是 python3 而非 save-review.sh，原 comm == "save-review.sh"
            分支永远到不了（死代码）。F-012 round-3 删除该 fallback，仅保留 PID 通道。

        实现细节（F-024/F-028 round-2 沿用）：
          - subprocess.check_output(timeout=1)：避免僵尸进程下挂死
          - 单次 ps -o comm=,ppid= 同时取两字段，从 5×2 次降到 5 次 ps 调用
          - _walk_ppid_chain 生成器把链遍历逻辑抽出，便于读和测
            （comm 字段仍 yield 出来，留给将来 macOS 截断诊断用，但不参与白名单判定）

        异常路径（F-030 round-2 沿用）：
          - 任意 OSError/CalledProcessError/TimeoutExpired/ValueError → 打 WARNING
            log 后保守拒绝（return False），让用户能区分"白名单识别故障"vs"真不在白名单"
          - 容器场景（PPID=1）下白名单 1 必然 false，需走白名单 2（CLAUDE_GATES_BYPASS）
          - SAVE_REVIEW_PID 缺失 → target_pid=None → 链遍历全部不命中 → 走白名单 2 或 FAIL
        """
        target_pid_str = ctx.env.get("SAVE_REVIEW_PID")
        target_pid = int(target_pid_str) if (target_pid_str and target_pid_str.isdigit()) else None
        if target_pid is None:
            # SAVE_REVIEW_PID 未设置：白名单 1 全无意义，直接 false 让上层走白名单 2
            return False
        try:
            for _comm, ppid in _walk_ppid_chain(os.getppid(), max_depth=5):
                if ppid == target_pid:
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
