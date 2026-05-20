# 20260519-context-usage-report · 工作笔记

## workflow 执行中遇到的 bug 记录（待后续处理）

以下问题在使用 `/workflow:run standard-8phase` 启动本需求 + `/workflow:continue` 推进 bootstrap-validate 节点时被触发。仅记录现象、复现路径、影响面与可能根因，**不在本需求中修复**——按用户要求等后续单独立项处理。

---

## F-006 code-review follow-up（用户接受 A 方案：先修 F-13+F-5 再转 done；其余 major 挂这里）

> **2026-05-20 收尾**：A 阶段重构 commit `7fbdf03` + B 阶段 minor commit `9e4e164` 已闭环以下 follow-up：
> - F-006-FU-1（拆模块 1881 → 8 模块）✅
> - F-006-FU-3（删 import pytest）✅
> - F-006-FU-M2 / M3 / M4 ✅
> - F-007-FU-1（classify 拆 5 助手）✅ / F-007-FU-2（_warnings 机制）✅ / F-007-FU-M2 ✅
> - F-008-FU-1（fetch_git_timestamps 拆 2 助手）✅ / F-008-FU-2（since 窗口 warning）✅
> - F-009-FU-1（aggregate 拆 2 助手）✅
> - F-010-FU-1（render_markdown 拆 5 _render_*_section）✅
> - F-011-FU-1（_run 拆 _scan_and_filter + _aggregate_summaries）✅ / F-011-FU m1 / m2 / m3 ✅
>
> 已确认无需修（A 重构后实测已干净）：F-007-FU-M1（# noqa 全角括号）
>
> **2026-05-20 收口（最终 3 条）**：commit `f726a6f` 闭环以下 3 条挂账（subagent sonnet 档位）：
> - **F-006-FU-2** ✅：`_scan_json_file` 抽 `_build_first_line_index(lines, targets) -> dict` 助手，复杂度 O(M×L) → O(L×T)（T = 唯一 target 数，早退 break），实测真机冒烟 reports/context-usage.md 字节级一致 732 行
> - **F-006-FU-M1** ✅：`_scan_json_file` 嵌套深度 5 → 4（与 FU-2 同源，抽助手即完成）；`_scan_json_values` 原本 ≤ 4 无需改
> - **F-006-FU-M5** ✅：`EvidenceScanner.scan` 用 `itertools.chain(rglob('*.md'), rglob('*.txt'), rglob('*.json'), rglob('*.yaml'), rglob('*.yml'))` 替代 `rglob('*')` + suffix 过滤；sorted 全集后顺序与改前一致，测试无回归
>
> **全 follow-up 收口**：本需求所有 F-006~F-011 系列 follow-up（含 3 条 algo/struct）已全部闭环，无遗留。

来源：`artifacts/review-F-006-20260520.md` + `reviews/code-F-006-001.json`，Judge 复核 F-13+F-5 fix（commit c17431b）通过，剩 3 major + 5 minor 留 F-007 之前一并清。

### F-006-FU-1：单文件 594 行 > 阈值 500（原 F-2 major）

- 位置：`scripts/lib/context_usage_report.py`
- 处置建议：拆 `evidence_scan.py` 子模块（_scan_text_lines / _scan_json_values / EvidenceScanner），原文件 re-export
- 优先级：F-007 起新 feature 仍在该文件继续累积，**应在 F-007 启动前先做拆分**

### F-006-FU-2：_scan_json_file 嵌套 O(M×L) 全行扫描（原 F-4 major）

- 位置：`scripts/lib/context_usage_report.py:570-577`
- 处置建议：用 dict 预扫一次 lines 构建 target→first_line 映射，O(L+M)
- 优先级：当前 requirements 规模不会触发，违反 detailed-design.md L812 性能目标 `<2s`；与 F-006-FU-1 同源 keep follow-up

### F-006-FU-3：tests/lib/test_context_usage_report_evidence_scanner.py:17 import pytest 未用（原 F-6 major）

- 处置建议：删 `import pytest` 行（ruff F401 会拦）
- 优先级：lint 红 → F-006-FU-1 拆模块时一并清

### F-006-FU 系列 minor（5 条）

- F-006-FU-M1：`_scan_json_file` 嵌套深度 5 > 阈值 4（与 FU-2 同源）
- F-006-FU-M2：`_resolve_url_to_context_rel` 内重复调 `repo_root.resolve()` syscall（context_usage_report.py:346,355）
- F-006-FU-M3：`_scan_json_values` 死参数 `source_rel` 从未消费（context_usage_report.py:435）
- F-006-FU-M4：`_RAW_PATH_RE` 注释 ".md 结尾" 偏离实际正则（.md/.txt/.yaml/.yml/.json）（context_usage_report.py:303）
- F-006-FU-M5：`rglob("*")` 后 suffix 过滤（context_usage_report.py:493，reviewer 自标 low priority）

---

## F-007 code-review follow-up（用户接受 A 方案：先修 G-11+G-4 再转 done；其余 minor 挂这里）

来源：`artifacts/review-F-007-20260520.md` + `reviews/code-F-007-001.json`，Judge 复核 G-11+G-4 fix（commit 4208d24）通过，剩 5 minor + 1 design 澄清留 F-008 之前一并清。

### F-007-FU-1：classify CC 偏高（原 G-2 major→minor）

- 位置：`scripts/lib/context_usage_report.py:707-790`
- 描述：classify 函数 84 行，嵌套 4 层（critic 实测，非 7）；与 F-006-FU-1 同源拆模块时一并处理
- 优先级：与 F-006-FU-1 合并处理

### F-007-FU-2：classify 2 处裸 except Exception 缺 _warnings 机制（原 G-5）

- 位置：`scripts/lib/context_usage_report.py:719,732`
- 描述：F-006 EvidenceScanner 有 `_warnings: list[str]` 机制（fail-open 可观测），F-007 AppliedSignalClassifier 未沿用；实测吞的异常源（Path.name / str.endswith / mask_code_blocks / _build_section_map）实抛错概率极低，但完全静默
- 建议：增加 `self._warnings: list[str]`，捕获后 append；与 EvidenceScanner 一致
- 与 F-007-FU-1 同源拆函数时一并处理

### ~~F-007-FU-3：路径 B 作用域 spec 歧义~~（**已解决 2026-05-20** commit b28860e）

- ~~设计层债务~~ → 已澄清为 `##` 二级小节级匹配（与路径 A 对称，符合 spec L48 保守原则）
- 实现：classify 路径 B 改为按 ref_section 切小节文本 + section=None 时跳过
- detailed-design.md §组件 4 路径 B 已补"作用域"段
- 测试：3 现有 + 2 新增（小节内命中 / 不同小节不命中）= 17 全 pass

### F-007-FU 系列其他 minor（2 条）

- F-007-FU-M1：`# noqa: E402（中文）` 全角括号注释（context_usage_report.py:610）—— 当前 ruff 不报，旧版本会 warn，建议改英文或挪到上一行
- F-007-FU-M2：UPGRADE_PHRASES frozenset 迭代非确定 → matched_keyword 跨运行可能不同（context_usage_report.py:316-319）—— 改 sorted 或 tuple

