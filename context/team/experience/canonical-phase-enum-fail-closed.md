# canonical phase 枚举 fail-closed（防 typo vacuous pass）

**沉淀原因**：跨需求高频（每个需求都可能写错 phase 名）、AI 反复犯（已有"technical-research" typo 26 分钟未发现案例）、跨会话需保留（防御机制必须长期生效）。

## 问题

REQ-2026-003 phase-transition 时 `meta.yaml.phase` 被前一次会话写成非 canonical 名 `'technical-research'`（应为 `'tech-research'`）。门禁链上有 **3 层 vacuous pass** 都没拦住 typo：

1. `check_reviews.py:_r001_review_exists`：`PHASE_REQUIREMENTS.get(target_phase, [])` 默认空 list 兜底 → for-loop 不进入 → R001 静默通过
2. `scripts/gates/plugins/review_verdict.py`：`effective_phase not in _PHASE_REQUIREMENTS` 分支返回 PASS → 把 typo 当成"无 review 要求"放行
3. `scripts/gates/run.py` 入口：不校验 `--from / --to` 是否在 canonical 枚举内 → 照单全收

后果：错的 phase 名通过所有门禁，AI 误判流程已切换。

## 根因

枚举默认值兜底（`dict.get(key, default=[])`）是"软容错"，但用在**安全门禁**场景就变成 vacuous pass——既然你不在白名单里，那就当你"不需要校验"，反而比硬错更危险。fail-closed 的反面：未知输入应该报错，不应该静默放行。

## 解法

**单一事实源 + 三层 fail-closed**（commit `a25bfcd` 落地）：

1. `scripts/lib/phase_enum.py` 从 `meta-schema.yaml.enums.phase` 加载 canonical 枚举（缓存），所有消费者共用，避免漂移
2. `check_reviews.py` R001 头部检查 `target_phase` 是否 canonical，typo 直接报 R001 错误
3. `review_verdict.py` plugin 入口先用 canonical 枚举区分"typo"vs"合法但无前置 review 要求"，前者 FAIL（code=`REVIEW-INVALID-PHASE`）
4. `run.py` 入口 `_validate_phase_args` 对 `--from / --to` 白名单校验，typo 直接退 2

## 验证方法

- 故意把 `meta.yaml.phase` 写成 `'technical-research'` → 跑任意 phase-transition → 立即 R001 fail
- 单测：`tests/lib/test_check_reviews_r001_phase_typo.py`（5 个分支）+ `tests/gates/test_runner.py` runner 入口 4 个分支 + `tests/gates/test_review_verdict_plugin.py` plugin 2 个分支

## 引用来源

- `requirements/REQ-2026-003/notes.md:5-10`
- 落实：`scripts/lib/phase_enum.py` / `scripts/lib/check_reviews.py:_r001_review_exists` / `scripts/gates/plugins/review_verdict.py` / `scripts/gates/run.py:_validate_phase_args`
- commit `a25bfcd`
