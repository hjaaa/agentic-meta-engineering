"""features.json F-N.touches 与 tasks/F-N.md frontmatter touches 一致性测试。

防止 trend-G-meta 元信息债务（M-1 在 rev1/rev2/rev3 三轮反复未真闭合）：
  - features.json modules/touches 是 GATE-FEATURES-SCHEMA 机读输入
  - F-N.md frontmatter touches 是 dispatch_precheck.py / touches_guard.py 机读输入
  - 两者必须 set-equal，否则 governance metadata 漂移会让 reviewer 反复识别同一债务

来源：REQ-2026-009 D-017 ADR Consequences；F-012 rev3 trend-G-meta 三轮未终结教训。

注：当前版本为 governance gate 起步版，仅覆盖 REQ-2026-009 F-012（保守范围）。
未来推广由后续 feature 处理，避免把既有其他 REQ 的潜在不一致引入 CI 阻塞。
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


def test_should_match_when_features_json_touches_compared_with_frontmatter():
    """REQ-2026-009 F-012 的 features.json touches 与 tasks/F-012.md frontmatter touches 必须 set-equal。

    防止 trend-G-meta 元信息债务复发（M-1 三轮未真闭合历史教训）。
    gate 起步版：仅验证 REQ-2026-009 F-012，未来扩展时在 _GATE_SCOPE 字典追加即可。
    """
    mismatches = []

    for req_name, feature_ids in _GATE_SCOPE.items():
        req_dir = REQ_DIR / req_name
        features_path = req_dir / "artifacts" / "features.json"
        tasks_dir = req_dir / "artifacts" / "tasks"

        if not features_path.exists():
            mismatches.append({
                "req": req_name,
                "fid": "N/A",
                "error": f"features.json not found: {features_path}",
            })
            continue

        if not tasks_dir.is_dir():
            mismatches.append({
                "req": req_name,
                "fid": "N/A",
                "error": f"tasks dir not found: {tasks_dir}",
            })
            continue

        try:
            data = json.loads(features_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            mismatches.append({"req": req_name, "fid": "N/A", "error": str(exc)})
            continue

        for feature in data.get("features", []):
            fid = feature.get("id")
            if fid not in feature_ids:
                continue

            f_touches = set(feature.get("touches", []) or [])

            task_path = tasks_dir / f"{fid}.md"
            if not task_path.exists():
                mismatches.append({
                    "req": req_name,
                    "fid": fid,
                    "error": f"task file not found: {task_path}",
                })
                continue

            try:
                content = task_path.read_text(encoding="utf-8")
                parts = content.split("---")
                if len(parts) < 3:
                    mismatches.append({
                        "req": req_name,
                        "fid": fid,
                        "error": "task file missing YAML frontmatter",
                    })
                    continue
                fm = yaml.safe_load(parts[1]) or {}
                t_touches = set(fm.get("touches", []) or [])
            except (yaml.YAMLError, OSError) as exc:
                mismatches.append({"req": req_name, "fid": fid, "error": str(exc)})
                continue

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
