"""派发状态文件锁工具（F-004）。

用途：
  - 提供 `requirements/<id>/.dispatch-state.json` 的并发安全读写
  - 给 dispatch_precheck.py / touches_guard.py / dispatch_state_cleanup.py 复用

公开 API（detail-design.md §3.2）：
  - L1（强约束 TOCTOU 修复）：
      flock_state_file(req_dir) → 上下文管理器；with 块内 read/write 不再二次取锁
  - L2（单读 / 单写 / 单清；无 TOCTOU 风险时使用）：
      read_state(req_dir) → Optional[DispatchState]
      write_state(req_dir, state) → None
      clear_state(req_dir) → None

强约束（detail-design §3.2.1）：
  - dispatch_precheck.py **必须** 使用 L1 上下文管理器（read+三校验+write 单锁内原子）
  - L2 read_state + write_state 顺序调用 = TOCTOU 漏洞，禁止在新代码中出现

锁实现：fcntl.flock LOCK_EX + 5s timeout + 50ms 轮询；
  write 路径：truncate(0) + write + flush + fsync 原地写（非 atomic rename）。
  原因：flock_state_file with 块在持 fd 的 read+write 复用场景下，
  rename 换 inode 会致后续 fd 操作作用于旧 inode；
  LOCK_EX 持锁期已序列化合规读者，truncate 瞬间无并发观测窗口。
  详见 plan.md ADR D-010。

异常契约：
  - TimeoutError：5s 内未取到锁
  - ValueError：JSON 解析失败 / 顶层不是 object
  - OSError：磁盘 / 权限错误
  - AssertionError：write_state 入参缺字段（调用方 bug）

数据载荷 schema（.dispatch-state.json）（detail-design §3.1）：
  {
    "schema_version": "1.0",        # 必填
    "req_id": "REQ-xxxx-xxx",       # 必填；自检冗余
    "current_feature": "F-002" | null,  # 必填
    "acquired_at": "<ISO8601>",     # current_feature 非 null 时必填
    "acquired_by_pid": <int>        # current_feature 非 null 时必填
  }
"""
from __future__ import annotations

import fcntl
import json
import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Iterator, Literal, Optional, TypedDict

# ---------- 常量 ----------

# 锁等待上限（秒）；超过即抛 TimeoutError
LOCK_TIMEOUT_S: float = 5.0
# 轮询间隔（秒）；50ms 在低延迟与 CPU 占用间平衡
POLL_INTERVAL_S: float = 0.05
# 当前支持的数据载荷 schema_version
SUPPORTED_SCHEMA_VERSION: str = "1.0"
# .dispatch-state.json 文件名
STATE_FILE_NAME: str = ".dispatch-state.json"


# ---------- 类型定义 ----------

class DispatchState(TypedDict, total=False):
    """派发状态字典；total=False 因 acquired_at/pid 在 idle 态可缺省。"""
    schema_version: Literal["1.0"]
    req_id: str
    current_feature: Optional[str]
    acquired_at: str       # ISO8601 with offset
    acquired_by_pid: int


# ---------- 内部工具函数 ----------

def _state_path(req_dir: Path) -> Path:
    """计算 .dispatch-state.json 绝对路径。"""
    return req_dir / STATE_FILE_NAME


def _infer_req_id(req_dir: Path) -> str:
    """req_dir = requirements/REQ-2026-008 → "REQ-2026-008"。"""
    return req_dir.name


# ---------- L1 公开 API：上下文管理器（单锁原子） ----------

class StateFileHandle:
    """flock_state_file 上下文内暴露给调用方的句柄；read/write 在外层锁内运行，不再二次取锁。

    调用方在 with 块内可任意 read / write，所有 IO 受 LOCK_EX 保护。
    """

    def __init__(self, path: Path, file_obj: IO[str]) -> None:
        self._path = path
        self._f = file_obj  # 已持锁的 fd（调用方禁止主动 close）

    def read(self) -> Optional[DispatchState]:
        """锁内读；返回 None 表示空文件 / 空 dict / 不存在。

        异常：
          - ValueError：JSON 解析失败 / 顶层不是 dict
        """
        self._f.seek(0)
        text = self._f.read()
        if not text.strip():
            # 空骨架（"{}"）或空文件 → 视同未派发过
            return None
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"dispatch-state JSON 解析失败：{self._path} | {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"dispatch-state 顶层必须是 object：{self._path}")
        if not data:  # "{}" 空骨架
            return None
        return data  # type: ignore[return-value]

    def write(self, state: DispatchState) -> None:
        """锁内写；通过 truncate+write 原地写入。

        实现策略：
          - 不用 atomic rename（rename 会换 inode → 当前 fd 失效，with 块内后续 read 读到旧文件）
          - 改用 truncate+write：保留 fd 与锁不变；锁本身保证读者看不到半写
          - 所有读者都通过 L1 / L2 取 LOCK_EX，与 write 互斥；故无需 rename 的"读不到半写"保证

        异常：
          - AssertionError：缺 schema_version / req_id；
                            current_feature 非 null 时缺 acquired_at / acquired_by_pid
          - OSError：磁盘满 / 权限拒绝
        """
        # 字段必填校验（调用方 bug 暴露；hook 顶层 except Exception 兜底）
        assert "schema_version" in state and state["schema_version"] == SUPPORTED_SCHEMA_VERSION, \
            f"write_state 缺 schema_version 或值非 {SUPPORTED_SCHEMA_VERSION}"
        assert "req_id" in state and state["req_id"], "write_state 缺 req_id"
        if state.get("current_feature") is not None:
            assert "acquired_at" in state and state["acquired_at"], \
                "current_feature 非 null 时 acquired_at 必填"
            assert "acquired_by_pid" in state and isinstance(state["acquired_by_pid"], int), \
                "current_feature 非 null 时 acquired_by_pid 必填且为 int"

        text = json.dumps(state, ensure_ascii=False, indent=2)
        # truncate + write：保持 fd 与锁有效；with 块内后续 read 可看到最新内容
        self._f.seek(0)
        self._f.truncate(0)
        self._f.write(text)
        self._f.flush()
        # 关键：fsync 确保数据落盘；防止崩溃丢失（accept 一些 fs 上无效的开销）
        try:
            os.fsync(self._f.fileno())
        except OSError:
            # 某些 fs（tmpfs / 测试环境）不支持 fsync；忽略
            pass


