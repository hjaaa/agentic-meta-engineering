# 仓库级 Makefile —— 仅暴露门禁体系入口（YAGNI：本 PR 仅 gates-validate 一个 target）
# 来源：requirements/REQ-2026-002/artifacts/detailed-design.md F-001 任务规格

.PHONY: gates-validate

gates-validate:
	@python3 scripts/gates/run.py --validate-registry