---

## F-008 code-review follow-up（用户接受 A 方案：rev2 修 F-4 后 looks_clean 转 done；其他 follow-up 挂这里）

### F-008-FU-1：fetch_git_timestamps 复杂度超线（rev2 后紧迫度上升）

- 函数 147 行 / 圈复杂度约 18（rev1 是 138 行/CC 17，rev2 加 timeout + TimeoutExpired catch + warning 微增 +9 行）
- 项目硬约束：80 行 / CC 10
- 根因：git log 输出协议适配（commit-header + file-path + exception 三分支同居一函数）
- 建议下个 feature 抽两个纯函数：
  - `_parse_git_log_output(output: str) -> dict[str, tuple[datetime, datetime]]`
  - `_build_timestamp_result(files, timestamps) -> dict[str, GitTimestamp]`
- 与 F-006-FU-1（文件 980 行拆模块）协同处理：先拆 module → 再拆 func

### F-008-FU-2：since 窗口内无 commit 文件静默回退 fs_mtime（design 一致性 + observability）

- 位置：`context_usage_report.py:196-203`
- 现象：git log 成功但某文件超出 `since_days` 窗口 → 静默 `source=fs_mtime, first_commit_at=None, last_commit_at=fs_mtime`，无 warning
- 与 subprocess 失败路径用户层无法区分
- design doc L763 异常表仅定义 subprocess 失败分支，未覆盖"窗口内无 commit"
- 建议二选一：(a) 补 design 异常表显式声明该分支为静默回退；(b) 在该分支聚合追加 `f"N 个文件在 since={D}d 内无 git 记录，已回退 fs_mtime"`
- 优先级：JSON 输出已含 `last_modified_at_source=fs_mtime` 信号，最终用户可辨；属可观测性增强

### F-009-FU-1：aggregate() 方法复杂度超线（与 F-006-FU-1 合并）

- 位置：`scripts/lib/context_usage_report.py:1072-1166` `UsageAggregator.aggregate`
- 指标：95 行 / 圈复杂度 CC=11 / 最大嵌套深度 5
- 项目硬约束：80 行 / CC 10 / depth 4
- 根因：单函数承担 4 件事——构建倒排索引 + 解析时间戳 + 评分 + 状态分类
- 建议抽取：
  - `_build_lookup_indexes() -> tuple[dict, dict]`（构建 ref_by_target / applied_by_target）
  - `_resolve_timestamps(file_refs, rel) -> tuple[datetime|None, datetime|None, datetime|None, Literal]`（解析 last/first_referenced_at + last_modified_at）
- 与 F-006-FU-1（整文件 1220 行拆模块）协同处理：先拆 module → 再拆 func
- 来源：F-009 review-F-009-20260520.md F-3 keep major，用户软确认 A 接受 follow-up

### F-010-FU-1：render_markdown 复杂度超线（合并 F-009-FU-1 渲染/聚合层重构）

- 位置：`scripts/lib/context_usage_report.py:1284-1398` `ReportRenderer.render_markdown`
- 指标：可执行 89 行（+warnings 段后约 96 行）/ 圈复杂度 CC≈12 / 嵌套深度 4
- 项目硬约束：80 行 / CC 10 / depth 4
- 根因：单方法承载 4 章节 + warnings 渲染（"总览 / 高价值知识 / 待治理知识 / 引用明细 / Warnings"）
- 建议抽取：
  - `_render_overview_section(summaries) -> list[str]`
  - `_render_high_value_section(summaries) -> list[str]`
  - `_render_to_review_section(summaries) -> list[str]`
  - `_render_reference_detail_section(summaries) -> list[str]`
  - `_render_warnings_section(warnings) -> list[str]`
- **与 F-009-FU-1（aggregate 拆分）+ F-006-FU-1（整文件 1496 行拆模块）合并为统一渲染/聚合层重构**
- 来源：F-010 review-F-010-20260520.md F-B keep major，用户软确认 A 接受 follow-up

### F-011-FU-1：_run 复杂度超线（合并 F-010-FU-1 / F-009-FU-1 渲染/聚合/调度层重构）

- 位置：`scripts/lib/context_usage_report.py:1728-1825` `_run`
- 指标：98 行 / 81 业务行（阈值 80）
- 根因：单方法承载 "校验 + 扫描 + 过滤 + 时间戳 + 聚合 + 渲染 + 标志检查" 7 个阶段；已抽 _check_dirs / _build_file_cache / _build_all_files_for_git / _render_and_write / _print_summary 5 helper，主体仍偏高
- 建议进一步抽：
  - `_scan_and_filter(args, warnings) -> tuple[list[KnowledgeFile], IndexGraphResult, list[ReferenceEvidence]]`
  - `_aggregate(files, graph_result, evidences, applied, timestamps, since_days, now) -> list[KnowledgeUsageSummary]`
- **与 F-010-FU-1 / F-009-FU-1 / F-006-FU-1 合并为统一渲染/聚合/调度/拆模块 refactor**
- 来源：F-011 review-F-011-20260520.md M3 keep major，用户软确认 A 接受 follow-up

### F-011-FU 系列 minor / drop（已被 critic + judge drop，仅备忘）

