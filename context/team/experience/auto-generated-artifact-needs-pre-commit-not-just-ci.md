# 自动生成产物必须挂 pre-commit，不能仅靠 CI 兜底

**沉淀原因**：跨需求重复（任何"自动生成 + CI 强校验"产物都会撞）、AI 反复错（加新条目改源 yaml 后忘跑 render）、跨会话保留（pre-submit 检查链需要固化）。

## 问题

REQ-2026-005 F-001 / F-004 给 `registry.yaml` 加新 gate 后没跑 `python3 scripts/gates/migration/render-docs.py` 重新生成 `gate-checklist.md`。本地 `pre-commit` / `post-dev` / `submit` 全部门禁都不卡，提 PR 后 CI 跑 `render-docs.py --check` 直接 FAIL（"当前 59 行，渲染结果 63 行"）。

## 根因

`gate-checklist.md` 是从 `registry.yaml` 自动生成的派生产物。CI 跑 `--check` 强制比对原文件 vs 渲染结果。但**生成动作没纳入本地任何门禁**——只在 CI 兜底，导致：

1. AI / 人改完源 yaml 不知道要重渲染（无显式提示）
2. submit 前置门禁也不查（gate runner 不知道这个生成关系）
3. 失败时已经在 GitHub 上跑了 CI，浪费一次 round-trip

**通用规律**：凡是「源文件 → 自动生成派生文件」+「CI 校验是否同步」的组合，必须把生成动作挂到本地 pre-commit / pre-submit 强校验，不能仅在 CI 兜底。

## 解法

**两条防线**：

1. **pre-commit hook**：staged 文件含源 yaml 时，自动跑 render 比对；不一致 → 提示 `make render-XXX` 并 abort commit
2. **submit 前置门禁**：`python3 scripts/gates/run.py --trigger=submit` 加 GATE-DERIVED-DOCS-SYNC，调用所有 `--check` 类生成器

**Makefile 约定**：所有自动生成命令统一到 `make gates-render` / `make docs-render` 入口；commit-checklist.md / CONTRIBUTING.md 显式列出。

## 验证方法

- 改 `registry.yaml` 后忘跑 render 时 pre-commit 阻断
- `make gates-render` 一键全跑 + `git status` 看是否有 diff（有 = 忘跑了）
- CI 仍保留 `--check`（兜底）

## 引用来源

- `.github/workflows/quality-check.yml:42-45`（CI 强校验入口）
- `scripts/gates/migration/render-docs.py`（生成器）
- commit `d65afba`（REQ-2026-005 触发后修复）
- `requirements/REQ-2026-005/notes.md` PR CI 修复复盘 #2
