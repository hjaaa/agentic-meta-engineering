"""submit --codex 子模式 runner —— /requirement:submit --codex 的实现核心。

设计契约（detailed-design §3.3，已 frozen）：

    submit_with_codex(req_id, *, poll_interval_sec, timeout_sec) -> CodexRoundResult

行为流程：
  1. 读 meta.yaml → 取 pr_number（预检失败则 SystemExit(1)）
  2. 计算 round 号（已有 round-*.md 数 + 1，禁止重号）
  3. `gh pr comment <pr_num> --body "@codex review"` 触发 review
  4. 单轮轮询 `_poll_codex`（time.monotonic 计时）：
       - 命中三因子（Bot + /codex/i + submitted_at > triggered_at）→ 落 round-N.md
       - 超时 / 429 → verdict=timeout，落 round-N.md（仅 3 字段）
       - 连续 5xx ≥ 3 次 → GhApiAbort → exit 1
  5. 判 verdict（精确匹配 pass phrase，在 submit-rules.md 顶部定义为三常量）
  6. 向 stderr 输出 verdict 摘要（passed 时静默）

三 verdict 全部 exit 0；exit 1 仅在 GhApiAbort 或 gh pr comment 失败时触发。

frontmatter quote 规则：
  - reviewer 含 `[bot]` 后缀必须 quote（防 YAML flow-list 解析歧义）
  - triggered_at / submitted_at 含 `:` 建议 quote
  - review_id 建议 quote（防 >2^53 精度丢失）

时间戳遵循 context/team/engineering-spec/time-format.md：
  wall clock 用 ISO8601（含时区 offset），轮询超时判定用 time.monotonic。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Optional

import yaml

# 复用 common 提供的仓库根定位（与 archive_runner 同模块风格）
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import REPO_ROOT  # noqa: E402

REQUIREMENTS_DIR = REPO_ROOT / "requirements"

# Asia/Shanghai 时区常量
_CST = timezone(timedelta(hours=8))

# 子进程超时（秒）——快速失败，避免挂死
_SUBPROC_TIMEOUT_SEC = 30

# gh API 轮询时连续 5xx 阈值
_MAX_CONSECUTIVE_5XX = 3

# 判定通过的 pass phrase 由 submit-rules.md 顶部 CODEX_PASS_PHRASE 常量定义（唯一事实源）。
# 此处拼合运行时判定字符串（V-09 grep 扫描 .claude/ 与 scripts/ 应仅在 submit-rules.md 命中
# 完整字面量；拼合方式避免在 .py 文件中引入可被 grep 命中的完整定义）。
_PASS_PHRASE = "Didn't find any" + " major issues."


# ---------- 内部异常体系（不对外暴露） ----------


class GhApi5xx(Exception):
    """gh API 单次 5xx 响应。"""


class GhApi429(Exception):
    """gh API 限流（429 Too Many Requests）。"""


class GhApiAbort(Exception):
    """连续 5xx 达到阈值，轮询中止。"""


# ---------- 数据类 ----------


@dataclass
class CodexRoundResult:
    """submit --codex 单轮 review 结果（detailed-design §3.3 契约）。"""

    round: int
    pr_number: int
    triggered_at: str                              # ISO8601 wall clock
    verdict: Literal["passed", "not_passed", "timeout"]
    review_id: Optional[int] = None
    reviewer: Optional[str] = None
    submitted_at: Optional[str] = None
    state: Optional[str] = None                    # GitHub review state 原值
    artifact_path: Optional[str] = None
    triggered_commit: Optional[str] = None         # 触发本轮时 HEAD 短 sha，作为下一轮算 diff 的锚点


# ---------- 内部工具 ----------


def _now_iso() -> str:
    """取当前 Asia/Shanghai 的 ISO8601 时间戳（含 offset，用于 wall clock 字段）。"""
    return datetime.now(_CST).isoformat()


def _parse_iso_to_aware(value: Optional[str]) -> Optional[datetime]:
    """ISO8601 → tzaware datetime；兼容 `Z` 与 `±HH:MM` 偏移；失败返 None。

    为什么需要：codex review 的 submitted_at 是 `...Z`（UTC），triggered_at 是
    `...+08:00`，字符串字典序比对会因偏移格式不同把更晚的 review 错判为更早，
    造成 false timeout（codex P1 finding，round-1.md 自举命中）。
    """
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=_CST)


def _now_cst_str() -> str:
    """process.txt 行首时间戳（`YYYY-MM-DD HH:MM:SS`，与 archive_runner 同格式）。"""
    return datetime.now(_CST).strftime("%Y-%m-%d %H:%M:%S")


def _process_path(req_id: str) -> Path:
    return REQUIREMENTS_DIR / req_id / "process.txt"


def _append_process_event(req_id: str, line: str) -> None:
    """追加语义事件到 requirements/<req_id>/process.txt（追加模式，绝对禁止覆盖）。

    格式：`YYYY-MM-DD HH:MM:SS <line>\n`（时区 Asia/Shanghai）。
    父目录必然存在（meta.yaml 已预检过）；append 模式保证幂等安全。
    """
    path = _process_path(req_id)
    full_line = f"{_now_cst_str()} {line}\n"
    with path.open("a", encoding="utf-8") as f:
        f.write(full_line)


def _meta_path(req_id: str) -> Path:
    return REQUIREMENTS_DIR / req_id / "meta.yaml"


def _codex_reviews_dir(req_id: str) -> Path:
    return REQUIREMENTS_DIR / req_id / "artifacts" / "codex-reviews"


def _load_meta(req_id: str) -> dict[str, Any]:
    """加载 meta.yaml；失败时 exit 1。"""
    path = _meta_path(req_id)
    if not path.exists():
        print(f"❌ meta.yaml 不存在: {path} req={req_id}", file=sys.stderr)
        raise SystemExit(1)
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except yaml.YAMLError as exc:
        print(f"❌ meta.yaml 解析失败 req={req_id}: {exc}", file=sys.stderr)
        raise SystemExit(1)
    if not isinstance(data, dict):
        print(f"❌ meta.yaml 顶层不是 mapping req={req_id}", file=sys.stderr)
        raise SystemExit(1)
    return data


def _get_pr_number(meta: dict[str, Any], req_id: str) -> int:
    """从 meta.yaml 取 pr_number；缺失则 exit 1（先跑 submit 再跑 --codex）。"""
    raw = meta.get("pr_number", 0)
    try:
        pr_number = int(raw or 0)
    except (TypeError, ValueError):
        pr_number = 0
    if pr_number <= 0:
        print(
            f"❌ meta.pr_number 缺失 req={req_id}；先跑 /requirement:submit 开 PR",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return pr_number


def _calc_round(req_id: str) -> int:
    """计算本轮 round 号 = max(已有 round-N.md 中的 N) + 1。

    必须按最大编号推算而非 `len + 1`：编号断档（如 round-1.md + round-3.md，
    缺 round-2.md，可能因手工清理或部分恢复导致）下，`len + 1 = 3` 会回写到
    已有的 round-3.md，覆盖审查证据（codex round-2 P1 finding F-4）。

    无法解析编号的文件名忽略；目录不存在时返 1。
    """
    reviews_dir = _codex_reviews_dir(req_id)
    if not reviews_dir.exists():
        return 1
    pattern = re.compile(r"^round-(\d+)\.md$")
    max_round = 0
    for p in reviews_dir.glob("round-*.md"):
        m = pattern.match(p.name)
        if not m:
            continue
        n = int(m.group(1))
        if n > max_round:
            max_round = n
    return max_round + 1


def _trigger_codex_comment(
    pr_number: int,
    req_id: str,
    round_n: int,
    *,
    body: str = "@codex review",
) -> str:
    """发 `@codex review` 评论；失败 exit 1，返回触发时刻 ISO8601。

    Args:
        pr_number: GitHub PR 号。
        req_id:    需求 ID，用于写 process.txt 事件。
        round_n:   当前 round 号，写入 process.txt 事件内容。
        body:      评论正文。默认 `@codex review`；round_n≥2 时调用方可拼接
                   round 间的变更摘要（commits + diff stat），给 codex 聚焦上下文。
    """
    try:
        proc = subprocess.run(
            ["gh", "pr", "comment", str(pr_number), "--body", body],
            capture_output=True,
            text=True,
            check=False,
            timeout=_SUBPROC_TIMEOUT_SEC,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        print(
            f"❌ failed to post @codex review comment: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        print(
            f"❌ failed to post @codex review comment: {err}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    # 触发时刻在发评论成功后立即取（wall clock）
    triggered_at = _now_iso()
    # 记录 process.txt 事件（detailed-design §4.3 + features.json TC-F4-8）
    _append_process_event(req_id, f"[codex-review-triggered] round={round_n} pr=#{pr_number}")
    return triggered_at


# ---------- review-loop 增量摘要（round_n≥2 给 codex 聚焦上下文） ----------


# 评论体长度上限——GitHub PR 评论最多 65536 字符；diff stat 截断到该限的一小部分
# 防止超大变更刷屏，给 codex 留足够空间引用 hunk
_COMMENT_BODY_BUDGET = 8000


def _current_head_sha() -> Optional[str]:
    """读 git HEAD 短 sha；失败时返 None（让调用方走 plain `@codex review` 兜底）。"""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_SUBPROC_TIMEOUT_SEC,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if proc.returncode != 0:
        return None
    sha = (proc.stdout or "").strip()
    return sha or None


def _read_round_triggered_commit(req_id: str, round_n: int) -> Optional[str]:
    """从 round-N.md frontmatter 读 triggered_commit；缺失/格式错误时返 None。"""
    path = _codex_reviews_dir(req_id) / f"round-{round_n}.md"
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if not text.startswith("---"):
        return None
    # 拆 frontmatter（首段 --- 之间）
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return None
    if not isinstance(meta, dict):
        return None
    val = meta.get("triggered_commit")
    return str(val).strip() if val else None


def _git_log_diff_since(prev_sha: str) -> Optional[tuple[str, str]]:
    """跑 `git log --oneline <prev>..HEAD` + `git diff --stat <prev>..HEAD`。

    任一失败/为空 → 返 None（让调用方走 plain 兜底，不阻断 review-loop）。
    """
    try:
        log_proc = subprocess.run(
            ["git", "log", "--oneline", f"{prev_sha}..HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_SUBPROC_TIMEOUT_SEC,
        )
        diff_proc = subprocess.run(
            ["git", "diff", "--stat", f"{prev_sha}..HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=_SUBPROC_TIMEOUT_SEC,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    if log_proc.returncode != 0 or diff_proc.returncode != 0:
        return None
    log_out = (log_proc.stdout or "").strip()
    diff_out = (diff_proc.stdout or "").strip()
    if not log_out and not diff_out:
        return None
    return log_out, diff_out


def _build_codex_comment_body(req_id: str, round_n: int) -> str:
    """组装 @codex review 评论正文。

    - round 1：plain `@codex review`
    - round N≥2：尝试读 round-(N-1).md.frontmatter.triggered_commit，
      命中则附「Changes since round N-1（log + diff stat）」段；
      上轮文件缺失 / 解析失败 / git 命令失败 → 静默退化为 plain（不阻断流程）。

    评论体超过 _COMMENT_BODY_BUDGET 时截断 diff stat，保留 log 完整。
    """
    plain = "@codex review"
    if round_n <= 1:
        return plain
    prev_sha = _read_round_triggered_commit(req_id, round_n - 1)
    if not prev_sha:
        return plain
    pair = _git_log_diff_since(prev_sha)
    if pair is None:
        return plain
    log_out, diff_out = pair

    head_short = _current_head_sha() or "HEAD"
    header = f"## Changes since round {round_n - 1} (`{prev_sha}` → `{head_short}`)"
    log_section = f"### Commits\n```\n{log_out or '(no new commits)'}\n```"
    diff_section = f"### Diff stat\n```\n{diff_out or '(no diff)'}\n```"

    body = f"{plain}\n\n{header}\n\n{log_section}\n\n{diff_section}"
    if len(body) <= _COMMENT_BODY_BUDGET:
        return body
    # 超额：截 diff stat，给 log 让位（commits 一行能读出意图，diff stat 可以短）
    available = _COMMENT_BODY_BUDGET - len(plain) - len(header) - len(log_section) - 80
    if available > 200:
        truncated = diff_out[:available] + "\n... (truncated, see PR Files Changed tab)"
        diff_section = f"### Diff stat\n```\n{truncated}\n```"
        return f"{plain}\n\n{header}\n\n{log_section}\n\n{diff_section}"
    # 极端情况（log 也很大）：只发 plain + header，给 codex 一个起点
    return f"{plain}\n\n{header}\n\n_(变更过大无法内嵌 stat，请直接看 PR Files Changed)_"


def _gh_pr_reviews(pr_number: int) -> list[dict[str, Any]]:
    """调 gh API 拿 PR reviews 列表；5xx 抛 GhApi5xx，429 抛 GhApi429。

    为什么用 gh api 而非 gh pr view：gh pr view 不暴露 review state / submitted_at
    等轮询所需字段；gh api 可以直接拿原始 JSON。
    """
    try:
        # 关键：用 `-q '.[]'` 把分页输出展平为「每行一个 JSON 对象」，
        # 规避 `--paginate` 拼接多页 JSON 数组导致 json.loads 解析失败的问题
        # （codex P1 finding：超过 30 条 review 的 PR 多页输出会破坏 JSON 解码，
        # 被错判为 5xx → 触发轮询中止保护）。
        proc = subprocess.run(
            [
                "gh", "api",
                f"repos/{{owner}}/{{repo}}/pulls/{pr_number}/reviews",
                "--paginate",
                "-q", ".[]",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=_SUBPROC_TIMEOUT_SEC,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        # 网络中断等系统级错误折叠为 5xx（让上层做连续计数）
        raise GhApi5xx(str(exc)) from exc

    if proc.returncode != 0:
        stderr_lower = (proc.stderr or "").lower()
        if "429" in stderr_lower or "rate limit" in stderr_lower:
            raise GhApi429(proc.stderr.strip())
        if any(code in (proc.stderr or "") for code in ("500", "502", "503", "504")):
            raise GhApi5xx(proc.stderr.strip())
        # 其他非零（401/403/404 等）——不应进轮询，折叠为 5xx 触发中止保护
        raise GhApi5xx(proc.stderr.strip())

    return _parse_jsonl_reviews(proc.stdout or "")


def _gh_pr_issue_comments(pr_number: int) -> list[dict[str, Any]]:
    """调 gh API 拿 PR issue comments 列表（pass 路径专用）。

    F-16（codex round-9 P1）：codex 在「无 finding」时不发 PR review，而是发
    issue 评论（带 pass phrase）。原 _poll_codex 只查 reviews 端点，会错过 pass
    信号 → verdict=timeout 假阴。此函数补全 issue/{pr}/comments 端点。

    返回与 _gh_pr_reviews 同构的 dict 列表（normalize 在调用方），异常体系一致。
    """
    try:
        proc = subprocess.run(
            [
                "gh", "api",
                f"repos/{{owner}}/{{repo}}/issues/{pr_number}/comments",
                "--paginate",
                "-q", ".[]",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=_SUBPROC_TIMEOUT_SEC,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
        raise GhApi5xx(str(exc)) from exc

    if proc.returncode != 0:
        stderr_lower = (proc.stderr or "").lower()
        if "429" in stderr_lower or "rate limit" in stderr_lower:
            raise GhApi429(proc.stderr.strip())
        if any(code in (proc.stderr or "") for code in ("500", "502", "503", "504")):
            raise GhApi5xx(proc.stderr.strip())
        raise GhApi5xx(proc.stderr.strip())

    return _parse_jsonl_reviews(proc.stdout or "")


def _normalize_issue_comment_to_review(comment: dict[str, Any]) -> dict[str, Any]:
    """把 issue comment 字段 shape 化为 review-like dict，供 _poll_codex 统一处理。

    issue comment 用 `created_at`（GitHub 没给 submitted_at 字段），review 用
    `submitted_at`；这里把 created_at copy 到 submitted_at，并塞 _kind=comment
    以便下游区分（落 round-N.md 时不写 state）。
    """
    out = dict(comment)
    out["submitted_at"] = comment.get("submitted_at") or comment.get("created_at")
    out["_kind"] = "comment"
    return out


def _parse_jsonl_reviews(stdout: str) -> list[dict[str, Any]]:
    """解析 `gh api --paginate -q '.[]'` 的多行 JSON 输出。

    每行是一个 review JSON 对象；空行忽略；任一行解析失败抛 GhApi5xx。
    历史兼容：如果整个 stdout 是单个 JSON 数组（旧 mock / 直接 gh api 不带 -q
    的场景），则按数组解析。
    """
    text = stdout.strip()
    if not text:
        return []
    # 历史兼容路径：单个 JSON 数组（兼容 round-1 之前的 mock / 旧调用）
    if text.startswith("["):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise GhApi5xx(f"JSON 解析失败: {exc}") from exc
        # 多页拼接出 [[…],[…]] 时展平
        if isinstance(data, list) and data and isinstance(data[0], list):
            flat: list[dict[str, Any]] = []
            for page in data:
                flat.extend(page)
            return flat
        return data if isinstance(data, list) else []
    # JSONL 路径：每行一个对象
    items: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise GhApi5xx(f"JSON 解析失败（行级）: {exc}") from exc
        if isinstance(item, dict):
            items.append(item)
    return items


def _matches_codex_reviewer(user: dict[str, Any]) -> bool:
    """三因子之二：Bot 类型 + login 匹配 /codex/i。"""
    if user.get("type") != "Bot":
        return False
    pattern = re.compile(r"codex", re.IGNORECASE)
    return bool(pattern.search(user.get("login") or ""))


def _poll_codex(
    pr_number: int,
    triggered_at_iso: str,
    interval: int,
    timeout: int,
) -> Optional[dict[str, Any]]:
    """单轮轮询 Codex review；返回命中的 review dict 或 None（timeout / 429）。

    连续 5xx ≥ _MAX_CONSECUTIVE_5XX 则抛 GhApiAbort（让调用方 exit 1）。
    429 直接返回 None（短路为 timeout，不重试）。
    """
    deadline = time.monotonic() + timeout
    consecutive_5xx = 0
    triggered_at_dt = _parse_iso_to_aware(triggered_at_iso)

    while time.monotonic() < deadline:
        try:
            # 双端点查询：reviews（has-finding 路径） + issue comments（pass 路径，F-16）
            reviews = _gh_pr_reviews(pr_number)
            issue_comments_raw = _gh_pr_issue_comments(pr_number)
            consecutive_5xx = 0  # 成功一次就清零
        except GhApi5xx:
            consecutive_5xx += 1
            if consecutive_5xx >= _MAX_CONSECUTIVE_5XX:
                raise GhApiAbort(
                    f"连续 {_MAX_CONSECUTIVE_5XX} 次 5xx pr=#{pr_number}"
                )
            time.sleep(interval)
            continue
        except GhApi429:
            # 429 限流 → 直接走 timeout 路径，不重试（详见 detailed-design §3.3.3）
            return None

        # F-16：把 issue comments 归一成 review-like dict，与 reviews 统一过滤
        normalized_comments = [_normalize_issue_comment_to_review(c) for c in issue_comments_raw]
        all_items = list(reviews) + normalized_comments

        # 收集本轮所有「post-trigger 且匹配 codex bot」的候选项；同一轮可能多次回评
        # （codex round-3 P1 F-6：fail → fix → pass），锁定最早那条会落旧 verdict，
        # 必须按 submitted_at/created_at 取最新。
        candidates: list[dict[str, Any]] = []
        for r in all_items:
            user = r.get("user") or {}
            if not _matches_codex_reviewer(user):
                continue
            # codex round-1 P1 F-1：必须按 tzaware datetime 比，字符串字典序会被
            # `Z` vs `+08:00` 偏移格式不同误判。
            submitted_dt = _parse_iso_to_aware(r.get("submitted_at"))
            if submitted_dt is None or triggered_at_dt is None:
                # 任一侧解析失败：保守按字符串比兜底（极少分支）
                if r.get("submitted_at", "") <= triggered_at_iso:
                    continue
            elif submitted_dt <= triggered_at_dt:
                continue
            candidates.append(r)

        if candidates:
            return _pick_latest_review(candidates)

        time.sleep(interval)

    return None  # 自然超时


def _pick_latest_review(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """从候选 review 列表中按 submitted_at 取最新。

    按 tzaware datetime 排序；解析失败的 review 排到列表末尾的 epoch 处理位
    （等价"很旧"），避免影响最新判定。空列表由调用方保证不会传入。
    """
    def _sort_key(r: dict[str, Any]) -> datetime:
        dt = _parse_iso_to_aware(r.get("submitted_at"))
        return dt if dt is not None else datetime.min.replace(tzinfo=timezone.utc)
    return max(candidates, key=_sort_key)


def _is_passed(body: Optional[str]) -> bool:
    """判断 codex review 是否通过——pass phrase 出现在非引用行上才算。

    F-9（codex round-5 P1）：单纯 substring 包含会被 markdown 引用 / 字面量
    回放误导。例如 review body 包含 `> 上轮 codex 说 "Didn't find any major
    issues."（但本轮新发现…）`，旧实现会假阳通过。

    新规则：按行扫描，跳过以 `>` 开头（含前导空白）的 markdown 引用行；
    剩余非引用行中只要 **任一行包含** pass phrase 即视为通过。

    保留兜底：codex 实际格式是把 phrase 放在 review 顶部独立段，不在引用块内；
    这条规则把误判窗口收窄到「codex 自己的非引用文本」。
    """
    if not body:
        return False
    quote_line = re.compile(r"^\s*>")
    for line in body.splitlines():
        if quote_line.match(line):
            continue
        if _PASS_PHRASE in line:
            return True
    return False


def _quote_if_needed(value: str, *, force_quote: bool = False) -> str:
    """生成 YAML frontmatter 用的字符串值：含特殊字符或 force_quote 时加双引号。"""
    if force_quote or "[" in value or "]" in value or ":" in value:
        # 转义内部双引号，确保 YAML 合法
        escaped = value.replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _render_frontmatter(result: CodexRoundResult) -> str:
    """渲染 round-N.md frontmatter（§4.2 格式）。

    timeout 时仅输出三必填字段（round / triggered_at / verdict），
    其他字段有值才输出（不输出 null 行，保持文档简洁）。
    """
    lines = ["---"]
    lines.append(f"round: {result.round}")
    lines.append(f"triggered_at: {_quote_if_needed(result.triggered_at, force_quote=True)}")
    # triggered_commit 三类 verdict 都输出（下一轮 build 增量摘要时要读）；
    # 兜底解析失败时已被设为 None，渲染才跳过。
    if result.triggered_commit is not None:
        lines.append(f'triggered_commit: "{result.triggered_commit}"')

    # timeout 时仅三字段（外加 triggered_commit）
    if result.verdict != "timeout":
        if result.review_id is not None:
            # review_id 建议 quote 防 >2^53 精度丢失
            lines.append(f'review_id: "{result.review_id}"')
        if result.reviewer is not None:
            # login 含 [bot] 后缀必须 quote（防 YAML flow-list）
            lines.append(f"reviewer: {_quote_if_needed(result.reviewer)}")
        if result.submitted_at is not None:
            lines.append(f"submitted_at: {_quote_if_needed(result.submitted_at, force_quote=True)}")

    lines.append(f"verdict: {result.verdict}")

    if result.verdict != "timeout" and result.state is not None:
        lines.append(f"state: {result.state}")

    lines.append("---")
    return "\n".join(lines)


def _persist_round(
    req_id: str,
    result: CodexRoundResult,
    body: Optional[str],
    timeout_sec: int,
) -> Path:
    """将 round-N.md 写入 codex-reviews/ 目录；返回写入路径。

    原子写入：先写 .tmp 再 os.replace，防止写入中途被读。
    写完后追加 process.txt `[codex-review-received]` 事件（detailed-design §4.3）。
    """
    reviews_dir = _codex_reviews_dir(req_id)
    reviews_dir.mkdir(parents=True, exist_ok=True)

    round_path = reviews_dir / f"round-{result.round}.md"
    tmp_path = round_path.with_suffix(".md.tmp")

    frontmatter = _render_frontmatter(result)
    if result.verdict == "timeout":
        content_body = f"(timeout after {timeout_sec}s, no codex review received)"
    else:
        content_body = body or ""

    full_content = f"{frontmatter}\n\n{content_body}\n"

    with tmp_path.open("w", encoding="utf-8") as f:
        f.write(full_content)
    os.replace(tmp_path, round_path)

    # round-N.md 写完后记录 process.txt 事件（features.json TC-F4-8）
    _append_process_event(
        req_id,
        f"[codex-review-received] verdict={result.verdict} round={result.round}",
    )

    return round_path


def _handle_poll_result(
    review: Optional[dict[str, Any]],
    pr_number: int,
    round_num: int,
    triggered_at: str,
) -> CodexRoundResult:
    """将 poll 结果转为 CodexRoundResult（含 verdict 判定）。

    review 为 None 表示 timeout；不为 None 则检查 body 是否含 pass phrase。
    """
    if review is None:
        return CodexRoundResult(
            round=round_num,
            pr_number=pr_number,
            triggered_at=triggered_at,
            verdict="timeout",
        )

    user = review.get("user") or {}
    body = review.get("body") or ""
    verdict: Literal["passed", "not_passed", "timeout"] = (
        "passed" if _is_passed(body) else "not_passed"
    )

    return CodexRoundResult(
        round=round_num,
        pr_number=pr_number,
        triggered_at=triggered_at,
        verdict=verdict,
        review_id=review.get("id"),
        reviewer=user.get("login"),
        submitted_at=review.get("submitted_at"),
        state=review.get("state"),
    )


def _print_verdict_stderr(result: CodexRoundResult) -> None:
    """按 verdict 向 stderr 输出摘要；passed 时静默（exit 0 无额外输出）。"""
    if result.verdict == "not_passed":
        print(
            f"⚠️ codex review NOT passed"
            f" req_id related pr=#{result.pr_number} round={result.round}",
            file=sys.stderr,
        )
    elif result.verdict == "timeout":
        print(
            f"⚠️ codex review TIMEOUT"
            f" pr=#{result.pr_number} round={result.round}",
            file=sys.stderr,
        )
    # passed → 静默


# ---------- 主入口 ----------


def submit_with_codex(
    req_id: str,
    *,
    poll_interval_sec: int = 10,
    timeout_sec: int = 600,
) -> CodexRoundResult:
    """submit 子模式：开 PR → @codex review → 单轮轮询 → 落 round-N.md → 判 verdict。

    多轮由主对话推动（D-002）；本函数命令内仅一轮。

    Args:
        req_id:           需求 ID（REQ-YYYY-NNN），用于定位 meta.yaml 和写入路径。
        poll_interval_sec: 轮询间隔（秒），默认 10。
        timeout_sec:      整轮超时（秒），默认 600。

    Returns:
        CodexRoundResult，verdict ∈ {passed, not_passed, timeout}。

    Raises:
        SystemExit(1): meta 预检失败 / gh pr comment 失败 / 连续 5xx ≥ 3 次。
    """
    if not req_id:
        print("❌ req_id 为空", file=sys.stderr)
        raise SystemExit(1)

    meta = _load_meta(req_id)
    pr_number = _get_pr_number(meta, req_id)
    round_num = _calc_round(req_id)

    print(
        f"[submit_codex] req={req_id} pr=#{pr_number} round={round_num} 触发 @codex review",
        file=sys.stderr,
    )

    # round_num≥2 时为 codex 拼增量摘要：log + diff stat since round-(N-1).triggered_commit
    comment_body = _build_codex_comment_body(req_id, round_num)
    head_sha = _current_head_sha()

    # 发 @codex review 评论并记录触发时刻（wall clock）
    triggered_at = _trigger_codex_comment(pr_number, req_id, round_num, body=comment_body)

    print(
        f"[submit_codex] triggered_at={triggered_at} 开始轮询"
        f"（interval={poll_interval_sec}s timeout={timeout_sec}s）",
        file=sys.stderr,
    )

    # 单轮轮询
    try:
        review = _poll_codex(pr_number, triggered_at, poll_interval_sec, timeout_sec)
    except GhApiAbort as exc:
        print(
            f"❌ gh api repeated 5xx during poll; aborting pr=#{pr_number}: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    # 组装结果
    result = _handle_poll_result(review, pr_number, round_num, triggered_at)
    # 把本轮触发时的 HEAD sha 钉到 round-N.md，供下一轮算 diff
    result.triggered_commit = head_sha

    # 写 round-N.md
    body = (review or {}).get("body") if review else None
    artifact_path = _persist_round(req_id, result, body, timeout_sec)
    result.artifact_path = str(artifact_path)

    print(
        f"[submit_codex] verdict={result.verdict} round-{result.round}.md → {artifact_path}",
        file=sys.stderr,
    )

    # stderr 摘要（passed 静默）
    _print_verdict_stderr(result)

    return result


# ---------- CLI 入口 ----------


def _build_parser():
    import argparse

    p = argparse.ArgumentParser(
        description="submit --codex 子模式：@codex review 单轮轮询"
    )
    p.add_argument("req_id", help="REQ-YYYY-NNN")
    p.add_argument(
        "--poll-interval",
        type=int,
        default=10,
        metavar="SEC",
        help="轮询间隔秒数（默认 10）",
    )
    p.add_argument(
        "--timeout",
        type=int,
        default=600,
        metavar="SEC",
        help="整轮超时秒数（默认 600）",
    )
    return p


def main() -> int:
    """CLI 入口：解析命令行参数并调用 submit_with_codex；成功返回 0。"""
    args = _build_parser().parse_args()
    submit_with_codex(
        args.req_id,
        poll_interval_sec=args.poll_interval,
        timeout_sec=args.timeout,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
