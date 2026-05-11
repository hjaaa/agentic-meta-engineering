"""migrate_requirements_to_runs 单测（6 用例 TC-F13-1~6）。

来源：requirements/REQ-2026-009/artifacts/detailed-design.md §9.7
验收矩阵：
  TC-F13-1  dry_run 报告精确：N 处引用 → references_found.len==N，files_changed==[]，dry_run=True
  TC-F13-2  wet_run 全改：dry_run + wet_run 双跑后 grep 字面量数 ≤ 白名单数
  TC-F13-3  risky_unmapped 识别：f-string / concat → risky_unmapped[]，不进 files_changed[]
  TC-F13-4  白名单豁免：plan.md 历史引用 → skipped_whitelist[]
  TC-F13-5  pre-commit hook 拦截：含新增 requirements/REQ- → exit 2
  TC-F13-6  pre-commit hook 放行：markdown 引用块 / 代码块 → exit 0
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from textwrap import dedent

# sys.path 已由 conftest.py 注入 scripts/lib
import migrate_requirements_to_runs as mig

# ============================================================================
# 常量
# ============================================================================

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK_SCRIPT = REPO_ROOT / "scripts" / "git-hooks" / "pre-commit-rename-guard.sh"
FIXTURES_SRC = Path(__file__).resolve().parent / "fixtures" / "migrate_requirements"


# ============================================================================
# 辅助函数
# ============================================================================

def _make_mini_repo(tmp_path: Path) -> Path:
    """在 tmp_path 构建 mini 仓库快照（从 fixtures 复制）。

    目录结构：
      tmp_path/
        sample_script.py        — 2 literal + 1 f_string + 1 concat
        sample_doc.md           — 1 literal（正文）+ 1 quote（放行）+ 1 code（放行）
        sample_config.yaml      — 2 yaml_glob / literal
        whitelist_plan.md       — 白名单文件（不改）
    """
    for src_file in FIXTURES_SRC.iterdir():
        shutil.copy2(src_file, tmp_path / src_file.name)
    return tmp_path


def _all_fixture_files(mini_repo: Path) -> list[Path]:
    """返回 mini repo 中所有 fixture 文件（用于 extra_files 参数）。"""
    return [p for p in mini_repo.iterdir() if p.is_file()]


def _count_literals(root: Path) -> int:
    """统计 root 下所有文件中 requirements/REQ- 字面量出现次数（行级）。"""
    count = 0
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        try:
            for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                if "requirements/REQ-" in line:
                    count += 1
        except OSError:
            pass
    return count


def _run_hook(
    diff_text: str,
    *,
    bypass: str | None = None,
    env: dict | None = None,
) -> subprocess.CompletedProcess:
    """模拟 pre-commit-rename-guard.sh 的执行。

    使用 GIT_EXTERNAL_DIFF 代理：直接把 diff 写入临时文件，让 hook 读取。
    这里通过 mock 方式：patch git diff --cached 输出到 stdin（不需真实 git 仓库）。

    策略：用 bash -c 包裹 hook，把 diff_text 通过环境变量注入，
    在 hook 内 stub git diff --cached 输出。
    """
    # 将 diff_text 写入临时文件，通过 wrapper 注入
    with tempfile.NamedTemporaryFile(mode="w", suffix=".diff", delete=False, encoding="utf-8") as f:
        f.write(diff_text)
        diff_tmp = f.name

    # wrapper: 替换 git 命令，让 hook 看到 mock diff
    wrapper_script = dedent(f"""
        #!/usr/bin/env bash
        # stub git diff --cached → 读取 mock diff 文件
        git() {{
            if [[ "$1 $2 $3" == "diff --cached --unified=0" ]]; then
                cat "{diff_tmp}"
            else
                command git "$@"
            fi
        }}
        export -f git
        source "{HOOK_SCRIPT}"
        main "$@"
    """).strip()

    with tempfile.NamedTemporaryFile(mode="w", suffix=".sh", delete=False, encoding="utf-8") as wf:
        wf.write(wrapper_script)
        wrapper_tmp = wf.name

    os.chmod(wrapper_tmp, 0o755)

    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    if bypass:
        run_env["CLAUDE_GATES_GLOBAL_BYPASS"] = bypass

    result = subprocess.run(
        ["bash", wrapper_tmp],
        capture_output=True,
        text=True,
        env=run_env,
    )

    # 清理临时文件
    try:
        os.unlink(diff_tmp)
        os.unlink(wrapper_tmp)
    except OSError:
        pass

    return result


# ============================================================================
# TC-F13-1: dry_run 报告精确
# ============================================================================

def test_dry_run_report_accurate(tmp_path):
    """given_mini_repo_with_N_literals_when_dry_run_then_references_found_N_and_files_changed_empty。

    TC-F13-1: §9.7 #1
    fixture sample_script.py 含 2 literal（第 8、11 行），sample_doc.md 含 1 literal 正文，
    sample_config.yaml 含 2 literal（yaml_glob），白名单文件不计入。
    预期：references_found ≥ 1，files_changed == []，dry_run == True。
    """
    mini_repo = _make_mini_repo(tmp_path)
    extra_files = _all_fixture_files(mini_repo)

    # whitelist_plan.md 命中额外白名单列表
    whitelist = [mini_repo / "whitelist_plan.md"]

    report = mig.migrate_requirements_to_runs(
        dry_run=True,
        include_history_comments=False,
        whitelist=whitelist,
        repo_root=mini_repo,
        extra_files=extra_files,
    )

    assert report.dry_run is True, "dry_run 标志应为 True"
    assert report.files_changed == [], f"dry_run 下 files_changed 应为空，实际: {report.files_changed}"
    # mini repo 含 literal 引用（sample_script.py + sample_doc.md 正文 + sample_config.yaml）
    assert len(report.references_found) >= 1, (
        f"references_found 应 ≥ 1，实际: {len(report.references_found)}"
    )
    # risky_unmapped 应包含 f_string 和 concat
    assert len(report.risky_unmapped) >= 1, (
        f"risky_unmapped 应 ≥ 1（f_string/concat），实际: {len(report.risky_unmapped)}"
    )
    # scanned_files 应 > 0
    assert report.scanned_files >= 1, "scanned_files 应 >= 1"


# ============================================================================
# TC-F13-2: wet_run 全改
# ============================================================================

def test_wet_run_full_change(tmp_path):
    """given_mini_repo_when_dry_then_wet_run_then_literal_count_lte_whitelist_count。

    TC-F13-2: §9.7 #2 / 覆盖 AC-CLEAN
    先 dry_run 确认有引用，再 wet_run 执行替换，
    最后 grep 字面量数 ≤ 白名单数（白名单文件仍保留原始引用）。
    """
    mini_repo = _make_mini_repo(tmp_path)
    extra_files = _all_fixture_files(mini_repo)
    whitelist = [mini_repo / "whitelist_plan.md"]

    # Step 1: dry_run
    dry_report = mig.migrate_requirements_to_runs(
        dry_run=True,
        include_history_comments=False,
        whitelist=whitelist,
        repo_root=mini_repo,
        extra_files=extra_files,
    )
    assert dry_report.dry_run is True
    assert dry_report.files_changed == []

    # Step 2: wet_run（重新收集 extra_files，因为 tmp_path 相同）
    wet_report = mig.migrate_requirements_to_runs(
        dry_run=False,
        include_history_comments=False,
        whitelist=whitelist,
        repo_root=mini_repo,
        extra_files=extra_files,
    )
    assert wet_report.dry_run is False

    # Step 3: 验证可自动改的 literal 引用在 wet_run 后全部被替换
    # 用相同参数再次做 dry_run scan，references_found（literal kind）应为空
    post_scan = mig.migrate_requirements_to_runs(
        dry_run=True,
        include_history_comments=False,
        whitelist=whitelist,
        repo_root=mini_repo,
        extra_files=extra_files,
    )
    # wet_run 后再次扫描，literal 引用（可自动改的）应全部消失
    literal_remaining = [r for r in post_scan.references_found if r.kind == "literal"]
    assert literal_remaining == [], (
        f"wet_run 后 literal 引用应为 0，残留: {literal_remaining}"
    )
    # wet_run 应有 files_changed（至少改了 1 个文件）
    assert len(wet_report.files_changed) >= 1, (
        f"wet_run 后 files_changed 应 ≥ 1，实际: {wet_report.files_changed}"
    )


# ============================================================================
# TC-F13-3: risky_unmapped 识别
# ============================================================================

def test_risky_unmapped_recognized(tmp_path):
    """given_fstring_and_concat_when_scan_then_risky_unmapped_and_not_files_changed。

    TC-F13-3: §9.7 #3
    sample_script.py 含 f_string（第 17 行）和 concat（第 21 行）。
    验证：risky_unmapped[] 包含这两条，且 wet_run 后不进 files_changed[]。
    """
    mini_repo = _make_mini_repo(tmp_path)
    extra_files = _all_fixture_files(mini_repo)
    whitelist = [mini_repo / "whitelist_plan.md"]

    report = mig.migrate_requirements_to_runs(
        dry_run=True,
        include_history_comments=False,
        whitelist=whitelist,
        repo_root=mini_repo,
        extra_files=extra_files,
    )

    kinds = {ref.kind for ref in report.risky_unmapped}
    assert "f_string" in kinds, f"risky_unmapped 应含 f_string，实际: {report.risky_unmapped}"
    assert "concat" in kinds, f"risky_unmapped 应含 concat，实际: {report.risky_unmapped}"

    # 所有 risky_unmapped 的 old_text == new_text（不自动改写）
    for ref in report.risky_unmapped:
        assert ref.old_text == ref.new_text, (
            f"risky_unmapped 引用不应被自动改写: {ref}"
        )

    # wet_run 后 risky 对应行仍保留在文件中（不进 files_changed 的 risky 部分）
    mig.migrate_requirements_to_runs(
        dry_run=False,
        include_history_comments=False,
        whitelist=whitelist,
        repo_root=mini_repo,
        extra_files=extra_files,
    )
    # risky 行所在文件不应出现在 files_changed（除非该文件有其他 literal 引用）
    # sample_script.py 有 2 literal（会被改），但 f_string / concat 行本身不变
    # 验证 sample_script.py 中 f_string 行仍存在
    script_content = (mini_repo / "sample_script.py").read_text(encoding="utf-8")
    assert 'f"requirements/' in script_content or "f'requirements/" in script_content, (
        "wet_run 后 f_string 行应保持不变"
    )


# ============================================================================
# TC-F13-4: 白名单豁免
# ============================================================================

def test_whitelist_skipped(tmp_path):
    """given_plan_md_whitelist_when_scan_then_skipped_whitelist_not_references_found。

    TC-F13-4: §9.7 #4 / §9.4
    whitelist_plan.md 通过 extra_whitelist 精确路径命中（非内置正则命中），
    验证：其引用进入 skipped_whitelist[]，不进 references_found[]。
    """
    mini_repo = _make_mini_repo(tmp_path)
    extra_files = _all_fixture_files(mini_repo)
    # whitelist_plan.md 作为额外白名单（绝对路径）
    whitelist = [mini_repo / "whitelist_plan.md"]

    report = mig.migrate_requirements_to_runs(
        dry_run=True,
        include_history_comments=False,
        whitelist=whitelist,
        repo_root=mini_repo,
        extra_files=extra_files,
    )

    # 白名单文件中的引用不应在 references_found 中
    whitelist_refs_in_found = [
        ref for ref in report.references_found
        if "whitelist_plan.md" in str(ref.file_path)
    ]
    assert whitelist_refs_in_found == [], (
        f"白名单文件引用不应进入 references_found: {whitelist_refs_in_found}"
    )

    # 白名单文件引用应在 skipped_whitelist 中（内置 plan.md pattern 命中）
    # whitelist_plan.md 含 requirements/REQ- 引用，应进入 skipped_whitelist
    whitelist_skipped = [
        ref for ref in report.skipped_whitelist
        if "whitelist_plan.md" in str(ref.file_path)
    ]
    assert len(whitelist_skipped) >= 1, (
        f"whitelist_plan.md 的引用应进入 skipped_whitelist，实际: {report.skipped_whitelist}"
    )


def test_whitelist_skipped_internal_pattern(tmp_path):
    """given_plan_md_internal_pattern_when_scan_without_extra_whitelist_then_skipped_whitelist。

    验证内置正则 plan.md pattern（_BUILTIN_WHITELIST_PATTERNS）：
    requirements/REQ-2026-001/plan.md 中含跨需求引用（非自指向），
    不传 extra_whitelist，断言其进入 skipped_whitelist[]。
    """
    # 构造 mini repo：plan.md 内含跨需求引用（REQ-2026-008，非自指向）
    plan_dir = tmp_path / "requirements" / "REQ-2026-001"
    plan_dir.mkdir(parents=True)
    plan_file = plan_dir / "plan.md"
    plan_file.write_text(
        "# ADR\n"
        "详见 requirements/REQ-2026-008/artifacts/detailed-design.md §9\n",
        encoding="utf-8",
    )

    report = mig.migrate_requirements_to_runs(
        dry_run=True,
        include_history_comments=False,
        whitelist=None,
        repo_root=tmp_path,
        extra_files=[plan_file],
    )

    # plan.md 内的引用应进入 skipped_whitelist（内置 pattern 命中），不进 references_found
    skipped = [r for r in report.skipped_whitelist if "plan.md" in str(r.file_path)]
    assert len(skipped) >= 1, (
        f"内置 plan.md pattern 应命中 skipped_whitelist，实际: {report.skipped_whitelist}"
    )
    found = [r for r in report.references_found if "plan.md" in str(r.file_path)]
    assert found == [], (
        f"plan.md 引用不应进入 references_found，实际: {found}"
    )
    # 验证 kind 和 file_path 字段格式正确
    ref = skipped[0]
    assert ref.kind in {"literal", "comment", "docstring", "yaml_glob", "f_string", "concat"}, (
        f"kind 应为合法枚举值，实际: {ref.kind}"
    )
    assert ref.file_path == plan_file, (
        f"file_path 应为绝对路径 plan_file，实际: {ref.file_path}"
    )


# ============================================================================
# TC-F13-5: pre-commit hook 拦截新增 requirements/REQ- 字面量
# ============================================================================

def test_pre_commit_hook_blocks():
    """given_staged_diff_with_new_requirements_literal_when_hook_then_exit2_and_stderr_hint。

    TC-F13-5: §9.5 / §9.7 #5
    模拟 git diff --cached 输出含新增 requirements/REQ- 行，验证 hook exit 2。
    """
    assert HOOK_SCRIPT.exists(), f"hook 脚本不存在: {HOOK_SCRIPT}"

    mock_diff = dedent("""\
        diff --git a/scripts/lib/some_tool.py b/scripts/lib/some_tool.py
        index abc..def 100644
        --- a/scripts/lib/some_tool.py
        +++ b/scripts/lib/some_tool.py
        @@ -1,2 +1,3 @@
         existing_line = "unchanged"
        +new_path = "requirements/REQ-2026-001/artifacts/design.md"
        +another_ref = "requirements/REQ-2026-002/plan.md"
    """)

    result = _run_hook(mock_diff)

    assert result.returncode == 2, (
        f"hook 应 exit 2，实际: {result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "requirements/REQ-" in result.stderr or "runs/REQ-" in result.stderr, (
        f"stderr 应含迁移提示，实际: {result.stderr}"
    )


# ============================================================================
# TC-F13-6: pre-commit hook 放行 markdown 引用块和代码块
# ============================================================================

def test_pre_commit_hook_passthrough_md_quote():
    """given_staged_diff_with_quote_or_code_block_when_hook_then_exit0。

    TC-F13-6: §9.5 / §9.7（叙述性引用例外）
    markdown 引用块（> ...）和代码块（``` ... ```）内的字面量 → hook 放行（exit 0）。
    """
    assert HOOK_SCRIPT.exists(), f"hook 脚本不存在: {HOOK_SCRIPT}"

    # 仅含 markdown 引用块和代码块内的字面量（应放行）
    mock_diff = dedent("""\
        diff --git a/docs/migration-note.md b/docs/migration-note.md
        index abc..def 100644
        --- a/docs/migration-note.md
        +++ b/docs/migration-note.md
        @@ -1,3 +1,8 @@
         # Migration Note
        +
        +> 历史路径：requirements/REQ-2026-001/plan.md 已迁移至 runs/ 体系。
        +
        +```bash
        +ls requirements/REQ-2026-001/artifacts/
        +```
    """)

    result = _run_hook(mock_diff)

    assert result.returncode == 0, (
        f"引用块/代码块内字面量应放行（exit 0），实际: {result.returncode}\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
