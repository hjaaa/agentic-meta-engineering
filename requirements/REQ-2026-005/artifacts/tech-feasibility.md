---
id: REQ-2026-005
title: "门禁系统加固 · 技术可行性评估"
created_at: "2026-05-01"
refs-tech-feasibility: true
---

# REQ-2026-005 · 技术可行性评估

## 总结

可行性：**high**。5 组 FG 的核心改动全部基于项目现有技术栈（Python argparse / registry.yaml / subprocess / pathspec），无需引入新外部依赖（ruff 是唯一新工具，风险可控）。最大不确定性在 FG-003 的性能基线：runner 层消费 `applies_when` 字段后若退化 > 20%，需触发降级（保留 plugin 内 changed_files 副本），**baseline 抓取是 FG-003 的硬前置条件**。无 blocker 级阻碍。

总工作量估算：**11 人天**（design 1.1 + dev 5.0 + test 4.9），可 2~3 人并行压缩至约 5 人天。

---

## 1. FG-001 · strict 模式 + CI 兜底

### 1.1 技术路径

**根因澄清**：`calc_exit_code`（来源：scripts/gates/audit.py:111）本身逻辑正确——`if strict and has_warning_fail: return 1`（来源：scripts/gates/audit.py:126）。问题在于 `has_warning_fail` 永远不被触发：各 plugin 的 `_legacy_to_report` 在"仅有 warnings 无 errors"时一律返回 `Decision.PASS`，把 warnings 写入 `vars["warnings"]`（来源：scripts/gates/plugins/sourcing.py:143）（来源：scripts/gates/plugins/plan_freshness.py:157）（来源：scripts/gates/plugins/meta_schema.py:152）。`calc_exit_code` 只遍历 `r.decision == Decision.FAIL` 的 report，因此永远看不见 warning-only 情况。

**选择方案：修 plugin 的 `_legacy_to_report`**

当 `warnings` 非空且 `errors` 为空时，返回 `Decision.FAIL`（让 runner 看见 warning fail），而非 `Decision.PASS`。涉及 3~4 处：`meta_schema._legacy_to_report`（来源：scripts/gates/plugins/meta_schema.py:130）、`sourcing._legacy_to_report`（来源：scripts/gates/plugins/sourcing.py:122）、`plan_freshness._legacy_to_report`（来源：scripts/gates/plugins/plan_freshness.py:133）。

不修改 `calc_exit_code`（来源：scripts/gates/audit.py:111）：该函数已正确处理 `has_warning_fail`，修复点在上游 plugin 层。

备选方案"修 `calc_exit_code` 额外读 `vars['warnings']`"被否：让 audit 层感知 PASS report 内部 vars 语义，违反 Report 契约的"PASS 即通过"语义。

**F8（reviews_consistency 加入 CI trigger）**：

修 `registry.yaml`（来源：scripts/gates/registry.yaml:190）的 `triggers` 加入 `ci`，同时修 plugin precheck（来源：scripts/gates/plugins/reviews_consistency.py:57）允许 `ci` trigger 通过。CI 路径下 `ctx.changed_files` 通常为空（非 pre-commit 不注入 `GATE_CHANGED_FILES`），plugin 的 `run` 方法将调用 `_get_staged_files()`（来源：scripts/gates/plugins/reviews_consistency.py:81），但 CI 环境 `git diff --cached` 返回空 → 提前 PASS。需在 CI trigger 下改为扫全量 `requirements/*/meta.yaml` + 对应 `reviews/*.json`（而非依赖 staged 列表）。

### 1.2 依赖关系

FG-001 独立，无依赖其他 FG。F8 需先改 registry.yaml 再改 plugin precheck，两者同 PR。

### 1.3 风险

