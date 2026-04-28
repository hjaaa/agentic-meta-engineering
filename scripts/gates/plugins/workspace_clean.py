"""GATE-WORKSPACE-CLEAN：工作区干净性检查（从 post-dev-verify.sh 拆出）。

逻辑：git status --porcelain 为空 → PASS；非空 → FAIL。

设计说明（来源：detailed-design.md §3.4）：
  workspace_clean 从旧 post-dev-verify.sh 第 1 步（工作区干净）拆出为独立 plugin，
  让 gate 系统统一管理，同时也作为其他 gate（如 review_verdict）的前置依赖。

precheck：
  - trigger=ci 时，CI 环境 checkout 出来始终是干净的，直接 Skip；
  - trigger=pre-tool-use 时，非文件写操作直接 Skip；
  - 其他 trigger 一律继续。
"""
from __future__ import annotations

import subprocess
from typing import Optional

from .base import Decision, Gate, GateContext, Report, Severity, Skip


class WorkspaceCleanGate(Gate):
    """工作区干净性检查 gate。"""

    id = "GATE-WORKSPACE-CLEAN"
    severity = Severity.ERROR
    triggers = {"pre-commit", "phase-transition", "submit", "post-dev"}
    side_effects = "none"

    def precheck(self, ctx: GateContext) -> Optional[Skip]:
        # CI checkout 出来始终干净，跳过检查避免误报
        if ctx.trigger == "ci":
            return Skip("ci environment is always clean after checkout")
        return None

    def run(self, ctx: GateContext) -> Report:
        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                check=False,
            )
        except FileNotFoundError:
            return Report(
                gate_id=self.id,
                decision=Decision.FAIL,
                code="WORKSPACE-GIT-MISSING",
                message="git 命令不可用",
                fix_hint="确认 git 已安装且在 PATH 中",
            )
        except OSError as exc:
            return Report(
                gate_id=self.id,
                decision=Decision.FAIL,
                code="WORKSPACE-GIT-ERROR",
                message=f"git status 执行失败: {exc}",
                fix_hint="在 git 仓库根目录运行",
            )

        dirty = result.stdout.strip()
        if dirty:
            # 取前 10 行展示，避免日志过长
            preview_lines = dirty.splitlines()[:10]
            preview = "\n".join(preview_lines)
            return Report(
                gate_id=self.id,
                decision=Decision.FAIL,
                code="WORKSPACE-DIRTY",
                message=f"工作区有未提交的改动（共 {len(dirty.splitlines())} 处）:\n{preview}",
                fix_hint="git stash / git add + commit 清理工作区后重试",
                vars={"dirty_files": dirty.splitlines()},
            )

        return Report(gate_id=self.id, decision=Decision.PASS)


# 模块级导出
GATE_CLASS = WorkspaceCleanGate
