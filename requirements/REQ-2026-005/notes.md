# REQ-2026-005 Notes

## 背景

本需求覆盖经对抗式 review-critic 验证后成立的 10 条 finding，被驳回的 F3 不入范围。

## Finding 清单

- **F1**（P0）：`scripts/gates/audit.py:111` `calc_exit_code` 在 --strict 时不读 `vars["warnings"]`，多个插件（sourcing/meta_schema/index_integrity/plan_freshness）的 warning 被吞
- **F2**（P0）：`.claude/settings.json:27` matcher `Bash|Edit|Write` 不匹配 MultiEdit；protect_branch.py:27 内部支持 MultiEdit 但 hook 不被拉起。本项目决定不维护 codex 双轨，所以仅修 `.claude` 侧
- **F4**（P1）：`scripts/gates/run.py:281` `filter_gates` 仅按 trigger 过滤；registry.yaml 的 `applies_when.changed_files / target_phase / current_phase_in / transition / requires` 在 runner 层零消费
- **F5**（P1）：`scripts/gates/run.py:333` `_validate_phase_args` 仅查 phase 是否在 canonical 集合，不查相邻表
- **F6**（P1）：`scripts/gates/run.py:516` `_handle_escape_hatch` 命中后不区分 finding 类别，所有 error gate 失败一律返 0；对比 `legacy-requirement` 有 `skips_gates_with_tag: [review-verdict]`，本参数无任何 tag 限定
- **F7**（P1）：submit.md 列出 7 项硬门禁，`scripts/gates/triggers/submit.py:74` 仅透传 `--trigger=submit --req=<id>`；`base_reachable.py:58` 不读 `cli_flags.target`，submit.md `--target` 参数链路不通
- **F8**（P1）：`reviews_consistency.py:21` 自带 `triggers={"pre-commit"}` + 显式 Skip 非 pre-commit；CI 不跑该 gate
- **F9**（P2）：`traceability.py:39-49` 仅 `to_phase=="testing"` 真跑；`_feature_mentioned` 用 `re.search(re.escape(feature_id), text)` 字符串包含
- **F10**（P2）：`pr_state.py:82-93` gh 失败 → PASS+WARNING；CLOSED 显式 PASS
- **F11**（P2）：`.github/workflows/quality-check.yml` 仅 5 step，无 build / test / lint；roadmap.md G1/G4 自承待办

## 不入范围

- F3：已被 review-critic 驳回