- F-A SEC-001 --project 路径穿越（drop，rel_path POSIX normalize 不命中含 `..` 攻击）
- F-B SEC-002 _build_file_cache evidence.source 路径穿越（drop，source 来自 rglob.relative_to 真实路径）
- F-C SEC-003/004 路径泄露 + --output 无边界（follow-up m2：本地 CLI 信任模型，文档补一句）
- F-D _parse_args 79 行（drop，声明式 CC=1）
- F-F 文件 1847 行（drop，累积债 F-006-FU-1）
- F-G _parse_since else 死代码（drop，防御性兜底）
- F-H import argparse 缺 noqa（drop，ruff `select=["F"]` 不报 E402）
- F-I --since exit 1 vs 设计 exit 1=argparse（drop，设计未禁止业务层复用）
- F-J 函数体内 from common import（drop，lazy import 避循环依赖）
- F-K file=sys.stdout 冗余（drop，风格 nit）
- F-L 测试 @staticmethod 装饰局部函数（follow-up m3：pytest 实测通过，可清理）
- F-M 测试函数体内 import（drop，pytest 常见 lazy 模式）
- F-N .tmp 名固定（drop，单进程单线程契约）
- F-O git log 路径过长（drop，250KB < ARG_MAX 1MB）
- F-P 双 stat()（drop，< 1ms）
- F-Q file_cache 无大小上限（drop，requirements/*.md < MB 级）
- F-R evidences 双遍历（drop，微优化）
- F-T BROKEN_LINKS_DETECTED 文案多 `ERROR:` 前缀（follow-up m1：CI grep 仍命中，文案对齐设计）
- F-U main 注释 exit code 2 vs 设计 exit 1 矛盾（drop，注释 nit，代码透传 argparse 正确）
- F-V main 无 catch-all 兜底（drop，Python CLI 标准透传）
- F-X _check_dirs 消息 "不存在或非目录"（drop，设计未要求字面一致）

---

### F-010-FU 系列 minor / drop（已被 critic + judge drop，仅备忘）

- F-A write 原子化（os.replace 失败 tmp 残留 / 多进程 .tmp 命名冲突）（drop，CLI 单次写不在并发契约内）
- F-C 文件 1496 行 + 测试 1419 行（drop，累积债，与 F-006-FU-1/F-009-FU-1 同源）
- F-E mkdir Raises docstring 不全（drop，OSError 已覆盖子类）
- F-F summaries 多次遍历（drop，5000 files 仍在 0.5s SLA）
- F-G render_json TypeError 文档（drop，受控类型不会触发）
- F-H history-context import 注释缩短（drop，事实陈述，F-010 仅删注释字符串无逻辑变更）
- F-I mid-file import 注释缺失（drop，与 F-009 drop 的 F-6 同模式）
- F-J WHAT vs WHY 注释（drop，章节 navigational marker）
- F-K JSON_SCHEMA_URL 占位常量（drop，设计 L413 自身已标 `[待补充]`）
- F-L `[:50]` 魔数（drop，一次使用命名收益低）
- F-M `patch('os.replace')` 路径（drop，当前 import os 写法下正确）
- F-N context_line 空字符串 → '... |'（drop，EvidenceScanner 保证非空）
- F-O Markdown `|` 注入（drop，context/** 受信任）
- F-P write 路径无边界（drop，main() 契约保证）
- F-Q JSON config 路径泄露（drop，设计 L574-580 schema 要求）
- F-R __init__ 设计文档未声明（drop，interfaces_frozen 不约束私有构造）
- F-S generated_at 类型严格（drop，now: datetime 非 Optional）
- F-T context_line JSON 不截断（drop，与 Markdown :50 分工）
- F-U history-context 文件高频变更 + 测试 import 交叉（drop，与 F-009 F-2 同模式）

---

### F-009-FU 系列 minor / drop（已被 critic + judge drop，仅备忘）

- F-5 UsageAggregator.__init__ 缺 Args docstring（drop，detailed-design.md L376-384 已逐字段说明）
- F-6 `from enum import Enum` 位于 L999 而非顶部（drop，L440/L774 已有 mid-file import per feature block 先例）
- F-7 `partial: dict` 裸类型（drop，私有方法内部 4-key dict 不必 TypedDict）
- F-8 私有方法形参名 `s` vs `summary_partial`（drop，interfaces_frozen 不约束私有方法形参）
- F-9 KnowledgeUsageSummary.index_paths 别名 IndexGraphResult.indexed_by[rel] list（drop，单线程纯计算下游不 mutate）
- F-10/F-11 future timestamp / naive datetime（drop，clock skew 极端边角 + 调用方契约保证）
- F-13 last_modified_at else 死代码（drop，契约保守化保留 defensive 回退）
- F-14 last_ref_at None → ACTIVE 文档（drop，与 design L898-901 伪码一致）
- F-15 test_aggregate_full_pipeline 85 行（drop，共享 fixture 拆分会复制）
- F-16 性能 SLA benchmark 缺失（drop，由 F-013 fixture 仓 / 集成测试承担）
- F-17/F-19 测试 import 分散 + 工厂函数缺 docstring（drop，feature 段集中 import 是文件既定风格）
- F-20 `[待用户确认]` 在源码注释（drop，ai-collaboration.md 约束范围仅 artifacts/*.md）
- F-21 per-loop dict 分配 + sort 冗余（drop，< 5ms 不命中 SLA + 不同维度排序）
- F-2 history-context 4 critical "F-009 紧跟 4 fix"（drop，事实陈述误判为 bug）

---

### F-008-FU 系列 minor / drop（已被 critic + judge drop，仅备忘）

- AUX-003：`(blank line)` 注释（drop，是 git log 输出格式字面示例）
- AUX-004：GitTimestamp 字段列对齐（drop，风格偏好）
- AUX-005：tests 内 import os（drop，fixture 惯例）
- AUX-006：source 字段注释信息量（drop，已含语义）
- PERF-003：output.split 全量物化（drop，规模 ≪ MB 级）
- PERF-004 / SEC-003：commit header `|` 判定歧义（drop，context/** 112 文件无 `|`）
- SEC-001：rel_path 路径穿越（drop，结构上不可能）
- SEC-002：CalledProcessError exc 泄漏（**已在 rev2 顺手收紧**，{exc} → {type(exc).__name__}）

---

### Bug-18：post-dev gate 在 GATE-SOURCING 非 strict 模式下也把 R-WARNING-ONLY 升为 exit 1（误报）

**触发**：F-006 完成后跑 `python3 scripts/gates/run.py --trigger=post-dev --req=20260519-context-usage-report`，stdout 显示 `Total: 0 error, 5 warning` 但 exit=1。

**现象**：audit 日志显示 `GATE-SOURCING` 被记为 failed，code=`R-WARNING-ONLY`，message 是 detailed-design.md L778 / outline-design.md L188 / review-F-002 L39 三处 W002/W003。3 处 warning 都是 **pre-existing 内容**，**不在 F-006 diff 内**（F-006 只动 `scripts/lib/context_usage_report.py` + 新建 test 文件）。

**根因猜测**：GATE-SOURCING 注册时 severity=error，但 `check_sourcing.py --strict` 才把 W 升为 error；非 strict 时仍报 Decision.FAIL（plugin 把"含 warning"视为 fail？）。audit.py `calc_exit_code` 按 registry severity (error) 判定 → exit=1。`strict 模式下视为失败` 这句 fix_hint 与实际行为不符。

**影响面**：所有 post-dev / submit / phase-transition 节点。即便本次 feature 没改设计文档，只要历史 design 文件存在 W002/W003，gate 就硬挡。

**workaround**：F-006 用 `--force-with-blockers "F-006 之外的 pre-existing W002/W003，不在本 feature diff 内"` 放行（exit=0）。

**根治建议**：要么 plugin 在非 strict 时不报 Decision.FAIL（只产生 warning report）；要么 runner 按 plugin 实际 decision 用 plugin 自身 severity；要么把这类 sourcing 校验从 post-dev 触发器移除（pre-commit/CI 仍保留）。

---

### Bug-2：bootstrap 时 meta.yaml `project:` 字段默认空，bootstrap-validate 必失败

**现象**

`/workflow:run standard-8phase` 写入的 meta.yaml 骨架中 `project:` 字段为空（带注释 `# 关联 context/project/<project>/`）。紧接着 `bootstrap-validate` 节点跑 `check_meta.py` 会失败：

```
❌ empty: 流程组字段 project 不能为空
```

**根因（推断）**

- `workflow_run.py` 的 meta.yaml 模板没有从 workflow yaml / project 上下文中推导 project 字段。
- `check_meta.py` 的 strict 模式不允许 project 为空。

**复现路径**

```bash
python3 scripts/lib/workflow_command_dispatcher.py run standard-8phase "Context 知识利用率统计机制" --slug=context-usage-report
# 进 worktree，跑 continue
python3 scripts/lib/workflow_command_dispatcher.py continue 20260519-context-usage-report
# → node_failed: bootstrap-validate / check_meta.py exit=1 (empty project)
```

**当前 workaround**

bootstrap 后手动编辑 meta.yaml，把 `project:` 改成 `project: agentic-meta-engineering`（或合法 project 名）。

**影响面**

- 所有走 standard-8phase 的新需求第一步都会卡 bootstrap-validate。
- 与 Bug-3 联动：失败后无法 retry，需要清理 jsonl 才能继续。

**建议修复方向**

两选一：
1. `workflow_run.py` 把当前活跃 project（context/project/<project>/ 单值时默认取它，多值时让用户选）写进 meta.yaml。
2. `check_meta.py` 在 bootstrap 阶段放宽 project 校验（毕竟模板还没填完整），到 definition 阶段切换时再强校验。

---

### Bug-4：「待确认清单」 vs 「待澄清清单」工具命名不一致

**现象**

阶段 2 推进时同时被两个工具吐警告/失败：

- `.claude/workflows/requirement/standard-8phase.yaml` 的 `req-artifact-check` 节点的 `must_contain_sections` 要求 `requirement.md` 含 `待确认清单` 章节。
- `scripts/lib/check_sourcing.py:52` 的 `RE_CLARIFY_HEADING = re.compile(r"^#{2,6}\s*待澄清清单?\s*$")` 只认 `待澄清清单`（W001 / W003 都看这个）。

文档无法同时只用一个章节名满足两个工具。

**复现路径**

- 改成 `## 待确认清单` → `req-artifact-check` 通过，但 `check_sourcing` 触发 W001「缺 '## 待澄清清单' 章节」。
- 改成 `## 待澄清清单` → `check_sourcing` 通过，但 `req-artifact-check` 报 must_contain_sections 失败。
- 同时保留两个章节 → 两个工具都过，但 P3 评审反馈正确指出「重复且语义混乱」。

**当前 workaround**

requirement.md 同时保留 `## 待确认清单` 与 `## 待澄清清单` 两个章节并显式说明「同义节，因工具命名不一致需要并存」。内容主要放在「待澄清清单」下（check_sourcing 看 list 项数）。

**影响面**

- 所有走 standard-8phase 的需求都会撞上这个矛盾。
- P3 评审反馈直接打到该问题——团队评审会反复出现「这两个章节为什么并存」的疑问。

**建议修复方向**

二选一统一命名：
1. 把 `standard-8phase.yaml` 中 `must_contain_sections: [..., 待确认清单]` 改成 `待澄清清单`，向 check_sourcing 对齐（推荐，影响面小：只改一个 yaml）。
2. 把 `check_sourcing.py:52` 正则改为 `r"^#{2,6}\s*待(澄|确认)清单?\s*$"`，向 yaml 对齐（影响面大：所有历史 requirement 已写 `待澄清清单` 的需要同步改）。

---

### Bug-5：phase-transition 节点强依赖 `yq` 但系统未安装且未在依赖文档中声明

**现象**

`req-confirm` approval 通过后，下一节点 `phase-to-tech-research`（以及所有 `phase-to-*` 节点）的 bash 脚本调用 `yq e ...` 失败：

```
bash: line 1: yq: command not found
```

`max_retries=3` retry 同样 fail（每次重试都是同样错），最终升级为 abort 阻塞 workflow。

**根因**

`standard-8phase.yaml` 多个节点（`phase-to-tech-research:184` / `phase-to-outline-design:271` / `phase-to-detail-design:347` / `phase-to-task-planning:466` / `phase-to-development:521` / `phase-to-testing:562` / `pr-submit:687` / `archive-finalize:712`）都用 `yq e '.field = "val"' -i "$META_PATH"` 来更新 meta.yaml。但仓库的 tool-chain 文档 / setup 脚本 / README 都未声明 `yq` 是硬依赖。

**复现路径**

走任何 `standard-8phase` 工作流，过完一个 phase 必撞。

**当前 workaround**

两条路（本次选 a）：

a) 用 Python + PyYAML 等价替代：写一个 `scripts/lib/meta_set.py`，参数语义 `--path meta.yaml --set .phase=tech-research --append .gates_passed=GATE-X`，然后逐个改 yaml 中所有 `yq e` 调用为 `python3 scripts/lib/meta_set.py`。

b) 手动 `brew install yq` / 在 README 声明依赖。

本次推进采用 c) 折中：临时直接 `python -c` 改 meta.yaml + 手动 `append_process.py`，让本节点的产物等价完成，然后写 node_completed 跳过 bash 调用（Bug-3 workaround 链）。

**影响面**

- 任何走 standard-8phase 的需求一过完 approval 阶段都会卡 `yq command not found`。
- 项目 onboarding 文档（`context/team/onboarding/agentic-engineer-guide.md` / `context/team/tool-chain.md`）未声明 yq 依赖 → 新人撞墙。
- 等 yq 安装到位也只是把 a / b 矛盾绕过，根因还是没在 setup 检查中声明。

**建议修复方向**

- 在 `context/team/tool-chain.md` 与 `Makefile gates-validate` 中加 `yq` 存在性检查；不存在则给出安装提示（macOS: `brew install yq`，linux: `apt-get install yq` / `pip install yq`）。
- 或：把所有 yaml 中的 `yq` 调用替换为 `scripts/lib/meta_set.py`（消除外部命令依赖，统一用 Python+PyYAML）。

---

### Bug-10：`task-frontmatter-check` 节点的 CLI 不支持目录扫描，但 yaml 传的是目录路径

**现象**

`task-decompose` 生成 `tasks/F-001.md ~ F-013.md` 后，`task-frontmatter-check` 节点立即失败：

```
schema_check 失败：scripts/lib/check_task_frontmatter.py 期望 exit=0 实际 exit=1
> 错误：task.md 文件读取失败：[Errno 21] Is a directory: '.../requirements/20260519-context-usage-report/artifacts/tasks'
```

**根因**

- `.claude/workflows/requirement/standard-8phase.yaml:487-490`：
  ```yaml
  schema_check:
    - script: scripts/lib/check_task_frontmatter.py
      args: [$ARTIFACTS_DIR/tasks/]
      expected_exit_code: 0
  ```
- 把目录 `$ARTIFACTS_DIR/tasks/` 当 arg 传给 CLI。
- `scripts/lib/check_task_frontmatter.py:325-345` 只接受单文件路径，无 glob / 目录扩展逻辑。

**复现路径**

走 standard-8phase 到 task-frontmatter-check 必撞。

**当前 workaround**

人工 `for f in tasks/*.md; do python3 scripts/lib/check_task_frontmatter.py "$f"; done` 逐个跑通过，再用 Bug-3 workaround 写 `node_completed`。

**建议修复方向**

- `check_task_frontmatter.py` 增加目录扩展：传入 Path 是目录时 rglob 该目录 `*.md` 逐个校验，聚合 exit code（任一失败 exit 1）；或
- yaml 改为 inline shell：`for f in $ARTIFACTS_DIR/tasks/*.md; do python3 ... $f || exit 1; done`（但 artifact schema_check 节点不支持 shell loop）。

推荐方案一（CLI 双模式：传文件 → 单文件校验；传目录 → 批量校验）。

---

### Bug-14：`dev-feature-loop` loop 引擎空转——50 次 iteration 全部 `loop_iteration_started → loop_iteration_completed`，从未真正派发 prompt 让 implementer 工作

**现象（最严重）**

阶段 7 进入 `dev-feature-loop` 节点后，单次 `/workflow:continue` 调用：

- jsonl 写入 50 组 `loop_iteration_started / loop_iteration_completed / loop_counter_advanced` 事件
- 末尾写 `loop_max_iterations_exceeded`（max_iterations=50 触发上限）
- 13 个 task.md 全部仍为 `status: pending`，**从未派过任何 implementer subagent**
- 也没有 `node_ready` 事件包含 `dev-feature-loop` 的 prompt 内容供 main Claude 消费

**根因（推断）**

`dev-feature-loop` 是 loop 节点（`.claude/workflows/requirement/standard-8phase.yaml:535-552`）：

```yaml
- id: dev-feature-loop
  loop:
    prompt_file: prompts/standard-8phase/development.md
    until: "ALL_FEATURES_DONE"
    max_iterations: 50
    fresh_context: false
    interactive: true
    gate_message: |
      ## Feature 第 $LOOP_ITERATION 轮已完成 ...
```

预期行为（按 yaml 字面意思 + skill 文档）：每个 iteration 派 prompt 给 Claude，Claude 调 `task-context-builder` + 派 implementer subagent + 等用户确认（`interactive: true`），收完 user 反馈再下一轮。

实际行为：loop 引擎只在内部空转计数器（看似已经"完成"了 50 个 iteration），从来没有：
- 写 `node_ready{prompt=development.md 内容, ...}` 等 Claude 接管
- 在 `loop_iteration_started` 之后停在 awaiting_claude_action 等用户/Claude 输入

可能 loop 节点 dispatcher 在 `interactive: true` 模式下没正确把控制权交给 Claude，而是把整个 prompt_file / gate_message 当 dispatch 模板自动 fire-and-forget 推进——但因为没有任何 outcome 写入（无 `loop_iteration_outcome` 事件），引擎判定每个 iteration "已完成"。

**复现路径**

走 standard-8phase 到阶段 7 dev-feature-loop 必撞。

**当前 workaround（重大决策点）**

三选一：

a) **手工逐 feature 派发**：跳过 loop 节点，对 13 个 feature 逐个：
   - 调 `task-context-builder` skill 取上下文
   - Agent 工具派 implementer subagent 写代码（fresh context）
   - 跑 `/code-review` scope=feature
   - 用户在主对话给软确认 → task.md status: done
   - 重复 13 次

b) **标 done 但不真实现**：13 个 task.md 全部改 `status: done` + 写空 receipt.json + Bug-3 workaround 写 dev-feature-loop node_completed。**结果：features.json 看似 all-done 但实际无代码、无测试、PR 提交时 GATE-POST-DEV-RECEIPT 会硬挡。**

c) **/workflow:save 暂存，移到独立 session 慢慢做**：保留当前状态 jsonl，用户另起会话逐个 feature 推进。

