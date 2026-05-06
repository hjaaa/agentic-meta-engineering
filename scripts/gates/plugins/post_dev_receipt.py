"""GATE-POST-DEV-RECEIPT：开发实施阶段完成后 receipt.json 存在性与合规性校验（F-001）。

功能：
  - 扫描 features.json 中的 feature 列表，对每个 task md frontmatter.status==done 的 feature
    校验 tasks/<fid>.receipt.json 存在且合规（status ∈ {DONE, DONE_WITH_CONCERNS}）。
  - 触发时机：phase-transition（development→testing）/ submit。
  - 自然隔离：本 gate 不在 ci triggers 列表，历史 completed REQ 无 phase-transition 触发
    → 不命中（detailed-design.md §5.2 V-07 三重保证第 1 层）。

状态 source-of-truth（detailed-design.md §2.1.1）：
  tasks/<feature_id>.md frontmatter.status，不是 features.json。
  features.json 仅用于取 feature_id 列表。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

# noqa: E402 —— sys.path 注入后才能 import
import check_receipt  # noqa: E402

from .base import Decision, Gate, GateContext, Report, Severity, Skip

# receipt status 集合：视为"通过"的状态（detailed-design.md §5.3）
_PASS_STATUSES = frozenset({"DONE", "DONE_WITH_CONCERNS"})


class PostDevReceiptGate(Gate):
    """开发阶段 receipt.json 完整性校验 gate。"""

    id = "GATE-POST-DEV-RECEIPT"
    severity = Severity.ERROR
    triggers = {"phase-transition", "submit"}
    side_effects = "none"

    def precheck(self, ctx: GateContext) -> Optional[Skip]:
        """多层 precheck——快速过滤不命中场景（detailed-design.md §5.3）。

        过滤层次：
          1. trigger 防御性确认：非 phase-transition / submit → Skip
          2. req_dir 存在性：无法定位需求目录 → Skip
          3. features.json 存在性：早期需求未到 task-planning → Skip
          4. phase-transition 时必须是 development→testing → Skip
        """
        # 第 1 层：trigger 白名单防御性确认
        # （registry.yaml triggers 已静态过滤，此处是运行时双保险）
        if ctx.trigger not in ("phase-transition", "submit"):
            return Skip(f"trigger={ctx.trigger!r} 不命中（仅 phase-transition / submit）")

        # 第 2 层：定位需求目录
        req_dir = _resolve_req_dir(ctx)
        if req_dir is None:
            return Skip("无法定位 req_dir（requirement_id 缺失或需求目录不存在）")

        # 第 3 层：features.json 必须存在
        features_json = req_dir / "artifacts" / "features.json"
        if not features_json.exists():
            return Skip("features.json 不存在（需求可能未到 task-planning 阶段）")

        # 第 4 层：phase-transition 时仅 development→testing 触发
        if ctx.trigger == "phase-transition":
            target = ctx.extra.get("target_phase") or ctx.to_phase
            if target != "testing":
                return Skip(f"target_phase={target!r}，仅 development→testing 切换时命中")

        return None  # 通过所有 precheck，进入 run()

    def run(self, ctx: GateContext) -> Report:
        """主体校验逻辑。

        流程：
          1. 读 features.json 获取 feature_id 列表
          2. 对每个 feature_id，读 tasks/<fid>.md frontmatter.status
          3. status != "done" → 跳过该 feature
          4. status == "done" → 必须存在 tasks/<fid>.receipt.json
          5. receipt.json 存在 → 调 check_receipt 校验；
             receipt.status ∈ {DONE, DONE_WITH_CONCERNS} → pass，否则 fail

        失败消息含 fix_hint（详细设计 §5.1 failure_message 模板）。
        """
        req_dir = _resolve_req_dir(ctx)
        if req_dir is None:
            return Report(
                gate_id=self.id,
                decision=Decision.FAIL,
                code="R-NO-REQ-DIR",
                message="无法定位需求目录",
                fix_hint="确认 requirement_id 正确，需求目录 requirements/<id>/ 存在",
            )

        features_json = req_dir / "artifacts" / "features.json"
        feature_ids = _load_feature_ids(features_json)
        if feature_ids is None:
            return Report(
                gate_id=self.id,
                decision=Decision.FAIL,
                code="R-FEATURES-PARSE",
                message=f"features.json 解析失败：{features_json}",
                fix_hint="确认 features.json 存在且 JSON 格式合法",
            )

        tasks_dir = req_dir / "artifacts" / "tasks"
        failures: list[str] = []

        for fid in feature_ids:
            failure = _check_single_feature(fid, tasks_dir)
            if failure:
                failures.append(failure)

        if failures:
            message = f"共 {len(failures)} 个 feature receipt 校验失败：" + "；".join(failures[:3])
            if len(failures) > 3:
                message += f"（另有 {len(failures) - 3} 条省略）"
            return Report(
                gate_id=self.id,
                decision=Decision.FAIL,
                code="R-RECEIPT-MISSING-OR-INVALID",
                message=message,
                fix_hint=(
                    "每个 status=done 的 feature 必须有对应的 tasks/<fid>.receipt.json，"
                    "且 receipt.status ∈ {DONE, DONE_WITH_CONCERNS}。"
                    "请检查 subagent 是否已写入 receipt.json。"
                ),
            )

        return Report(gate_id=self.id, decision=Decision.PASS)


# ---------- 辅助函数 ----------

def _resolve_req_dir(ctx: GateContext) -> Optional[Path]:
    """从 ctx 定位需求根目录 requirements/<id>/。

    优先级：
      1. ctx.extra["req_dir"]（测试注入）
      2. ctx.requirement_id → requirements/<id>/
    """
    explicit = ctx.extra.get("req_dir")
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None

    if ctx.requirement_id:
        p = _REPO_ROOT / "requirements" / ctx.requirement_id
        return p if p.exists() else None

    return None


def _load_feature_ids(features_json: Path) -> Optional[list[str]]:
    """读 features.json，返回 feature_id 列表；失败返回 None。

    features.json 结构（来自 features-schema.yaml 设计）：
      {"features": [{"id": "F-001", ...}, ...]}
    或列表形式 [{"id": "F-001", ...}, ...]。
    """
    try:
        with features_json.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    # 兼容两种格式：顶层 dict.features 或 直接列表
    if isinstance(data, dict):
        features = data.get("features", [])
    elif isinstance(data, list):
        features = data
    else:
        return None

    ids = []
    for item in features:
        if isinstance(item, dict) and "id" in item:
            ids.append(item["id"])
    return ids


def _read_task_frontmatter_status(task_md: Path) -> Optional[str]:
    """读 task md frontmatter 中的 status 字段（source-of-truth）。

    frontmatter 格式（YAML between ---）：
      ---
      status: done
      ...
      ---

    返回 status 字符串（小写）；失败或不存在返回 None（fail-open 处理）。
    """
    if not task_md.exists():
        return None
    try:
        content = task_md.read_text(encoding="utf-8")
    except OSError:
        return None

    # 提取 frontmatter（第一对 ---...--- 之间的 YAML）
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return None

    end_idx = None
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = i
            break

    if end_idx is None:
        return None

    fm_text = "\n".join(lines[1:end_idx])
    try:
        fm = yaml.safe_load(fm_text)
    except yaml.YAMLError:
        return None

    if not isinstance(fm, dict):
        return None

    status = fm.get("status")
    return str(status).lower() if status is not None else None


def _check_single_feature(fid: str, tasks_dir: Path) -> Optional[str]:
    """对单个 feature 执行 done 检查 + receipt 校验。

    返回：None（通过 / 非 done feature 跳过）；错误描述字符串（失败）。
    """
    task_md = tasks_dir / f"{fid}.md"
    status = _read_task_frontmatter_status(task_md)

    # status != "done" → 跳过（包括 None / "pending" / "in-progress" 等）
    if status != "done":
        return None

    # status == "done" → 必须存在 receipt.json
    receipt_path = tasks_dir / f"{fid}.receipt.json"
    if not receipt_path.exists():
        return f"{fid}: status=done 但 receipt.json 不存在（{receipt_path}）"

    # receipt.json 存在 → 校验内容
    return _validate_receipt_file(fid, receipt_path)


def _validate_receipt_file(fid: str, receipt_path: Path) -> Optional[str]:
    """校验 receipt.json 内容：加载 schema 后走 check_receipt.validate 管道。

    返回：None（通过）；错误描述字符串（失败）。
    """
    try:
        schema = check_receipt._load_schema()
    except SystemExit:
        # _load_schema 内部 exit 2 → 这里捕获后转为 fail 描述
        return f"{fid}: receipt-schema.yaml 加载失败（schema 文件损坏）"

    try:
        with receipt_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        return f"{fid}: receipt.json 读取/解析失败：{exc}"

    report = check_receipt.validate(data, schema, str(receipt_path))
    if report.has_errors:
        # 取第一条错误用于 failure_message
        errors = report._errors
        first = errors[0] if errors else "未知错误"
        extra = f"（共 {len(errors)} 条）" if len(errors) > 1 else ""
        return f"{fid}: receipt.json 校验失败：{first}{extra}"

    # receipt 内容合规；再检查 status 语义
    receipt_status = data.get("status")
    if receipt_status not in _PASS_STATUSES:
        return (
            f"{fid}: receipt.status={receipt_status!r} 不在通过集合 {set(_PASS_STATUSES)}；"
            f"BLOCKED / NEEDS_CONTEXT 需先解决阻塞再切 testing"
        )

    return None  # 通过


# 模块级导出：runner 通过 module.GATE_CLASS 拿到子类
GATE_CLASS = PostDevReceiptGate
