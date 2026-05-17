---
id: REQ-2026-013
title: "REQ-2026-013 · 技术可行性评估"
created_at: "2026-05-17"
refs-tech-feasibility: true
---

# REQ-2026-013 · REQ-2026-012 follow-up bundle 技术可行性评估

**可行性结论：high**。5 个 feature 无 blocker 级阻碍。改造点均在现有文件的局部函数内，无新依赖引入。F-A 向后兼容历史 completed 需求 verdict（A2 双侧 normalize 路径）；F-B fail-open 语义保持；F-C 纯文档改造零代码风险；F-D/F-E 仅改 Markdown 文件。

---

## 1. 5 feature 逐项可行性

### F-A · check_reviews.py R005 hash 比对 normalize

**实现路径**

改造点在 `scripts/lib/check_reviews.py` 的 `_r005_hash_drift` 函数（来源：scripts/lib/check_reviews.py）。当前 hash 计算以 `rb` 模式读取整文件 bytes 后直接 `hashlib.sha256(f.read()).hexdigest()`（来源：scripts/lib/check_reviews.py）。

A2 方案在读取路径上插入 normalize 步骤：仅当 `path_str` 以 `artifacts/tasks/` 开头时，先以文本模式读取内容，用 `re.sub` 去掉 frontmatter `status` 和 `updated_at` 两字段行（仅在首对 `---` 之间应用），再 `encode('utf-8')` 后计算 sha256。normalize 白名单 = `{"status", "updated_at"}`（来源：context/team/engineering-spec/task-frontmatter-schema.yaml），dev 期演进仅这 2 个字段，其余 7 个设计期 frozen（来源：requirements/REQ-2026-013/plan.md）。

历史 completed 需求 verdict.artifact_hashes 存的是整文件 hash；A2 双侧 normalize 后，已 done 状态 task.md strip 掉相同字段值，body 不变，hash 仍等于 verdict 旧值，完全向后兼容（来源：context/team/experience/reviewer-artifact-selection-excludes-evolving-frontmatter.md）。

**可行性：高**

改动约 15 行 Python，`hashlib` 与 `re` 均为标准库已在 `check_reviews.py` 中导入（来源：scripts/lib/check_reviews.py）。无新依赖。

**关键技术风险**

1. normalize re.sub 正则误 strip body 内容（body 内出现 status 字段行）：缓解——仅在首对 `---` frontmatter 块内应用 strip，body 内不处理；pytest 用例覆盖 body-contains-status 反例。
2. 白名单字段名与 schema 解耦，schema 升级时不自动同步：缓解——testing 阶段回归用例 `test_check_reviews_normalize_schema_sync.py` 读 schema `enums.status` 字段集与白名单对比（来源：requirements/REQ-2026-013/artifacts/requirement.md）。
3. re.sub 在非 UTF-8 frontmatter 场景下产生 encoding 边界 bug：缓解——以 utf-8 errors=replace 模式读取，strip 操作在 str 层面，encode 回 utf-8 后 hash；task.md 规范要求 UTF-8 编码（来源：context/team/engineering-spec/task-frontmatter-schema.yaml）。

**工作量预估**：3 小时（含 pytest 参数化覆盖 + schema-sync 回归用例骨架）

---

### F-B · touches_guard.py path normalize 仓库外路径直接 exit 0

**实现路径**

改造点在 `.claude/hooks/touches_guard.py` 的 `_main_inner` 函数（来源：.claude/hooks/touches_guard.py）。当前步骤 7 的 for 循环内，`_is_in_touches` 返回 False 时直接调 `_record_violation`（来源：.claude/hooks/touches_guard.py）。

`_is_in_touches` 对仓库外绝对路径已有 `relative_to(_REPO_ROOT)` 尝试，ValueError 后返回 False（来源：.claude/hooks/touches_guard.py），但 False 仍触发 `_record_violation`，这是 bug 所在。

修复：在 for 循环 `_is_in_touches` 判断之前，新增 `_is_out_of_repo(fp)` 快速判断——用 `Path(fp).resolve()` + 缓存的 `git rev-parse --show-toplevel` 结果判定，out-of-repo 则 continue 跳过，不进入 violation 路径。改动约 10 行（来源：context/team/experience/hook-path-normalization-out-of-repo.md）。

D-006 已确认 worktree cwd 场景：hook 进程 cwd 调 `git rev-parse --show-toplevel` 取 worktree 根，worktree 内路径按 worktree-local 语义判定，符合设计意图（来源：requirements/REQ-2026-013/plan.md）。

**可行性：高**

`Path.resolve()` 与 subprocess 调用均为现有 hook 已引入模式（来源：.claude/hooks/touches_guard.py）。无新依赖。