| # | 类别 | 描述 | 可能性 | 影响 | 缓解 |
|---|---|---|---|---|---|
| R1-1 | tech | `Decision.FAIL` 语义扩大后，sourcing（registry severity=error）的 W 类 finding 在非 strict 模式下也会触发 exit 1，可能改变现有行为 | medium | high | 确认 sourcing W 类 finding 是否应在 strict 下升 exit 1（场景 1 只明确 plan_freshness 的 W003，来源：requirements/REQ-2026-005/artifacts/requirement.md:35）；如不需要，sourcing 的 `_legacy_to_report` 保持 PASS 不改，只改 plan_freshness。详见待澄清清单第 1 条 |
| R1-2 | tech | reviews_consistency CI 路径走全量扫描，逻辑分支与 pre-commit 不同，新增测试覆盖面 | low | low | 新增 `test_reviews_consistency_ci_trigger.py` 单测，mock `_get_staged_files` 返回值 |

### 1.4 工作量

| 子任务 | dev | test |
|---|---|---|
| 3~4 处 `_legacy_to_report` 修改（各约 5 行） | 0.5 | 0.5 |
| reviews_consistency 加 CI trigger + CI 路径全量扫描逻辑（约 20 行） | 0.5 | 0.5 |
| **合计** | **1.0** | **1.0** |

### 1.5 验证方式

```bash
# 构造含 W003 的 plan.md 场景，strict 模式期望 exit 1
python3 scripts/gates/run.py --trigger=ci --req=<测试 REQ> --strict
echo "exit=$?"  # 期望: 1

# 同场景非 strict 期望 exit 0
python3 scripts/gates/run.py --trigger=ci --req=<测试 REQ>
echo "exit=$?"  # 期望: 0

# pytest
pytest tests/gates/ -v -k "strict or reviews_consistency"
```

---

## 2. FG-002 · Hook matcher 覆盖

### 2.1 技术路径

**现状**：`.claude/settings.json:29` matcher 为 `"Bash|Edit|Write"`（来源：.claude/settings.json:29），缺 `MultiEdit`；`protect_branch.py` 的 `WRITE_TOOLS` 已含 `MultiEdit`（来源：scripts/gates/plugins/protect_branch.py:27），但 hook 不被拉起。

**Claude Code matcher 语法**（经 WebSearch 确认）：`PreToolUse` hook 的 `matcher` 字段为管道分隔工具名字符串，如 `"Write|Edit|MultiEdit"`，大小写敏感，管道两侧无空格。不支持数组形式，必须是单一字符串。matcher 按工具名完整匹配（split by `|`），不是正则 OR——无歧义风险。

**修复**：`.claude/settings.json:29` 的 matcher 从 `"Bash|Edit|Write"` 改为 `"Bash|Edit|Write|MultiEdit"`（来源：.claude/settings.json:29）。plugin 代码无需任何变更（来源：scripts/gates/plugins/protect_branch.py:27）。

### 2.2 依赖关系

FG-002 完全独立，单文件单行修改。

### 2.3 风险

| # | 类别 | 描述 | 可能性 | 影响 | 缓解 |
|---|---|---|---|---|---|
| R2-1 | tech | Claude Code 未来版本更新 matcher 语法导致 hook 失效 | low | high | testing 阶段人工在 develop 分支执行 MultiEdit 验证拦截（场景 2） |

### 2.4 工作量

| 子任务 | dev | test |
|---|---|---|
| `.claude/settings.json` 单行改动 | 0.1 | 0.2（人工验收） |
| **合计** | **0.1** | **0.2** |

### 2.5 验证方式

```bash
# 人工验收：在 develop 分支尝试 MultiEdit，期望被 protect_branch.py 拦截
# CI 无法自动测试 hook 拉起，testing 阶段人工执行场景 2
```

---

## 3. FG-003 · registry SoR + phase 相邻表

### 3.1 技术路径

**A. applies_when 字段消费——一次性消费全部字段**

现状：`filter_gates`（来源：scripts/gates/run.py:281）仅按 trigger 过滤，注释显式标明"applies_when 内更精细的条件留给 F-002 实现"（来源：scripts/gates/run.py:282）。各 plugin precheck 重复实现 changed_files 过滤。

