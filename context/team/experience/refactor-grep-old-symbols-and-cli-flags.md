# 重构核心模块要全仓 grep 旧符号 + 旧 CLI flag

**沉淀原因**：跨需求会重复（重构是高频操作）、AI 反复犯（这次 testing 阶段才暴露 stale 测试）、跨会话需保留。

## 问题

REQ-2026-003 testing 阶段首跑 `pytest -q` 报 6 个 failure，定位到 `tests/skills/test_code_review_prepare_routing.py` mock `_is_tty` / 调 `_run_default_mode` / CLI `--scope-out --all`——这些在当前 `code_review_routing.py` 中**根本不存在**。

时间线：F-002 commits `4502752`（加入这批测试）→ `3d46fcb`（移除 `_is_tty` 后门 + CLI 重构）之间，**漏改这一个测试文件**。核心 `tests/lib/test_code_review_routing.py` 已被同步重写、F-001/F-002 review 时跑的是 lib 那份，未触发 skills 那份的失败。

## 根因

- review scope（routing.yaml 的 must/suggest 命中）是**子集**——有的"等价重复测试"在不同路径分类下会被漏跑
- 重构跨多步进行时，单纯靠"我记得改了"的人脑追踪不可靠
- pytest scope 限定（`--feature-id=F-002`）只跑相关目录，不全量回归

## 解法

1. **重构核心模块时**——改函数名 / 改 CLI 必填参数 / 改返回类型 / 改 dataclass 字段——必须**全仓 grep 旧符号 + 旧 CLI flag**：
   ```bash
   grep -rn '_is_tty\|--scope-out\|_run_default_mode' .
   ```
   单测目录、skill 文档、command 引用、wiki / SOP 全扫一遍。

2. **review scope 不能完全替代全量回归**——`phase-transition` 切 testing 时强制跑 `pytest -q` 作为门禁兜底（不是只信任前置 review 的局部跑）。

3. **stale 测试发现后**——优先用 `pytestmark = pytest.mark.skip(reason=...)` **整文件标记**而不是直接 `rm`：保留 git 可见的占位 + 明确理由（指向覆盖等价物路径），等用户审视后再 `git rm`。直接 `rm` 会触发 hook 拦截"删除预存测试文件"，需要更高授权层级。

## 验证方法

- 重构 PR 提交前：`git grep '<旧符号>'` 必须无命中（除 git 历史外）
- testing 阶段切换前：`pytest -q` 全量回归 0 failed
- 删 stale 测试时：先 SKIP + commit，PR 评审时再决定是否 `git rm`

## 引用来源

- `requirements/REQ-2026-003/notes.md:77-101`
- 类似系列：`context/team/experience/spec-drift-consumer-aligns-with-producer.md`（规范 vs 实现双向漂移）
