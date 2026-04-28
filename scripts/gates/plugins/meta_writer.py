"""meta.yaml 原子 + 加锁写入 helper（F-015 round-3 从 review_verdict.py 拆出）。

设计来源：requirements/REQ-2026-002/artifacts/detailed-design.md §3.1（H1 事务化）。

职责：
  - commit_meta_writes：把多个 (path="meta.yaml", dot_key, value) 暂存条目一次性
    原子写入 meta.yaml；先写 .tmp 再 replace；用 fcntl.lockf 对 sidecar lock 文件加排他锁，
    避免与 save_review CLI / 其他并发 runner 触发 read-modify-write 数据竞争。
  - set_dot_path：按 "a.b.c" dot path 在 dict 中递归设置 value，缺失节点自动建空 dict。

注意：本模块不是 Gate plugin（不导出 GATE_CLASS、不在 registry.yaml 注册），仅作为
review_verdict.py 的 commit_staged_writes 工具函数。文件名落在 plugins/ 目录下是为了
share import path（plugins/ 已在 sys.path），不引入新的 import 链。
"""
from __future__ import annotations

import fcntl
import sys
from pathlib import Path

# 复用 save_review 的 ruamel 实例（保留注释；与 save_review.py CLI 写盘行为一致）
_LIB_DIR = Path(__file__).resolve().parents[2] / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))


def commit_meta_writes(meta_path: Path, writes: list[tuple[str, str, object]]) -> None:
    """把多个 (path="meta.yaml", dot_key, value) 一次性原子写入 meta.yaml。

    使用 ruamel.yaml round-trip 保留注释（与 save_review.py 保持一致）；
    先写 .tmp 再 replace 保证原子性。

    F-010 round-2 加固：用 fcntl.lockf 对一个 sidecar lock 文件加排他锁，
    避免 commit_staged_writes 与 save_review CLI / 其他并发 runner 同时改同一份
    meta.yaml 触发 read-modify-write 数据竞争。锁随 with 块自动释放。

    参数：
      meta_path — requirements/<REQ-ID>/meta.yaml 绝对 Path
      writes   — 暂存条目列表，每项 (path, dot_key, value)；上层已过滤 path == "meta.yaml"

    异常：
      OSError / yaml.YAMLError 不吞，向上抛由调用方走 H1 rollback 路径。
    """
    import save_review as _save_review  # noqa: PLC0415（按需 import，避免本模块顶层依赖 save_review）

    lock_path = meta_path.with_suffix(meta_path.suffix + ".lock")
    # 'a' 模式确保锁文件存在；fcntl.lockf 在 fd 上加 LOCK_EX，关闭即释放
    with lock_path.open("a") as lock_f:
        fcntl.lockf(lock_f.fileno(), fcntl.LOCK_EX)
        try:
            with meta_path.open("r", encoding="utf-8") as f:
                meta_rt = _save_review._meta_yaml.load(f) or {}

            for _path, dot_key, value in writes:
                set_dot_path(meta_rt, dot_key, value)

            tmp_path = meta_path.with_suffix(meta_path.suffix + ".tmp")
            with tmp_path.open("w", encoding="utf-8") as f:
                _save_review._meta_yaml.dump(meta_rt, f)
            tmp_path.replace(meta_path)
        finally:
            fcntl.lockf(lock_f.fileno(), fcntl.LOCK_UN)


def set_dot_path(target: dict, dot_key: str, value: object) -> None:
    """按 dot path 在 target dict 中递归设置 value，缺失节点自动建空 dict。

    例：set_dot_path({}, "reviews.code.stale", True) → {"reviews": {"code": {"stale": True}}}
    """
    parts = dot_key.split(".")
    node: dict = target
    for part in parts[:-1]:
        nxt = node.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            node[part] = nxt
        node = nxt
    node[parts[-1]] = value
