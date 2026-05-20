---
id: 20260519-context-usage-report
title: Context 知识利用率统计机制 · 技术可行性评估
created_at: 2026-05-19T15:50:00+08:00
refs-tech-feasibility: true
---

# 20260519-context-usage-report · 技术可行性评估

> 阶段 3 产出物。基于 `requirement.md`（来源：requirements/20260519-context-usage-report/artifacts/requirement.md:1）与 spec（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:1）评估。

## 可行性结论

**结论：feasible**

理由：

1. **零外部依赖**：MVP 实现只需 Python 3.x 标准库（`pathlib / re / json / subprocess / argparse`）+ PyYAML（已是仓库依赖，来源：scripts/lib/workflow_loader.py:47）。无需向量数据库 / 后端服务 / 外部 API（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:38）。
2. **可复用既有基础设施**：
   - Markdown 链接解析复用 `scripts/lib/check_index.py` 已有正则与逻辑（来源：scripts/lib/check_index.py:31），decision 表已定将其抽到 `scripts/lib/markdown_links.py` 公共模块（来源：requirements/20260519-context-usage-report/artifacts/requirement.md:172）。
   - 代码块/inline code 隔离复用 `scripts/lib/check_sourcing.py:_mask_code_for_position` 思路（来源：scripts/lib/check_sourcing.py:107），避免应用信号关键字在 fenced code 中误判。
3. **数据规模可控**：当前仓库 `context/**/*.md` < 200 个、`requirements/**` < 100 个，离 5000 文件的 10× 上限有充足余量；`pathlib.rglob` + 单遍扫描可在秒级完成。
4. **完全只读**：仅写 `reports/context-usage.md` 与 `reports/context-usage.json`，不修改既有任何 context / requirements / source 文件，符合 AC-08（来源：requirements/20260519-context-usage-report/artifacts/requirement.md:139）。

## 风险识别

| # | 类别 | 严重度 | 描述 | 缓解 |
|---|---|---|---|---|
| R-01 | 集成 | medium | Markdown 链接解析抽公共模块需同步修改 `check_index.py` 的 6 个相关函数（`LINK_RE / _extract_links / _resolve_link / _is_external_or_intra_anchor / _slugify / _extract_headings`，来源：scripts/lib/check_index.py:31），并保留 `index-config.yaml` 忽略规则语义（来源：scripts/lib/index-config.yaml:12）；遗漏 `**` glob 扩展（来源：scripts/lib/check_index.py:49）或 anchor slug 规则（来源：scripts/lib/check_index.py:78）会回归 INDEX 健康判定 | 抽模块时保留 `check_index.py` 全量回归（`tests/gates/test_index_integrity_plugin.py`）+ 新增 pytest 覆盖 4 类用例（LINK_RE / slug / glob `**` / 外链跳过）；commit 拆为 (a) 抽模块 + `check_index.py` 切换 (b) `context_usage_report.py` 引用模块，便于回滚 |
| R-02 | 性能 | medium | AC-11 < 5s 守门（来源：requirements/20260519-context-usage-report/artifacts/requirement.md:70）；当前规模毫无压力，但 spec 10× 余量基线（5000 文件，来源：requirements/20260519-context-usage-report/artifacts/requirement.md:70）下 `pathlib.rglob` 逐项 stat 开销 + `subprocess` 调 `git log` 单文件 ~50-200ms 会显著拖慢 | git 历史走单次批量 `git log --name-only --since=<recency_window> --pretty=format:%H\|%cI` 抓最近 90 天 commits，缓存 `path → last_commit_ts`，O(N_changed) 而非 O(N_files)；rglob 后立即按 ignore 规则过滤，避免对忽略路径做 stat / read；CI 用 `time` 守门并对 fixture 仓库（1000 个 md）回归 < 5s |
| R-03 | 技术 | medium | AC-05 复合上下文窗口（同 `##` 二级小节 ∧ 前 5 行 + 后 10 行，来源：requirements/20260519-context-usage-report/artifacts/requirement.md:171）需双约束扫描；关键字 `Decision / 决策 / 应对 / 风险 / 验证` 若被 inline code 或 fenced code block 包裹会误判（参考 `check_sourcing.py:_mask_code_for_position`，来源：scripts/lib/check_sourcing.py:107） | 复用 `check_sourcing.py` 的 fenced code mask 抽到公共工具，或在 `AppliedSignalClassifier` 内引入相同的代码块跳过逻辑；fixture 覆盖「关键字在 code block 内」反例与「跨段落」边界用例；保守原则下宁可漏判不可误判（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:48） |
| R-04 | 集成 | low | `reports/` 入 `.gitignore` 决策（来源：requirements/20260519-context-usage-report/artifacts/requirement.md:170），现有 `.gitignore` 无 `reports/` 条目（来源：.gitignore:44），需新增；AC-08 「不修改除报告文件外的仓库内容」与 `.gitignore` 修改在 PR 中需明确豁免 | Phase 1 首个 commit 同步追加 `reports/` 到 `.gitignore`，commit message 明示「需求决策表豁免」；requirement.md 决策表已记录依据 |
| R-05 | 技术 | low | `requirements/**` 显式引用扫描覆盖多种格式：Markdown 链接 / 直接路径 / `来源：` 标记 / JSON 字段 / YAML key 值（来源：requirements/20260519-context-usage-report/artifacts/requirement.md:115）。其中 `reviews/*.json` 是 JSON 不是 Markdown，需走 `json.loads` + 递归字符串扫描；YAML frontmatter 内的 `context/` 路径也要识别 | EvidenceScanner 按后缀分发：`.md` 走文本正则；`.json` 走 `json.loads` + 递归扫描；`.txt` 走文本正则；fixture 覆盖每种引用形式；`reviews/*.json` 解析失败时 fail-open（warning 不阻断报告） |
| R-06 | ops | low | `git log` 子进程在 CI 环境（shallow clone / submodule）可能拿不到完整历史，回退到文件系统 `mtime`；fs `mtime` 在 git clone 后通常等于 clone 时间，会污染 `recency_score`（30 天 10 分 / 90 天 5 分，来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:181） | `subprocess` 包 `try/except`，`git log` 失败时在 JSON 报告显式标 `last_modified_at_source: fs_mtime`；CI 文档提示 `actions/checkout` 用 `fetch-depth: 0`；`recency_score=0` 回退路径单测覆盖；git 历史不作为强证据（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:239） |

