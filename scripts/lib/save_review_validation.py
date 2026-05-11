"""save_review / signoff 公用纯函数 helper（F-012 rev6 D-017 预留路径落地）

职责范围：
  - 纯校验 / 纯工具类 helper，无 save_review / signoff 模块级依赖
  - 单向依赖关系：signoff.py → save_review_validation.py（不反向 import）
  - 为 D-017 ADR 自述的"双向 import 解开"路径提供落地入口

本模块迁入的 helper 均满足：
  1. 无 save_review / signoff 运行时依赖
  2. 函数体为纯逻辑（时间 / 字符串清洗）
  3. 不被测试侧 monkeypatch.setattr(sig, ...) 路径依赖，无需在 signoff 命名空间中做原地修改

注意（设计边界）：
  - _resolve_verdict_path / _check_args_mutex / _validate_signed_by / _get_git_email
    依赖 REQUIREMENTS_DIR 或被测试通过 monkeypatch.setattr(sig, "...") 直接 patch，
    保留在 signoff.py 中以支持现有测试，不迁入本模块。
  - 未来推广时若测试切换到 dependency-injection 风格，可将这些函数迁入本模块。

来源：requirements/REQ-2026-009/plan.md D-017 ADR Consequences（"下次拆 helper 时建议进一步
抽 save_review_validation.py 作为公共依赖，彻底打破双向依赖"）
"""
from __future__ import annotations

from datetime import datetime, timezone

__all__ = [
    "_get_iso8601_now",
    "_sanitize_log_field",
]


def _get_iso8601_now() -> str:
    """返回当前时间的 ISO8601 含时区字符串。

    从 signoff.py 迁入（F-012 rev6 Major 1）。
    """
    return datetime.now(timezone.utc).astimezone().isoformat()


def _sanitize_log_field(v: str) -> str:
    """strip \\r\\n 防 process.txt 日志注入。

    从 signoff.py 迁入（F-012 rev6 Major 1）。
    """
    return v.replace("\n", " ").replace("\r", " ")


