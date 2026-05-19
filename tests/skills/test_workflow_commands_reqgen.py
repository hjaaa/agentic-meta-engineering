"""F-001/F-003 · workflow run ID/REQ ID 生成 + schema 门禁单测。

覆盖范围：
  TC-F1-1  [DEPRECATED · REQ-2026-014 D-013] generate_req_id 空 requirements/ 返回 REQ-YYYY-001
  TC-F1-2  [DEPRECATED · REQ-2026-014 D-013] generate_req_id_concurrency_safe 并发 3 路 ID 唯一
  TC-F1-3  [DEPRECATED · REQ-2026-014 D-013] generate_req_id_max_plus_one max+1 编号
  TC-F3-1  load_workflow_schema_gate：非法 yaml exit 1，合法模板正常路由

REQ-2026-014 F-003 D-013 迁移：requirement key 格式从 REQ-YYYY-NNN 改为 YYYYMMDD-<slug>。
TC-F1-1 / TC-F1-2 / TC-F1-3 的 REQ-YYYY-NNN 断言已失效；新格式覆盖在
tests/lib/test_requirement_naming.py（24 用例）。本文件保留作历史档存，
3 个旧用例标 @pytest.mark.skip（contract 已迁移，非测试 bug），不删除以保留 git blame 追溯。

外部依赖全部 mock（git / TaskStop / isatty）。
pytest 命名规范：test_<场景>_<期望>（CLAUDE.md §7）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# ---------- 路径注入 ----------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
_SKILLS_TEST_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))
if str(_SKILLS_TEST_DIR) not in sys.path:
    sys.path.insert(0, str(_SKILLS_TEST_DIR))

# ---------- 被测模块 ----------

import workflow_run  # noqa: E402


# ---------- 公共 fixture ----------


@pytest.fixture()
def tmp_repo(tmp_path: Path) -> Path:
    """创建临时仓库根目录（含基础目录结构）。"""
    (tmp_path / "runs").mkdir()
    (tmp_path / "requirements").mkdir()
    (tmp_path / ".claude" / "workflows").mkdir(parents=True)
    return tmp_path


@pytest.fixture()
def sample_template(tmp_repo: Path) -> str:
    """在临时仓库中创建 minimal workflow yaml 模板（F-003 后含 schema 必填字段）。"""
    template_name = "test-template"
    template_content = """\
name: test-template
version: 1
category: assist
description: 测试模板（F-005 单测用）
nodes:
  - id: node-a
    prompt: "hello"
  - id: node-b
    prompt: "world"
    depends_on: [node-a]
