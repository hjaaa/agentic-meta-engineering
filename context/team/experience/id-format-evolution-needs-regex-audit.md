# 标识符格式演进时必须扫全仓正则覆盖

**沉淀原因**：跨需求会重复（A）+ AI 反复错（B）+ 跨会话需保留（C）

## 问题

20260519-context-usage-report 一周内复发两次同款盲区（Bug-21 / Bug-22），都是**标识符格式从 `REQ-YYYY-NNN` 演进到 `YYYYMMDD-<slug>[-NN]` 时，散落各处的正则没同步**：

- **Bug-21** `scripts/gates/plugins/workspace_clean.py:_STASH_RESIDUE_PATTERN`：
  - 旧：`^\?\?\s+requirements/REQ-\d{4}-\d{3}/meta\.yaml\.bak\s*$`
  - 新格式 id `20260519-context-usage-report` 的 `.bak` 不匹配 → state_io.stash_state 合法残留被 workspace_clean 误判为 dirty → submit / phase-transition 阻断
- **Bug-22** `scripts/lib/check_sourcing.py:W002_DERIVED_FILENAME_PATTERNS`：
  - 旧：`^review-\d{8}-\d{6}\.md$`（单次评审报告时间戳格式）
  - 新格式 per-feature 评审 `review-F-NNN-YYYYMMDD.md`（如 `review-F-001-20260519.md`）不匹配 → 8 个文件触发 W002 → CI strict 12 warnings 阻塞 codex precheck

两条都在本期 CI / codex precheck 一连串排查后才暴露，每条单独看像孤立 bug，**合在一起暴露的是"id 命名约定变化时的正则覆盖审计缺失"**。

## 根因

仓库内有 N 个独立位置消费"requirement id 格式"：

- `scripts/lib/requirement_naming.py`（canonical regex 源头：`_LEGACY_REQUIREMENT_KEY_RE` + `_NEW_REQUIREMENT_KEY_RE`）
- `scripts/gates/plugins/*.py`（个别 plugin 自己写 regex 而非复用 canonical）
- `scripts/lib/check_sourcing.py`（衍生文档命名豁免）
- `scripts/lib/check_index.py`、`scripts/lib/archive_runner.py` 等
- workflow yaml 的 trigger / applies_when 字段

引入新格式时（如本期把 `REQ-YYYY-NNN` 扩展到 `YYYYMMDD-<slug>`），**主迁移文件改了 + 主测试通过 + 新格式需求跑起来了**，但这些"散落副本"在新格式生效后才被触发——CI 上 / 本地 fixture 用旧格式时全过，新需求一来才暴露。

## 解法

**新增 / 修改命名约定时的 Definition-of-Done checklist**（应纳入 `/requirement:new` 文档或 iteration-sop）：

1. canonical regex 源头改完后，**grep 全仓**找所有可能引用：
   ```bash
   rg "REQ-\\\\d|REQ-\\d{4}-\\d{3}|requirement[-_]?id" scripts/ .claude/ tests/
   ```
2. 列出 N 个命中位置，逐个判断：
   - 引用了 canonical helper（`is_legacy_requirement_key` / `is_new_requirement_key`）→ ✓ 自动覆盖
   - 自己写 regex → ⚠️ 必须更新 regex；考虑改 import canonical helper
   - workflow yaml 的 trigger / pattern → 看具体语义
3. 加一条 **CI 守门测试**：fixture 中放至少 1 个老格式 + 1 个新格式 + 1 个新格式带 -NN 后缀的 id 文件，跑全套 plugin / runner，确认都 PASS

**复用优先于复制**：所有 plugin 共享 `requirement_naming.is_*_requirement_key()` helper，而不是各自抄 regex（Bug-21 / Bug-22 都是因为 plugin 自带 regex 而非复用 helper）。

## 验证方法

- 引入命名约定变更的 PR 必须含上述 grep 输出 + 命中位置审计表
- 新格式覆盖测试：`tests/gates/test_workspace_clean_plugin.py::test_workspace_clean_passes_when_stash_residue_uses_new_id_format` / `test_sourcing_exempts_w002_for_per_feature_review_files`（本期沉淀的两条回归 case）

## 引用来源

- `requirements/20260519-context-usage-report/notes.md` Bug-21 / Bug-22
- PR #84 commits `0f34a50` / `19775e8`（两条同期 fix）
- `scripts/lib/requirement_naming.py`（canonical regex 源头）
- 关联：REQ-2026-014（命名格式从 `REQ-YYYY-NNN` 引入 `YYYYMMDD-<slug>` 的源 PR）