## 工作量估算

总计：**5.5 人天**（按 1 人开发节奏）。

| 工作包 | 人天 | 说明 |
|---|---:|---|
| WP-1 抽取 `scripts/lib/markdown_links.py` 公共模块 + 切换 `check_index.py` 调用 | 1.0 | 含 4 类用例 pytest + `tests/gates/test_index_integrity_plugin.py` 回归不变 |
| WP-2 `ContextInventory` + `IndexGraph`（spec §架构设计 ContextInventory / IndexGraph，来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:274） | 0.5 | 文件清单 + INDEX 链接图，过滤 `INDEX.md` / ignore 路径 |
| WP-3 `EvidenceScanner`（含 `.md / .json / .txt` 三种格式分发） | 1.0 | 见 R-05 缓解 |
| WP-4 `AppliedSignalClassifier`（复合上下文窗口 + code block mask） | 1.0 | 见 R-03 缓解；保守优先 |
| WP-5 `UsageAggregator` + `ReportRenderer`（含 Markdown 四章节 + JSON schema） | 0.5 | spec §报告格式（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:389） |
| WP-6 CLI + 参数（默认 + `--context-dir / --requirements-dir / --output / --json-output / --since / --project / --only-experience / --format`，来源：requirements/20260519-context-usage-report/artifacts/requirement.md:147） | 0.5 | `argparse`；治理参数 `--fail-on-broken-index / --fail-on-orphan` 留接口默认不启用 |
| WP-7 fixture 测试 + 回归测试（仓库真实数据 + 1000 文件性能 fixture） | 1.0 | 含 CI `time` 守门 |

> 工作量缓冲：每个 WP 内已计入正常 review / 修复时间；不含开放问题 / 评审反馈集中修订时间。

## 替代方案对比

| 方案 | 优 | 劣 | 取舍 |
|---|---|---|---|
| **A. 离线脚本**（采纳） | 零依赖、易回滚、与 spec 第 723 行建议一致；MVP 范围最小 | 不能感知模型隐式引用；只看显式文本 | 采纳。MVP 优先做"事实基础" |
| B. Hook 触发 + 实时统计 | 实时；不依赖人工跑脚本 | 改 PreToolUse / PostToolUse hook 链，影响面大；与 spec 第 41 行「不阻断」原则冲突 | 推后到 Phase 4 |
| C. 接入 LSP / 检索 Agent 打点 | 能捕获隐式使用 | 需改所有 Agent 工作流；spec 明确推后到 Phase 4（来源：docs/superpowers/specs/2026-05-19-context-knowledge-usage-design.md:599） | 推后 |

## 影响模块

- `scripts/lib/context_usage_report.py`（新建，本需求主产物）
- `scripts/lib/markdown_links.py`（新建，抽取公共解析）
- `scripts/lib/check_index.py`（改：切换到 `markdown_links.py`）
- `reports/`（新目录，`.gitignore` 入忽略）
- `tests/lib/test_context_usage_report.py`（新建）
- `tests/lib/test_markdown_links.py`（新建）
- `tests/fixtures/context_usage_report/`（新建 fixture）
- `.gitignore`（追加 `reports/` 一行）

## 评审依据

下一步 `outline-design` 阶段进入概要设计，需要把上述模块划分细化为：模块间依赖图、数据流、状态分类规则伪代码、CLI 入参 schema、报告章节模板。
