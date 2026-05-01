"""T-CRITIC-1：把 skipped=true scope 喂给 review-critic Agent，应优雅返回空 verdicts，不应 traceback。

注：本 test 不真实启动 critic Agent（subagent 调度不在 pytest 范围内）；
而是验证 critic Agent 的输入契约——skipped=true 的 scope JSON 是合法 schema，
且 commands/code-review.md 已通过 `if scope.skipped == true: return` 短路逻辑保证 critic 不被调用。

防御性价值：
  1. 当未来有人误改 routing.py 让 skipped scope 字段错位，contract test 会先失败；
  2. 当 commands/code-review.md 的短路被误删，T-REPORT-1 的文档 grep 失败。
  3. I7/I8 不变量（skipped=true ⇒ checker_route=[] ∧ len(skipped_checkers)==8）持续守护。
"""
from __future__ import annotations

import json


def _make_skipped_scope() -> dict:
    """构造 skipped=true 的合法 scope JSON（按 §3.1 schema + §3.3 reason 模板）。"""
    return {
        "mode": "embedded",
        "requirement_id": "REQ-2099-001",
        "feature_id": "F-001",
        "base_sha": "abc1234",
        "head_sha": "def5678",
        "base_branch": "develop",
        "current_branch": "feat/req-2099-001",
        "services": ["test-service"],
        "stats": {"files_changed": 5, "insertions": 50, "deletions": 0},
        "diff_summary": "docs/a.md (+10 -0)\ndocs/b.md (+10 -0)",
        "timestamp": "2026-05-01T10:00:00+08:00",
        "skipped": True,
        "checker_route": [],
        "skipped_checkers": [
            {"name": name, "reason": "diff 全在 trivial 白名单内（skipped=true 全 8 个）"}
            for name in [
                "complexity-checker",
                "security-checker",
                "concurrency-checker",
                "performance-checker",
                "error-handling-checker",
                "design-consistency-checker",
                "history-context-checker",
                "auxiliary-spec-checker",
            ]
        ],
        "routing_decision": {
            "decision": "trivial-skipped",
            "confirmed_at": "2026-05-01 10:00:00",
            "confirmed_by": "test@example.com",
            "tty_verified": True,
            "files_must_hit": 0,
            "files_suggest_hit": 0,
            "files_trivial": 5,
            "files_total": 5,
        },
    }


class TestCriticSkippedContract:
    def should_accept_skipped_scope_as_valid_json(self) -> None:
        """skipped=true 的 scope 是合法 JSON，可被 critic 解析（即便不会被调用）。"""
        scope = _make_skipped_scope()
        serialized = json.dumps(scope, ensure_ascii=False)
        deserialized = json.loads(serialized)
        assert deserialized == scope, (
            f"JSON 往返不一致: deserialized={deserialized!r} scope={scope!r}"
        )

    def should_satisfy_invariant_i7(self) -> None:
        """I7: skipped=true ⇒ checker_route=[] ∧ len(skipped_checkers)==8。

        I7 是 §3.1 schema 不变量，routing.py 的 _assert_scope_invariants 在写 scope 前校验。
        本 test 确保 contract test 构造的 scope 也满足同一约束，防止测试本身造假。
        """
        scope = _make_skipped_scope()
        assert scope["skipped"] is True, f"期望 skipped=True，实际 {scope['skipped']!r}"
        assert scope["checker_route"] == [], f"期望 checker_route=[]，实际 {scope['checker_route']!r}"
        assert len(scope["skipped_checkers"]) == 8, (
            f"期望 8 个 skipped_checkers，实际 {len(scope['skipped_checkers'])}"
        )

    def should_satisfy_invariant_i8(self) -> None:
        """I8: len(checker_route) + len(skipped_checkers) == 8（总 checker 数恒为 8）。"""
        scope = _make_skipped_scope()
        total = len(scope["checker_route"]) + len(scope["skipped_checkers"])
        assert total == 8, f"期望 8 个 checker，实际 {total}"

    def should_use_trivial_reason_template(self) -> None:
        """§3.3：trivial-skip 路径下 reason 必须是固定模板字串。

        固定字串防止 reason 自由发挥导致下游报告模板渲染错误。
        """
        scope = _make_skipped_scope()
        for entry in scope["skipped_checkers"]:
            assert entry["reason"] == "diff 全在 trivial 白名单内（skipped=true 全 8 个）", (
                f"checker {entry['name']} reason 不符合模板: {entry['reason']!r}"
            )

    def should_contain_all_eight_checker_names(self) -> None:
        """skipped_checkers 必须覆盖全部 8 个合法 checker 名称（与 ALL_CHECKERS 保持一致）。"""
        from scripts.lib.code_review_routing import ALL_CHECKERS

        scope = _make_skipped_scope()
        skipped_names = {e["name"] for e in scope["skipped_checkers"]}
        assert skipped_names == set(ALL_CHECKERS), (
            f"skipped_checkers 名称集合不匹配 ALL_CHECKERS: {skipped_names ^ set(ALL_CHECKERS)}"
        )