"""
    (tmp_repo / ".claude" / "workflows" / f"{template_name}.yaml").write_text(template_content, encoding="utf-8")
    return template_name


# ============================================================
# F-001：_generate_req_id 单测
# ============================================================

@pytest.mark.skip(reason="REQ-2026-014 F-003 D-013 contract 迁移：REQ-YYYY-NNN → YYYYMMDD-<slug>；新覆盖见 tests/lib/test_requirement_naming.py")
class TestGenerateReqId:
    """_generate_req_id 空 requirements/ 时返回 REQ-{当年}-001。"""

    def test_empty_requirements_returns_first_id(self, tmp_repo: Path):
        """given_empty_requirements_when_generate_req_id_then_returns_REQ_YYYY_001。

        tmp_repo/requirements/ 已在 fixture 建好（空目录），
        断言返回 REQ-{当年}-001 且目录已创建。
        """
        import workflow_run as wr
        from datetime import datetime, timezone

        req_id = wr._generate_req_id(tmp_repo)

        year = datetime.now(timezone.utc).strftime("%Y")
        expected = f"REQ-{year}-001"
        assert req_id == expected, (
            f"空 requirements/ 首次调用期望 {expected}，实际：{req_id}"
        )
        assert (tmp_repo / "requirements" / req_id).is_dir(), (
            f"{req_id} 对应顶层目录未创建"
        )


@pytest.mark.skip(reason="REQ-2026-014 F-003 D-013 contract 迁移：REQ-YYYY-NNN → YYYYMMDD-<slug>；新覆盖见 tests/lib/test_requirement_naming.py")
class TestGenerateReqIdConcurrencySafe:
    """_generate_req_id 并发 3 路调用，3 个 REQ-ID 唯一（原子化验证）。"""

    def test_concurrent_req_id_no_collision(self, tmp_repo: Path):
        """given_three_concurrent_calls_when_generate_req_id_then_req_ids_are_unique ✓。

        使用 threading 三发 _generate_req_id，断言 3 个 req_id 互不重叠，
        且每个对应目录均已创建。复刻 TC-F5-G8 并发安全验证模式。
        用 threading 近似进程模型：mkdir(exist_ok=False) 的原子性在跨进程同样适用，
        无需 multiprocessing 提升测试复杂度。
        """
        import threading
        import workflow_run as wr

        results: list[str] = []
        errors: list[Exception] = []
        # Barrier 同步三线程起跑线，强化真并发竞争密度
        barrier = threading.Barrier(3)

        def worker() -> None:
            barrier.wait()  # 等所有线程就位后同步起跑，最大化竞争密度
            try:
                req_id = wr._generate_req_id(tmp_repo)
                results.append(req_id)
            except Exception as exc:
                errors.append(exc)

        # 同时启动三个线程竞争创建 req_id
        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 断言：无异常 + 3 个 req_id 均不重复
        assert not errors, f"_generate_req_id 抛出异常：{errors}"
        assert len(results) == 3, f"期望 3 个 req_id，实际：{results}"
        assert len(set(results)) == 3, (
            f"并发生成的 req_id 存在重复：{results}"
        )
        # 确认 3 个目录都已实际创建
        for rid in results:
            assert (tmp_repo / "requirements" / rid).is_dir(), (
                f"req_id {rid!r} 对应顶层目录未创建"
            )


# TC-F1-3: max+1 策略一致（features.json F-001 acceptance[2]）
@pytest.mark.skip(reason="REQ-2026-014 F-003 D-013 contract 迁移：REQ-YYYY-NNN → YYYYMMDD-<slug>；新覆盖见 tests/lib/test_requirement_naming.py")
class TestGenerateReqIdMaxPlusOne:
    """_generate_req_id 存在多个现有目录时，返回 max+1 编号。"""

    def test_picks_max_plus_one_when_existing_dirs(self, tmp_repo: Path):
        """given_existing_dirs_003_and_007_when_generate_req_id_then_returns_008。

        预建 REQ-{当年}-003 和 REQ-{当年}-007，
        调用 _generate_req_id 后期望返回 REQ-{当年}-008，
        验证 max+1 策略与 _generate_run_id 保持一致。
        """
        import workflow_run as wr
        from datetime import datetime, timezone

        year = datetime.now(timezone.utc).strftime("%Y")
        req_dir = tmp_repo / "requirements"

        # 预建两个目录，非连续编号以验证取 max 而非 count
        (req_dir / f"REQ-{year}-003").mkdir()
        (req_dir / f"REQ-{year}-007").mkdir()

        req_id = wr._generate_req_id(tmp_repo)

        expected = f"REQ-{year}-008"
        assert req_id == expected, (
            f"存在 -003、-007 时 max+1 期望 {expected}，实际：{req_id}"
        )
        assert (req_dir / req_id).is_dir(), (
            f"{req_id} 对应顶层目录未创建"
        )


# ============================================================
# F-003：load_workflow schema 校验门禁单测
# ============================================================

class TestLoadWorkflowSchemaGate:
    """TC-F3-1：main() schema 校验门禁——非法 yaml exit 1，合法模板正常路由。"""

    # ------------------------------------------------------------------
    # 辅助：在 tmp_repo 写入一个 workflow yaml，返回 template_id
    # ------------------------------------------------------------------

    def _write_template(self, tmp_repo: Path, template_id: str, content: str) -> str:
        """将 yaml 内容写入 tmp_repo/.claude/workflows/<template_id>.yaml。"""
        template_dir = tmp_repo / ".claude" / "workflows" / "test-gate"
        template_dir.mkdir(parents=True, exist_ok=True)
        (template_dir / f"{template_id}.yaml").write_text(content, encoding="utf-8")
        return template_id

    # ------------------------------------------------------------------
    # AC-1：非法 yaml（缺 name / category / nodes）→ exit 1 + stderr 报告
    # ------------------------------------------------------------------

    def test_main_exits_1_on_invalid_schema(self, tmp_repo: Path, capsys):
        """given_invalid_yaml_missing_required_fields_when_run_then_exit_1_with_schema_report ✗。

        构造一个缺少 `category` 和 `nodes` 的最小 yaml，
        验证 main() 返回 1，且 stderr 中包含校验报告（W1xx 错误码或 render 关键字）。
        """
        # 故意缺 category / nodes / version
        bad_content = "name: bad-template\n"
        template_id = self._write_template(tmp_repo, "bad-template", bad_content)

        rc = workflow_run.main([template_id], repo_root=tmp_repo)

        assert rc == 1, f"非法 yaml 应返回 1，实际 rc={rc}"
        captured = capsys.readouterr()
        # render() 至少含 "ERROR" 或 "W1" 字样（load_workflow 报告内容）
        assert captured.err.strip(), (
            "非法 yaml 时 stderr 应含校验报告，实际 stderr 为空"
        )
        # 检查报告中包含错误信息（W 开头错误码 或 "error" / "ERROR" 字样）
        stderr_lower = captured.err.lower()
        assert any(kw in stderr_lower for kw in ("error", "w1", "w0", "缺少")), (
            f"stderr 应含 W1xx 错误码或错误关键字，实际：{captured.err!r}"
        )

    # ------------------------------------------------------------------
    # AC-2：合法最小 yaml 通过门禁 → 进入 _run_requirement / _run_generic
    # ------------------------------------------------------------------

    def test_main_passes_through_valid_template(self, tmp_repo: Path, monkeypatch):
        """given_valid_schema_yaml_when_run_then_not_blocked_by_schema_gate ✓。

        构造最小合法 yaml（category=assist），monkeypatch _run_generic 立即 return 0，
        验证 schema 门禁不误判合法模板（即 main() 能穿透到 _run_generic 而非在校验处 return 1）。
        """
        valid_content = """\
