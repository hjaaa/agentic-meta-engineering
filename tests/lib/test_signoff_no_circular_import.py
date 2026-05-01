"""回归测试：is_signed_off 不能因循环导入退化为 stub（Codex P1-B 防再发）。

背景：check_reviews.py 顶层 `import save_review`，save_review.py 顶层
`from check_reviews import is_signed_off`。若 SIGNOFF_PASS / is_signed_off 的定义
位于 `import save_review` 之后，循环导入会让 save_review 拿到 ImportError 并永久
绑定 stub `return False`——CR-1 / CR-4 静默失效。

本测试通过两种 import 顺序触发循环路径，断言 is_signed_off 在两个模块里都是真函数
（对 approved verdict 返回 True），而不是 stub。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_LIB = _REPO_ROOT / "scripts" / "lib"
if str(_SCRIPTS_LIB) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_LIB))


def _purge_modules() -> None:
    """移除两个模块以触发完整 import 流程。"""
    for name in ("check_reviews", "save_review"):
        sys.modules.pop(name, None)


@pytest.mark.parametrize("import_first", ["check_reviews", "save_review"])
def test_is_signed_off_returns_true_for_approved_after_either_import_order(import_first: str) -> None:
    """given_either_import_order_when_verdict_approved_then_is_signed_off_returns_true。

    若回退到旧的循环导入 stub，approved verdict 也会被判 False，本断言会失败。
    """
    _purge_modules()
    if import_first == "check_reviews":
        import check_reviews  # noqa: F401
        import save_review
    else:
        import save_review  # noqa: F401
        import check_reviews

    approved = {"human_signoff": {"decision": "approved"}}
    assert save_review.is_signed_off(approved) is True, (
        f"循环导入回退到 stub 了——save_review.is_signed_off 在 import 顺序 "
        f"'{import_first}' 下返回 False"
    )
    assert check_reviews.is_signed_off(approved) is True

    # 关键不变量：两边必须是同一个函数对象（不是各自的 stub）
    assert save_review.is_signed_off is check_reviews.is_signed_off, (
        "save_review.is_signed_off 与 check_reviews.is_signed_off 不是同一函数——"
        "提示循环导入仍然在某条路径上退化"
    )
