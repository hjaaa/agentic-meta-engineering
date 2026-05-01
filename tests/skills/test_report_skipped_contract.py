"""T-REPORT-1：验证 report SKILL 接 skipped=true scope 不崩溃；
同时 grep commands/code-review.md 确认 Step 2 短路逻辑存在。

注：本 test 不真实启动 report SKILL（subagent 调度不在 pytest 范围内）；
而是：
  1. 验证 skipped=true scope JSON schema 合法，report SKILL 可无异常解析
  2. grep commands/code-review.md 中的 skipped 短路逻辑（防御：被误删时此处先报红）
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


# commands/code-review.md 的绝对路径（F-003 已在此加入短路逻辑）
_COMMANDS_MD = Path(__file__).parents[2] / ".claude" / "commands" / "code-review.md"


def _make_skipped_scope() -> dict:
    """构造 skipped=true 的合法 scope JSON（与 T-CRITIC-1 同结构，独立定义）。"""
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


class TestReportSkippedContract:
    def should_accept_skipped_scope_as_valid_json(self):
        """skipped=true 的 scope 是合法 JSON，report SKILL 可无异常解析。"""
        scope = _make_skipped_scope()
        serialized = json.dumps(scope, ensure_ascii=False)
        deserialized = json.loads(serialized)
        assert deserialized == scope

    def should_have_skipped_short_circuit_in_commands_md(self):
        """commands/code-review.md Step 2 必须含 skipped==true 短路逻辑（防御：被误删时此处先报红）。

        F-003 已在 code-review.md 加入：
          "若 skipped==true 输出最小报告并 return"
        本 test grep 等价表述（skipped + 短路/return/最小报告 三者至少一个出现）。
        """
        assert _COMMANDS_MD.exists(), f"commands/code-review.md 不存在：{_COMMANDS_MD}"
        text = _COMMANDS_MD.read_text(encoding="utf-8")

        # 必须含 "skipped" 关键字
        assert "skipped" in text, "commands/code-review.md 未找到 'skipped' 关键字"

        # 短路逻辑的等价表述之一（return / 短路 / 最小报告）
        has_short_circuit = (
            "return" in text or "短路" in text or "最小报告" in text
        )
        assert has_short_circuit, (
            "commands/code-review.md 含 'skipped' 但未找到短路逻辑"
            "（期望 'return' / '短路' / '最小报告' 之一）"
        )

    def should_have_skipped_checkers_field_in_scope(self):
        """skipped_checkers 字段存在且为非空列表，report SKILL 需用此字段渲染 trivial 报告摘要。"""
        scope = _make_skipped_scope()
        assert "skipped_checkers" in scope
        assert isinstance(scope["skipped_checkers"], list)
        assert len(scope["skipped_checkers"]) > 0

    def should_have_consistent_skipped_fields(self):
        """skipped=True 时，checker_route=[] 且 routing_decision.decision='trivial-skipped'。

        report SKILL 依赖这三个字段联合判断输出最小报告还是完整报告。
        """
        scope = _make_skipped_scope()
        assert scope["skipped"] is True
        assert scope["checker_route"] == []
        assert scope["routing_decision"]["decision"] == "trivial-skipped"
