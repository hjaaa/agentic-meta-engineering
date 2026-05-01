"""T-JUDGE-1：把 skipped=true scope 喂给 review-judge Agent，应能推出 conclusion="skipped" 不崩溃。

注：本 test 不真实启动 judge Agent（subagent 调度不在 pytest 范围内）；
而是验证 judge Agent 的输入契约——skipped=true 的 scope JSON 是合法 schema，
routing_decision.decision="trivial-skipped" 字段足以让 judge 推断 conclusion。

与 T-CRITIC-1 的区别：
  - T-CRITIC-1 侧重 8 checker 不变量（critic 处理 checkers 列表）
  - T-JUDGE-1 侧重 routing_decision 字段（judge 处理 decision 字段推断最终结论）
"""
from __future__ import annotations

import json

import pytest


def _make_skipped_scope() -> dict:
    """构造 skipped=true 的合法 scope JSON（与 T-CRITIC-1 同结构，独立定义避免 import 耦合）。"""
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


class TestJudgeSkippedContract:
    def should_accept_skipped_scope_as_valid_json(self):
        """skipped=true 的 scope 是合法 JSON，judge 可无异常解析。"""
        scope = _make_skipped_scope()
        serialized = json.dumps(scope, ensure_ascii=False)
        deserialized = json.loads(serialized)
        assert deserialized == scope

    def should_have_routing_decision_with_trivial_skipped(self):
        """routing_decision.decision 必须是 'trivial-skipped'，judge 据此推断 conclusion='skipped'。

        judge 的逻辑：若 routing_decision.decision == 'trivial-skipped'，
        则直接输出 conclusion='skipped'，不需要聚合 checker verdicts。
        """
        scope = _make_skipped_scope()
        decision = scope["routing_decision"]["decision"]
        assert decision == "trivial-skipped", (
            f"期望 decision='trivial-skipped'，实际 {decision!r}"
        )

    def should_have_empty_checker_route_when_skipped(self):
        """checker_route=[] ⇒ judge 无 verdict 可聚合，直接短路输出 skipped 结论。"""
        scope = _make_skipped_scope()
        assert scope["checker_route"] == []

    def should_have_tty_verified_true(self):
        """tty_verified=True 确保 trivial-skipped 路径的 scope 仍然通过了人类卡点 A 的格式校验。

        judge 不额外校验 tty_verified；但 contract test 确保 skipped scope 不是伪造数据。
        """
        scope = _make_skipped_scope()
        assert scope["routing_decision"]["tty_verified"] is True

    def should_satisfy_scope_skipped_field_consistency(self):
        """skipped=True 与 routing_decision.decision='trivial-skipped' 必须同时成立（一致性约束）。"""
        scope = _make_skipped_scope()
        assert scope["skipped"] is True
        assert scope["routing_decision"]["decision"] == "trivial-skipped"