**影响面**

- 阶段 7 自动化完全失效，13 feature 全靠手工编排
- subagent-driven-development 的 happy path 不通过
- 单次需求开发体验从"loop 自驱"退化为"用户与 main Claude 来回交互"
- 与 Bug-15 联动：`dev-all-features-done-check` 也不工作

**建议修复方向**

- workflow loop 节点 dispatcher 需要：每个 iteration 第一次进入时写 `node_ready{prompt=..., loop_iteration=N}` 事件，把 state 转 `awaiting_claude_action`，等 Claude 调 `save_node_result.py --kind=skill_result --output={feature_done|continue|all_done}` 才推进或终止
- `until` 条件求值需要在 iteration 结束后真实检查 features.json all-done 状态，而不是无脑 +1 直到 max_iterations
- 单元测试覆盖：`interactive: true` 模式必须有"awaiting_claude_action between iterations"用例

---

### Bug-12：`task-list-summary` 节点使用未注入变量 `$LOG_DIR`，bash 解释为空导致写根目录

**现象**

```
node_failed task-list-summary
error: bash: line 1: /task-count.txt: Read-only file system
```

**根因**

- `.claude/workflows/requirement/standard-8phase.yaml:496` `ls $ARTIFACTS_DIR/tasks/*.md | wc -l > $LOG_DIR/task-count.txt`
- `$LOG_DIR` 变量在整个 workflow framework 中**没有定义**（`grep -rn "LOG_DIR" scripts/lib/workflow_run.py .claude/workflows/` 只命中此 yaml 一处）。
- bash 解释 `$LOG_DIR` 为空字符串，命令展开为 `... > /task-count.txt` 试图写根文件系统。