选择方案（来源：requirements/REQ-2026-005/artifacts/requirement.md:103）：在 `filter_gates` 中对每个 registry entry 额外检查 5 个 applies_when 子字段：

1. `changed_files`（非空列表）：用 `pathspec`（已在 CI 依赖，来源：.github/workflows/quality-check.yml:25）匹配 `ctx.changed_files`；空列表 = 不限制，pass through。
2. `requires`（非空列表）：检查 `ctx.meta.get(field)` 均非空（已有 `GATE-PR-MERGED-STATE` 依赖此字段，来源：scripts/gates/registry.yaml:219）。
3. `target_phase`（非 null）：检查 `ctx.to_phase == target_phase`。
4. `current_phase_in`（非空列表）：检查 `ctx.meta.get("phase")` 在列表中。
5. `transition`（非 null，格式 `"from->to"`）：检查 `ctx.from_phase→ctx.to_phase`。

删除 4 个 plugin precheck 内的 changed_files 过滤（来源：scripts/gates/plugins/meta_schema.py:54）（来源：scripts/gates/plugins/sourcing.py:48）（来源：scripts/gates/plugins/index_integrity.py:49）（来源：scripts/gates/plugins/plan_freshness.py:46）。**此删除必须与 filter_gates 升级同 PR 合入**，否则出现"plugin 过滤逻辑删了但 runner 还未消费"的窗口期导致 gate 漏跑。

备选方案"渐进式：先 changed_files，其他留 Phase 2"：仅在性能超标触发降级时使用，否则按一刀切原则执行（来源：requirements/REQ-2026-005/plan.md:78）。

**glob 匹配引擎**：registry 中 `changed_files` 使用 gitignore 风格 glob（如 `requirements/*/meta.yaml`、`context/**/*.md`，来源：scripts/gates/registry.yaml:26）。`pathspec` 已是 CI 现有依赖（来源：.github/workflows/quality-check.yml:25），零新增依赖，支持 `**`（`fnmatch` 不支持，来源：requirements/REQ-2026-003/artifacts/tech-feasibility.md:29）。

**B. phase 相邻表**

当前 `_validate_phase_args`（来源：scripts/gates/run.py:333）只验证 phase 在 canonical 集合内，不验证 from→to 相邻合法性。

相邻关系数据源：`meta-schema.yaml` 的 `enums.phase` 为有序列表（来源：context/team/engineering-spec/meta-schema.yaml:39），从列表位置动态推导相邻关系，不硬编码：`phase[i] → phase[i+1]` 为合法前进。回退允许跨阶段，但 from/to 仍需在 canonical 集内。

实现：在 `scripts/lib/phase_enum.py` 新增 `load_adjacent_phases()`（或 `frozenset[tuple[str,str]]`）；修改 `_validate_phase_args`（来源：scripts/gates/run.py:333）：当 from_phase 非空时，若 to_phase > from_phase（前进方向）则校验相邻；回退方向不校验（来源：.claude/skills/managing-requirement-lifecycle/reference/phase-rules.md:25）。

**C. Baseline 测量（硬前置条件）**

```bash
# 本机运行（非 CI），取 5 次中位数
for i in 1 2 3 4 5; do
  { time python3 scripts/gates/run.py --trigger=ci --req=REQ-2026-005; } 2>&1 \
    | grep real | awk '{print $2}'
done
# 剔除异常值（> 2x 中位数）；FG-003 实施后重跑对比；增幅 > 20% 触发降级
```

（来源：requirements/REQ-2026-005/artifacts/requirement.md:147）

### 3.2 依赖关系

FG-003 无依赖其他 FG，可并行开发。内部约束：filter_gates 升级 + plugin precheck 删除**必须同 PR**，baseline 测量**必须在 PR 合入前**完成。

### 3.3 风险

