

## 会话经验（2026-05-05 22:31）

_本轮无新经验_


## 会话经验（2026-05-05 22:45）

_本轮无新经验_


## 会话经验（2026-05-05 23:45）

_[hook-skipped: claude-exit-143]_


## 会话经验（2026-05-06 09:42）· detail-design 首日 #2 实采样

- **关键发现**：PreToolUse Task 派发的 `tool_name` 实测为 `"Agent"`（不是 outline-design §3.2 假设的 `"Task"`），但 hook matcher 字符串写 `"Task"` 仍能命中——Claude Code 端 matcher 与 tool_name 之间存在别名映射。`dispatch_precheck.py` 实现层必须以 `tool_name == "Agent"` 为校验门面，matcher 配置保留 `"Task"`。
- **派发模板硬约束**：`feature_id: F-xxx` 必须独占 prompt 首行（行首无任何前缀），否则 §3.2 的 `^feature_id:\s*(F-\d{3})\s*$` regex 解析失败 → fail-open 放行 = 校验形同虚设。`feature-task.md.tmpl` + `subagent-dispatch.md` detail-design 必补此约束 + 解析失败单测。
- **采样工程经验**：临时 hook 注入 `.claude/settings.local.json` 触发 self-modification 防护被两次拒绝；最终走"用户在 ! shell 前缀里跑 Python 一行命令"路径绕过——这个经验提示后续 detail-design 阶段若需再次实采样，应预留"用户授权安装/清理 hook"的 SOP 节点（候选：在 `subagent-dispatch.md` 加附录"采样自检流程"）。

## 会话经验（2026-05-06 09:00）· tech-research 待澄清条目实证

- **关键发现**：`feature-task.md.tmpl` frontmatter 缺 `touches` 字段（仅在正文 §"触及范围"段有占位）。detail-design F-005 / F-007 必须把 `touches: __TOUCHES__` 加进 frontmatter，否则 `touches_guard.py` 无法机器化读取——这是隐藏的设计前提，不补就 V-03 直接 fail。
- **正面信号**：`pytest tests/ --ignore=tests/benchmarks/` 603 passed / 8 skipped / 36s，CI 扩展覆盖零修复成本，F-006 可直接合入本次 PR。
- **reviewer 体系启示（D-006 衍生）**：reviewer hash 校验无 trivial 豁免通道——任何 artifact 措辞修订都计入"重审"成本（hash drift → R005 硬 fail，stale=true 不豁免）。未来类似情况直接走重审，不再尝试"标 stale 跳过"。

### F-2 / F-4 累积技术债（推 F-005+ 一起处理）

- **F-2**：`scripts/gates/plugins/task_frontmatter.py` / `features_schema.py` 同位置 `_validate_*_file` 捕获 `SchemaLoadError` 后追加到 failures，最终以 `Decision.FAIL + R-*-INVALID code` 返回，混淆 exit 1（数据违规）/ exit 2（schema 损坏）语义。修法：抽公共 `ValidationReport` 抽象时区分 (kind, msg)，schema 类返回独立 code（如 `R-*-SCHEMA-BROKEN`）。
- **F-4**：`scripts/lib/check_*.py` main() 中 OSError（文件不可读）走 exit 1，按契约更接近 exit 2（schema/环境损坏）。F-001/F-002/F-003 三件套同模式，应在抽公共时统一。

触发条件：F-005+ 任意新 schema-driven gate 派发时，把这两条纳入 scope。
