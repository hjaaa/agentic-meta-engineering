"""F-003 H3 · /requirement:submit 与 /requirement:next 同源（gate 集合一致性）。

来源：requirements/REQ-2026-002/artifacts/detailed-design.md §4.2（行 411-423）。

核心断言：
  phase-transition 的 gate 集合 ⊆ submit 的 gate 集合
  submit 多出的 gate 必须只挂 'submit' trigger（如 GATE-PR-MERGED-STATE）

实现方式：
  - 构造临时 REQ 目录（pytest tmp_path），写最小 meta.yaml
  - 用 run.main(...) 走 dry-run 通道分别取两次候选 gate id 集合
  - 集合差比对
"""
from __future__ import annotations

from pathlib import Path

import yaml

import run as runner


def _make_min_req(tmp_path: Path, req_id: str = "REQ-2099-001") -> Path:
    """构造最小可加载的 REQ 目录，满足 build_context 读 meta.yaml 不抛错。

    F-003：filter_gates 升级后 GATE-PR-MERGED-STATE 的 applies_when.requires
    含 'meta.pr_number'；为满足"submit 计划包含该 gate"断言，meta 写入占位
    pr_number=999999（dry-run 不会真调 gh）。
    """
    repo_root = Path(runner._REPO_ROOT)
    # 临时把 REQ 目录建到 repo_root/requirements 下；注意：
    # _validate_requirement_id 只放行 REQ-YYYY-NNN，所以这里用 REQ-2099-001
    req_dir = repo_root / "requirements" / req_id
    req_dir.mkdir(parents=True, exist_ok=True)
    meta = req_dir / "meta.yaml"
    meta.write_text(
        yaml.safe_dump(
            {
                "id": req_id,
                "title": "submit/next parity test",
                "phase": "development",
                "branch": f"feat/{req_id.lower()}",
                # F-003：让 GATE-PR-MERGED-STATE.applies_when.requires=[meta.pr_number] 命中
                "pr_number": 999999,
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    return req_dir


def _capture_gate_plan(monkeypatch, capsys, trigger: str, req_id: str, **extra_args) -> set[str]:
    """跑 run.main 在 dry-run 模式，从 stdout 解析候选 gate id 集合。"""
    argv = [f"--trigger={trigger}", f"--req={req_id}", "--dry-run"]
    for k, v in extra_args.items():
        argv.append(f"--{k}={v}")
    rc = runner.main(argv)
    assert rc == 0, f"dry-run 应返回 0，实际 {rc}"
    out = capsys.readouterr().out
    ids: set[str] = set()
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("- GATE-"):
            # 形如 "- GATE-XXX (plugin=..., severity=...)"
            ids.add(line.split()[1])
    return ids


def test_phase_transition_gates_are_subset_of_submit(tmp_path, capsys, monkeypatch):
    """given_same_req_when_collect_gates_then_phase_transition_subset_of_submit。

    断言 phase-transition 候选集合 ⊆ submit 候选集合；
    submit 多出的 gate 必须只挂 submit trigger（不在 phase-transition 上出现）。
    """
    req_id = "REQ-2099-001"
    req_dir = _make_min_req(tmp_path, req_id=req_id)
    try:
        submit_ids = _capture_gate_plan(monkeypatch, capsys, "submit", req_id)
        phase_ids = _capture_gate_plan(
            monkeypatch, capsys, "phase-transition", req_id,
            **{"from": "development", "to": "testing"},
        )

        # 核心断言：phase-transition ⊆ submit
        missing = phase_ids - submit_ids
        assert not missing, f"phase-transition 独有 gate（应被 submit 复用）：{missing}"

        # submit 多出的 gate 必须存在于 registry 且只挂 submit trigger（或与 submit 一起）
        extra = submit_ids - phase_ids
        assert extra, "submit 应该至少多出 GATE-PR-MERGED-STATE 等 submit-only gate"
        registry = runner.load_registry()
        by_id = {g["id"]: g for g in registry["gates"]}
        for gid in extra:
            triggers = set(by_id[gid].get("triggers") or [])
            assert "submit" in triggers, f"{gid} 出现在 submit 候选但 registry triggers={triggers}"
            assert "phase-transition" not in triggers, (
                f"{gid} 既不在 phase-transition 候选又不挂 phase-transition trigger，配置矛盾"
            )
    finally:
        # 清理临时 REQ 目录（避免污染仓库）
        import shutil
        shutil.rmtree(req_dir, ignore_errors=True)


def test_submit_includes_pr_merged_state(tmp_path, capsys, monkeypatch):
    """given_submit_trigger_when_collect_gates_then_includes_pr_merged_state（防漂移）."""
    req_id = "REQ-2099-002"
    req_dir = _make_min_req(tmp_path, req_id=req_id)
    try:
        submit_ids = _capture_gate_plan(monkeypatch, capsys, "submit", req_id)
        assert "GATE-PR-MERGED-STATE" in submit_ids
    finally:
        import shutil
        shutil.rmtree(req_dir, ignore_errors=True)


def test_submit_trigger_module_main_returns_runner_exit_code(tmp_path, capsys, monkeypatch):
    """given_submit_trigger_module_when_call_main_then_proxy_runner_exit_code（H3 接通验证）."""
    import sys
    sys.path.insert(0, str(Path(runner._REPO_ROOT) / "scripts" / "gates" / "triggers"))
    import submit as submit_mod

    req_id = "REQ-2099-003"
    req_dir = _make_min_req(tmp_path, req_id=req_id)
    try:
        rc = submit_mod.main([f"--req={req_id}", "--dry-run"])
        assert rc == 0
    finally:
        import shutil
        shutil.rmtree(req_dir, ignore_errors=True)


def test_submit_forwards_force_with_blockers_to_runner(monkeypatch):
    """given_submit_main_with_--force-with-blockers_when_call_then_runner_argv_contains_flag.

    F-004 round-5（Codex P1 修复）：原实现把 --force-with-blockers 转 env var
    但 run.py 不读 env，escape_hatch 在 submit 入口完全非功能性。修后 submit.py
    直接 forward `--force-with-blockers='<reason>'` 给 runner argv。
    """
    import sys
    sys.path.insert(0, str(Path(runner._REPO_ROOT) / "scripts" / "gates" / "triggers"))
    import submit as submit_mod

    captured_argv: list[list[str]] = []

    def fake_runner_main(argv):
        captured_argv.append(list(argv))
        return 0

    monkeypatch.setattr(submit_mod.runner, "main", fake_runner_main)

    rc = submit_mod.main([
        "--req=REQ-2099-004",
        "--force-with-blockers=临时绕过：已有 Jira-1234 跟进",
        "--dry-run",
    ])
    assert rc == 0
    assert len(captured_argv) == 1
    forwarded = captured_argv[0]
    # 关键断言：runner 收到了 --force-with-blockers='<reason>'，不是 env var 兜底
    force_flags = [a for a in forwarded if a.startswith("--force-with-blockers=")]
    assert force_flags, f"runner argv 缺 --force-with-blockers='...': {forwarded}"
    assert "临时绕过：已有 Jira-1234 跟进" in force_flags[0], (
        f"reason 文本未透传给 runner: {force_flags[0]}"
    )


def test_submit_omits_force_flag_when_not_provided(monkeypatch):
    """given_submit_main_without_force_when_call_then_runner_argv_no_force_flag。

    确保不传 --force-with-blockers 时也不在 argv 加占位（否则 runner 会校验空 reason 失败）。
    """
    import sys
    sys.path.insert(0, str(Path(runner._REPO_ROOT) / "scripts" / "gates" / "triggers"))
    import submit as submit_mod

    captured_argv: list[list[str]] = []
    monkeypatch.setattr(submit_mod.runner, "main", lambda a: captured_argv.append(list(a)) or 0)

    rc = submit_mod.main(["--req=REQ-2099-005", "--dry-run"])
    assert rc == 0
    forwarded = captured_argv[0]
    assert not any(a.startswith("--force-with-blockers") for a in forwarded), (
        f"未传 --force-with-blockers 时 runner argv 不应含此 flag: {forwarded}"
    )