| # | 类别 | 描述 | 可能性 | 影响 | 缓解 |
|---|---|---|---|---|---|
| R3-1 | tech | pathspec glob 与旧 plugin fnmatch 行为不一致，导致部分 gate 过滤结果改变 | medium | high | 逐一核查现有 21 条 gate 的 `applies_when.changed_files`；新增"filter before/after"对比测试，确保 SKIP 集合变化仅限于预期范围 |
| R3-2 | ops | FG-003 性能退化 > 20% | low | medium | 先抓 baseline；超标时保留 plugin 内 changed_files 副本（降级），registry 字段消费仅作可选优化（来源：requirements/REQ-2026-005/artifacts/requirement.md:75） |
| R3-3 | tech | `changed_files: []` 语义歧义（不限制 vs 无文件则 skip） | medium | medium | 明确文档：空列表 = 不做 changed_files 过滤，与现有 gate 行为一致（如 GATE-WORKSPACE-CLEAN，来源：scripts/gates/registry.yaml:124）；详见待澄清清单第 2 条 |

### 3.4 工作量

| 子任务 | dev | test |
|---|---|---|
| baseline 抓取（命令见 3.1C） | 0.2 | 0 |
| `filter_gates` 升级：消费 5 个 applies_when 字段（约 50 行） | 0.5 | 0.5 |
| 删除 4 个 plugin precheck 的 changed_files 过滤逻辑 | 0.3 | 0.5 |
| `phase_enum.py` 新增相邻推导 + `_validate_phase_args` 修改（约 30 行） | 0.3 | 0.3 |
| **合计** | **1.3** | **1.3** |

### 3.5 验证方式

```bash
# 非法 phase 跳跃（bootstrap→testing）期望 exit 2
python3 scripts/gates/run.py --trigger=phase-transition \
  --from=bootstrap --to=testing --req=REQ-2026-005 --dry-run
echo "exit=$?"  # 期望: 2

# 合法跳跃期望 exit 0
python3 scripts/gates/run.py --trigger=phase-transition \
  --from=bootstrap --to=definition --req=REQ-2026-005 --dry-run
echo "exit=$?"  # 期望: 0

# 性能对比（baseline vs 实施后）
for i in 1 2 3 4 5; do
  { time python3 scripts/gates/run.py --trigger=ci --req=REQ-2026-005; } 2>&1 \
    | grep real
done

# pytest
pytest tests/gates/ -v -k "filter_gates or phase_transition"
```

---

## 4. FG-004 · escape hatch + submit 门禁链路

### 4.1 技术路径

**A. escape hatch tag 限定**

现状：`registry.yaml` 的 `force-with-blockers` escape hatch 无 `skips_gates_with_tag` 约束（来源：scripts/gates/registry.yaml:313），命中后 `_handle_escape_hatch`（来源：scripts/gates/run.py:516）对任意 error gate 一律返 0。

修复：
1. `registry.yaml:313` 条目加入 `skips_gates_with_tag: [review-verdict]`（参考 legacy-requirement 模式，来源：scripts/gates/registry.yaml:308）
2. `_handle_escape_hatch`（来源：scripts/gates/run.py:516）中读取当前失败 gate 的 tag（从 registry 加载的 entry），若不在 `skips_gates_with_tag` 内，则不走 escape_hatch 路径而走正常 fail 路径

注意：registry.yaml 现有 gate entry 格式无 `tags` 字段（来源：scripts/gates/registry.yaml:1），需先为相关 gate（如 GATE-REVIEW-VERDICT）加 `tags: [review-verdict]`，再在 escape hatch 条目引用此 tag。这是一个新字段引入，需同步更新 registry schema 校验（S1-S10）。

**B. `--bypass-review-blockers` argparse alias**

argparse 不原生支持 alias。

**选择方案 A：两次 `add_argument` + 相同 `dest` + argv 扫描打 deprecation**

