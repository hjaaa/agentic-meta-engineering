# lint 规则要区分 spec 类与衍生文档

**沉淀原因**：跨需求会重复（任何新增 lint 规则都涉及）、跨会话需保留（lint 设计原则）。

## 问题

REQ-2026-003 testing 阶段 CI `--strict` 报 17+ W002（数字断言缺三态标记），分布广：

- 设计 spec 文档：`detailed-design.md`（2 处）✅ 应该报
- 任务清单：`tasks/F-002.md / F-003.md / F-004.md`（4 处）❌ 误报
- 评审报告：`review-20260501-*.md`（5 处）❌ 误报
- 历史回顾：`retrospective.md`（4 处）❌ 误报
- 测试报告：`test-report.md`（隐含）❌ 误报

`tasks/*.md` 的"必须 done + 数字"等表述是**复述上游 features.json**；`review-*.md` 的"必修 N critical"是**已 sign-off 的评审结论**；`retrospective.md` 是**回顾性叙述**——这些数字断言的来源**不在自己**，强制要求"`（来源：xxx）` 三态标记"是把 spec 类规则误用到衍生类文档。

修这些会触发 R005 hash drift（review-tracked 文件改动失效已 signoff verdict），需要逐个重审重 signoff——churn 数倍于实际价值。

## 根因

W002 的设计意图是抓"spec 文档里的幻觉数字"——刨根问底要求**每条强约束必须可追溯到上游来源**。但 lint 规则没区分文档**性质**：

- **spec 类**（requirement / outline-design / detailed-design / tech-feasibility / plan）：规则的源头，必须有 source citation
- **衍生类**（tasks / reviews / retrospective / test-report）：上游 spec 的派生物，源头追溯由上游负责

在所有 .md 上无差别施加 W002 = 让衍生文档为上游负责，违反"溯源到源头"原则。

## 解法

**lint 规则按文档性质分层**：

1. 在 `scripts/lib/check_sourcing.py` 加白名单常量：
   ```python
   W002_DERIVED_FILENAME_PATTERNS = (
       re.compile(r"^review-\d{8}-\d{6}\.md$"),
       re.compile(r"^retrospective\.md$"),
       re.compile(r"^test-report\.md$"),
   )
   W002_DERIVED_PARENT_DIRS = ("tasks",)
   ```

2. 在 W002 检查头部短路：
   ```python
   if _is_w002_exempt(md_file):
       return  # 衍生文档豁免 W002
   ```

3. 配单测：spec 类仍触发 W002 / 衍生类不触发（`tests/gates/test_sourcing_plugin.py`）

4. **新增 lint 规则时必问**：本规则的源头追溯责任在哪里？只对该层文档施加，不向下游 derived 文档传递。

## 验证方法

- `tests/gates/test_sourcing_plugin.py::test_sourcing_exempts_w002_for_review_files / test_sourcing_exempts_w002_for_tasks_files`：衍生文档不触发
- `tests/gates/test_sourcing_plugin.py::test_sourcing_still_emits_w002_for_design_spec`：spec 类仍触发
- `python3 scripts/gates/run.py --trigger=ci --strict` 全仓跑：spec 文档红 / 衍生文档绿

## 引用来源

- `scripts/lib/check_sourcing.py:46-67`（豁免常量 + `_is_w002_exempt`）
- 单测：`tests/gates/test_sourcing_plugin.py`（3 个新用例）
- commit `e8fa757`（PR #48 修复落地）
