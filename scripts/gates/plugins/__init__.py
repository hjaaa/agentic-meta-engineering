"""Gate plugin 包。

每个具体 gate 在 `plugins/<plugin>.py` 文件中实现，并暴露 `Gate` 子类。
runner 通过 registry.yaml 的 `plugin` 字段动态 import，因此本包入口保持轻量，
仅 re-export 抽象基类供 plugin 模块继承。
"""
from .base import (
    TRIGGERS,
    Decision,
    Gate,
    GateContext,
    Report,
    Severity,
    Skip,
)

__all__ = [
    "TRIGGERS",
    "Decision",
    "Gate",
    "GateContext",
    "Report",
    "Severity",
    "Skip",
]