```python
# 在 parse_args 函数中（来源：scripts/gates/run.py:143）
p.add_argument(
    "--bypass-review-blockers",
    dest="force_with_blockers",
    default=None,
    help="（推荐）绕过 review-blocker 类 gate；等价于 --force-with-blockers",
)
p.add_argument(
    "--force-with-blockers",
    dest="force_with_blockers",
    default=None,
    help="[DEPRECATED 2026-11-01] 请使用 --bypass-review-blockers",
)
```

deprecation 打印：在 `main()` 调用 `parse_args` 之后（来源：scripts/gates/run.py:406），扫原始 argv：

```python
if any(a.startswith("--force-with-blockers") for a in (argv or sys.argv[1:])):
    print(
        "[DEPRECATED] use --bypass-review-blockers instead, "
        "removed at 2026-11-01",
        file=sys.stderr,
    )
```

`submit.py` 同步新增 `--bypass-review-blockers` 参数（来源：scripts/gates/triggers/submit.py:46）。

备选方案 B（自定义 `DeprecatedAction`）：代码更多但不需要扫 argv；选方案 A 因实现更简单且 deprecation 逻辑集中。

**C. 三个新 submit plugin**

`GATE-BRANCH-MATCH`：
- `git branch --show-current` 获取当前分支（复用 protect_branch 的 `_get_current_branch` 模式，来源：scripts/gates/plugins/protect_branch.py:133）
- 对比 `ctx.meta.get("branch")`；不匹配返回 `FAIL(R-BRANCH-MISMATCH)`，stderr 含 `当前分支 <X> 与 meta.branch <Y> 不一致`

`GATE-PHASE-IN-SET`：
- `ctx.meta.get("phase")` ∈ `{"development", "testing"}` 才允许 submit
- 不在范围返回 `FAIL(R-PHASE-NOT-SUBMITTABLE)`

`GATE-AHEAD-OF-ORIGIN`：
- `git rev-list origin/<base_branch>..HEAD --count`；count = 0 → FAIL(R-NOTHING-TO-PUSH)
- base_branch 从 `ctx.meta.get("base_branch")` 或 fallback `develop` 取

`base_reachable._resolve_base_branch` 修复（来源：scripts/gates/plugins/base_reachable.py:58）：优先读 `ctx.cli_flags.get("target")`，再 fallback `ctx.meta.get("base_branch")`。`submit.py`（来源：scripts/gates/triggers/submit.py:76）透传 `--target` 参数给 runner。

### 4.2 依赖关系

FG-004 无依赖其他 FG。内部约束：registry.yaml 新增 `tags` 字段 + gate entry 标注 + escape hatch 修改 + runner `_handle_escape_hatch` 修改必须**同 PR**；三个新 plugin 的 registry 注册与 plugin 代码必须**同 PR**。

注意：registry tags 字段是 schema 新增字段，需更新 S1-S10 校验规则（若 tags 为可选字段可不破坏现有 gate 定义）。

### 4.3 风险

| # | 类别 | 描述 | 可能性 | 影响 | 缓解 |
|---|---|---|---|---|---|
| R4-1 | tech | registry tags 字段是新增字段，schema 校验（S1-S10）可能拒绝含 tags 的 entry | medium | high | 先确认 S1-S10 是否有"禁止额外字段"规则；若有，同步更新 schema 定义允许 tags 可选字段 |
| R4-2 | business | 现有调用 `--force-with-blockers` 的 CI/文档改动后语义变化，使原本可绕过的 gate 被真实拦截 | medium | high | 修改前搜索 `.claude/commands/`、CI workflow 中所有该 flag 调用场景，确认仅 review-blocker 场景 |
| R4-3 | tech | argparse 两次同 dest `add_argument`，默认值冲突 | low | medium | 两处均设 `default=None`，实际提供的值覆盖 None，无冲突 |

### 4.4 工作量

