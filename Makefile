# 仓库级 Makefile —— 暴露门禁体系入口
# 来源：requirements/REQ-2026-002/artifacts/detailed-design.md F-001/F-004 任务规格

.PHONY: gates-validate gates-render

gates-validate:
	@python3 scripts/gates/run.py --validate-registry

gates-render:
	@python3 scripts/gates/migration/render-docs.py

# ============ ci-local：本地镜像 CI 入口（F-007 / D-004 D-009）============
#
# FAIL labels（detail-design 同步出表，与下方子 target 名 1:1；
# 任一子 target 失败时 stderr 末段写一行 `FAIL: <label>`，AC-5 自动断言模式
# `make ci-local 2>&1 | grep -E '^FAIL: '` 依赖此契约）：
#
#   ci-local-deps           ci-local-pytest         ci-local-bats
#   ci-local-gates          ci-local-settings-check ci-local-ruff
#   ci-local-render-check   ci-local-routing-e2e
#
# hyperfine 路径：嵌在 ci-local-bats 内由 bats V-06 触发，不单独立 target
# （D-008 二选一兜底：若 V-06 实际不跑 hyperfine 则补 ci-local-hyperfine）。
# benchmarks 目录：与 CI 一致由 pytest --ignore=tests/benchmarks/ 跳过。

.PHONY: ci-local ci-local-deps ci-local-gates ci-local-pytest \
        ci-local-settings-check ci-local-bats ci-local-ruff \
        ci-local-render-check ci-local-routing-e2e

ci-local: ci-local-deps ci-local-gates ci-local-pytest \
          ci-local-settings-check ci-local-bats ci-local-ruff \
          ci-local-render-check ci-local-routing-e2e
	@echo "ci-local: ALL PASS"

ci-local-deps:
	@pip install -r requirements/ci.txt \
	  || { echo "FAIL: ci-local-deps" >&2; exit 1; }

ci-local-gates:
	@python3 scripts/gates/run.py --trigger=ci --strict \
	  || { echo "FAIL: ci-local-gates" >&2; exit 1; }

ci-local-pytest:
	@pytest tests/ --ignore=tests/benchmarks/ -v \
	  || { echo "FAIL: ci-local-pytest" >&2; exit 1; }

ci-local-settings-check:
	@python3 -c "import json, os, sys; \
	  s = json.load(open('.claude/settings.json')); \
	  missing = [f'{evt}: {h[\"command\"]}' for evt, hooks in s.get('hooks', {}).items() \
	    for hg in hooks for h in hg.get('hooks', []) \
	    if h.get('command') and not os.path.isfile(h['command'])]; \
	  sys.exit(1 if missing else 0)" \
	  || { echo "FAIL: ci-local-settings-check" >&2; exit 1; }

ci-local-bats:
	@command -v bats >/dev/null \
	  || { echo "FAIL: ci-local-bats (bats missing; brew install bats-core / apt-get install bats)" >&2; exit 1; }
	@bats tests/hooks/ \
	  || { echo "FAIL: ci-local-bats" >&2; exit 1; }

ci-local-ruff:
	@ruff check scripts tests --select=F \
	  || { echo "FAIL: ci-local-ruff" >&2; exit 1; }

ci-local-render-check:
	@python3 scripts/gates/migration/render-docs.py --check \
	  || { echo "FAIL: ci-local-render-check" >&2; exit 1; }

ci-local-routing-e2e:
	@bash tests/lib/test_routing_e2e.sh \
	  || { echo "FAIL: ci-local-routing-e2e" >&2; exit 1; }
