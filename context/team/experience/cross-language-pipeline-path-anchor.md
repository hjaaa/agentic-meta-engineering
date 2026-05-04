# 跨语言文件管道的路径锚定漂移

**沉淀原因**：跨需求会重复（A）+ AI 反复错（B）+ 跨会话需保留（C）

## 问题

F-004 异步 audit 设计：bash 写 + Python 读。`audit_async.sh` / `pre-tool-use-guard.sh` / `run.py` BYPASS 块 / `triggers/submit.py` 共 4 处 producer 都写 `audit/.queue/<日>.log`（cwd-relative），但 consumer `audit_flush.py` 用 `Path(__file__).resolve().parent.parent.parent` 锚到 repo 根。当 hook 在 cwd ≠ repo 时（用户 cd 到子目录跑工具 / IDE 工作区子目录 / 远端启动），audit 记录散落到 cwd-local `audit/.queue/`，SessionEnd flush 永远捞不到——审计静默丢失。

`audit-flush.sh` 自身用 `python3 scripts/lib/audit_flush.py` 调用也是 cwd-relative，cwd ≠ repo 时 file-not-found 被 stderr 重定向 + `|| true` 静默吞掉，flush 永不触发。

8 个内部 checker + review-critic + judge 全没抓到，Codex 一句话指出 P1。

## 根因

bash 与 Python 默认锚定语义不同：bash 字面量路径默认 cwd-relative，Python `Path()` 字面量同样默认 cwd 但 `__file__` 提供 script-relative。多语言混合管道的开发者各自按自己语言的"自然写法"实现，producer/consumer 在锚定坐标上分叉而无人显式约定。Hook 调用约定（cwd 不确定）放大了这一漂移。

## 解法

**设计阶段**：跨语言文件管道在 detail-design 强制声明锚定坐标——repo 根 / cwd / hook 文件目录 三选一，明文写到设计文档、Producer/Consumer 表格列出对齐方式。

**实现规范**：
- Bash producer：`_src_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"` + 相对锚定，路径名形如 `${ROOT}/path/...` 而非裸 `path/...`
- Python producer/consumer：`_REPO_ROOT = Path(__file__).resolve().parent.parent.parent`，禁止裸 `Path(f"...")`
- Shell 调用 Python 脚本：`python3 "$ROOT/scripts/lib/foo.py"`，禁止 `python3 scripts/lib/foo.py`
- 加 `<TOOL>_ROOT` env override（如 `CLAUDE_GATES_AUDIT_ROOT`）作测试隔离通道

**回归测试**：必须存在「cwd ≠ root」回归用例——`subprocess.run(... cwd=tmp_path/elsewhere)` + 验证文件落在指定 root 不落 cwd。

## 验证方法

```python
# 测试模板：producer 在异 cwd 跑，consumer 必须能读到
def test_anchor_consistency(tmp_path):
    elsewhere = tmp_path / "elsewhere"; elsewhere.mkdir()
    audit_root = tmp_path / "fake-repo"; audit_root.mkdir()
    env = {**os.environ, "TOOL_AUDIT_ROOT": str(audit_root)}
    subprocess.run(["bash", str(producer)], cwd=elsewhere, env=env, ...)
    expected = audit_root / "..." / "log"
    cwd_relative = elsewhere / "..." / "log"
    assert expected.exists()
    assert not cwd_relative.exists()  # 关键：拒绝 cwd-relative 回归
```

## 引用来源

- `requirements/REQ-2026-006/process.txt`（PR #54 Codex P1 round-1/round-2）
- `scripts/lib/audit_async.sh`（修复后）
- `tests/gates/test_global_bypass.py::test_*_audit_anchors_to_audit_root_not_cwd`
- PR #54（squash merge commit `1152ca8`）— 全部 4 个 producer + 1 个 consumer 修复落于此
