

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

### F-005 review-001 drop 的 follow-up（dev-time 威胁模型 + 链路兜底打断 → 不修，未来引入多用户协作 / 网络暴露面再开 follow-up）

- **F-1 路径穿越纵深防御**（security-checker minor，drop）：`.claude/hooks/touches_guard.py:362` `receipt_path` 由 `read_state.current_feature` 拼接，无 `^F-\d{3}$` 校验。当前威胁模型：本地 dev-time 工具 + 攻击者已有 `.dispatch-state.json` 写权限即 game over；上游 dispatch_precheck.py L1 锁内已做 fid 校验。修法：拼路径前加 `re.fullmatch(r"F-\d{3}", fid)` 兜底；与 F-2 同步。
- **F-2 路径穿越纵深防御**（security-checker minor，drop）：`scripts/gates/plugins/touches_violation.py:191` `receipt_path` 由 features.json 的 `fid` 拼接。check_features.py schema gate 上游守住 `^F-\d{3}$`；dev-time 同 F-1。修法：plugins/base.py 抽公共 `_safe_feature_path(tasks_dir, fid, suffix)` 复用；与 F-1 同步。
- **F-3 touches_violations[] 上限**（security-checker minor，drop）：理论 disk DoS 链路被 hook fail-open + GATE-TOUCHES-VIOLATION 仅列前 3 条 fail 打断；生产环境优化项（候选 `MAX_VIOLATIONS=1000` 截断 + logger.warning）。

### dev→testing phase-transition 期工具盲点 follow-up（D-015 / D-016 上游）

- **save_review supersedes 写入偏差**（D-016 上游）：`save_review.py` 写 verdict json 时，supersedes 字段在 round-001（无前序）场景下应统一写 `null` 而非空字符串。F-008-001.json 是已知单点偏差（其余 first-round 都是 null）。修法：定位 save_review 写入路径里 supersedes 默认值赋值点，强制 None；同时反向 audit `requirements/*/reviews/*.json` 是否还有 `supersedes=""` 单点。本需求 D-016 走兼容兜底（工具层接受 falsy），不修写入路径——避免 scope 蔓延。
- **GATE-SOURCING inline code mask follow-up**（D-015 上游）：本需求只 mask fenced + 反引号 inline code。其他 markdown 引用语境（如 `<!-- comment -->` HTML 注释、链接 `[text](path)`、图像 `![alt](src)`）当前不 mask，理论上仍可能误报。短期内未观测到此类场景，记为 follow-up 不立即修。

### F-2 / F-4 累积技术债（推 F-005+ 一起处理）

- **F-2**：`scripts/gates/plugins/task_frontmatter.py` / `features_schema.py` 同位置 `_validate_*_file` 捕获 `SchemaLoadError` 后追加到 failures，最终以 `Decision.FAIL + R-*-INVALID code` 返回，混淆 exit 1（数据违规）/ exit 2（schema 损坏）语义。修法：抽公共 `ValidationReport` 抽象时区分 (kind, msg)，schema 类返回独立 code（如 `R-*-SCHEMA-BROKEN`）。
- **F-4**：`scripts/lib/check_*.py` main() 中 OSError（文件不可读）走 exit 1，按契约更接近 exit 2（schema/环境损坏）。F-001/F-002/F-003 三件套同模式，应在抽公共时统一。

触发条件：F-005+ 任意新 schema-driven gate 派发时，把这两条纳入 scope。