**关键技术风险**

1. `git rev-parse --show-toplevel` subprocess 增加 hook 延迟：缓解——函数内一次性取 toplevel 并在 for 循环复用，预计 +1ms 以内（来源：requirements/REQ-2026-013/artifacts/requirement.md）。
2. `git rev-parse` 在非 git 目录抛异常：缓解——现有 fail-open try/except 在 `_main_inner` 全程覆盖（来源：.claude/hooks/touches_guard.py）。

**工作量预估**：2 小时（含 bats 新增 /tmp、/var、~/ 三类路径 violation-free 用例）

---

### F-C · archive-rules.md + archive_runner._render_summary 加 CI gate 预检提示

**实现路径**

两处改动：

1. `.claude/skills/managing-requirement-lifecycle/reference/archive-rules.md`（来源：.claude/skills/managing-requirement-lifecycle/reference/archive-rules.md）：在现有 §1 「5 项预检」之后新增 §「archive 前 CI gate 预检」一节，内容按 D-002 B3 + D-008 决策（来源：requirements/REQ-2026-013/plan.md）：要求主 Agent 在调 `archive_requirement` 前先执行 `python3 scripts/gates/run.py --trigger=ci --strict`，exit 0 才继续；说明 ci trigger 会扫全仓，其他 REQ 的 R005 按「refresh-only-current-req」原则手动 ack（来源：requirements/REQ-2026-013/plan.md）。

2. `scripts/lib/archive_runner.py` 的 `_render_summary` 函数（来源：scripts/lib/archive_runner.py）：在现有 6 行终端反馈末尾追加 1 行 reminder 文案，提醒主 Agent archive 前先跑 ci gate（来源：scripts/lib/archive_runner.py）。B3 路径不改 5 项硬门禁（来源：requirements/REQ-2026-013/artifacts/requirement.md）。

**可行性：高**

纯文档 + 1 行字符串改动，无逻辑风险。

**关键技术风险**

1. reminder 为被动提示而非主动预检，主 Agent 可能未看到即触发 archive：缓解——archive-rules.md 是 Skill 强约束文档，主 Agent 执行前必读；未来 archive 频次升高可升级为 B1/B2 主动预检（来源：context/team/experience/archive-completed-triggers-framework-rule-fullset.md）。

**工作量预估**：1 小时（文档新增约 150 字 + 1 行代码 + _render_summary 输出断言）

---

### F-D · context/team/experience/INDEX.md 格式约定修订

**实现路径**

改造点在 `context/team/experience/INDEX.md` 的「格式约定」段（来源：context/team/experience/INDEX.md）。当前规则：「正文不超过 200 字 / 必须包含：问题、根因、解法、验证方法」（来源：context/team/experience/INDEX.md）。

修订内容（D-009 / D-003 决策，来源：requirements/REQ-2026-013/plan.md）：字数约束改为「正文建议 600 字内，800 字是软上限；超出考虑拆分到独立 reference 文件」；节结构扩展为五段（问题/根因/解法/验证方法/关联，关联段可空）。同 commit 内附兼容性 review 清单，列出 38 邻居中缺验证方法节的文件名。

**可行性：高**

纯 Markdown 文本改动约 3-5 行，零兼容性风险（D-003 D1 路径不回头改 38 文件正文，来源：requirements/REQ-2026-013/plan.md）。

**关键技术风险**

1. 规则改完与 38 历史文件结构仍有 gap（部分缺验证方法节）：缓解——兼容性 review 清单在 F-D commit 内列出作为 backlog（来源：requirements/REQ-2026-013/plan.md），gap 可见可追踪。

**工作量预估**：0.5 小时（改 INDEX.md 约 5 行 + 附兼容性清单）

---

### F-E · test-assets-must-be-wired-into-ci.md 补验证方法节

**实现路径**

改造点在 `context/team/experience/test-assets-must-be-wired-into-ci.md`（来源：context/team/experience/test-assets-must-be-wired-into-ci.md）。当前文件含问题/根因/解法/反面案例/关联五段，缺验证方法节。

修订：将解法段中的「不进 CI 必须说明：手跑命令 + owner」三条信息抽出，独立成验证方法节，与 97% 邻居文件结构对齐（来源：context/team/experience/test-assets-must-be-wired-into-ci.md）。依赖 F-D 已合入（INDEX.md 规则修订后验证方法节明确为必须节），同 PR 内 F-D commit 先于 F-E commit（来源：requirements/REQ-2026-013/plan.md）。

**可行性：高**

纯 Markdown 段落重排，改动约 5-8 行移动 + 新增节标题，无逻辑改动。

**关键技术风险**