**复现路径**

走 standard-8phase 到阶段 6 task-list-summary 必撞。

**当前 workaround**

手工跑：`ls tasks/*.md | wc -l` 然后 Bug-3 workaround 写 node_completed。

**建议修复方向**

要么 workflow runner 注入 `$LOG_DIR`（如 `requirements/<id>/logs/`），要么 yaml 改用已有变量（如 `$ARTIFACTS_DIR/.log/` 或 `runs/<id>/`）。需要先 ADR 决定 logs 落点。

---

### Bug-13：`task-list-summary` 节点引用的 `scripts/lib/summarize_tasks.py` 不存在

**现象**

即使 Bug-12 修了 `$LOG_DIR`，第二条命令 `python3 scripts/lib/summarize_tasks.py $ARTIFACTS_DIR/tasks/` 也会失败：

```
$ ls scripts/lib/summarize_tasks.py
ls: scripts/lib/summarize_tasks.py: No such file or directory
```

**根因**

- `.claude/workflows/requirement/standard-8phase.yaml:497` 引用了不存在的脚本，与 Bug-7（`append_process.py`）同性质。
- yaml 节点定义未做"脚本存在性预检"。

**复现路径**

走 standard-8phase 到 task-list-summary 节点（Bug-12 修复后也会撞）。

**当前 workaround**

直接跳过该命令，统计信息（13 个 task / 总工作量 44h ≈ 5.5 天）已经在 features.json 内有。Bug-3 workaround 写 node_completed。

**建议修复方向**

二选一：

1. 新增 `scripts/lib/summarize_tasks.py`，参数 `<tasks_dir>`，输出 `total / by_complexity / by_status` 摘要到 stdout。
2. 删 yaml 第 497 行 + 修 Bug-12 后只保留 `ls | wc -l` 的统计需求。

