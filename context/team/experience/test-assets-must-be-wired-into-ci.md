# 测试资产创建后必须接入执行入口

**沉淀原因**：跨需求重复（任何"新加 shell / e2e / contract 测试但忘了接 CI"都会撞）、AI 反复错（写测试只测一遍即提 PR，忘记把"日常 push 触发"的钩子接上）、跨会话保留（review 阶段需要立刻能定位测试入口）。

## 问题

REQ-2026-012 F-A 前置发现：tests/lib/test_routing_e2e.sh 是 routing 路径的真实 E2E shell 测试（本地 PASS=3 FAIL=0），但 `.github/workflows/quality-check.yml` 没有任何 step 调用它。这意味着 routing.py 上线之后任何回归都不会被 CI 拦——开发者本地"还记得跑"才能保住。

## 根因

新增测试资产时只看"这个测试本身能跑过"，没看"它会不会被 CI / 本地 make 入口自动触发"。这是"工具封装知识，不封装流程"的反例——测试存在但不被自动消费，等同于 dead code。

**通用规律**：凡是「新建 shell / e2e / contract / property-based 测试」+「希望它在 PR / push 时强制执行」的组合，必须同时接入 CI workflow step + 本地镜像入口（make ci-local 之类）；不接入则必须显式说明原因和手跑命令。

## 解法

1. 新增测试默认进 CI；不进 CI 必须 PR 描述说明原因
2. CI YAML 改动需 PR 描述列出新增/删除 step

## 验证方法

- **不进 CI 的测试必须写在 PR 描述里**：手跑命令 + owner（谁负责定期跑）
- **PR reviewer 检查项**：核对 PR 描述是否齐全；workflow yml 改动是否在 PR 描述列出
- **持续门禁**：CI 通过即视为测试已对齐（CI 自身是 sample-of-truth）

## 反面案例

- REQ-2026-012 F-A 前：test_routing_e2e.sh 存在 4 个月未入 CI，期间 routing.py 经历过 3 次重构（来源：git log），靠运气没破。
- 与 `auto-generated-artifact-needs-pre-commit-not-just-ci.md` 是邻问题——前者是"派生产物 / CI 兜底同步"，本经验是"测试资产接入执行入口"；两条原则共同对抗"本地过 = CI 过"幻觉。

## 关联

- `context/team/experience/auto-generated-artifact-needs-pre-commit-not-just-ci.md` — 派生产物侧
- `context/team/ai-collaboration.md` § 验证清单 — review 时此条作为强制检查项