name: valid-minimal
version: 1
category: assist
nodes:
  - id: step-1
    prompt: "do something"
"""
        template_id = self._write_template(tmp_repo, "valid-minimal", valid_content)

        # monkeypatch 截断 _run_generic，避免触发完整 run 流程
        monkeypatch.setattr(workflow_run, "_run_generic", lambda *a, **kw: 0)

        rc = workflow_run.main([template_id], repo_root=tmp_repo)

        assert rc == 0, (
            f"合法 yaml 不应被 schema 门禁拦截，期望 rc=0，实际 rc={rc}"
        )

    def test_main_passes_through_valid_requirement_template(self, tmp_repo: Path, monkeypatch):
        """given_valid_requirement_yaml_when_run_then_routes_to_run_requirement ✓。

        构造最小合法 category=requirement yaml，monkeypatch _run_requirement 立即 return 0，
        验证 schema 通过后走 requirement 分支（workflow.get("category") == "requirement"）。
        """
        req_content = """\
name: req-minimal
version: 1
category: requirement
nodes:
  - id: step-1
    prompt: "bootstrap requirement"
"""
        template_id = self._write_template(tmp_repo, "req-minimal", req_content)

        # monkeypatch 截断 _run_requirement，避免触发 bootstrap 副作用
        monkeypatch.setattr(workflow_run, "_run_requirement", lambda *a, **kw: 0)

        rc = workflow_run.main([template_id], repo_root=tmp_repo)

        assert rc == 0, (
            f"合法 requirement yaml 应通过门禁并路由到 _run_requirement，期望 rc=0，实际 rc={rc}"
        )