| 子任务 | dev | test |
|---|---|---|
| registry.yaml: tags 字段 + gate 标注 + escape hatch 修改（约 10 行 YAML） | 0.2 | 0.2 |
| runner `_handle_escape_hatch` 逻辑修改（约 15 行） | 0.3 | 0.3 |
| argparse alias + deprecation warning（约 15 行） | 0.3 | 0.3 |
| 三个新 plugin（各约 50 行）+ registry 注册 | 0.6 | 0.6 |
| `base_reachable._resolve_base_branch` + `submit.py --target` 透传（约 10 行） | 0.2 | 0.2 |
| **合计** | **1.6** | **1.6** |

### 4.5 验证方式

```bash
# escape hatch tag 限定：workspace dirty 场景不被 --bypass-review-blockers 绕过
python3 scripts/gates/run.py --trigger=phase-transition \
  --from=development --to=testing --req=REQ-2026-005 \
  --bypass-review-blockers="测试" 2>&1
# 期望: GATE-WORKSPACE-CLEAN 仍正常检查

# deprecation warning
python3 scripts/gates/run.py --trigger=ci \
  --force-with-blockers="旧名" 2>&1 | grep DEPRECATED
# 期望: "[DEPRECATED] use --bypass-review-blockers instead, removed at 2026-11-01"

# submit gate 链路 dry-run
python3 scripts/gates/triggers/submit.py --req=REQ-2026-005 --dry-run
# 期望: plan 含 GATE-BRANCH-MATCH / GATE-PHASE-IN-SET / GATE-AHEAD-OF-ORIGIN

# pytest
pytest tests/gates/ -v -k "branch_match or phase_in_set or ahead_of_origin or escape_hatch"
```

---

## 5. FG-005 · 降级路径收紧 + CI build/test/lint

### 5.1 技术路径

**A. traceability 收紧（F9）**

现状：precheck 仅 `to_phase == "testing"` 才真跑（来源：scripts/gates/plugins/traceability.py:45），submit trigger 被跳过。

修复：precheck 改为：`trigger == "phase-transition" and to_phase == "testing"` 或 `trigger == "submit"`（来源：requirements/REQ-2026-005/artifacts/requirement.md:115）。

grandfather 机制：在 runner 的 `filter_gates`（而非 plugin 层，来源：requirements/REQ-2026-005/plan.md:78）检查 `ctx.meta.get("legacy") == True` 时跳过 GATE-TRACEABILITY。

`_feature_mentioned` 升级（来源：scripts/gates/plugins/traceability.py:160）：当前 `re.search(re.escape(feature_id), text)` 可能误匹配前缀（如 `FG-001` 匹配到 `FG-0015`）。升级为单词边界匹配：`re.search(r'(?<![A-Za-z0-9-])' + re.escape(feature_id) + r'(?![A-Za-z0-9-])', text)`。feature_id 格式为 `FG-NNN`，负向断言以非连字符/数字/字母为边界，精确。

**B. pr_state 降级路径收紧（F10）**

现状：gh 失败 → `Decision.PASS`（来源：scripts/gates/plugins/pr_state.py:82）；CLOSED → `Decision.PASS`（来源：scripts/gates/plugins/pr_state.py:124）。

修复（来源：requirements/REQ-2026-005/plan.md:90）：
- gh 失败时：增加 `git ls-remote origin HEAD` 作为网络连通性探测（fallback）；仍失败才 `Decision.PASS + vars["gh_call_failed"]`
- CLOSED：改为 `Decision.PASS + vars["pr_state_closed"] = True`，打 INFO 提示用户确认是否重开 PR（不升级为 FAIL）

注意：`Decision` 枚举仅有 PASS/FAIL/SKIP 三态（来源：scripts/gates/plugins/base.py:43），无 INFO 态；INFO 语义通过 `Decision.PASS + vars["severity_hint"] = "info"` 实现。

**C. ruff 集成（F11）**

**安装位置**：在 quality-check.yml 的 `Install dependencies` step 加入 `ruff`（来源：.github/workflows/quality-check.yml:25），不单独新增 step。

版本约束：`"ruff>=0.4,<1.0"`（参考 pathspec 策略，来源：requirements/REQ-2026-003/artifacts/tech-feasibility.md:134）。

