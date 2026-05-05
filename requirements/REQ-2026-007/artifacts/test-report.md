# Test Report — REQ-2026-007

**需求**：submit Codex review-loop + archive 命令
**执行时间**：2026-05-05T08:47:53Z
**测试命令**：`python3 -m pytest tests/ -q --tb=short`
**执行分支**：feat/req-2026-007（commit 5617f3a 基础上）

---

## 1. 执行摘要

| 维度 | 数量 |
|---|---|
| 全量用例（pytest） | 577 |
| passed | 569 |
| failed | 0 |
| skipped | 8 |
| 覆盖估算 | ~90%（4 features 全部有对应自动化用例） |

skipped 说明（均与本需求无关）：

- `test_argparse_double_dest_python_311_312`：Python 版本条件跳过（本机 3.14）
- `test_code_review_prepare_routing::test_tc_a1~a7`（7 条）：tty 检测跳过，已有独立机制保障

---

## 2. 按 Feature 分组小计

| Feature | 测试文件 | 用例数 | passed | failed | skipped | AC 映射 |
|---|---|---|---|---|---|---|
| F-001 门禁放宽 + --draft | test_ahead_of_origin.py / test_review_verdict.py | 7 | 7 | 0 | 0 | TC-F1-1~7 全覆盖 |
| F-002 completed + list 过滤 | test_list_filter.py | 5 | 5 | 0 | 0 | TC-F2-4~7 全覆盖；TC-F2-1~3 文档类（见下） |
| F-003 archive 命令链 | test_archive.py | 13 | 13 | 0 | 0 | TC-F3-1~7 全覆盖 |
| F-004 submit --codex + V-09 | test_submit_codex.py | 18 | 18 | 0 | 0 | TC-F4-1~7 + V-09 全覆盖 |
| **全量回归** | tests/gates + tests/lifecycle + tests/agents + tests/lib + tests/integration | 577 | 569 | 0 | 8 | — |

---

## 3. AC 一对一映射表

### F-001

| TC | 用例名 | 结果 |
|---|---|---|
| TC-F1-1 | test_skip_when_pr_open | PASSED |
| TC-F1-2 | test_no_skip_when_pr_closed | PASSED |
| TC-F1-3 | test_fail_closed_when_gh_missing | PASSED |
| TC-F1-4 | test_fail_closed_when_gh_unauth | PASSED |
| TC-F1-5 | test_skip_on_draft_submit | PASSED |
| TC-F1-6 | test_no_skip_on_phase_transition_with_draft | PASSED |
| TC-F1-7 | test_no_skip_when_draft_unset | PASSED |
| TC-F1-8 | V-01 沙盒 e2e | manual/pending |
| TC-F1-9 | V-06 历史需求回归 | manual/pending |

### F-002

| TC | 验收内容 | 结果 |
|---|---|---|
| TC-F2-1 | phase-rules.md 第 9 行 completed 存在 | 文档检查（不阻塞） |
| TC-F2-2 | phase-rules.md archived_at 字段说明段 | 文档检查（不阻塞） |
| TC-F2-3 | meta-schema.yaml archived_at 约束 | 文档检查（不阻塞） |
| TC-F2-4 | test_default_hides_completed | PASSED |
| TC-F2-5 | test_all_includes_completed | PASSED |
| TC-F2-6 | test_phase_filter | PASSED |
| TC-F2-7 | test_all_and_phase_mutex | PASSED |

### F-003

| TC | 用例名 | 结果 |
|---|---|---|
| TC-F3-1 | test_precheck_phase_invalid | PASSED |
| TC-F3-2 | test_precheck_dirty | PASSED |
| TC-F3-3 | test_precheck_no_pr | PASSED |
| TC-F3-4 | test_precheck_pr_not_merged | PASSED |
| TC-F3-5 | test_three_prompts_yes_path | PASSED |
| TC-F3-6 | test_three_prompts_no_path | PASSED |
| TC-F3-7 | test_experience_failure_does_not_break_archive / test_local_branch_delete_rejected / test_remote_branch_already_deleted | PASSED |
| TC-F3-8 | V-01 沙盒 archive e2e | manual/pending |
| TC-F3-9 | V-08 自举归档 | manual/pending（PR merge 后执行） |

### F-004

| TC | 用例名 | 结果 |
|---|---|---|
| TC-F4-1 | test_passed_path | PASSED |
| TC-F4-2 | test_not_passed_path | PASSED |
| TC-F4-3 | test_timeout_path | PASSED |
| TC-F4-4 | test_429_to_timeout | PASSED |
| TC-F4-5 | test_round_increment | PASSED |
| TC-F4-6 | test_filter_old_review | PASSED |
| TC-F4-7 | test_codex_args_mutex | PASSED |
| TC-F4-8 | V-01 沙盒 submit --codex e2e | manual/pending |
| TC-F4-9 | test_v09_constant_uniqueness（V-09 自动化） | PASSED |

---

## 4. 失败用例详情

无。0 failed。

---

## 5. V-09 常量唯一性验证（已自动执行）

```
grep -rn "Didn't find any major issues." .claude/ scripts/
```

结果：`.claude/skills/managing-requirement-lifecycle/reference/submit-rules.md:7` 仅一处，符合预期。

注意：`tests/` 和 `requirements/` 下存在该字符串的引用属正常（测试 fixture 和文档引用），验收范围限 `.claude/` + `scripts/`，通过。

---

## 6. 沙盒/自举类待人工验收清单

以下条目不阻塞 testing 阶段通过，在 staging/PR merge 后执行：