---

### Bug-11：`feature-task.md.tmpl` 缺 `schema_version` 字段，与 `task-frontmatter-schema.yaml` 必填项不一致

**现象**

补完 Bug-10 后，逐个跑 `check_task_frontmatter.py tasks/F-001.md` 报：

```
错误：F-001.md frontmatter 缺必填字段 schema_version
```

但项目模板 `.claude/skills/feature-lifecycle-manager/templates/feature-task.md.tmpl` 中**没有 `schema_version` 字段**。

**根因**

- `context/team/engineering-spec/task-frontmatter-schema.yaml:32` `required_fields` 含 `schema_version`，docstring 注释「ADR（F-003）：schema_version 列为 required（不软兼容缺失）。迁移：F-007 派发模板改造时统一给所有 task.md 注入 schema_version: "1.0"。」
- `feature-task.md.tmpl` 至今没注入 schema_version 字段——F-007 派发模板改造未完成或漏了 task 模板。

**复现路径**

走 standard-8phase 走到 task-frontmatter-check + 已修 Bug-10 后必撞。

**当前 workaround**

`task-decompose` skill 渲染 task.md 时手工注入 `schema_version: "1.0"`，或直接修模板。

**建议修复方向**

`.claude/skills/feature-lifecycle-manager/templates/feature-task.md.tmpl` 第 1 行后加 `schema_version: "1.0"`；并加测试 fixture 覆盖。

---

### Bug-9：`features-json-generate` 节点 prompt 描述的 schema 与 `check_features.py` / `features-schema.yaml` 实际期望严重不一致

**现象**

`features-json-generate` 节点的 prompt 给的 schema 模板是：

```json
{
  "features": [
    { "id": "feat-001", "acceptance_criteria": [...], "estimated_hours": 8, "depends_on": [...] }
  ],
  "total_features": ..., "total_estimated_hours": ...
}
```

但下游 `detail-design-artifact-check` 节点调 `python3 scripts/lib/check_features.py` 对 features.json 做 schema_check，schema 来自 `context/team/engineering-spec/features-schema.yaml`，实际期望：

- 顶层必填：`schema_version: "1.0"` / `requirement_id` / `features`
- feature.id：`^F-\d{3}$`（不是 `feat-NNN`）
- 字段名是 **`acceptance`**（不是 `acceptance_criteria`）
- 必填 `modules` (list) / `depends_on` / `depends_on_features` / `complexity` / `touches`
- complexity 枚举：`trivial / light / medium / heavy`（不是 `low / medium / high`）
- 字段是 **`estimate_days`**（不是 `estimated_hours`）
- 顶层**不需要** `total_features` / `total_estimated_hours`

按 prompt 写出来的 features.json 100% 撞 schema_check 失败：

```
features[12].acceptance 必填，当前缺失
features[12].id 值 'feat-013' 不符合正则 ^F-\d{3}$
features[12].complexity 值 'low' 不在枚举 ['trivial', 'light', 'medium', 'heavy'] 内
```

**根因**

`features-json-generate` 节点的 prompt 在 `.claude/workflows/requirement/standard-8phase.yaml:366-392` 是**手写示例**，没有引用 `features-schema.yaml` 作为唯一事实源，导致 prompt 与 schema 漂移。

**复现路径**

走任何 standard-8phase 流程到阶段 5 `features-json-generate` → `detail-design-artifact-check`。

**当前 workaround**

照 schema 真实定义手写 features.json：id 用 `F-NNN`、字段名 `acceptance` / `estimate_days` / `modules` / `touches`、加 `schema_version` / `requirement_id` 顶层、complexity 用 `light/medium/heavy`，删除 `total_features` / `total_estimated_hours`。

**影响面**

- standard-8phase 阶段 5 必踩。
- 评审 agent（detail-design-quality-reviewer）也读 prompt 写的字段 schema 给反馈，建议补 `complexity / interfaces_frozen / touches`——其中 complexity 又把枚举推回错的（reviewer 自己也不知道真 schema）。
- prompt 与 schema 不同步，新人完全没法照 prompt 一次性写对。

**建议修复方向**

`standard-8phase.yaml:366-392` 的 prompt 改为：

1. 直接引用 `context/team/engineering-spec/features-schema.yaml` 作为唯一 schema 来源（让 AI 读文件）；或
2. 把 schema 的字段表 + 枚举 + 正则直接 inline 进 prompt（保持 yaml 自包含但要与 schema 同步更新）。

无论哪种都需要在 `features-schema.yaml` 改动 PR 中加一道 CI 检查：grep yaml 中的 prompt 是否含已废弃字段（如 `feat-NNN` / `acceptance_criteria` / `estimated_hours` / `total_features`）。

---

### Bug-7：`standard-8phase.yaml` 所有 `phase-to-*` 节点引用的 `scripts/lib/append_process.py` 不存在

**现象**

执行 `phase-to-outline-design` 节点 bash workaround 时：

```
$ python3 scripts/lib/append_process.py "phase-transition: tech-research → outline-design"
can't open file '<repo_root>/scripts/lib/append_process.py': [Errno 2] No such file or directory
```

**根因**

`.claude/workflows/requirement/standard-8phase.yaml` 多个节点调用 `python3 scripts/lib/append_process.py "..."`：

- `phase-to-tech-research:187`
- `phase-to-outline-design:274`
- `phase-to-detail-design:350`
- `phase-to-task-planning:468`
- 等等

仓库实际只有 `scripts/lib/submit_codex.py:_append_process_event` / `scripts/lib/archive_runner.py:_append_process_event` 两个**模块内部函数**，没有公开 CLI 脚本 `append_process.py`。yaml 这些 bash 调用永远会 exit=2（file not found），整条 phase 切换 bash 会 `set -e` 中断。

**复现路径**

1. 任意走 standard-8phase 流程到 phase-to-* 节点。
2. 即便 yq 已装好，`set -e` 在 append_process.py 调用上 fail。
3. → `node_failed` → 触发 Bug-3 卡死链。

**当前 workaround**

直接 `echo "$(date '+%Y-%m-%d %H:%M:%S') phase-transition: tech-research → outline-design" >> requirements/<id>/process.txt`，等价补齐语义事件追加。

**影响面**

- 与 Bug-3 / Bug-5 联动：任何走 standard-8phase 的需求过完 approval 阶段都会双重撞墙（yq 缺 + 脚本缺）。
- phase-to-tech-research 此前那次 jsonl 写的 `manual-equivalent: ... (Bug-5 workaround)` 实际暗含本 bug — 当时被归到 Bug-5 名下，但根因独立。

**建议修复方向**

二选一：

