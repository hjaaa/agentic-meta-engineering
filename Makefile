# 仓库级 Makefile —— 暴露门禁体系入口
# 来源：requirements/REQ-2026-002/artifacts/detailed-design.md F-001/F-004 任务规格

.PHONY: gates-validate gates-render

gates-validate:
	@python3 scripts/gates/run.py --validate-registry

gates-render:
	@python3 scripts/gates/migration/render-docs.py
