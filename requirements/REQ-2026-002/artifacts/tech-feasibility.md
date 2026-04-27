---
id: REQ-2026-002
title: 统一门禁系统 · 技术可行性评估
created_at: "2026-04-27 21:00:00"
refs-tech-feasibility: true
---

# REQ-2026-002 · 技术可行性评估

## 总结

可行性：**high**。核心技术路径（Python graphlib 拓扑排序 + Plugin 类体系 + 薄壳迁移）均基于项目已有技术栈，无外部平台 bug 依赖（对比 REQ-2026-001 有 3 个平台级 bug 的 medium 可行性，来源：requirements/REQ-2026-001/artifacts/tech-feasibility.md:11）。主要风险集中在 7 个 adapter 的行为等价验证和 PreToolUse Hook 的进程链识别；两者均有明确的工程缓解路径。无 blocker 级阻碍。

总工作量估算：**27 人天**（单人串行），双人部分并行可压缩至约 23 天。

---

## 1. 关键技术选型

### 1.1 runner 拓扑排序 + 事务回滚

**拓扑排序**：Python 标准库 `graphlib.TopologicalSorter`（Python 3.9+ 内置，项目 CI 已固定 Python 3.11，来源：.github/workflows/quality-check.yml:22）直接可用，无需引入第三方依赖。`TopologicalSorter` 内置循环检测，依赖关系非法时抛 `CycleError`，可在 registry 加载期捕获并报错，而非在运行时崩溃。

**事务回滚**：门禁的副作用仅限于 `meta.yaml` 写回（如 R005 的 `stale=true`，来源：scripts/lib/check_reviews.py:152）。使用 `shutil.copy2` 在执行前 stash，失败时 copy 回原位，足以覆盖当前场景。无需引入数据库事务或 WAL 机制。rollback 本身失败的降级路径（写 `[blocker]` 到 process.txt + audit 标记 `rollback_failed=true`）在需求中已明确（来源：requirements/REQ-2026-002/artifacts/requirement.md:68）。

**结论**：graphlib + shutil.copy2 方案可行，零新增依赖。

### 1.2 snapshot 行为契约 / normalize-stderr

项目当前无 normalize-stderr 工具，需新写。逻辑明确：

- 去 ANSI color：`sed 's/\x1b\[[0-9;]*m//g'`
- 去绝对路径前缀：`sed "s|$REPO_ROOT/||g"`
- 去时间戳：视现有脚本输出格式决定正则——去时间戳和绝对路径前缀（来源：requirements/REQ-2026-002/artifacts/requirement.md:123）

关键前缀过滤（`ERROR`/`WARNING`/`✗`/`❌`/`E\d+`/`W\d+`/`R\d+`/`CR-\d+`）后做 diff，这是需求明确的验收判据（来源：requirements/REQ-2026-002/artifacts/requirement.md:122）。现有 common.py 的 paint() 函数（来源：scripts/lib/common.py:25）用 ANSI code，正则可精确匹配。实现约 40-60 行 bash，复杂度低，无阻塞项。

**结论**：自写，约 0.5 天，可行。

### 1.3 Bash 写保护 / 进程链识别（跨平台）

当前 protect-branch.sh 对 Bash 工具直接放行——`Bash` case 分支执行 `exit 0`（来源：.claude/hooks/protect-branch.sh:32）。H5 修复需要在 PreToolUse Hook 解析 Bash 的 `command` 字段，正则匹配写 `requirements/*/reviews/*.json` 的操作（来源：requirements/REQ-2026-002/artifacts/requirement.md:89）。

**跨平台进程链识别**：`ps -p $PPID -o comm=` 在 macOS 和 Linux 均可用，但 macOS 的 `comm` 字段会被截断（`save-review.sh` 长度处于安全区间，但需在 F-003 集成测试实测，详见下方"假设记录"块）

[待补充]
- 内容：macOS `ps -p $PPID -o comm=` 在 GitHub Actions macOS runner 容器中是否与本地行为一致
- 依据：需求 D-006 已明确双轨策略（父进程链 + 环境变量），来源：requirements/REQ-2026-002/plan.md:96
- 风险：容器中 PPID 可能为 1（init），导致父进程链判断失效，退化为仅靠 `CLAUDE_GATES_BYPASS` 环境变量
- 验证时机：F-003 PR 的集成测试，在 GitHub Actions macOS runner 上实测

