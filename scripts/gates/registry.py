"""门禁 registry 加载与 schema 校验（S1~S10）。

设计来源：requirements/REQ-2026-002/artifacts/detailed-design.md §1。

职责：
  1. load_registry：加载 registry.yaml，跑 S1~S10 校验
  2. _validate_registry_schema / _validate_one_entry / _validate_write_state_plugin：
     具体校验子例程
  3. RegistryError：所有 schema 违反统一异常类型，runner 退出码 2

F-012 round-2 拆出：从 run.py 抽出，run.py 通过 re-export 保持向后兼容。
F-018 round-2：load_registry 加 validate_only_ids 参数，pre-tool-use 高频路径
冷启动优化（F-002：pre-tool-use 已删除，不再使用此参数；参数保留供历史参考）。
"""
from __future__ import annotations

import importlib
import re
import sys
from graphlib import CycleError, TopologicalSorter
from pathlib import Path
from typing import Any, Optional

import yaml

# 把 plugins 包加入 import 路径
_PKG_ROOT = Path(__file__).resolve().parent
if str(_PKG_ROOT) not in sys.path:
    sys.path.insert(0, str(_PKG_ROOT))

from plugins.base import TRIGGERS, Gate  # noqa: E402

REGISTRY_PATH = _PKG_ROOT / "registry.yaml"

ID_PATTERN = r"^GATE-[A-Z][A-Z0-9-]+$"
SEVERITY_VALUES = {"error", "warning", "info"}
SIDE_EFFECTS_VALUES = {"none", "write_state"}


class RegistryError(Exception):
    """registry.yaml 加载或 schema 校验失败。退出码 2。"""


def load_registry(
    path: Optional[Path] = None,
    validate_only_ids: Optional[set[str]] = None,
) -> dict[str, Any]:
    """加载 registry.yaml，跑 S1~S10 校验，返回 dict（含 gates / escape_hatches）。

    参数：
      path              — registry.yaml 路径；None 时回退到模块级 REGISTRY_PATH（保证测试期 monkeypatch 生效）。
      validate_only_ids — （F-002：pre-tool-use 已删除，此参数不再使用；保留供向后兼容）
                          仅对这些 gate id 跑 S2 import 校验（原用于冷启动优化）；
                          None 表示全量校验。S1/S5/S6/S7 仍跑全量，保证依赖图与 schema 完整性不被绕过。

    场景：
      - make gates-validate / ci 路径：validate_only_ids=None → 全量 plugin import + 拓扑
    """
    if path is None:
        path = REGISTRY_PATH
    if not path.exists():
        raise RegistryError(f"registry.yaml 不存在: {path}")
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        raise RegistryError(f"registry.yaml YAML 解析失败: {exc}") from exc

    if not isinstance(data, dict):
        raise RegistryError("registry.yaml 顶层必须是 mapping")
    gates = data.get("gates") or []
    if not isinstance(gates, list):
        raise RegistryError("registry.yaml gates 字段必须是 list")

    _validate_registry_schema(gates, validate_only_ids=validate_only_ids)
    return data


def _validate_registry_schema(
    gates: list[dict[str, Any]],
    validate_only_ids: Optional[set[str]] = None,
) -> None:
    """跑 S1~S10 schema 校验，违反即抛 RegistryError。

    validate_only_ids 非 None 时，S2 import + S7 rollback 检查跳过白名单外 gate；
    其他校验（S1/S3/S4/S5/S6/S8/S9/S10）仍跑全量，保证依赖图与字段完整性。

    F-014 round-3：把内部 4 段长循环拆为 _validate_s1_ids / _validate_s5_deps /
    _validate_s6_no_cycles / _validate_s7_rollback 子例程，CC 18 → 各 ≤ 4。
    """
    id_to_entry = _validate_s1_ids(gates, validate_only_ids)
    _validate_s5_deps(id_to_entry)
    _validate_s6_no_cycles(id_to_entry)
    _validate_s7_rollback(id_to_entry, validate_only_ids)


