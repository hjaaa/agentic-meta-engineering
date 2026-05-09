"""F-003 · TC-F3-2：8 阶段 prompt 文件 frontmatter 完整性校验。

覆盖：
- 8 个 standard-8phase prompt 文件必须存在
- 每个文件的 YAML frontmatter 必须含三必填字段：name / node_id / version
- name 格式：kebab-case，与文件名（去 .md 后缀）一致
- node_id 格式：kebab-case，与 yaml 中对应引用节点的 id 一致
- version 格式：semver（major.minor.patch）
- 对于 yaml 中实际有 prompt_file 引用的节点，node_id 必须与 yaml 节点 id 匹配

测试运行：
    python3 -m pytest tests/workflows/test_prompt_structure.py -v
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

from workflow_loader import load_workflow  # noqa: E402

PROMPTS_DIR = REPO_ROOT / ".claude" / "workflows" / "prompts" / "standard-8phase"
YAML_PATH = REPO_ROOT / ".claude" / "workflows" / "requirement" / "standard-8phase.yaml"

# 期望的 8 个 prompt 文件名（与 features.json modules 严格一致）
EXPECTED_PROMPT_FILES = [
    "initialization.md",
    "definition.md",
    "tech-research.md",
    "outline-design.md",
    "detail-design.md",
    "task-planning.md",
    "development.md",
    "testing.md",
]

# semver 正则（major.minor.patch，允许 major 为 0）
SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")

# kebab-case 正则（小写字母/数字/连字符，不以连字符开头/结尾）
KEBAB_RE = re.compile(r"^[a-z][a-z0-9-]*[a-z0-9]$|^[a-z]$")


# ============================================================================
# 固定装置
# ============================================================================


def _parse_frontmatter(md_path: Path) -> dict[str, Any]:
    """解析 Markdown 文件头部的 YAML frontmatter（--- 包围区块）。

    返回解析后的字典；如果无 frontmatter 或解析失败，返回空字典。
    """
    text = md_path.read_text(encoding="utf-8")
    # frontmatter 必须从第一行 --- 开始
    if not text.startswith("---"):
        return {}
    # 找结束的 ---
    end_marker = text.find("\n---", 3)
    if end_marker == -1:
        return {}
    fm_text = text[3:end_marker].strip()
    try:
        parsed = yaml.safe_load(fm_text)
        return parsed if isinstance(parsed, dict) else {}
    except yaml.YAMLError as e:
        import sys
        print(f"WARN: frontmatter parse failed in {md_path}: {e}", file=sys.stderr)
        return {}


@pytest.fixture(scope="module")
def workflow_nodes_by_id() -> dict[str, dict[str, Any]]:
    """加载 standard-8phase.yaml，返回 {node_id: node} 映射。"""
    result = load_workflow(YAML_PATH)
    assert result.report.errors == 0, result.report.render()
    assert result.workflow is not None
    return {n["id"]: n for n in result.workflow["nodes"]}


@pytest.fixture(scope="module")
def prompt_file_refs(workflow_nodes_by_id: dict[str, dict[str, Any]]) -> dict[str, str]:
    """收集 yaml 中所有 prompt_file 引用：{节点 id: prompt_file 路径}。

    包含节点级 prompt_file 和 loop.prompt_file 引用。
    """
    refs: dict[str, str] = {}
    for node_id, node in workflow_nodes_by_id.items():
        if "prompt_file" in node:
            refs[node_id] = node["prompt_file"]
        loop = node.get("loop")
        if isinstance(loop, dict) and "prompt_file" in loop:
            refs[node_id] = loop["prompt_file"]
    return refs


# ============================================================================
# TC-F3-2：8 个 prompt 文件 frontmatter 校验
# ============================================================================


class TestPromptFilesExist:
    """所有期望的 prompt 文件必须存在。"""

    def test_prompts_dir_exists(self) -> None:
        """standard-8phase prompts 目录必须存在。"""
        assert PROMPTS_DIR.exists(), f"prompts 目录不存在: {PROMPTS_DIR}"
        assert PROMPTS_DIR.is_dir(), f"不是目录: {PROMPTS_DIR}"

    @pytest.mark.parametrize("filename", EXPECTED_PROMPT_FILES)
    def test_prompt_file_exists(self, filename: str) -> None:
        """每个期望的 prompt 文件必须存在。"""
        fpath = PROMPTS_DIR / filename
        assert fpath.exists(), f"prompt 文件不存在: {fpath}"
        assert fpath.is_file(), f"不是文件: {fpath}"


class TestPromptFrontmatterRequired:
    """每个 prompt 文件必须含合法的 name / node_id / version 三必填字段。"""

    @pytest.mark.parametrize("filename", EXPECTED_PROMPT_FILES)
    def test_frontmatter_parseable(self, filename: str) -> None:
        """frontmatter 必须能被成功解析。"""
        fpath = PROMPTS_DIR / filename
        fm = _parse_frontmatter(fpath)
        assert fm, (
            f"{filename} 缺少合法的 YAML frontmatter（--- 包围区块）"
        )

    @pytest.mark.parametrize("filename", EXPECTED_PROMPT_FILES)
    def test_frontmatter_has_name(self, filename: str) -> None:
        """frontmatter 必须含 name 字段。"""
        fm = _parse_frontmatter(PROMPTS_DIR / filename)
        assert "name" in fm, f"{filename} frontmatter 缺少必填字段 name"
        assert isinstance(fm["name"], str), f"{filename} frontmatter.name 必须是字符串"
        assert fm["name"], f"{filename} frontmatter.name 不能为空"

    @pytest.mark.parametrize("filename", EXPECTED_PROMPT_FILES)
    def test_frontmatter_has_node_id(self, filename: str) -> None:
        """frontmatter 必须含 node_id 字段。"""
        fm = _parse_frontmatter(PROMPTS_DIR / filename)
        assert "node_id" in fm, f"{filename} frontmatter 缺少必填字段 node_id"
        assert isinstance(fm["node_id"], str), f"{filename} frontmatter.node_id 必须是字符串"
        assert fm["node_id"], f"{filename} frontmatter.node_id 不能为空"

    @pytest.mark.parametrize("filename", EXPECTED_PROMPT_FILES)
    def test_frontmatter_has_version(self, filename: str) -> None:
        """frontmatter 必须含 version 字段。"""
        fm = _parse_frontmatter(PROMPTS_DIR / filename)
        assert "version" in fm, f"{filename} frontmatter 缺少必填字段 version"

    @pytest.mark.parametrize("filename", EXPECTED_PROMPT_FILES)
    def test_frontmatter_name_is_kebab_case(self, filename: str) -> None:
        """frontmatter.name 必须是 kebab-case 格式。"""
        fm = _parse_frontmatter(PROMPTS_DIR / filename)
        name = fm.get("name", "")
        assert KEBAB_RE.match(str(name)), (
            f"{filename} frontmatter.name={name!r} 必须是 kebab-case 格式"
        )

    @pytest.mark.parametrize("filename", EXPECTED_PROMPT_FILES)
    def test_frontmatter_name_matches_filename(self, filename: str) -> None:
        """frontmatter.name 建议与文件名（去后缀）一致。"""
        fm = _parse_frontmatter(PROMPTS_DIR / filename)
        name = str(fm.get("name", ""))
        stem = filename.removesuffix(".md")
        assert name == stem, (
            f"{filename} frontmatter.name={name!r} 应与文件名 {stem!r} 一致"
        )

    @pytest.mark.parametrize("filename", EXPECTED_PROMPT_FILES)
    def test_frontmatter_node_id_is_kebab_case(self, filename: str) -> None:
        """frontmatter.node_id 必须是 kebab-case 格式。"""
        fm = _parse_frontmatter(PROMPTS_DIR / filename)
        node_id = fm.get("node_id", "")
        assert KEBAB_RE.match(str(node_id)), (
            f"{filename} frontmatter.node_id={node_id!r} 必须是 kebab-case 格式"
        )

    @pytest.mark.parametrize("filename", EXPECTED_PROMPT_FILES)
    def test_frontmatter_version_is_semver(self, filename: str) -> None:
        """frontmatter.version 必须是 semver 格式（major.minor.patch）。"""
        fm = _parse_frontmatter(PROMPTS_DIR / filename)
        version = str(fm.get("version", ""))
        assert SEMVER_RE.match(version), (
            f"{filename} frontmatter.version={version!r} 必须是 semver 格式（如 1.0.0）"
        )


class TestPromptNodeIdConsistency:
    """对于 yaml 中实际有 prompt_file 引用的节点，node_id 必须与 yaml 节点 id 一致。"""

    def test_outline_design_node_id_matches(
        self, workflow_nodes_by_id: dict[str, dict[str, Any]]
    ) -> None:
        """outline-design.md 的 node_id 必须与 yaml outline-design-draft 节点 id 一致。"""
        fm = _parse_frontmatter(PROMPTS_DIR / "outline-design.md")
        node_id = fm.get("node_id")
        assert node_id in workflow_nodes_by_id, (
            f"outline-design.md frontmatter.node_id={node_id!r} 在 yaml 中不存在"
        )
        # yaml 中该节点必须有 prompt_file 引用此文件
        node = workflow_nodes_by_id[node_id]
        pf = node.get("prompt_file", "")
        assert "outline-design" in pf, (
            f"yaml 节点 {node_id} 的 prompt_file={pf!r} 未引用 outline-design.md"
        )

    def test_detail_design_node_id_matches(
        self, workflow_nodes_by_id: dict[str, dict[str, Any]]
    ) -> None:
        """detail-design.md 的 node_id 必须与 yaml detail-design-draft 节点 id 一致。"""
        fm = _parse_frontmatter(PROMPTS_DIR / "detail-design.md")
        node_id = fm.get("node_id")
        assert node_id in workflow_nodes_by_id, (
            f"detail-design.md frontmatter.node_id={node_id!r} 在 yaml 中不存在"
        )
        node = workflow_nodes_by_id[node_id]
        pf = node.get("prompt_file", "")
        assert "detail-design" in pf, (
            f"yaml 节点 {node_id} 的 prompt_file={pf!r} 未引用 detail-design.md"
        )

    def test_development_node_id_matches(
        self, workflow_nodes_by_id: dict[str, dict[str, Any]]
    ) -> None:
        """development.md 的 node_id 必须与 yaml dev-feature-loop 节点 id 一致。"""
        fm = _parse_frontmatter(PROMPTS_DIR / "development.md")
        node_id = fm.get("node_id")
        assert node_id in workflow_nodes_by_id, (
            f"development.md frontmatter.node_id={node_id!r} 在 yaml 中不存在"
        )
        node = workflow_nodes_by_id[node_id]
        # development 是 loop 节点，prompt_file 在 loop 子字段
        loop = node.get("loop", {})
        pf = loop.get("prompt_file", "") if isinstance(loop, dict) else ""
        assert "development" in pf, (
            f"yaml 节点 {node_id} 的 loop.prompt_file={pf!r} 未引用 development.md"
        )

    def test_placeholder_node_ids_exist_in_yaml(
        self, workflow_nodes_by_id: dict[str, dict[str, Any]]
    ) -> None:
        """占位 prompt 文件的 node_id 也必须在 yaml 中存在（以保证引用有效）。"""
        placeholder_files = [
            "initialization.md",
            "definition.md",
            "tech-research.md",
            "task-planning.md",
            "testing.md",
        ]
        for filename in placeholder_files:
            fm = _parse_frontmatter(PROMPTS_DIR / filename)
            node_id = fm.get("node_id")
            assert node_id in workflow_nodes_by_id, (
                f"{filename} frontmatter.node_id={node_id!r} 在 yaml 中不存在"
            )


def test_8phase_prompt_frontmatter(
    workflow_nodes_by_id: dict[str, dict[str, Any]],
) -> None:
    """TC-F3-2 主入口：加载 yaml + 解析每个 prompt_file frontmatter，
    断言 name/node_id/version 三必填齐 + node_id 与 yaml 节点 id 一致（适用于有 prompt_file 引用的节点）。
    """
    # 验证所有 8 个文件都存在并含三必填字段
    for filename in EXPECTED_PROMPT_FILES:
        fpath = PROMPTS_DIR / filename
        assert fpath.exists(), f"prompt 文件不存在: {fpath}"
        fm = _parse_frontmatter(fpath)
        assert fm, f"{filename} 缺少合法 frontmatter"
        for required in ("name", "node_id", "version"):
            assert required in fm, f"{filename} frontmatter 缺少 {required}"
        # version 格式
        assert SEMVER_RE.match(str(fm["version"])), (
            f"{filename} frontmatter.version={fm['version']!r} 不是 semver"
        )
        # node_id 必须在 yaml 中存在
        node_id = fm.get("node_id")
        assert node_id in workflow_nodes_by_id, (
            f"{filename} frontmatter.node_id={node_id!r} 在 yaml 中不存在"
        )


# ============================================================================
# TC-F4-4（F-004 新增）：11 个 code-review-embedded prompt frontmatter 校验
# ============================================================================

# code-review-embedded prompt 目录
_CR_EMBEDDED_PROMPTS_DIR = REPO_ROOT / ".claude" / "workflows" / "prompts" / "code-review-embedded"
_CR_EMBEDDED_YAML_PATH = REPO_ROOT / ".claude" / "workflows" / "review" / "code-review-embedded.yaml"

# 11 个 prompt 文件清单（对应 detailed-design §2.1）
_CR_EMBEDDED_PROMPT_FILES = [
    "cr-prepare.md",
    "cr-checker-security.md",
    "cr-checker-performance.md",
    "cr-checker-complexity.md",
    "cr-checker-concurrency.md",
    "cr-checker-error-handling.md",
    "cr-checker-design-consistency.md",
    "cr-checker-auxiliary-spec.md",
    "cr-checker-history-context.md",
    "cr-critic.md",
    "cr-judge.md",
]

# 属于 fresh context 的文件（8 checker + cr-critic + cr-judge）
_CR_FRESH_CONTEXT_FILES = {
    "cr-checker-security.md",
    "cr-checker-performance.md",
    "cr-checker-complexity.md",
    "cr-checker-concurrency.md",
    "cr-checker-error-handling.md",
    "cr-checker-design-consistency.md",
    "cr-checker-auxiliary-spec.md",
    "cr-checker-history-context.md",
    "cr-critic.md",
    "cr-judge.md",
}

# cr-prepare 是 shared 上下文
_CR_SHARED_CONTEXT_FILES = {"cr-prepare.md"}

# fresh context（checker/critic/judge）严格白名单：只允许 Read / Grep
_FRESH_CONTEXT_ALLOWED_TOOLS_WHITELIST = {"Read", "Grep"}
# shared context（cr-prepare）允许的工具集合（需要 git + 写盘）
_SHARED_CONTEXT_ALLOWED_TOOLS = {"Read", "Grep", "Bash", "Write"}


def _check_existence(filename: str, violations: list[str]) -> bool:
    """子检查 1：prompt 文件存在且 frontmatter 可解析。返回 False 则跳过后续检查。"""
    fpath = _CR_EMBEDDED_PROMPTS_DIR / filename
    if not fpath.exists():
        violations.append(f"{filename}: 文件不存在")
        return False
    fm = _parse_frontmatter(fpath)
    if not fm:
        violations.append(f"{filename}: frontmatter 解析失败或为空")
        return False
    return True


def _check_required_fields(filename: str, fm: dict[str, Any], violations: list[str]) -> None:
    """子检查 2：三必填字段 name / node_id / version + semver 格式。"""
    for required_field in ("name", "node_id", "version"):
        if required_field not in fm:
            violations.append(f"{filename}: frontmatter 缺少必填字段 {required_field}")
    version = str(fm.get("version", ""))
    if version and not SEMVER_RE.match(version):
        violations.append(f"{filename}: frontmatter.version={version!r} 不是 semver")


def _check_context(filename: str, fm: dict[str, Any], violations: list[str]) -> None:
    """子检查 3：context 值合法且与预期一致（fresh / shared）。"""
    context = fm.get("context")
    if context is not None and context not in ("fresh", "shared"):
        violations.append(
            f"{filename}: frontmatter.context={context!r} 必须 ∈ {{fresh, shared}}"
        )
    if filename in _CR_FRESH_CONTEXT_FILES and context is not None and context != "fresh":
        violations.append(f"{filename}: 期望 context=fresh，实际 {context!r}")
    if filename in _CR_SHARED_CONTEXT_FILES and context is not None and context != "shared":
        violations.append(f"{filename}: 期望 context=shared，实际 {context!r}")


def _check_allowed_tools(filename: str, fm: dict[str, Any], violations: list[str]) -> None:
    """子检查 4：allowed_tools 白名单校验。

    - fresh context（8 checker + cr-critic + cr-judge）：严格白名单 {Read, Grep}
    - shared context（cr-prepare）：宽松白名单 {Read, Grep, Bash, Write}
    """
    allowed_tools = fm.get("allowed_tools")
    if allowed_tools is None:
        return
    if not isinstance(allowed_tools, list):
        violations.append(f"{filename}: frontmatter.allowed_tools 格式错误（应为 list）")
        return

    tools_set = {str(t) for t in allowed_tools}
    if filename in _CR_FRESH_CONTEXT_FILES:
        # fresh context：严格排他白名单，只允许 Read / Grep
        extra = tools_set - _FRESH_CONTEXT_ALLOWED_TOOLS_WHITELIST
        if extra:
            violations.append(
                f"{filename}: fresh context allowed_tools 超出白名单 {{Read,Grep}}，多余: {extra}"
            )
    elif filename in _CR_SHARED_CONTEXT_FILES:
        # shared context（cr-prepare）：宽松检查，不能超出 Bash/Write/Read/Grep
        extra = tools_set - _SHARED_CONTEXT_ALLOWED_TOOLS
        if extra:
            violations.append(
                f"{filename}: shared context allowed_tools 含未知工具 {extra}"
            )


def _check_node_id_in_yaml(
    filename: str, fm: dict[str, Any], cr_nodes_by_id: dict[str, Any], violations: list[str]
) -> None:
    """子检查 5：node_id 必须在 yaml 节点中存在（仅当 yaml 已加载时校验）。"""
    if not cr_nodes_by_id:
        return
    node_id = fm.get("node_id")
    if node_id and node_id not in cr_nodes_by_id:
        violations.append(
            f"{filename}: frontmatter.node_id={node_id!r} 在 yaml 中不存在"
        )


def test_review_prompts_frontmatter() -> None:
    """TC-F4-4：11 个 code-review-embedded prompt 文件 frontmatter 完整性校验。

    校验项：
    1. 所有 11 个文件存在
    2. 每个文件 frontmatter 含 name / node_id / version 三必填
    3. context ∈ {fresh, shared}（fresh=10 个 checker/critic/judge，shared=cr-prepare）
    4. fresh context 文件 allowed_tools 严格 ⊆ {Read, Grep}；
       shared context（cr-prepare）allowed_tools ⊆ {Read, Grep, Bash, Write}
    5. node_id 在 code-review-embedded.yaml 节点中存在
    """
    # 加载 yaml，取节点 id 集合用于校验 node_id
    cr_nodes_by_id: dict[str, dict[str, Any]] = {}
    if _CR_EMBEDDED_YAML_PATH.exists():
        result = load_workflow(_CR_EMBEDDED_YAML_PATH)
        if result.workflow is not None:
            cr_nodes_by_id = {n["id"]: n for n in result.workflow["nodes"]}

    violations: list[str] = []

    for filename in _CR_EMBEDDED_PROMPT_FILES:
        if not _check_existence(filename, violations):
            continue
        fm = _parse_frontmatter(_CR_EMBEDDED_PROMPTS_DIR / filename)
        _check_required_fields(filename, fm, violations)
        _check_context(filename, fm, violations)
        _check_allowed_tools(filename, fm, violations)
        _check_node_id_in_yaml(filename, fm, cr_nodes_by_id, violations)

    assert not violations, (
        f"TC-F4-4 frontmatter 校验发现 {len(violations)} 个问题:\n"
        + "\n".join(f"  - {v}" for v in violations)
    )
