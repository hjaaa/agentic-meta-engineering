#!/usr/bin/env python3
"""meta_set.py — 替代 yq e 的最小 PyYAML CLI（Bug-5）。

支持 standard-8phase.yaml 的 phase-to-* / archive-finalize 节点用得到的全部
yq 写入语义；不实现 yq 完整能力（read / multi-doc / expressions 不在范围）。

用法：
    python3 scripts/lib/meta_set.py --path <yaml> \
        [--set .key=value ...]         # 字符串 set；value 视作字符串
        [--set-json .key=JSON ...]     # 把 JSON 解析后 set（支持数组/对象/数字/bool）
        [--append .key=value ...]      # 把 value 当字符串 append 到 list（list 不存在则建空）

key path 形如 `.foo` / `.foo.bar` / `.foo.bar.baz`；不支持数组下标。
yaml 文件不存在 → exit 1；key 路径中间节点非 dict → exit 2。

安全：
    --path 必须指向 requirements/ 或 runs/ 子树内的 yaml；禁止改 .claude/
    内 yaml（避免 workflow 节点意外覆盖配置）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
_ALLOWED_PREFIXES = ("requirements", "runs")


def _split_key(key: str) -> list[str]:
    if not key.startswith("."):
        raise ValueError(f"key 必须以 '.' 起始，got {key!r}")
    return [p for p in key[1:].split(".") if p]


def _set_path(data: dict, key: str, value):
    parts = _split_key(key)
    cur = data
    for p in parts[:-1]:
        nxt = cur.get(p)
        if nxt is None:
            nxt = {}
            cur[p] = nxt
        if not isinstance(nxt, dict):
            raise TypeError(f"key 路径 .{p} 当前值非 dict，无法继续下钻")
        cur = nxt
    cur[parts[-1]] = value


def _append_path(data: dict, key: str, value):
    parts = _split_key(key)
    cur = data
    for p in parts[:-1]:
        nxt = cur.get(p)
        if nxt is None:
            nxt = {}
            cur[p] = nxt
        if not isinstance(nxt, dict):
            raise TypeError(f"key 路径 .{p} 当前值非 dict，无法继续下钻")
        cur = nxt
    last = parts[-1]
    existing = cur.get(last)
    if existing is None:
        cur[last] = [value]
    elif isinstance(existing, list):
        existing.append(value)
    else:
        raise TypeError(f"key {key} 当前值非 list，无法 append")


def _parse_kv(raw: str) -> tuple[str, str]:
    if "=" not in raw:
        raise ValueError(f"参数缺 '='：{raw!r}")
    key, value = raw.split("=", 1)
    return key, value


def _check_path_allowed(yaml_path: Path) -> None:
    """fail-closed：只允许写 requirements/ 或 runs/ 下的 yaml。"""
    try:
        rel = yaml_path.resolve().relative_to(REPO_ROOT)
    except ValueError:
        print(
            f"❌ 路径 {yaml_path} 不在仓库根 {REPO_ROOT} 之下；拒绝写入",
            file=sys.stderr,
        )
        raise SystemExit(2)
    if not rel.parts or rel.parts[0] not in _ALLOWED_PREFIXES:
        print(
            f"❌ 路径白名单拒绝：{rel}；仅允许 requirements/* 或 runs/* 子树",
            file=sys.stderr,
        )
        raise SystemExit(2)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="替代 yq e 的最小 PyYAML CLI")
    parser.add_argument("--path", required=True, help="yaml 文件路径")
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        metavar=".KEY=VALUE",
        help="字符串 set；可重复",
    )
    parser.add_argument(
        "--set-json",
        action="append",
        default=[],
        metavar=".KEY=JSON",
        help="JSON 解析后 set；可重复",
    )
    parser.add_argument(
        "--append",
        action="append",
        default=[],
        metavar=".KEY=VALUE",
        help="字符串 append 到 list；可重复",
    )
    args = parser.parse_args(argv)
    yaml_path = Path(args.path)
    if not yaml_path.exists():
        print(f"❌ yaml 不存在：{yaml_path}", file=sys.stderr)
        return 1
    _check_path_allowed(yaml_path)
    try:
        data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        print(f"❌ yaml 解析失败：{exc}", file=sys.stderr)
        return 1
    if not isinstance(data, dict):
        print(f"❌ yaml 顶层不是 mapping：{yaml_path}", file=sys.stderr)
        return 1
    try:
        for s in args.set:
            k, v = _parse_kv(s)
            _set_path(data, k, v)
        for s in args.set_json:
            k, v = _parse_kv(s)
            _set_path(data, k, json.loads(v))
        for s in args.append:
            k, v = _parse_kv(s)
            _append_path(data, k, v)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2
    yaml_path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
