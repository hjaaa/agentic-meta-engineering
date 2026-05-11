"""features.json F-N.touches 与 tasks/F-N.md frontmatter touches 一致性测试。

防止 trend-G-meta 元信息债务（M-1 在 rev1/rev2/rev3 三轮反复未真闭合）：
  - features.json modules/touches 是 GATE-FEATURES-SCHEMA 机读输入
  - F-N.md frontmatter touches 是 dispatch_precheck.py / touches_guard.py 机读输入
  - 两者必须 set-equal，否则 governance metadata 漂移会让 reviewer 反复识别同一债务

来源：REQ-2026-009 D-017 ADR Consequences；F-012 rev3 trend-G-meta 三轮未终结教训。

注：当前版本为 governance gate 起步版，仅覆盖 REQ-2026-009 F-012（保守范围）。
未来推广由后续 feature 处理，避免把既有其他 REQ 的潜在不一致引入 CI 阻塞。

F-012 rev6 Major 3：新增 self-coverage 红线——gate 文件本身必须 ∈ 某 feature touches。
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
REQ_DIR = REPO_ROOT / "requirements"

# 当前 gate 范围：仅检查 REQ-2026-009 F-012（保守起步）
_GATE_SCOPE = {
    "REQ-2026-009": {"F-012"},
}


def _load_feature_touches(features_path: Path, feature_ids: set) -> dict[str, set[str]]:
    """从 features.json 加载指定 feature_ids 的 touches；返回 {fid: touches_set}。"""
    try:
        data = json.loads(features_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    result: dict[str, set[str]] = {}
    for feature in data.get("features", []):
        fid = feature.get("id")
        if fid in feature_ids:
            result[fid] = set(feature.get("touches", []) or [])
    return result


def _load_frontmatter_touches(task_path: Path) -> set[str] | None:
    """从 task YAML frontmatter 加载 touches；解析失败返回 None。"""
    try:
        content = task_path.read_text(encoding="utf-8")
        parts = content.split("---")
        if len(parts) < 3:
            return None
        fm = yaml.safe_load(parts[1]) or {}
        return set(fm.get("touches", []) or [])
    except (yaml.YAMLError, OSError):
        return None


def test_should_match_when_features_json_touches_compared_with_frontmatter():
    """REQ-2026-009 F-012 的 features.json touches 与 tasks/F-012.md frontmatter touches 必须 set-equal。

    防止 trend-G-meta 元信息债务复发（M-1 三轮未真闭合历史教训）。
    gate 起步版：仅验证 REQ-2026-009 F-012，未来扩展时在 _GATE_SCOPE 字典追加即可。
    """
    # TODO(F-024 follow-up): 推广多 REQ × 多 feature 时用 pytest.mark.parametrize 拆独立 case。
    mismatches = []

    for req_name, feature_ids in _GATE_SCOPE.items():
        req_dir = REQ_DIR / req_name
        features_path = req_dir / "artifacts" / "features.json"
        tasks_dir = req_dir / "artifacts" / "tasks"

        if not features_path.exists():
            mismatches.append({"req": req_name, "fid": "N/A", "error": f"features.json not found: {features_path}"})
            continue
        if not tasks_dir.is_dir():
            mismatches.append({"req": req_name, "fid": "N/A", "error": f"tasks dir not found: {tasks_dir}"})
            continue

        f_touches_map = _load_feature_touches(features_path, feature_ids)
        if not f_touches_map:
            mismatches.append({"req": req_name, "fid": "N/A", "error": "features.json parse error or no matching features"})
            continue

        for fid in feature_ids:
            task_path = tasks_dir / f"{fid}.md"
            if not task_path.exists():
                mismatches.append({"req": req_name, "fid": fid, "error": f"task file not found: {task_path}"})
                continue
            t_touches = _load_frontmatter_touches(task_path)
            if t_touches is None:
                mismatches.append({"req": req_name, "fid": fid, "error": "task file YAML parse error or missing frontmatter"})
                continue
            f_touches = f_touches_map.get(fid, set())
            if f_touches != t_touches:
                mismatches.append({
                    "req": req_name,
                    "fid": fid,
                    "in_features_only": sorted(f_touches - t_touches),
                    "in_frontmatter_only": sorted(t_touches - f_touches),
                })

    assert not mismatches, (
        "features.json touches != frontmatter touches:\n"
        + "\n".join(str(m) for m in mismatches)
    )


def test_gate_file_must_be_in_some_feature_touches_within_scope():
    """gate 文件本身必须 ∈ _GATE_SCOPE 内某 feature 的 features.json touches AND frontmatter touches。

    F-012 rev6 Major 3 self-coverage 红线：防止 governance gate test 盲点（F-16）。
    如果 gate 文件不在任何 feature 的 touches 中，gate test 自身就是个未被追踪的修改，
    无法通过 touches_guard.py 检测到漂移，形成 self-blind-spot。
    """
    gate_file = "tests/lib/test_features_json_touches_consistency.py"
    found_in_features = False
    found_in_frontmatter = False

    for req_name, feature_ids in _GATE_SCOPE.items():
        req_dir = REQ_DIR / req_name
        features_path = req_dir / "artifacts" / "features.json"
        tasks_dir = req_dir / "artifacts" / "tasks"

        if not features_path.exists():
            continue

        f_touches_map = _load_feature_touches(features_path, feature_ids)
        for fid, f_touches in f_touches_map.items():
            if gate_file in f_touches:
                found_in_features = True
                task_path = tasks_dir / f"{fid}.md"
                t_touches = _load_frontmatter_touches(task_path)
                if t_touches is not None and gate_file in t_touches:
                    found_in_frontmatter = True

    assert found_in_features, (
        f"gate file {gate_file} is not declared in any scope feature's touches (features.json) "
        "— self-blind-spot detected"
    )
    assert found_in_frontmatter, (
        f"gate file {gate_file} is not declared in any scope feature's touches (frontmatter) "
        "— self-blind-spot detected"
    )
