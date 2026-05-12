# feature done 转换必须触发 dispatch lock cleanup CLI

**沉淀原因**：跨需求重复（每个 feature done 都需要）+ AI 反复漏调（全仓零调用，F-001~F-009 全程未触发）

## 问题

`scripts/lib/dispatch_state_cleanup.py` 在仓里写好了，docstring 明确说"feature 完成后清理"，但 `grep -rln dispatch_state_cleanup` **全仓零调用**——`feature-lifecycle-manager` SKILL.md 的 done 转换流程没把它列进步骤。结果 `.dispatch-state.json` 的 `current_feature` 字段一直停在最后一个派发的 feature，靠下次 `dispatch_precheck` 覆盖才"被动重置"。

副作用：feature 已 done 后做 review follow-up 清扫（编辑 6 个非 task touches 内的文件），全部被 `touches_guard` 记到该已 done feature 的 `receipt.json.touches_violations[]`。

## 根因

CLI 是 done 转换流程里的"必经动作"，但只写在 docstring + 隐式文档，没被流程文件强引用。AI 跑流程时只读 SKILL.md，看不到 cleanup CLI 的存在就会漏调。

## 解法

文档 + 兜底 双层：

1. **文档层**：`feature-lifecycle-manager/SKILL.md` 阶段 7 完成步骤 + `reference/feature-states.md` 状态变更动作表显式列出：

   ```bash
   python3 scripts/lib/dispatch_state_cleanup.py --req-dir requirements/<id>
   ```

   该 CLI 幂等，重复调安全

2. **兜底层**：`touches_guard._is_process_artifact` 白名单加 `<req_dir>/.dispatch-state.json` 精确路径匹配，万一 cleanup 漏调，至少 lock 文件本身写入不会被记 violation

**禁止**：靠 AI 自觉读 docstring 调 CLI。任何"必经动作"必须写在流程文件被强引用。

## 验证方法

- `grep -rln "dispatch_state_cleanup" .claude/skills/ scripts/` 输出 ≥ 2 处（CLI 自身 + SKILL.md 引用）
- TL-WL-011（`.dispatch-state.json` 白名单豁免）+ TL-WL-012（跨需求不豁免）测试通过
- 抽样：随机 done 一个 feature 后检查 `.dispatch-state.json.current_feature` 已重置

## 引用来源

- `requirements/REQ-2026-010/notes.md:74-89`（F-009 done 后 review follow-up 清扫触发 6 文件 violation 的完整事故）
- A+B+C 修复 commit：`scripts/lib/dispatch_state_cleanup.py` / `.claude/skills/feature-lifecycle-manager/SKILL.md` / TL-WL-011/012
