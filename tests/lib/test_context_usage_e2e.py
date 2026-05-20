"""F-013 · 端到端 fixture 仓库测试 + 1000 文件性能守门。

覆盖：
  - E2E 状态计数（orphan / visible_unused / needs_review / active / high_value）
  - E2E 断链 + 孤岛检测
  - E2E 4 种引用形式
  - AC-4 git status 非报告文件不被修改
  - 1000 文件性能守门（< 10.0s，走 git_log 主路径）
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

_THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_THIS_DIR.parents[1] / "scripts" / "lib"))
sys.path.insert(0, str(_THIS_DIR))

from _context_usage_helpers import FIXTURE_REPO as _FIXTURE_REPO  # noqa: E402


def _run_on_fixture(tmp_path: Path) -> tuple[int, dict]:
    """在 fixture 仓库上运行 main()，返回 (exit_code, json_data)。

    输出写到 tmp_path/reports/ 避免污染仓库。
    """
    from context_usage_report import main as _main  # noqa: PLC0415

    output_md = tmp_path / "reports" / "context-usage.md"
    output_json = tmp_path / "reports" / "context-usage.json"

    exit_code = _main(
        [
            "--context-dir", str(_FIXTURE_REPO / "context"),
            "--requirements-dir", str(_FIXTURE_REPO / "requirements"),
            "--output", str(output_md),
            "--json-output", str(output_json),
            "--repo-root", str(_FIXTURE_REPO),
            "--format", "both",
        ]
    )
    json_data: dict = {}
    if output_json.exists():
        json_data = json.loads(output_json.read_text(encoding="utf-8"))
    return exit_code, json_data


def test_e2e_fixture_status_counts(tmp_path: Path) -> None:
    """E2E：在 fixture 仓库上运行 main()，断言各 status 类别计数。

    状态覆盖要求：
    - orphan ≥ 1（context/team/orphan.md 不在 INDEX、无 requirements 引用）
    - visible_unused ≥ 1（context/team/glossary.md 在 INDEX、无 requirements 引用）
    - needs_review ≥ 1（context/team/archived.md 不在 INDEX、有 requirements 引用）
    - active 或 high_value 各 ≥ 1（有引用的 active 文件）
    """
    exit_code, json_data = _run_on_fixture(tmp_path)
    assert exit_code == 0, f"main() 返回非 0 退出码: {exit_code}"

    by_status = json_data["summary"]["by_status"]

    assert by_status.get("orphan", 0) >= 1, (
        f"期望 orphan ≥ 1，实际 by_status={by_status}"
    )
    assert by_status.get("visible_unused", 0) >= 1, (
        f"期望 visible_unused ≥ 1，实际 by_status={by_status}"
    )
    assert by_status.get("needs_review", 0) >= 1, (
        f"期望 needs_review ≥ 1，实际 by_status={by_status}"
    )
    has_active_or_hv = (
        by_status.get("active", 0) >= 1
        or by_status.get("high_value", 0) >= 1
    )
    assert has_active_or_hv, (
        f"期望 active 或 high_value ≥ 1，实际 by_status={by_status}"
    )
    total = json_data["summary"]["total"]
    status_sum = sum(by_status.values())
    assert status_sum == total, (
        f"status 计数之和 {status_sum} ≠ 总计 {total}"
    )


def test_e2e_fixture_broken_links_orphans(tmp_path: Path) -> None:
    """E2E：断言 broken_links ≥ 1 且 orphans ≥ 1。

    - context/INDEX.md 中引用了不存在的 context/team/does-not-exist.md → broken_link
    - context/team/orphan.md 不在任何 INDEX 中且无 requirements 引用 → orphan
    """
    exit_code, json_data = _run_on_fixture(tmp_path)
    assert exit_code == 0

    broken = json_data["summary"]["broken_links"]
    orphans = json_data["summary"]["orphans"]

    assert broken >= 1, f"期望 broken_links ≥ 1，实际 {broken}"
    assert orphans >= 1, f"期望 orphans ≥ 1，实际 {orphans}"


def test_e2e_fixture_reference_kinds(tmp_path: Path) -> None:
    """E2E：断言 4 种引用形式均出现在 JSON 输出的 reference_evidences 中。

    - markdown_link: [团队约定](context/team/conventions.md)
    - raw_path:      参见 context/team/ai-collab.md 的两条硬规则
    - source_marker: （来源：context/project/alpha/spec.md）
    - json_value:    data.json 中 "context/team/conventions.md"
    """
    exit_code, json_data = _run_on_fixture(tmp_path)
    assert exit_code == 0

    kinds_found: set[str] = set()
    for file_entry in json_data.get("files", []):
        for ev in file_entry.get("reference_evidences", []):
            kinds_found.add(ev["kind"])

    required_kinds = {"markdown_link", "raw_path", "source_marker", "json_value"}
    missing = required_kinds - kinds_found
    assert not missing, (
        f"缺少以下引用形式：{missing}；实际发现：{kinds_found}"
    )


@pytest.mark.integration
def test_main_does_not_modify_non_report_files(tmp_path: Path) -> None:
    """AC-4：跑 main() 后 git status 不应引入 reports/* 以外的新增改动。

    在真实仓库数据上运行 main()，捕获运行前后 git status --porcelain 的差异，
    确认 main() 本身没有修改或新增非报告文件。输出写到 tmp_path 避免污染仓库。
    """
    from context_usage_report import main as _main  # noqa: PLC0415

    repo_root = Path(__file__).resolve().parents[2]

    def _get_status(cwd: str) -> set[str]:
        """获取当前 git status --porcelain 行集合。"""
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=cwd,
            capture_output=True, text=True, check=True,
        )
        return set(result.stdout.splitlines())

    status_before = _get_status(str(repo_root))

    output = tmp_path / "report.md"
    json_output = tmp_path / "report.json"

    exit_code = _main(
        [
            "--context-dir", str(repo_root / "context"),
            "--requirements-dir", str(repo_root / "requirements"),
            "--output", str(output),
            "--json-output", str(json_output),
            "--repo-root", str(repo_root),
            "--format", "both",
        ]
    )
    assert exit_code == 0, f"main() 返回非 0 退出码: {exit_code}"

    status_after = _get_status(str(repo_root))

    new_lines = status_after - status_before
    non_report_new = [line for line in new_lines if "reports/" not in line]

    assert not non_report_new, (
        f"main() 引入了 reports/* 之外的非预期改动：{non_report_new}"
    )


# ---------------------------------------------------------------------------
# 1000 文件性能 fixture + CI 守门
# ---------------------------------------------------------------------------


def _build_perf_fixture(tmp_path: Path) -> tuple[Path, Path]:
    """程序化生成 1000 个 context 文件 + 50 个 requirements 文件到临时目录。

    初始化 git 仓库并 commit，让 fetch_git_timestamps 走 git_log 主路径而非 fallback。
    """
    context_dir = tmp_path / "context"
    req_dir = tmp_path / "requirements"
    context_dir.mkdir()
    req_dir.mkdir()

    index_lines = ["# INDEX", ""]
    for i in range(1000):
        kind = "team" if i % 2 == 0 else "project/alpha"
        rel = f"context/{kind}/file_{i:04d}.md"
        sub = context_dir / kind
        sub.mkdir(parents=True, exist_ok=True)
        (sub / f"file_{i:04d}.md").write_text(f"# file {i}\n", encoding="utf-8")
        index_lines.append(f"- [file {i}]({rel})")
    (context_dir / "INDEX.md").write_text("\n".join(index_lines), encoding="utf-8")

    for i in range(50):
        rd = req_dir / f"REQ-99-{i:03d}"
        rd.mkdir()
        (rd / "plan.md").write_text(
            f"# REQ {i}\n参见 context/team/file_{(i * 20) % 1000:04d}.md\n",
            encoding="utf-8",
        )

    # 初始化 git 仓库，让 fetch_git_timestamps 走 git_log 主路径（覆盖生产场景）
    subprocess.run(["git", "init"], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test"],
        cwd=str(tmp_path), check=True, capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(tmp_path), check=True, capture_output=True,
    )
    subprocess.run(["git", "add", "."], cwd=str(tmp_path), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "perf fixture bootstrap"],
        cwd=str(tmp_path), check=True, capture_output=True,
    )

    return context_dir, req_dir


def test_perf_1000_files(tmp_path: Path) -> None:
    """性能守门：1000 context + 50 requirements → 全流程 < 10.0s。

    程序化生成 fixture 并 git init + commit，让 fetch_git_timestamps 走 git_log 主路径
    而非 fallback（覆盖生产场景）。阈值 10.0s 比 5.0s 保守，git_log 主路径覆盖
    比时间精度更重要。使用 time.perf_counter() 计时。
    """
    from context_usage_report import main as _main  # noqa: PLC0415

    context_dir, req_dir = _build_perf_fixture(tmp_path)
    output_md = tmp_path / "reports" / "perf.md"
    output_json = tmp_path / "reports" / "perf.json"

    t0 = time.perf_counter()
    exit_code = _main(
        [
            "--context-dir", str(context_dir),
            "--requirements-dir", str(req_dir),
            "--output", str(output_md),
            "--json-output", str(output_json),
            "--repo-root", str(tmp_path),
            "--format", "both",
        ]
    )
    elapsed = time.perf_counter() - t0

    assert exit_code == 0, f"main() 返回非 0 退出码: {exit_code}"
    assert elapsed < 10.0, f"性能不达标：{elapsed:.2f}s > 10.0s"