1. 新增 `scripts/lib/append_process.py`，参数 `<event_line>`，写当前需求 `requirements/<id>/process.txt`；run_id 通过 cwd 或 env `$RUN_ID` 推断。复用 `submit_codex._append_process_event` 逻辑封装成 CLI。
2. 把所有 `phase-to-*` 节点的 bash 改成 `echo "$(date '+%Y-%m-%d %H:%M:%S') ..." >> "$PROCESS_PATH"`，并在 workflow runner 注入 `$PROCESS_PATH` 变量。

方案 1 优先（与 `requirement-progress-logger` Skill 语义同源、可扩展事件类型校验）。

---

### Bug-6：`/workflow:status` 把 failed 节点也算进 "completed (N)" 计数与列表

**现象**

phase-to-outline-design 已经写过 `node_failed`（无 `node_completed`），但 `workflow_command_dispatcher.py status` 输出：

```
state:        running
current_node: (none)
completed (11): bootstrap-validate, req-input-normalize, req-draft, req-quality-review, req-artifact-check, req-confirm, phase-to-tech-research, tech-feasibility-assess, tech-research-artifact-check, tech-research-confirm, phase-to-outline-design
```

把 failed 节点（phase-to-outline-design）列入 `completed`，与 jsonl 事件语义不一致；并且不打 failed 列表 / running 列表，用户看不出哪个节点是失败状态。

**根因（已定位）**

`scripts/lib/workflow_status.py:47`

```python
completed = list(run_state.node_outputs.keys())
lines.append(f"{prefix}completed ({len(completed)}): {', '.join(completed) or '(none)'}")
```

直接列出 `node_outputs.keys()`，没按 `entry.state` 过滤。同文件 `_compute_terminal_ids`（line 101-110）已存在 done/failed 区分逻辑，但 plain 文本输出未复用。

**复现路径**

1. 任意节点写过 `node_failed`，没有后续 `node_completed`。
2. 调 `python3 scripts/lib/workflow_command_dispatcher.py status <run_id>`。
3. 失败节点会被混入 "completed (N)" 列表。

**当前 workaround**

人工核对 jsonl 末位事件类型（`tail -1 run-state.jsonl`）判断真实状态，不信任 status 的 completed 列表。

**影响面**

- 用户根据 status 判断阶段进度时被误导（"明明 11 个 completed 了，为什么 continue 不动？"——其实最后一个是 failed）。
- 主 Agent 在 Bug-3 卡死场景下读 status 也会误判，可能错过重派窗口。

**建议修复方向**

`workflow_status.py:_format_state_plain` 改为按 state 分三桶输出：

```
completed (N): <only state == "completed" / "skipped">
failed    (M): <state == "failed">
running   (K): <state == "running">
```

或直接复用 `_compute_terminal_ids` 的 done/failed 切分。tests 需补一个 fixture：jsonl 含 node_failed 末位 → status 输出 failed 列表非空。

---

## 临时决定

- 本需求继续推进时，对**剩余 10 个 Bug**（Bug-2 / 4 / 5 / 6 / 7 / 9 / 10 / 11 / 12 / 13）继续采用上文记的 workaround，不在本需求范围内修复。
- 收尾阶段把这十个 bug 升级为后续独立需求处理（建议各开一个 REQ）。
- ~~**Bug-14（dev-feature-loop 空转）属于阶段 7 自动化失效的根本性问题**~~ → 已修，commit `4117380`，见下方"已修 Bug 索引"。
- 已知次生 bug：**rollback 不识别 `.claude/workflows/<name>.yaml`**，只查 `run_dir/workflow.yaml` 及 1-3 层父目录。本次 rollback 用 `requirements/<id>/workflow.yaml -> ../../.claude/workflows/requirement/standard-8phase.yaml` 软链兜底；建议未来在 `workflow_rollback_topology._find_workflow_yaml` 加 `.claude/workflows/**/<workflow_name>.yaml` 兜底（workflow_name 从 jsonl `workflow_started` 事件读）。

### 大测试文件按 feature 拆分准则（F-013 复核 F-1 沉淀）

来源：F-013 code-review 复核 F-1（test_context_usage_report.py 2012 行 > 500），subagent 拆分实践 commit `3c310a6`。供后续大文件拆分参考。

**触发条件**：单测试文件超 500 行 / 跨 ≥ 3 个 feature / grep / 定位耗时 > 30 秒。

**拆分原则**：

1. **按 feature 一对一映射**：原文件 `test_X.py` 跨 feat F-A/B/C/D → 拆 `test_X_A.py` / `test_X_B.py` / ... 主文件仅留入口（如 CLI / main）
2. **fixture 共享通过 conftest.py**：跨子文件复用的 fixture（`tmp_path` 工厂 / `_FIXTURE_REPO` 常量 / `git_repo` 仓库构造器）抽到 `tests/lib/conftest.py`
3. **辅助函数走 `_helpers.py`**：纯函数式辅助（如 `_make_file` / `_make_evidence` 工厂）抽到 `tests/lib/_helpers.py`（前缀 `_` 防 pytest 误收）
4. **保持各文件 < 500 行**：拆完每个子文件目标 200-450 行；超过仍要继续按子主题拆
5. **保持 import 风格一致**：sys.path 注入逻辑放各子文件顶部（不要共享到 conftest.py，避免测试间隐式依赖）
6. **测试函数命名前缀**：`test_<feature_id>_<scenario>` 便于 grep 反查归属（如 `test_aggregate_full_pipeline` → `test_F009_aggregate_full_pipeline` 可选）

**硬约束（拆分时守门）**：

- pytest 全量测试数 = 拆分前；不增不减（除非显式说明新增哪几个）
- ruff 全绿
- 不修改任何 production code（拆分仅是测试组织，不应触发实现层差异）

**典型拆分映射**（F-013 实例）：

| 拆出文件 | 来源 feature | 行数 |
|---|---|---|
| test_context_usage_inventory.py | F-004 | 141 |
| test_context_usage_git_timestamps.py | F-008 | 258 |
| test_context_usage_aggregator.py | F-009 | 463 |
| test_context_usage_renderer.py | F-010 | 403 |
| test_context_usage_e2e.py | F-013 (e2e + perf) | 255 |
| test_context_usage_report.py（保留）| F-011 CLI / main | 435 |

主文件由 2012 行 → 435 行（-78%）；分散 6 子文件后任一文件 < 500，命中阈值。

---

### 2026-05-19 会话：6 处框架修复已 commit 落盘（Bug-1 / 3 / 8 / 15 / 16 / 17）

为让本需求 dev-all-features-done-check + dev-feature-loop + /code-review + 主仓直跑 continue 跑通，外科手术式修了 6 处工作流引擎层 bug 并落 commit。修完即从上文"待处理"段拿掉（按"修了就取消"约定），下方仅留 commit 索引供回溯：