@contextmanager
def flock_state_file(req_dir: Path) -> Iterator[StateFileHandle]:
    """L1 公开 API——LOCK_EX 5s timeout 上下文管理器。

    用法（dispatch_precheck.py 单锁原子，杜绝 TOCTOU）::

        with flock_state_file(req_dir) as fh:
            state = fh.read()             # 锁内读
            # 业务校验 status / depends_on / current_feature ...
            fh.write({"current_feature": fid, ...})   # 锁内写

    模式：始终用 'r+'。
      - 文件不存在 → 先建空骨架 "{}"（仅用于让 'r+' 可打开；read 时仍返回 None）
      - 'r+' 允许 read+write 复用同一 fd；read 与 write 都在锁内安全执行

    异常：
      - TimeoutError：5s 内未取到锁
      - ValueError：JSON 解析失败（read 时）
      - OSError：磁盘 / 权限错误
    """
    path = _state_path(req_dir)
    # 父目录可能首次访问；mkdir 幂等
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        # 'r+' 要求文件预先存在；首访问建空骨架（read 返回 None）
        path.write_text("{}", encoding="utf-8")

    f = path.open("r+", encoding="utf-8")
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    try:
        # LOCK_EX + LOCK_NB + 轮询；避免 LOCK_EX 阻塞模式死等
        while True:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"flock timeout {LOCK_TIMEOUT_S}s: {path}")
                time.sleep(POLL_INTERVAL_S)

        handle = StateFileHandle(path, f)
        try:
            yield handle
        finally:
            # 释放锁；即使 with 块抛异常也保证执行
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            except OSError:
                # 锁释放失败（fd 已无效等极端场景）；close 兜底
                pass
    finally:
        f.close()


# ---------- L2 公开 API：单读 / 单写 / 单清 ----------

def read_state(req_dir: Path) -> Optional[DispatchState]:
    """L2 单读——内部调 flock_state_file 取锁后读单次释放。

    适用：touches_guard.py（只读 current_feature，无后续写入）
    禁用：dispatch_precheck.py（必须用 L1，否则 TOCTOU；detail-design §3.2.1）

    返回：
      - DispatchState：文件存在且非空
      - None：文件不存在 或 空骨架 "{}"

    异常透传：TimeoutError / ValueError / OSError
    """
    state_path = _state_path(req_dir)
    # 文件不存在直接 None；避免无谓建空骨架（L2 read 路径优化）
    if not state_path.exists():
        return None
    with flock_state_file(req_dir) as fh:
        return fh.read()


def write_state(req_dir: Path, state: DispatchState) -> None:
    """L2 单写——内部调 flock_state_file 取锁后写单次释放。

    适用：单写场景（不基于读后状态做条件写）
    禁用：与 read_state 顺序调用 = TOCTOU 漏洞；改用 L1 with 块

    异常透传：TimeoutError / AssertionError / OSError
    """
    with flock_state_file(req_dir) as fh:
        fh.write(state)


def clear_state(req_dir: Path) -> None:
    """L2 单清——清掉 current_feature / acquired_at / acquired_by_pid，保留 schema_version + req_id。

    幂等：重复调用安全（已是空闲态时仍写一遍 JSON，结果等价）。
    调用方：feature 完成（dispatch_state_cleanup.py）+ /requirement:rollback

    异常透传：TimeoutError / ValueError（状态文件 JSON 格式损坏）/ OSError
    """
    with flock_state_file(req_dir) as fh:
        cur = fh.read() or {}
        cleared: DispatchState = {
            "schema_version": SUPPORTED_SCHEMA_VERSION,
            "req_id": cur.get("req_id") or _infer_req_id(req_dir),
            "current_feature": None,
        }
        fh.write(cleared)