配置：`pyproject.toml`（来源：pyproject.toml:1）当前只有 pytest 配置，新增：

```toml
[tool.ruff]
select = ["E", "W", "F"]
line-length = 120
ignore = ["E501"]  # 避免历史行超长噪音；可后续收紧
```

**首次历史问题处理策略**（两步，防首次 PR 红灯）：
1. 本地预扫：`ruff check scripts/ --select=E,W,F --statistics`，评估问题数量
2. 若 > 20 个：先单独 PR 运行 `ruff check scripts/ --fix`（auto-fix 安全的 E/W/F 类），再加 CI step；否则一次性修复 + 加 CI step

**CI step**（来源：requirements/REQ-2026-005/artifacts/requirement.md:117）：

```yaml
- name: pytest
  run: pytest tests/gates/ -v

- name: ruff lint
  run: ruff check scripts/ --select=E,W,F
```

### 5.2 依赖关系

FG-005 内三子项代码路径不重叠，按 requirement.md 归并依据（来源：requirements/REQ-2026-005/artifacts/requirement.md:114）同一批次 CI workflow 调整。ruff 历史问题预扫先于 CI step 加入。建议与 FG-001 的 strict 修复同批次验收，确保新 CI step 本身无 ruff 违规。

### 5.3 风险

| # | 类别 | 描述 | 可能性 | 影响 | 缓解 |
|---|---|---|---|---|---|
| R5-1 | ops | ruff 首次扫出大量历史问题，PR 红灯 | medium | medium | 先本地预扫 + auto-fix PR；加入 CI 前确认 0 error |
| R5-2 | tech | traceability submit trigger 路径缺少 `to_phase` 值（submit 不传 --to），导致 precheck 逻辑异常 | medium | medium | submit trigger 的 traceability 校验不依赖 to_phase，只依赖 req_id；precheck 分支应为 `trigger == "submit" and ctx.requirement_id` |
| R5-3 | tech | meta.legacy 字段在 meta-schema.yaml 中未有显式定义，filter_gates 读取时返回 None 而非 False，grandfather 判断 `== True` 需精确类型检查 | low | low | 使用 `ctx.meta.get("legacy") is True` 或 `bool(ctx.meta.get("legacy", False))`；同时在本需求中明确是否在 meta-schema.yaml 新增此字段（详见待澄清清单第 3 条） |

### 5.4 工作量

| 子任务 | dev | test |
|---|---|---|
| traceability precheck 扩展 + submit 路径 + `_feature_mentioned` 升级 + grandfather 逻辑（约 30 行） | 0.3 | 0.3 |
| pr_state gh 失败 fallback + CLOSED INFO 化（约 20 行） | 0.3 | 0.3 |
| ruff 集成：pyproject.toml + quality-check.yml + 历史问题预修 | 0.4 | 0.2 |
| **合计** | **1.0** | **0.8** |

### 5.5 验证方式

```bash
# ruff 预扫（本地，FG-005 实施前）
ruff check scripts/ --select=E,W,F --statistics

# 完整 CI 验证（PR 触发 quality-check workflow）
# 期望：pytest tests/gates/ -v 全绿 + ruff check 0 error

# traceability submit 路径
python3 scripts/gates/run.py --trigger=submit --req=REQ-2026-005 --dry-run
# 期望：GATE-TRACEABILITY 出现在 plan 中

# pytest
pytest tests/gates/ -v -k "traceability or pr_state"
```

---

## 6. 组间依赖 DAG

```
FG-001（strict + F8）  ─── 独立，无跨组依赖
FG-002（matcher）      ─── 独立，最小改动
FG-003（registry SoR） ─── 独立；必须先抓 baseline；filter_gates + plugin precheck 删除同 PR
FG-004（escape hatch） ─── 独立；registry tags 扩展 + runner + 三新 plugin 各同 PR 内
FG-005（CI lint）      ─── 独立；ruff 历史问题先扫；建议与 FG-001 同批次验收
```