| 已修 Bug | commit | 一句话 |
|---|---|---|
| Bug-3（retry 不持久化） | `714e78d` | `_handle_retry` 写 `node_retried` 事件 |
| Bug-8（prompt_file 路径基准错位） | `714e78d` | `_dispatch_prompt_node` 接 `_resolve_prompt_file` resolver |
| Bug-15（check_features --all-done） | `714e78d` | `check_features.py` 加 `--all-done` 标志扫 tasks frontmatter |
| Bug-16（loop_done 不写 node_completed） | `714e78d` | `_dispatch_loop_node` 两条 loop_done 路径补 `node_completed` |
| Bug-17（routing.py req-id 旧格式） | `140a8b8` | `code_review_routing.py` 接受 D-013 双格式 req-id |
| Bug-1（continue 不感知 worktree） | `019922b` | main 入口：未传 run_id 且当前非 feat/req-* 分支时扫 `git worktree list` 找活跃 worktree，单个 chdir+execv 切入，多个列出供选 |
| Bug-14（dev-feature-loop 空转） | `4117380` | `_dispatch_loop_node` 新增 interactive 分支：每轮写 `node_ready{loop_iteration, prompt, contract}` → `awaiting_claude_action`；闭环靠 `save_node_result --kind=loop_iteration --output={"outcome":"continue"\|"all_done"}`（continue 时附 `loop_counter_advanced`）；rebuild 把 `loop_iteration_completed` 从 awaiting 拉回 running；development.md 加调用指引；13 新单测 + 全量 1691 pass |

一次性恢复：本需求 `dev-all-features-done-check` 在 Bug-3 修复前留下了无 node_retried 的卡死状态，jsonl 末尾手工 `append_event` 补了一条 `{type: node_retried, ..., data: {manual_recovery: True}}` 才能让 continue 走通。后续可考虑封 `scripts/lib/workflow_recover_retry.py` 自动化恢复"末位 node_failed + 无后续 node_retried 且 fail_count < max_retries"场景。

已知遗留：`tests/skills/test_workflow_dispatcher_bash_skill_prompt.py::test_prompt_node_prompt_file_reads_and_renders` 单测因 Bug-8 修复（`_resolve_prompt_file` shim）失败——该测试此前依赖旧错误路径 `root/prompt_file`，需另起任务更新断言适配新 resolver 语义。

测试：相关 56 + 29 用例（loop dispatcher / loop_until / retry handler / check_features / continue main loop / code-review routing）全 pass。

PR 拆分建议：714e78d + 140a8b8 是工作流引擎修复，与本需求 13 个 feature 业务实现解耦。若开 PR 时希望按 commit 拆分 review，可在 PR 描述里强调"按 commit 看：F-001~F-N 是功能实现，714e78d / 140a8b8 是独立的引擎修复"——保留单 PR 也可，需要时按 commit cherry-pick 到 hotfix 分支无依赖。

---

## 阶段 4 概要设计起草完成（2026-05-19）

- 产出：`requirements/20260519-context-usage-report/artifacts/outline-design.md`（4 章节：架构方案 / 模块划分 / 技术选型 / 关键流程）
- 影响模块与 `tech-feasibility.md §影响模块` 一致，未新增模块。
- 状态分类规则、评分规则、异常回退策略已细化到伪代码 / 表驱动级别；接口签名、SQL、features.json、测试用例留阶段 5 / 8。

### 阶段 4 留下的待确认项

1. **`high_value` 阈值 `reference_count >= 3`**：是否合适，或改为 `>= 2`？仅一次窗口命中是否足够进入高价值名单？[待用户确认]
2. **`applied_signal_count` 是否在 JSON 报告中保留原始 count**：当前评分已封顶 40，语义上 count 本身不封顶。是否保留用于后续趋势分析？[待补充]

> 第 3 项「code block mask 抽公共模块」已在评审反馈后收敛为「Phase 3 治理入口落地后复盘」，不再作为开放待确认（详见 outline-design.md §待确认）。

### 阶段 5 详细设计起草完成（2026-05-19）

- 产出：`requirements/20260519-context-usage-report/artifacts/detailed-design.md`（4 章节：接口签名 / 数据结构 / 时序图 / 异常处理）
- 6 个组件全部给出 Python class / function 签名 + docstring + 入参约束 + 幂等性说明
- 8 个数据类字段表（MarkdownLink / KnowledgeFile / ReferenceEvidence / AppliedEvidence / BrokenLink / GitTimestamp / KnowledgeStatus / KnowledgeUsageSummary）
- 4 张 mermaid 时序图（主路径 + 3 条异常路径）+ 1 张状态分类流程图
- 评分函数与状态分类函数已给出可直接编码的伪代码
- 单测覆盖矩阵 TC-1 ~ TC-8 已给（阶段 8 落地）

### 阶段 5 留下的待确认项

1. **`HIGH_VALUE_REFERENCE_MIN = 3`**：与阶段 4 同款 [待用户确认]，未变。
2. **JSON `$schema` URL**：MVP 暂留字段位，不强制要 schema 文件。[待补充]
3. **是否保留原始 `applied_signal_count`（不封顶 40）**：当前设计已保留（score 封顶 ≠ 字段封顶），延续阶段 4 决议。

### 阶段 5 评审反馈应对（detail-design-quality-reviewer · 2026-05-19）

reviewer verdict = `approved`（5 个 minor issue 均不阻断），5 项已逐条应对：

| # | reviewer 建议 | 应对 |
|---|---|---|
| 1 | AppliedSignalClassifier.classify docstring 未声明对 markdown_links 的内部依赖 | docstring 增「内部依赖」段，明确依赖 mask_code_blocks + extract_headings |
| 2 | ReportRenderer.write 接口签名与幂等性章节对原子写表述不一致 | write docstring 写明「原子写：tmp + os.replace」，与异常处理章节统一 |
| 3 | KnowledgeUsageSummary.last_referenced_at 语义表述略绕 | 改为「所有引用本文件的 requirements 源文件中 last_commit_at 的最大值」 |
| 4 | features.json feat-009 acceptance_criteria 未提 6 个入参 wiring 校验 | 追加一条 acceptance：6 个入参串联校验 |
| 5 | features.json 缺机读派发字段（complexity / interfaces_frozen / touches） | 13 个 feature 全部补齐：feat-006/007/009 为 medium，其余 low；interfaces_frozen=true；touches 显式列出修改文件 |

### 阶段 4 评审反馈应对（outline-design-quality-reviewer · 2026-05-19）

reviewer verdict = `approved`（4 个 minor issue 均不阻断），4 项均已在 outline-design.md 内修复：

| # | reviewer 建议 | 应对 |
|---|---|---|
| 1 | 状态判定优先级未说明 high_value vs stale_candidate 取舍 rationale | outline-design.md §状态流转 加「优先级 rationale」段，明确高价值优于时效 |
| 2 | Mermaid 图缺 `EVD --> APP` 边，图文不一致 | 图中追加 `EVD --> APP` 依赖 |
| 3 | 边界章节未明示 `.gitignore` `reports/` 一行的 AC-08 豁免边界 | 边界章节新增条目，引用 requirement.md:170 / tech-feasibility.md R-04 |
| 4 | code block mask 抽公共模块的收敛时机悬置 | 改成「Phase 3 治理入口落地后复盘」，明确触发条件 |