**缓解**：双轨策略本身即是缓解——父进程链识别失效时，`CLAUDE_GATES_BYPASS=1 + CLAUDE_GATES_BYPASS_REASON` 环境变量作为显式豁免，写入 audit log（来源：requirements/REQ-2026-002/plan.md:100）。

**结论**：跨平台兼容 medium 风险，有明确缓解路径，非 blocker。

### 1.4 文档渲染引擎

gate-checklist.md 改为渲染产物（来源：requirements/REQ-2026-002/artifacts/requirement.md:135）。

**选型对比**：
- `Jinja2`：功能完整，支持循环/条件，项目当前无此依赖——quality-check 仅装 pyyaml ruamel.yaml（来源：.github/workflows/quality-check.yml:25）
- 裸 `str.format` / `str.replace`：zero-dep，适合简单占位符替换

gate-checklist.md 结构为"按门禁分组的 Markdown 表格/列表"，逻辑简单（遍历 registry.yaml 条目生成行），裸 Python 足够，不引入新依赖，与 D-002（registry 仅元数据，逻辑在代码，来源：requirements/REQ-2026-002/plan.md:64）一致。

**结论**：选裸 Python format，零新增依赖，可行。

### 1.5 registry schema 校验

**选型对比**：
- `jsonschema` 库：标准，支持 JSON Schema Draft 7，项目当前无此依赖
- 手写校验：与 check_meta.py / check_reviews.py 一脉相承（来源：scripts/lib/check_meta.py:1），无新依赖

现有 check_meta.py 和 save_review.py 均采用手写校验模式（来源：scripts/lib/save_review.py:1）。registry.yaml 的字段集约 9 个（来源：requirements/REQ-2026-002/artifacts/requirement.md:48），复杂度远低于 meta-schema.yaml。

**结论**：手写校验，与现有技术栈完全对齐，零新增依赖，可行。

---

## 2. 风险清单