def _validate_s1_ids(
    gates: list[dict[str, Any]],
    validate_only_ids: Optional[set[str]],
) -> dict[str, dict[str, Any]]:
    """S1：每条 entry 的 id 必须符合 ID_PATTERN 且全局唯一；同时驱动 _validate_one_entry。

    返回：{gid: entry} 映射，供 S5/S6/S7 直接复用，避免重复扫描 gates 列表。
    """
    seen_ids: set[str] = set()
    id_to_entry: dict[str, dict[str, Any]] = {}
    for entry in gates:
        if not isinstance(entry, dict):
            raise RegistryError(f"gate entry 必须是 mapping，实际: {type(entry).__name__}")
        gid = entry.get("id")
        if not isinstance(gid, str) or not re.match(ID_PATTERN, gid):
            raise RegistryError(f"S1 违反：id={gid!r} 不符合 {ID_PATTERN}")
        if gid in seen_ids:
            raise RegistryError(f"S1 违反：id={gid!r} 重复")
        seen_ids.add(gid)
        id_to_entry[gid] = entry
        # F-018：S2 import 冷启动开销大，pre-tool-use 路径只 import 候选 gate
        skip_import = validate_only_ids is not None and gid not in validate_only_ids
        _validate_one_entry(entry, skip_import=skip_import)
    return id_to_entry


def _validate_s5_deps(id_to_entry: dict[str, dict[str, Any]]) -> None:
    """S5：dependencies 引用必须存在于 gates 列表（全量跑，避免悬挂依赖）。"""
    seen_ids = set(id_to_entry)
    for gid, entry in id_to_entry.items():
        for dep in entry.get("dependencies") or []:
            if dep not in seen_ids:
                raise RegistryError(f"S5 违反：{gid} 的依赖 {dep!r} 不存在于 gates")


def _validate_s6_no_cycles(id_to_entry: dict[str, dict[str, Any]]) -> None:
    """S6：dependencies 拓扑无环（全量跑，环检测需要完整图）。"""
    graph = {gid: set(entry.get("dependencies") or []) for gid, entry in id_to_entry.items()}
    sorter = TopologicalSorter(graph)
    try:
        sorter.prepare()
    except CycleError as exc:
        raise RegistryError(f"S6 违反：dependencies 拓扑出现环 {exc.args[1]}") from exc


def _validate_s7_rollback(
    id_to_entry: dict[str, dict[str, Any]],
    validate_only_ids: Optional[set[str]],
) -> None:
    """S7：side_effects=write_state 必须实现 rollback；遵循 validate_only_ids 白名单。"""
    for gid, entry in id_to_entry.items():
        if entry.get("side_effects") != "write_state":
            continue
        if validate_only_ids is not None and gid not in validate_only_ids:
            continue
        _validate_write_state_plugin(gid, entry["plugin"])


def _validate_one_entry(entry: dict[str, Any], skip_import: bool = False) -> None:
    """单 gate 条目的 S2/S3/S4/S8/S9/S10 校验。

    skip_import=True 时跳过 S2 的 importlib.import_module + GATE_CLASS 检查，
    仅做纯字符串字段校验（plugin 必填 + plugin_path 文件存在）。
    保留以支持按需加载优化；pre-tool-use 已于 F-002 退役。

    F-013 round-3：把 6 段独立 if 链拆为 _validate_s2_plugin / _validate_s3_triggers /
    _validate_s4_severity / _validate_s8_fixtures / _validate_s9_requires /
    _validate_s10_escape_hatch 六个私有函数，CC 28 → 各 ≤ 5；每条规则可独立测试。
    """
    gid = entry["id"]
    _validate_s2_plugin(gid, entry, skip_import)
    triggers = _validate_s3_triggers(gid, entry)
    _validate_s4_severity(gid, entry)
    _validate_s8_fixtures(gid, entry)
    _validate_s9_requires(gid, entry)
    _validate_s10_escape_hatch(gid, entry, triggers)


