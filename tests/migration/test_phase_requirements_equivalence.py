"""F-011 migration 双跑对照测试：R001~R007 旧链路 vs 新链路等价性验证。

设计依据：requirements/REQ-2026-009/artifacts/detailed-design.md §8
通过门槛：21 条 parametrize 双跑对照 0 误差（0 false-pass + 0 false-fail）

旧链路：直接 import check_reviews，调用各 _rXXX 函数 → 返回 LegacyReport
新链路：调用 plugins.review_verdict_ci.run_r_rules（与 GATE-REVIEW-VERDICT plugin 复用同一 helper）
          → 返回 LegacyReport → 提取结论枚举 + violation codes

断言协议：
  - 结论枚举（pass / fail / warn）两条链路完全一致
  - violation code 集合（如 R001, R002/missing 等）前缀匹配一致
  - 错误码（exit 1 vs Decision.FAIL）允许差异，由 plugin 内部归一化
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

# conftest.py 已注入 scripts/lib 和 scripts/gates 到 sys.path
REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

# 延迟 import（conftest 注入 path 后才能用）
from common import Report as LegacyReport  # noqa: E402
from plugins import review_verdict_ci  # noqa: E402


# ============================================================================
# Fixture 加载器
# ============================================================================

def _load_fixture(rule: str, kind: str) -> dict[str, Any]:
    """加载 fixtures/<rule>/<kind>.yaml；失败时抛出含路径的明确异常。"""
    fixture_path = FIXTURES_DIR / rule / f"{kind}.yaml"
    if not fixture_path.exists():
        raise FileNotFoundError(
            f"Migration test fixture 不存在：{fixture_path}。"
            f"请确认 tests/migration/fixtures/{rule}/{kind}.yaml 已创建。"
        )
    with fixture_path.open("r", encoding="utf-8") as f:
        try:
            data = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise ValueError(
                f"Fixture YAML 解析失败（path={fixture_path}）：{exc}"
            ) from exc
    if not isinstance(data, dict):
        raise ValueError(
            f"Fixture 格式错误（path={fixture_path}）：期望 YAML mapping，实际为 {type(data)}"
        )
    return data


def _build_review_json(req_id: str, review_spec: dict) -> dict[str, Any]:
    """根据 fixture review 规格构建 review JSON 数据。

    支持字段：
      suffix, phase, conclusion, with_signoff, supersedes,
      malformed（缺字段）, bad_issues_type（issues 类型错）
    """
    suffix = review_spec["suffix"]
    phase = review_spec.get("phase", "definition")
    conclusion = review_spec.get("conclusion", "looks_clean")
    with_signoff = review_spec.get("with_signoff", True)
    supersedes = review_spec.get("supersedes", None)

    # reviewer 合法值映射（来源：review-schema.yaml）
    _reviewer_map = {
        "definition": "requirement-quality-reviewer",
        "outline-design": "outline-design-quality-reviewer",
        "detail-design": "detail-design-quality-reviewer",
        "code": "code-quality-reviewer",
    }
    reviewer = _reviewer_map.get(phase, "requirement-quality-reviewer")

    if review_spec.get("malformed"):
        # R002 failure：缺必填字段，仅保留 review_id 和 requirement_id
        return {
            "review_id": f"REV-{req_id}-{suffix}",
            "requirement_id": req_id,
            # 故意缺失 schema_version, reviewer, reviewed_at 等 required 字段
        }

    dimensions: dict[str, Any] = {}
    dim_keys = [
        "design_consistency", "security", "concurrency", "complexity",
        "error_handling", "auxiliary_spec", "performance", "history_context",
    ]
    for k in dim_keys:
        if review_spec.get("bad_issues_type") and k == "design_consistency":
            # R002 boundary：issues 类型错（object 而非 array）
            dimensions[k] = {"score": 90, "issues": {"wrong": "type"}}
        else:
            dimensions[k] = {"score": 90, "issues": []}

    signoff: dict[str, Any] | None = None
    if with_signoff:
        signoff = {
            "decision": "approved",
            "source": "cli-tty",
            "signed_at": "2026-01-01 00:00:00",
            "signed_by": "test-user",
        }

    data: dict[str, Any] = {
        "schema_version": "1.0",
        "review_id": f"REV-{req_id}-{suffix}",
        "requirement_id": req_id,
        "phase": phase,
        "reviewer": reviewer,
        "reviewed_at": "2026-01-01 00:00:00",
        "reviewed_commit": "abc1234567",
        "reviewed_artifacts": [],
        "conclusion": conclusion,
        "score": 90,
        "dimensions": dimensions,
        "required_fixes": [],
        "suggestions": [],
        "scope": {"feature_id": None},
        "supersedes": supersedes,
    }
    if signoff is not None:
        data["human_signoff"] = signoff
    return data


def _setup_req_dir(
    tmp_path: Path,
    fixture: dict[str, Any],
) -> tuple[Path, str, str]:
    """在 tmp_path 下按 fixture 描述搭建需求目录树。

    返回：(req_dir, req_id, target_phase)
    """
    req_id: str = fixture["req_id"]
    target_phase: str = fixture["target_phase"]
    meta: dict = fixture["meta"]
    review_specs: list[dict] = fixture.get("reviews", [])
    features: list[dict] = fixture.get("features", [])

    # 建目录
    req_dir = tmp_path / "requirements" / req_id
    req_dir.mkdir(parents=True, exist_ok=True)
    (req_dir / "reviews").mkdir(exist_ok=True)

    # 写 meta.yaml
    with (req_dir / "meta.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(meta, f, allow_unicode=True)

    # 写 review JSON 文件
    for spec in review_specs:
        review_data = _build_review_json(req_id, spec)
        suffix = spec["suffix"]
        review_path = req_dir / "reviews" / f"{suffix}.json"
        with review_path.open("w", encoding="utf-8") as f:
            json.dump(review_data, f, ensure_ascii=False)

    # 写 features.json（R007 场景）
    if features:
        artifacts_dir = req_dir / "artifacts"
        artifacts_dir.mkdir(exist_ok=True)
        features_data = {"features": features}
        with (artifacts_dir / "features.json").open("w", encoding="utf-8") as f:
            json.dump(features_data, f, ensure_ascii=False)

    return req_dir, req_id, target_phase


def _classify_report(report: LegacyReport, strict: bool = False) -> str:
    """把 LegacyReport 分类为 pass / fail / warn。

    - strict=True 时 warnings 也升为 fail（与 report.exit_code(strict=True) 对齐）
    - errors > 0       → "fail"
    - errors == 0 且 warnings > 0 且 strict → "fail"
    - errors == 0 且 warnings > 0 → "warn"
    - errors == 0 且 warnings == 0 → "pass"
    """
    if report.exit_code(strict=strict) != 0:
        if report.errors > 0:
            return "fail"
        # strict=True 且只有 warnings → exit_code=1，升为 fail
        return "fail"
    if report.warnings > 0:
        return "warn"
    return "pass"


def _extract_violation_rule_codes(report: LegacyReport) -> set[str]:
    """从 LegacyReport findings 中提取规则码集合（如 R001, R002, R003 等）。

    双跑对照使用：仅比较规则码前缀（Rn 部分），不比较子码（如 R002/missing 中的 /missing）。
    """
    codes: set[str] = set()
    for _, _, code, _ in report.findings():
        # 取 /前缀，如 "R002/missing" → "R002"，"R001" → "R001"
        prefix = code.split("/")[0]
        codes.add(prefix)
    return codes


# ============================================================================
# 旧链路：直接调用 check_reviews._rXXX 函数
# ============================================================================

def _run_old_chain(
    req_dir: Path, req_id: str, target_phase: str, strict: bool = False
) -> LegacyReport:
    """旧链路：monkeypatch REQUIREMENTS_DIR + 直接调用 R001~R007 函数。

    使用 review_verdict_ci.check_reviews 的内部引用做 patch，与新链路保持同一模块实例，
    避免 test_signoff_no_circular_import._purge_modules 导致模块漂移。

    strict=True 时 R004 的 WARNING 通过 report.exit_code(strict=True) 升为 ERROR 语义。
    """
    # 与 _run_new_chain 保持一致：从 review_verdict_ci 取内部 check_reviews 引用
    cr = review_verdict_ci.check_reviews
    original_dir = cr.REQUIREMENTS_DIR
    cr.REQUIREMENTS_DIR = req_dir.parent
    try:
        meta = cr._load_meta(req_id)
        report = LegacyReport()
        label = req_id
        cr._r001_review_exists(meta, target_phase, report, label)
        cr._r002_schema_recheck(meta, target_phase, report, label, req_id)
        cr._r003_blocked_or_unsigned(meta, target_phase, report, label, req_id)
        cr._r004_needs_revision(meta, target_phase, report, label)
        cr._r005_hash_drift(meta, target_phase, report, label, req_id)
        cr._r006_supersedes_chain(meta, target_phase, report, label, req_id)
        cr._r007_code_by_feature_coverage(meta, target_phase, report, label, req_id)
        return report
    finally:
        cr.REQUIREMENTS_DIR = original_dir


# ============================================================================
# 新链路：调用 review_verdict_ci.run_r_rules
# ============================================================================

def _run_new_chain(
    req_dir: Path, req_id: str, target_phase: str, strict: bool = False
) -> LegacyReport:
    """新链路：monkeypatch REQUIREMENTS_DIR + 调用 run_r_rules（plugin 内部 helper）。

    注意：使用 review_verdict_ci.check_reviews 的内部引用做 patch，而不是重新 import，
    避免 test_signoff_no_circular_import 的 _purge_modules() 导致模块实例漂移——
    purge 后 `import check_reviews` 会拿到新实例，但 review_verdict_ci 内部还持有旧引用，
    导致两条链路各自看到不同的 REQUIREMENTS_DIR 值（F-011 isolation bug）。

    strict=True 时 R004 的 WARNING 通过 report.exit_code(strict=True) 升为 ERROR 语义，
    由调用方在 _classify_report(report, strict=strict) 阶段消费。
    """
    # 从 review_verdict_ci 内部取 check_reviews 引用，保证与 run_r_rules 看到同一实例
    cr = review_verdict_ci.check_reviews
    original_dir = cr.REQUIREMENTS_DIR
    cr.REQUIREMENTS_DIR = req_dir.parent
    try:
        meta = cr._load_meta(req_id)
        report = LegacyReport()
        label = req_id
        # 新链路复用 run_r_rules（GATE-REVIEW-VERDICT plugin 的 _run_single_requirement 同一路径）
        review_verdict_ci.run_r_rules(report, meta, target_phase, label, req_id, None)
        return report
    finally:
        cr.REQUIREMENTS_DIR = original_dir


# ============================================================================
# 21 条 parametrize 对照用例
# ============================================================================

FIXTURE_MATRIX = [
    ("R001", "happy"),
    ("R001", "failure"),
    ("R001", "boundary"),
    ("R002", "happy"),
    ("R002", "failure"),
    ("R002", "boundary"),
    ("R003", "happy"),
    ("R003", "failure"),
    ("R003", "boundary"),
    ("R004", "happy"),
    ("R004", "failure"),
    ("R004", "boundary"),
    ("R005", "happy"),
    ("R005", "failure"),
    ("R005", "boundary"),
    ("R006", "happy"),
    ("R006", "failure"),
    ("R006", "boundary"),
    ("R007", "happy"),
    ("R007", "failure"),
    ("R007", "boundary"),
]


@pytest.mark.parametrize("rule,kind", FIXTURE_MATRIX, ids=[f"{r}-{k}" for r, k in FIXTURE_MATRIX])
def test_dual_run_equivalence(tmp_path: Path, rule: str, kind: str) -> None:
    """双跑对照：同一 fixture 在旧/新两条链路上结论枚举 + violation 规则码集合完全一致。

    覆盖 R001~R007 × {happy, failure, boundary} = 21 条对照用例。
    通过门槛：0 false-pass（旧 fail 但新 pass）+ 0 false-fail（旧 pass 但新 fail）。
    """
    fixture = _load_fixture(rule, kind)
    req_dir, req_id, target_phase = _setup_req_dir(tmp_path, fixture)

    # 从 fixture 读取 strict 标志（R004 boundary 等场景用）
    strict: bool = bool(fixture.get("strict", False))

    # 跑旧链路
    old_report = _run_old_chain(req_dir, req_id, target_phase, strict=strict)
    old_conclusion = _classify_report(old_report, strict=strict)
    old_codes = _extract_violation_rule_codes(old_report)

    # 跑新链路
    new_report = _run_new_chain(req_dir, req_id, target_phase, strict=strict)
    new_conclusion = _classify_report(new_report, strict=strict)
    new_codes = _extract_violation_rule_codes(new_report)

    assert old_conclusion == new_conclusion, (
        f"{rule} {kind} 结论枚举不一致："
        f"old={old_conclusion!r} vs new={new_conclusion!r}\n"
        f"  旧链路 findings={old_report.findings()}\n"
        f"  新链路 findings={new_report.findings()}"
    )
    assert old_codes == new_codes, (
        f"{rule} {kind} violation 规则码集合不一致："
        f"old={sorted(old_codes)} vs new={sorted(new_codes)}\n"
        f"  旧链路 findings={old_report.findings()}\n"
        f"  新链路 findings={new_report.findings()}"
    )

    # 验证 expected_conclusion（fixture 显式声明的预期）
    expected = fixture.get("expected_conclusion")
    if expected is not None:
        assert old_conclusion == expected, (
            f"{rule} {kind} 旧链路结论与 fixture expected 不符："
            f"actual={old_conclusion!r} expected={expected!r}\n"
            f"  findings={old_report.findings()}"
        )

    # 验证 expected_codes（如 fixture 显式声明了至少期望哪些规则码）
    expected_codes: list[str] = fixture.get("expected_codes", [])
    for ec in expected_codes:
        assert ec in old_codes, (
            f"{rule} {kind} 旧链路缺少期望规则码 {ec!r}：old_codes={sorted(old_codes)}"
        )
        assert ec in new_codes, (
            f"{rule} {kind} 新链路缺少期望规则码 {ec!r}：new_codes={sorted(new_codes)}"
        )


# ============================================================================
# 汇总断言：0 false-pass + 0 false-fail
# ============================================================================

def test_zero_mismatch_across_all_fixtures(tmp_path: Path) -> None:
    """汇总断言：全 21 条 fixture 双跑对照无任何 false-pass / false-fail。

    单独跑这个 test 会从零建目录，与上面的 parametrize 测试独立。
    通过本测试等价于 §8.4 的自举硬阈值。
    """
    mismatches: list[str] = []

    for rule, kind in FIXTURE_MATRIX:
        fixture = _load_fixture(rule, kind)
        req_dir, req_id, target_phase = _setup_req_dir(tmp_path / f"{rule}-{kind}", fixture)

        old_report = _run_old_chain(req_dir, req_id, target_phase)
        old_conclusion = _classify_report(old_report)
        new_report = _run_new_chain(req_dir, req_id, target_phase)
        new_conclusion = _classify_report(new_report)

        if old_conclusion != new_conclusion:
            mismatches.append(
                f"  {rule}/{kind}: old={old_conclusion!r} != new={new_conclusion!r}"
            )

    assert len(mismatches) == 0, (
        f"双跑对照发现 {len(mismatches)} 条 mismatch（0 false-pass + 0 false-fail 门槛未过）：\n"
        + "\n".join(mismatches)
    )


# ============================================================================
# TC-F11-2：断言 registry.yaml triggers 字段含 phase-transition / submit / ci
# ============================================================================

def test_three_triggers() -> None:
    """断言 GATE-REVIEW-VERDICT registry.yaml triggers 字段含 phase-transition / submit / ci 三项。

    TC-F11-2：不改 registry.yaml，仅读取并断言三 trigger 字段已存在。
    """
    registry_path = REPO_ROOT / "scripts" / "gates" / "registry.yaml"
    assert registry_path.exists(), f"registry.yaml 不存在：{registry_path}"

    with registry_path.open("r", encoding="utf-8") as f:
        try:
            reg = yaml.safe_load(f)
        except yaml.YAMLError as exc:
            raise ValueError(
                f"registry.yaml YAML 解析失败（path={registry_path}）：{exc}"
            ) from exc

    gates = reg.get("gates", [])
    gate = next(
        (g for g in gates if g.get("id") == "GATE-REVIEW-VERDICT"),
        None,
    )
    assert gate is not None, (
        "registry.yaml 中找不到 id=GATE-REVIEW-VERDICT 的 gate 配置"
    )
    triggers = set(gate.get("triggers") or [])
    required_triggers = {"phase-transition", "submit", "ci"}
    assert required_triggers <= triggers, (
        f"GATE-REVIEW-VERDICT triggers 字段缺少必要项："
        f"required={sorted(required_triggers)}, actual={sorted(triggers)}"
    )


# ============================================================================
# TC-F11-4：R003 signoff through hook 联动断言
# ============================================================================

def test_r003_signoff_through_hook(tmp_path: Path) -> None:
    """R003 signoff 路径：有 human_signoff → PASS；无 → FAIL；双跑等价。

    与 F-009 hook + isatty 双层校验联动：
    - APPROVAL_SLASH_PATTERN 常量已在 .claude/hooks/pre-tool-use-guard.sh 中定义
      （grep 断言证明 hook 链落地）
    - 本测试不真起 hook 子进程，仅验证 Python 层 R003 双跑等价
    """
    # ── 验证 hook 链已落地（TC-F11-4 联动部分）──
    hook_path = REPO_ROOT / ".claude" / "hooks" / "pre-tool-use-guard.sh"
    assert hook_path.exists(), f"pre-tool-use-guard.sh 不存在：{hook_path}"
    hook_content = hook_path.read_text(encoding="utf-8")
    assert "APPROVAL_SLASH_PATTERN" in hook_content, (
        "pre-tool-use-guard.sh 中未找到 APPROVAL_SLASH_PATTERN 字串，"
        "hook 链可能未落地（与 F-009 联动）"
    )

    req_id = "REQ-2099-199"
    target_phase = "tech-research"

    # ── 场景 A：有完整 signoff → 双跑均为 pass ──
    meta_with_signoff = {
        "id": req_id,
        "title": "R003 hook test with signoff",
        "phase": "definition",
        "created_at": "2026-01-01 00:00:00",
        "branch": f"feat/{req_id.lower()}",
        "base_branch": "develop",
        "reviews": {
            "definition": {
                "latest": f"REV-{req_id}-definition-001",
                "conclusion": "looks_clean",
            }
        },
    }
    review_with_signoff = {
        "schema_version": "1.0",
        "review_id": f"REV-{req_id}-definition-001",
        "requirement_id": req_id,
        "phase": "definition",
        "reviewer": "requirement-quality-reviewer",
        "reviewed_at": "2026-01-01 00:00:00",
        "reviewed_commit": "abc1234567",
        "reviewed_artifacts": [],
        "conclusion": "looks_clean",
        "score": 90,
        "dimensions": {
            k: {"score": 90, "issues": []}
            for k in [
                "design_consistency", "security", "concurrency", "complexity",
                "error_handling", "auxiliary_spec", "performance", "history_context",
            ]
        },
        "required_fixes": [],
        "suggestions": [],
        "scope": {"feature_id": None},
        "supersedes": None,
        "human_signoff": {
            "decision": "approved",
            "source": "cli-tty",
            "signed_at": "2026-01-01 00:00:00",
            "signed_by": "test-user",
        },
    }

    req_dir = tmp_path / "requirements" / req_id
    req_dir.mkdir(parents=True, exist_ok=True)
    (req_dir / "reviews").mkdir(exist_ok=True)
    with (req_dir / "meta.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(meta_with_signoff, f, allow_unicode=True)
    with (req_dir / "reviews" / "definition-001.json").open("w", encoding="utf-8") as f:
        json.dump(review_with_signoff, f, ensure_ascii=False)

    old_pass = _run_old_chain(req_dir, req_id, target_phase)
    new_pass = _run_new_chain(req_dir, req_id, target_phase)
    assert _classify_report(old_pass) == "pass", (
        f"R003 有 signoff 场景：旧链路应为 pass，实际 findings={old_pass.findings()}"
    )
    assert _classify_report(new_pass) == "pass", (
        f"R003 有 signoff 场景：新链路应为 pass，实际 findings={new_pass.findings()}"
    )
    assert _classify_report(old_pass) == _classify_report(new_pass), (
        "R003 有 signoff 场景：旧/新链路结论不一致"
    )

    # ── 场景 B：移除 human_signoff → 双跑均为 fail ──
    review_no_signoff = {k: v for k, v in review_with_signoff.items() if k != "human_signoff"}
    with (req_dir / "reviews" / "definition-001.json").open("w", encoding="utf-8") as f:
        json.dump(review_no_signoff, f, ensure_ascii=False)

    old_fail = _run_old_chain(req_dir, req_id, target_phase)
    new_fail = _run_new_chain(req_dir, req_id, target_phase)
    assert _classify_report(old_fail) == "fail", (
        f"R003 无 signoff 场景：旧链路应为 fail，实际 findings={old_fail.findings()}"
    )
    assert _classify_report(new_fail) == "fail", (
        f"R003 无 signoff 场景：新链路应为 fail，实际 findings={new_fail.findings()}"
    )
    assert _classify_report(old_fail) == _classify_report(new_fail), (
        "R003 无 signoff 场景：旧/新链路结论不一致"
    )


# ============================================================================
# TC-F11-5：notes.md Plan 6 自举验证 SOP 段落存在性断言
# ============================================================================

def test_plan6_sop_doc_present() -> None:
    """断言 requirements/REQ-2026-009/notes.md 中存在 Plan 6 自举验证 SOP 段落。

    TC-F11-5：保证 SOP 文档不被后续操作遗删。
    关键 marker：
    - "## Plan 6 自举验证 SOP"
    - "REQ-2026-005"（决策 A 记录）
    - 剩余阶段自举声明字样
    """
    notes_path = REPO_ROOT / "requirements" / "REQ-2026-009" / "notes.md"
    assert notes_path.exists(), f"notes.md 不存在：{notes_path}"

    content = notes_path.read_text(encoding="utf-8")

    assert "## Plan 6 自举验证 SOP" in content, (
        f"notes.md 中未找到 '## Plan 6 自举验证 SOP' 标题，"
        f"SOP 段落可能已被删除（path={notes_path}）"
    )
    assert "REQ-2026-005" in content, (
        f"notes.md 中未找到 'REQ-2026-005' 决策记录，"
        f"决策 A 可能已被删除（path={notes_path}）"
    )
    assert "剩余阶段" in content, (
        f"notes.md 中未找到'剩余阶段'自举声明字样，"
        f"AC-SELF 声明可能已被删除（path={notes_path}）"
    )