| # | 类别 | 描述 | 可能性 | 影响 | 缓解策略 |
|---|---|---|---|---|---|
| R-1 | tech | 7 个 check adapter 行为偏移：check_reviews.py（270 行，7 个 R 规则，来源：scripts/lib/check_reviews.py:33）是最复杂的 adapter，其 R005 写回副作用（来源：scripts/lib/check_reviews.py:152）需配合事务化改造，adapter 化时逻辑边界容易错位 | high | high | 每个 adapter 对应独立 snapshot 行为契约测试；R005 单独覆盖"中途失败回滚""全过提交""单独 R005 失败"三路径；F-002 PR 合入前 normalize-stderr diff 必须为空（来源：requirements/REQ-2026-002/artifacts/requirement.md:122） |
| R-2 | tech | PreToolUse Hook Bash 写保护：macOS ps comm 字段 15 字符截断风险，以及正则需覆盖 `cat >`/`tee`/`echo >`/`python3 -c` 等多种写入模式，漏洞或误伤均可能发生 | medium | high | 白名单双轨（父进程链 + 环境变量）确保合法路径不被误伤（来源：requirements/REQ-2026-002/plan.md:96）；dry-run 模式跑一周（来源：requirements/REQ-2026-002/plan.md:42）；F-003 集成测试覆盖白名单和拦截场景 |
| R-3 | tech | 拓扑排序引入循环依赖死锁：registry.yaml 的 `dependencies` 字段写错形成环，graphlib 在加载期即报 `CycleError`，若无充分测试可能导致所有 gate 执行失败 | low | high | registry 加载期校验作为 `make gates-validate` 必跑项；CI 每次执行前先过 registry schema + 依赖图校验 |
| R-4 | business | H1/H3 缺口修复集中在 F-003，该 PR 改动范围最广（check_reviews adapter + submit flow 重定向），review 成本高 | medium | medium | F-003 单独覆盖 H1 事务回滚 + H3 同源校验 + H4 PR 状态闭环单元测试；F-003 合入前过 submit 和 next 两个 trigger 的 snapshot 对比 |
| R-5 | ops | audit log 文件膨胀：CI 全量扫描每次写 audit JSON（来源：requirements/REQ-2026-002/artifacts/requirement.md:103），高频 PR 期间单月 audit 文件可能超过 1000 个（按月分目录来源：requirements/REQ-2026-002/plan.md:82） | medium | low | audit/ 目录纳入 .gitignore 仅本地落盘；90 天保留期以 governance 工具（下一轮迭代）自动清理（来源：requirements/REQ-2026-002/plan.md:84）；当前周期 PR review 关注 audit/ 目录大小 |
| R-6 | tech | test fixture 维护成本：7 个 check adapter 各需 pass/fail/skip 三用例，加上 H1/H3/H4/H5 测试，fixture 总量约 30-40 个，与实际 meta.yaml / reviews/*.json 格式漂移时出现假通过 | medium | medium | fixture 使用实际项目文件（requirements/REQ-2026-001/）的快照而非手写桩；detail-design 阶段锁定 fixture 目录结构 |
| R-7 | security | escape_hatch 滥用：本轮不做 RBAC（来源：requirements/REQ-2026-002/plan.md:88），`CLAUDE_GATES_BYPASS=1` 无权限分级，主对话 Agent 若自行设置可绕过所有门禁 | low | medium | escape 必须带 `CLAUDE_GATES_BYPASS_REASON` 写入 audit log + process.txt（来源：requirements/REQ-2026-002/plan.md:100）；registry.yaml 的 escape_hatches 段是 PR review 焦点（来源：requirements/REQ-2026-002/artifacts/requirement.md:126） |

---

## 3. 工作量估算

**估算依据**：
- 现有 7 个 check 脚本均为 Bash 薄壳 + Python 核心结构（来源：scripts/check-meta.sh:1）（来源：scripts/check-reviews.sh:1）
- check_reviews.py 最复杂（270 行，7 个 R 规则，来源：scripts/lib/check_reviews.py:1）；其余 Python 核心约 100-200 行
- common.py 的 Report + Severity + exit_code 体系（来源：scripts/lib/common.py:1）已稳定，adapter 复用无需重设计
- REQ-2026-001 历史参考（来源：requirements/REQ-2026-001/artifacts/tech-feasibility.md:1）：类似复杂度任务约 1-1.5 天/功能模块

### F-001：runner 骨架 + 2 个 adapter（check-meta / check-index）

| 子任务 | design | dev | test | 合计 |
|---|---|---|---|---|
| scripts/gates/ 目录结构 + Gate 基类 + Plugin 接口定义 | 1 | 0.5 | 0.5 | 2 |
| registry.yaml schema + 加载器（含依赖图校验） | 0.5 | 1 | 0.5 | 2 |
| runner 核心：trigger 过滤 + 拓扑排序 + 事务包裹 + audit 写入 | 0.5 | 1.5 | 1 | 3 |
| check-meta adapter + check-index adapter | 0 | 0.5 | 0.5 | 1 |
| make gates-validate 入口 + normalize-stderr.sh | 0 | 0.5 | 0.5 | 1 |
| **F-001 小计** | **2** | **4** | **3** | **9** |

### F-002：全量 7 个 check adapter + CI/pre-commit/post-dev 切换

| 子任务 | design | dev | test | 合计 |
|---|---|---|---|---|
| check-sourcing / check-reviews / check-plan adapter（各约 0.5d dev） | 0 | 1.5 | 1.5 | 3 |
| post-dev-verify adapter（workspace-clean / task-file-exists） | 0 | 0.5 | 0.5 | 1 |
| traceability-gate adapter（Skill 调用封装） | 0 | 0.5 | 0.5 | 1 |
| 旧入口薄壳化（7 个 .sh 改写为 exec runner 的薄壳） | 0 | 0.5 | 0.5 | 1 |
| snapshot 行为契约测试（capture-baseline.sh + 7 个对比） | 0 | 1 | 1 | 2 |
| CI yml 简化（5 step → 1 step，来源：requirements/REQ-2026-002/artifacts/requirement.md:105） | 0 | 0.5 | 0.5 | 1 |
| **F-002 小计** | **0** | **4.5** | **4.5** | **9** |

### F-003：关闭 H1/H3/H4/H5

| 子任务 | design | dev | test | 合计 |
|---|---|---|---|---|
| H1 R005 事务化（stash/rollback + 单测三路径，来源：requirements/REQ-2026-002/plan.md:40） | 0.5 | 0.5 | 0.5 | 1.5 |
| H3 submit 与 next 同源（submit 调 run.py + snapshot 对比） | 0.5 | 0.5 | 0.5 | 1.5 |
| H4 PR 合并状态闭环（PR-status gate plugin + gh api） | 0 | 0.5 | 0.5 | 1 |
| H5 Bash 写保护（protect-branch.sh 扩展 + 正则 + 白名单 + audit） | 0.5 | 1 | 1 | 2.5 |
| **F-003 小计** | **1.5** | **2.5** | **2.5** | **6.5** |

### F-004：gate-checklist.md 渲染产物 + 旧入口删除

| 子任务 | design | dev | test | 合计 |
|---|---|---|---|---|
| render-docs.py（遍历 registry.yaml 生成 gate-checklist.md） | 0 | 0.5 | 0.5 | 1 |
| CI 校验 render --check diff 必空（来源：requirements/REQ-2026-002/plan.md:106） | 0 | 0.5 | 0.5 | 1 |
| 删除 7 个旧入口薄壳 + 更新 README/onboarding | 0 | 0.5 | 0 | 0.5 |
| **F-004 小计** | **0** | **1.5** | **1** | **2.5** |

### 汇总

| PR | design | dev | test | PR 合计 |
|---|---|---|---|---|
| F-001 | 2 | 4 | 3 | 9 |
| F-002 | 0 | 4.5 | 4.5 | 9 |
| F-003 | 1.5 | 2.5 | 2.5 | 6.5 |
| F-004 | 0 | 1.5 | 1 | 2.5 |
| **总计** | **3.5** | **12.5** | **11** | **27** |

[待补充]
- 内容：F-002 与 F-003 是否并行推进（双人配置），影响总工期约 4 天
- 依据：F-002 专注 adapter 化，F-003 专注缺口修补，两者在 F-001 合入后可并行启动
- 风险：并行时 F-002 的 check_reviews adapter 与 F-003 的 H1 R005 事务化存在同文件改动风险（check_reviews.py），需 rebase 协调
- 验证时机：task-planning 阶段根据团队配置决定

---

## 4. 前置条件

1. Python 3.9+（graphlib 标准库）：CI 固定 Python 3.11（来源：.github/workflows/quality-check.yml:22），本地开发环境需同版本
2. `scripts/gates/` 目录结构在 detail-design 阶段锁定（Plugin 基类接口、registry.yaml 字段集、audit JSON schema）；当前 9 字段候选集合为初稿，由 detail-design 定稿（来源：requirements/REQ-2026-002/artifacts/requirement.md:48）
3. H4 PR 合并状态闭环需要 `gh` CLI 已安装且 `gh auth status` 通过；CI 环境需要 `GITHUB_TOKEN`（来源：.claude/skills/managing-requirement-lifecycle/reference/submit-rules.md:107）
4. gate-checklist.md 初始渲染产物需在 F-004 第一步入库，CI render --check 校验（D-007，来源：requirements/REQ-2026-002/plan.md:106）才能生效

## 5. 阻塞项

无 blocker 级阻碍。

---

## 待澄清清单

1. macOS `ps -p $PPID -o comm=` 在 GitHub Actions macOS runner 容器中的行为（详见正文「1.3 Bash 写保护 / 进程链识别」段，含完整假设四要素）：容器中 PPID 可能为 1 导致父进程链判断失效；验证时机为 F-003 集成测试。
2. F-002 与 F-003 是否并行推进（详见正文「3. 工作量估算 · 汇总」段，含完整假设四要素）：影响总工期约 4 天，需用户确认团队配置后在 task-planning 阶段决定。
