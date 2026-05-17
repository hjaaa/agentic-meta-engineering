# Makefile / shell 调 Python CLI 工具用 `python3 -m <tool>` 而非裸名

**沉淀原因**：跨需求重复（任何 Makefile / shell / CI 脚本调 pip / pytest / ruff / black 都会撞）、AI 反复错（照搬 detailed-design 设计稿的裸 `pip install` / `pytest` 字面命令）、跨会话需保留（一次性外部 reviewer 抓出后，下次仍易复发）。

## 问题

REQ-2026-012 F-007 把 `make ci-local-deps` 写成 `pip install -r requirements/ci.txt`、`make ci-local-pytest` 写成 `pytest tests/ ...`。macOS dev box `/bin/sh` PATH 看不到 `pip` / `pytest` 控制台脚本（Homebrew Python 仅装 `pip3` / `python3 -m pytest`），`make ci-local` 在本地直接 FAIL；GitHub Actions `setup-python@v4` 自动建 shim 才能跑——CI 不复现是假象。外部 codex review round-1 抓 2 处 P2，2 行机械改后 round-2 passed。

## 根因

「裸 cli 命令」依赖运行环境 PATH 上有对应 console-script，这在 Homebrew Python（PEP 668 externally-managed）、某些 Docker base image、CI runner 缺 setup-python step 等场景都失效。AI 写设计稿 / 落地代码时默认照搬 cli 名字面量，没意识到这是 PATH-fragile 接口。

## 解法

**硬规则**：Makefile recipe / shell script / CI 配置中调任何 Python CLI 工具时，**始终**用 `python3 -m <tool>` 形式：

| 反面 | 正面 |
|---|---|
| `pip install -r reqs.txt` | `python3 -m pip install -r reqs.txt` |
| `pytest tests/ -v` | `python3 -m pytest tests/ -v` |
| `ruff check src/` | `python3 -m ruff check src/`（如果用 ruff 包） |
| `black src/` | `python3 -m black src/` |

`python3 -m` 走的是 `sys.executable` + 模块解析，与是否有 console-script shim 解耦。

**例外**：GitHub Actions workflow yml 的 `Install dependencies` step 因 setup-python 已建 shim 可保留裸 `pip install`（与 CI runner 契约对齐）；但凡向 macOS dev / 别的 OS / 别的 Python 安装方式可移植的入口（Makefile / 文档 / 本地脚本）必须 `python3 -m`。

## 验证方法

- 任何新 Makefile recipe / shell 入口调 Python 工具时，grep `^[\t ]*(pip|pytest|ruff|black|isort|mypy)[[:space:]]` 应 0 命中（裸名）
- 跨 OS 自检：在新 fresh Python 安装（含 Homebrew Python）跑 `make <target>` 应能成功，不靠 shim
- 外部 reviewer（codex 等）若仍抓 P2 PATH 健壮性问题 → 复查是否漏改

## 引用来源

- `requirements/REQ-2026-012/artifacts/codex-reviews/round-1.md` — codex P2 finding 原文
- `requirements/REQ-2026-012/artifacts/codex-reviews/round-2.md` — 2 行修复后 passed
- 修复 commit `b1a3c8a`：`fix(F-007): ci-local-deps / ci-local-pytest 改走 python3 -m 调用`
