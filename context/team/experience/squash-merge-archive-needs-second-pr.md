# PR squash merge 后归档信息需二次 chore PR

**沉淀原因**：跨需求重复 + AI 易忽略 + 跨会话保留

## 问题

PR squash merge 完成后，需求仍处 `testing` 阶段；想切 `completed=shipped` 但 `completed_at` 必须用 PR `mergedAt`（合并后才能取），归档信息塞不进首个 PR。

## 根因

8 阶段流程的 `testing → completed` 切换时点必然错过 PR 主体。squash merge 又丢失 commit 链，无法对原分支 force-push 补 commit。

## 解法

合并后从 develop 切 `chore/<req-id>-archive` 分支，cherry-pick 一个"phase=completed + outcome + completed_at + process.txt 两行"的小 commit，单独走 PR 合入 develop。改动通常 < 10 行。

## 验证方法

- `git log develop` 含归档 commit
- develop 上 `meta.yaml.phase = completed`
- `/requirement:list` 显示真实状态而非 testing 假象

## 引用来源

- 本仓库 commits：feat 449e881 → chore 2ba41aa → 合并 c5a8bf0（PR #33）
- `requirements/REQ-2026-001/process.txt` 末段 phase-transition