| 编号 | 内容 | 建议执行命令 | 触发时机 |
|---|---|---|---|
| V-01-F1 | submit --draft → GATE-REVIEW-VERDICT skip | `python3 scripts/gates/run.py --trigger submit --draft --req REQ-2099-007` | PR 提交前沙盒 |
| V-01-F1b | submit 同分支已有 open PR → GATE-AHEAD-OF-ORIGIN skip | `python3 scripts/gates/run.py --trigger submit --req REQ-2099-007` | PR 提交前沙盒 |
| V-01-F3 | archive e2e：phase=completed + archived_at 写入 + process.txt [archived] | `/requirement:archive REQ-2099-007` | PR 提交前沙盒 |
| V-01-F4 | submit --codex e2e：round-1.md 落地 + frontmatter 8 字段 + process.txt 两事件 | `/requirement:submit --codex --req REQ-2099-007` | PR 提交前沙盒 |
| V-04 | archive 自举：用 archive 命令归档本需求 | `/requirement:archive REQ-2026-007` | PR merge 后 |
| V-08 | archive 幂等：process.txt [archived] 计数 = 1 | `grep -c '\[archived\]' requirements/REQ-2026-007/process.txt` | PR merge + archive 后 |

---

## 7. 追溯链快照

| Feature | 设计 anchor | 实现文件 | 测试文件 |
|---|---|---|---|
| F-001 | detailed-design.md §3.2.1/§3.2.2 | scripts/gates/plugins/ahead_of_origin.py / review_verdict.py | tests/gates/test_ahead_of_origin.py / test_review_verdict.py |
| F-002 | detailed-design.md §4.4/§3.4.3 | .claude/commands/requirement/list.md / context/team/engineering-spec/meta-schema.yaml | tests/lifecycle/test_list_filter.py |
| F-003 | detailed-design.md §3.4.2/§3.5 | scripts/lib/archive_runner.py / .claude/commands/requirement/archive.md | tests/lifecycle/test_archive.py |
| F-004 | detailed-design.md §3.4.1/§3.6/§3.3 | scripts/lib/submit_codex.py / .claude/skills/managing-requirement-lifecycle/reference/submit-rules.md | tests/lifecycle/test_submit_codex.py |

---

## 8. 结论

**READY-FOR-COMPLETED**

- 全量 pytest：569 passed / 0 failed / 8 skipped（skipped 均与本需求无关）
- 4 features 的自动化 TC 100% 通过
- V-09 常量唯一性已自动验证通过
- 待人工验收的沙盒/自举条目（V-01/V-04/V-08）不阻塞当前阶段，可在 PR merge 后补做
- 建议下一步：更新 process.txt → `[testing-completed]`，切换 meta.yaml phase → `completed`，提 PR

---

## 附录：Codex round-1 自举回归（2026-05-05 17:30 增补）

PR #57 提交后跑 `submit_codex.py` 第一轮，因脚本自身字符串比时间戳的 P1 bug 报 `verdict=timeout`；
人工核对后实际 verdict=not_passed，codex 给出 3 条 finding：

| Finding | Severity | 文件:行 | 修复 |
|---|---|---|---|
| F-1 | P1 | scripts/lib/submit_codex.py:302 | 新增 `_parse_iso_to_aware`；`_poll_codex` 改 tzaware datetime 比对 |
| F-2 | P1 | scripts/lib/submit_codex.py:225 | `gh api ... -q '.[]'` JSONL 输出 + `_parse_jsonl_reviews` 解析 |
| F-3 | P2 | scripts/lib/list_requirements.py:76 | `_parse_created_at` 永远返回 tzaware（naive 注 Asia/Shanghai） |

新增 4 条回归 pytest（覆盖 3 条 finding 各自的契约 + datetime 单元级辅助）。
更新后全量回归 **573 passed / 0 failed / 8 skipped**（+4 = 3 finding 回归 + 1 单元级 helper 测试）。
详情见 `artifacts/codex-reviews/round-1.md`。

### Round 2（2026-05-05 17:23~17:29，commit 2494e73）

F-1 修复生效，脚本正确识别 codex 回评（verdict=not_passed，不再 timeout）。Codex 又给 2 条新 finding：

| Finding | Severity | 文件:行 | 修复 |
|---|---|---|---|
| F-4 | **P1** | `scripts/lib/submit_codex.py:190` `_calc_round` | `len + 1` → `max(parsed_suffix) + 1`，断档下不覆盖 |
| F-5 | P2 | `scripts/lib/archive_runner.py:254` `_append_process_event` | `'a+'` 同句柄 + `fcntl.flock(LOCK_EX)` 把 check+append 包进临界区 |

再加 4 条回归 pytest → 全量 **577 passed / 0 failed / 8 skipped**。详情见 `artifacts/codex-reviews/round-2.md`。

### Round 3（2026-05-05 17:39~17:45，commit 9f8853c）

verdict=not_passed，codex 再给 2 条 finding：

| Finding | Severity | 文件:行 | 修复 |
|---|---|---|---|
| F-6 | **P1** | `submit_codex.py:375` `_poll_codex` | 收集所有 post-trigger 候选 → `max(submitted_at)`；新增 `_pick_latest_review` |
| F-7 | P2 | `archive_runner.py:384` `_delete_local_branch` | 删除前 `_current_branch()` 检测，HEAD 在目标分支 → 提示先切 base_branch |

再加 3 条回归 pytest → 全量 **580 passed / 0 failed / 8 skipped**。

**累计 round-1..3 自举闭环：7 finding（4 P1 + 3 P2）全 fix + 11 条新回归 pytest**——F-004 review-loop 系统性可用性验证完成。