**实施顺序建议**：FG-002 → FG-001 → FG-004 → FG-003（抓 baseline 后）→ FG-005

---

## 7. 总工作量估算

| FG | design | dev | test | 合计 |
|---|---|---|---|---|
| FG-001 | 0.2 | 1.0 | 1.0 | 2.2 |
| FG-002 | 0.1 | 0.1 | 0.2 | 0.4 |
| FG-003 | 0.3 | 1.3 | 1.3 | 2.9 |
| FG-004 | 0.3 | 1.6 | 1.6 | 3.5 |
| FG-005 | 0.2 | 1.0 | 0.8 | 2.0 |
| **合计** | **1.1** | **5.0** | **4.9** | **11.0** |

可 2~3 人并行（FG-001/002/003/004 间无强依赖）压缩至约 5 人天。

---

## 8. 前置条件（上线前必须解决）

1. **FG-003 baseline 抓取**：实施 FG-003 前，在本机跑 5 次取中位数（命令见 §3.1C）；超 20% 增幅触发降级方案（来源：requirements/REQ-2026-005/artifacts/requirement.md:75）
2. **ruff 历史问题预扫**：FG-005 加入 CI step 前，本地运行 `ruff check scripts/ --select=E,W,F --statistics`，决定是否需要单独 auto-fix PR
3. **escape hatch 现有调用清查**：FG-004 修改 `--force-with-blockers` 语义前，搜索 `.claude/commands/` 和 CI workflow 中所有该 flag 调用，确认无超范围绕过场景
4. **registry tags 字段 schema 兼容性**：FG-004 需在 gate entry 加 `tags` 新字段；若 S1-S10 registry schema 校验有"禁止额外字段"规则，需同步更新 schema 定义

---

## 待澄清清单

1. **FG-001 sourcing W 类 finding 在 strict 下是否应升 exit 1**：需求场景 1（来源：requirements/REQ-2026-005/artifacts/requirement.md:35）提到的 W003 来自 `GATE-PLAN-FRESHNESS`（registry severity=warning）。`sourcing` 的 registry severity=error，其 W 类 finding（W001/W002/W003）目前报 PASS——strict 模式下 sourcing W 类是否也应升 exit 1？若只需修 plan_freshness，则 sourcing `_legacy_to_report` 保持现状。[待用户确认]

2. **FG-003 `applies_when.changed_files: []` 的精确语义**：registry 中多个 gate（如 GATE-WORKSPACE-CLEAN，来源：scripts/gates/registry.yaml:124）的 `changed_files` 为空列表。新 `filter_gates` 逻辑中，空列表应视为"不做 changed_files 过滤（任意 changed_files 均通过）"，还是"没有 changed_files 时跳过该 gate"？推断为前者（与现有 GATE-WORKSPACE-CLEAN 行为一致），但需明确。[待用户确认]

3. **meta.legacy 字段在 meta-schema.yaml 中是否已有显式定义**：plan.md D-007 引用"复用 meta-schema.yaml 已定义的 legacy 字段"（来源：requirements/REQ-2026-005/plan.md:98），但 meta-schema.yaml 全文（来源：context/team/engineering-spec/meta-schema.yaml:1）中未见 `legacy: true/false` 的枚举或字段定义（`legacy` 仅出现在 `log_layout` 枚举值中）。请确认：① `meta.legacy` 字段是否已在 meta-schema.yaml 中定义；② 若未定义，本需求是否需新增此 optional boolean 字段。[待用户确认]

4. **FG-004 `GATE-AHEAD-OF-ORIGIN` gh 失败时的降级行为**：`git rev-list` 因网络不通或 origin 未配置失败时，是降级 PASS 还是 FAIL？建议与 `base_reachable` 一致（来源：scripts/gates/plugins/base_reachable.py:89）：网络类失败降级 PASS + WARNING，避免网络问题阻断 submit。[待用户确认]
