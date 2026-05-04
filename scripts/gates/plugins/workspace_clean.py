"""GATE-WORKSPACE-CLEAN：工作区干净性检查（从 post-dev-verify.sh 拆出）。

逻辑：git status --porcelain 为空 → PASS；非空 → FAIL。

设计说明（来源：detailed-design.md §3.4）：
  workspace_clean 从旧 post-dev-verify.sh 第 1 步（工作区干净）拆出为独立 plugin，
  让 gate 系统统一管理，同时也作为其他 gate（如 review_verdict）的前置依赖。

precheck：
  - trigger=ci 时，CI 环境 checkout 出来始终是干净的，直接 Skip；
  - 其他 trigger 一律继续。
  （pre-tool-use 已于 F-002 退役）

stash 残留过滤（F-004 round-4）：
  state_io.stash_state 在 _run_gates 前为 write_state plugin（如 GATE-REVIEW-VERDICT）
  对 requirements/<id>/meta.yaml 创建 .bak 备份，全 pass 路径下由 cleanup_snapshots
  清理。但 GATE-WORKSPACE-CLEAN 在拓扑序中可能晚于 stash，会把 .bak 误判为 untracked
  导致 phase-transition 永远过不去。本 plugin 显式忽略已知 stash residue（路径模式
  `requirements/REQ-YYYY-NNN/meta.yaml.bak`），不影响真实用户改动的检测。
"""
from __future__ import annotations

import re
import subprocess
from typing import Optional

from .base import Decision, Gate, GateContext, Report, Severity, Skip


# F-004 round-4：state_io.stash_state 残留的合法 .bak 文件模式
# 仅匹配 `?? requirements/REQ-YYYY-NNN/meta.yaml.bak`（git status --porcelain 格式：
# `?? <path>`，untracked 文件前缀两空格）。其他 .bak 文件不匹配，仍按 dirty 处理。
_STASH_RESIDUE_PATTERN = re.compile(
    r"^\?\?\s+requirements/REQ-\d{4}-\d{3}/meta\.yaml\.bak\s*$"
)


class WorkspaceCleanGate(Gate):
    """工作区干净性检查 gate。"""

    id = "GATE-WORKSPACE-CLEAN"
    severity = Severity.ERROR
    triggers = {"pre-commit", "phase-transition", "submit", "post-dev"}
    side_effects = "none"

    def precheck(self, ctx: GateContext) -> Optional[Skip]:
        """始终继续执行（registry triggers 不含 ci，ci 守卫已无意义）。

        参数：ctx — 当前执行上下文（registry 已保证 trigger ∈ triggers 白名单）。
        返回：None（继续执行 run）。
        """
        return None

    def run(self, ctx: GateContext) -> Report:
        """执行 git status --porcelain，非空输出视为工作区不干净，返回 FAIL。

        错误场景：工作区有未提交的改动（未 staged / staged 未 commit）时 FAIL。
        """
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
            # F-004 round-4：过滤 stash_state 创建的合法 .bak 残留
            # （仅 requirements/REQ-YYYY-NNN/meta.yaml.bak，避免与拓扑前置 stash 竞态）
            real_dirty_lines = [
                line for line in dirty.splitlines()
                if not _STASH_RESIDUE_PATTERN.match(line)
            ]
            if real_dirty_lines:
                # 取前 10 行展示，避免日志过长
                preview = "\n".join(real_dirty_lines[:10])
                return Report(
                    gate_id=self.id,
                    decision=Decision.FAIL,
                    code="WORKSPACE-DIRTY",
                    message=f"工作区有未提交的改动（共 {len(real_dirty_lines)} 处）:\n{preview}",
                    fix_hint="git stash / git add + commit 清理工作区后重试",
                    vars={"dirty_files": real_dirty_lines},
                )

        return Report(gate_id=self.id, decision=Decision.PASS)


# 模块级导出
GATE_CLASS = WorkspaceCleanGate
