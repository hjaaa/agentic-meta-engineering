"""Gate 抽象基类与共享数据结构。

本模块严格遵循 detailed-design.md §2.1（行 83-166）锁定的接口签名：

  - `Severity` / `Decision`：Gate 输出的两类核心枚举
  - `GateContext`：runner 注入到 Gate.precheck/run 的上下文，含 staged_writes 暂存通道
  - `Report`：Gate 的统一返回值（pass / fail / skip 三态）
  - `Skip`：precheck 返回的"主动跳过"信号
  - `Gate`：抽象基类，子类必须实现 precheck/run；可选实现
    commit_staged_writes/rollback（仅 side_effects=write_state 时）

注意：applies_when / dependencies 仅由 registry.yaml 承载，Gate 类**不重复声明**。
runner 在 filter / topo 阶段直接读 registry，不通过 Gate 实例查询。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Optional


# Trigger 枚举（S3 schema 校验白名单的事实源）。
# 注意：`adapter` 不在此枚举内，仅作为 run.py 的特殊 CLI 标志（snapshot 行为契约用）。
TRIGGERS: tuple[str, ...] = (
    "pre-tool-use",
    "pre-commit",
    "phase-transition",
    "submit",
    "ci",
    "post-dev",
)


class Severity(Enum):
    """Gate 严重度，对应 registry.yaml 的 severity 字段。"""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Decision(Enum):
    """Gate 单次执行的决策结果。"""

    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


@dataclass
class GateContext:
    """runner 注入到 Gate 的执行上下文。"""

    trigger: Literal[
        "pre-tool-use",
        "pre-commit",
        "phase-transition",
        "submit",
        "ci",
        "post-dev",
    ]
    requirement_id: Optional[str] = None
    from_phase: Optional[str] = None
    to_phase: Optional[str] = None
    changed_files: list[str] = field(default_factory=list)
    cli_flags: dict = field(default_factory=dict)
    # 显式注入需要的环境变量（避免 plugin 直接读 os.environ 造成隐式依赖）
    env: dict = field(default_factory=dict)
    actor: Literal["claude-code", "human", "ci"] = "claude-code"
    # meta.yaml 解析结果；plugin 通过 dot key 访问字段
    meta: dict = field(default_factory=dict)
    # trigger 特定字段：tool_name / file_path / command 等
    extra: dict = field(default_factory=dict)
    # 暂存待写：(path, dot_key, value)；由 side_effects=write_state 的 plugin 在 run() 中 append；
    # runner 在所有 gate pass 后调 plugin.commit_staged_writes() 落盘；fail 路径直接丢弃。
    staged_writes: list[tuple[str, str, object]] = field(default_factory=list)


@dataclass
class Report:
    """Gate 的统一返回值。decision=PASS 时 message/code/fix_hint 通常为空。"""

    gate_id: str
    decision: Decision
    code: Optional[str] = None        # 如 R005、E001、CR-3、PR-MERGED
    message: Optional[str] = None
    fix_hint: Optional[str] = None
    vars: dict = field(default_factory=dict)


@dataclass
class Skip:
    """precheck 返回的"主动跳过"信号；reason 必填。"""

    reason: str


class Gate(ABC):
    """Gate 抽象基类。

    子类必须设置 `id`/`severity`/`triggers` 类属性，并实现 `precheck` + `run`。
    `side_effects=write_state` 的子类必须额外实现 `commit_staged_writes`/`rollback`。

    注意：applies_when / dependencies 仅由 registry.yaml 承载，Gate 类不重复声明。
    runner 在 filter / topo 阶段直接读 registry，不通过 Gate 实例查询。
    """

    id: str
    severity: Severity
    triggers: set[str]
    side_effects: Literal["none", "write_state"] = "none"

    @abstractmethod
    def precheck(self, ctx: GateContext) -> Optional[Skip]:
        """返回 Skip 即跳过；None 即继续 run。"""

    @abstractmethod
    def run(self, ctx: GateContext) -> Report:
        """主体检查逻辑，必须返回 Report。

        side_effects=write_state 的 plugin 在此 append ctx.staged_writes，
        不直接落盘；落盘由 runner 在所有 gate pass 后统一调 commit_staged_writes()。
        """

    def commit_staged_writes(self, ctx: GateContext) -> None:
        """side_effects=write_state 时实现；把暂存写落盘。

        runner 在 try 块成功结束后调用。本基类提供空实现，给 F-002/F-003
        的 review_verdict 等写态 plugin 留扩展点。
        """

    def rollback(self, ctx: GateContext) -> None:
        """side_effects=write_state 时实现：清理暂存或回滚已 commit 的写。

        本基类提供空实现，由具体写态 plugin 覆盖。
        """