def _validate_s2_plugin(gid: str, entry: dict[str, Any], skip_import: bool) -> None:
    """S2：plugin 字段必填、plugin_path 文件存在；非 skip_import 还要 import + GATE_CLASS 校验。"""
    plugin_name = entry.get("plugin")
    if not isinstance(plugin_name, str) or not plugin_name:
        raise RegistryError(f"S2 违反：{gid} 的 plugin 字段必填且为字符串")
    plugin_path = _PKG_ROOT / "plugins" / f"{plugin_name}.py"
    if not plugin_path.exists():
        raise RegistryError(f"S2 违反：{gid} 的 plugins/{plugin_name}.py 不存在")
    if skip_import:
        return
    try:
        mod = importlib.import_module(f"plugins.{plugin_name}")
    except Exception as exc:  # noqa: BLE001
        raise RegistryError(f"S2 违反：plugins.{plugin_name} import 失败: {exc}") from exc
    cls = getattr(mod, "GATE_CLASS", None)
    if cls is None or not isinstance(cls, type) or not issubclass(cls, Gate):
        raise RegistryError(f"S2 违反：plugins/{plugin_name}.py 未导出 GATE_CLASS（Gate 子类）")


def _validate_s3_triggers(gid: str, entry: dict[str, Any]) -> list[str]:
    """S3：triggers 必须是非空 list，每个元素必须在 TRIGGERS 白名单内。返回 triggers 给 S10 复用。"""
    triggers = entry.get("triggers") or []
    if not isinstance(triggers, list) or not triggers:
        raise RegistryError(f"S3 违反：{gid} triggers 必须是非空 list")
    for t in triggers:
        if t not in TRIGGERS:
            raise RegistryError(f"S3 违反：{gid} 含未知 trigger={t!r}（白名单 {sorted(TRIGGERS)}）")
    return triggers


def _validate_s4_severity(gid: str, entry: dict[str, Any]) -> None:
    """S4：severity 枚举 + side_effects 枚举（同函数维护，因都是顶层枚举字段）。"""
    if entry.get("severity") not in SEVERITY_VALUES:
        raise RegistryError(f"S4 违反：{gid} severity 必须 ∈ {sorted(SEVERITY_VALUES)}")
    if entry.get("side_effects", "none") not in SIDE_EFFECTS_VALUES:
        raise RegistryError(f"{gid} side_effects 必须 ∈ {sorted(SIDE_EFFECTS_VALUES)}")


def _validate_s8_fixtures(gid: str, entry: dict[str, Any]) -> None:
    """S8：tests.fixtures 至少包含 pass / fail / skip 三个用例名。"""
    fixtures = ((entry.get("tests") or {}).get("fixtures")) or []
    if not {"pass", "fail", "skip"}.issubset(set(fixtures)):
        raise RegistryError(f"S8 违反：{gid} tests.fixtures 必须至少包含 [pass, fail, skip]")


def _validate_s9_requires(gid: str, entry: dict[str, Any]) -> None:
    """S9：applies_when.requires 每项必须是字符串且以 'meta.' 前缀。"""
    requires = ((entry.get("applies_when") or {}).get("requires")) or []
    for item in requires:
        if not isinstance(item, str) or not item.startswith("meta."):
            raise RegistryError(f"S9 违反：{gid} applies_when.requires 项 {item!r} 必须以 'meta.' 开头")


def _validate_s10_escape_hatch(gid: str, entry: dict[str, Any], triggers: list[str]) -> None:
    """S10：escape_hatch.cli_flag 仅 submit / phase-transition trigger 接受。"""
    eh = entry.get("escape_hatch") or {}
    cli_flag = eh.get("cli_flag")
    if cli_flag is None:
        return
    allowed = {"submit", "phase-transition"}
    if not (set(triggers) & allowed):
        raise RegistryError(
            f"S10 违反：{gid} escape_hatch.cli_flag={cli_flag!r} 仅 submit/phase-transition trigger 接受"
        )


def _validate_write_state_plugin(gid: str, plugin_name: str) -> None:
    """S7：side_effects=write_state 的 plugin 必须重写 rollback。"""
    mod = importlib.import_module(f"plugins.{plugin_name}")
    cls = mod.GATE_CLASS
    if cls.rollback is Gate.rollback:
        raise RegistryError(
            f"S7 违反：{gid} side_effects=write_state 但 plugins/{plugin_name}.py 未实现 rollback()"
        )