1. 重排后解法段内容减少，语义可能显得不完整：缓解——解法保留核心「两条约束」规则，验证方法说明如何验证约束是否被执行，职责拆分清晰。

**工作量预估**：0.5 小时（段落重排 + 核对与 INDEX.md 新规则对齐）

---

## 2. 风险表

| ID | 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|---|
| R-1 | F-A normalize re.sub 误 strip body 内容行（body 含 status 字段） | 低 | 高 | 仅在 frontmatter 块内应用 strip；pytest 参数化覆盖反例 |
| R-2 | F-A 白名单字段名与 schema 解耦，schema 升级时静默失效 | 低 | 中 | testing 阶段 test_check_reviews_normalize_schema_sync.py 读 schema 与白名单对比（来源：requirements/REQ-2026-013/artifacts/requirement.md）|
| R-3 | F-A 历史 completed 需求 A2 兼容性实测未覆盖——理论向后兼容但未实测 | 低 | 中 | testing 阶段跑 ci gate 全仓扫确认无新增 R005 |
| R-4 | F-B git subprocess 在非 git 目录抛异常导致 hook crash | 低 | 低 | 现有 fail-open try/except 在 _main_inner 全程覆盖（来源：.claude/hooks/touches_guard.py）|
| R-5 | F-B worktree cwd 下主仓文件视为 out-of-repo（false-negative） | 低 | 低 | D-006 确认语义正确（worktree 是隔离环境，来源：requirements/REQ-2026-013/plan.md）|
| R-6 | F-C reminder 被主 Agent 忽略，archive 后 CI 仍红 | 中 | 中 | archive-rules.md 是 Skill 强约束文档；future-proof 可升级为 B1 主动预检（来源：context/team/experience/archive-completed-triggers-framework-rule-fullset.md）|
| R-7 | F-D 规则改完与 38 历史文件结构仍有 gap | 高 | 低 | F-D commit 内附兼容性清单作为 backlog（来源：requirements/REQ-2026-013/plan.md）|

---

## 3. 工作量汇总

| Feature | 估算（小时） | 主要改动文件 |
|---|---|---|
| F-A | 3.0 | scripts/lib/check_reviews.py + pytest 覆盖 |
| F-B | 2.0 | .claude/hooks/touches_guard.py + bats 用例 |
| F-C | 1.0 | archive-rules.md + scripts/lib/archive_runner.py（1 行）|
| F-D | 0.5 | context/team/experience/INDEX.md |
| F-E | 0.5 | context/team/experience/test-assets-must-be-wired-into-ci.md |
| 合计 | 7.0 小时 | 约 1.5 人日 |

**关键路径**：F-A（3h）→ F-B（2h）→ F-C（1h）→ F-D → F-E（串行 1h）。F-A 与 F-B 互相独立可并行；F-D 是 F-E 前置（来源：requirements/REQ-2026-013/plan.md）。最短墙钟时间：F-A/F-B 并行 3h + F-C 1h + F-D/F-E 串行 1h = 5h。

---

## 4. detail-design 待决问题

1. **F-A normalize 函数封装位置**：`_r005_hash_drift` 内联 re.sub 约 15 行，还是抽出 `_normalize_task_md_for_hash(content: str) -> bytes` 公共函数？抽出方便 pytest 独立测试复用——detail-design 阶段决定，影响测试 fixture 设计。
2. **F-B `git rev-parse` 缓存策略**：`_main_inner` 函数局部变量缓存（本次调用内复用）还是模块级 `functools.lru_cache`（跨 hook 调用复用）？模块级增加全局状态，影响 bats 单测 mock 策略——detail-design 阶段决定。
3. **F-C archive-rules.md §预检节的「手动 ack」流程粒度**：D-008 要求「其他 REQ 的 R005 手动 ack」，但未给 step-by-step 操作步骤（如何快速 grep meta_path 定位 REQ ID）——detail-design 阶段补充具体操作文案，否则主 Agent 执行时需再查文档（来源：requirements/REQ-2026-013/plan.md）。
4. **F-A 历史 completed 需求 A2 兼容性验证是否纳入 testing 验收**：A2 双侧 normalize 理论向后兼容，建议 testing 阶段 V-02 集成验证对现有全部 completed 需求跑 ci gate 确认 R005 无新增——detail-design 阶段决定是否为 V-02 指定对应 TC 编号。
5. **F-E 验证方法节的最终文案范围**：当前解法内的「手跑命令」描述 reviewer 检查行为；验证方法节还应补充「工程师如何本地验证测试已入 CI（如 grep workflow 命令）」——detail-design 阶段决定验证方法节文案边界，与 F-D 新五段规则对齐（来源：requirements/REQ-2026-013/plan.md）。
