#!/usr/bin/env bash
# mock-claude.sh
# 用于集成测试的 claude 命令 stub。
# 通过 MOCK_CLAUDE_MODE 环境变量控制行为，模拟 claude -p 的四种典型结果。
# 设计原则：吞下所有 --add-dir / --output-format / -p 等参数不报错。

set -eu

# 吞下所有参数——我们不解析它们，只关心环境变量
while [[ $# -gt 0 ]]; do
  shift
done

# 根据 MOCK_CLAUDE_MODE 决定行为（默认 success）
MODE="${MOCK_CLAUDE_MODE:-success}"

case "$MODE" in
  success)
    # 模拟 claude -p 成功返回 markdown 经验列表
    cat <<'EOF'
- 关键决策：选择 mkdir 原子锁方案代替 flock，因 macOS/Linux 跨平台兼容性更好
- 踩过的坑：bash 3.2 不支持 mapfile/readarray，需改用 while read 逐行读取
- 验证过的事实：disown $! 在 macOS bash 3.2 语法正确，可脱离进程组
- 踩过的坑：claude -p 在大 stdin 时 exit 0 但输出为空（issue #7263），需 </dev/null
- 验证过的事实：tail -n 60 截断后 worker 流程正常，覆盖约 30 轮对话
EOF
    exit 0
    ;;
  fail)
    # 模拟 claude -p 非零退出（网络超时、认证失败等场景）
    exit 1
    ;;
  empty)
    # 模拟命中 bug-7263：exit 0 但 stdout 为空
    # stdout 输出空字符串（不打印任何内容）
    exit 0
    ;;
  slow)
    # 模拟 claude -p 挂住，用于验证 worker 30s watchdog 超时机制
    sleep 60
    cat <<'EOF'
- 这条输出不会被看到，因为 watchdog 会在 30s 后 kill -9 worker
EOF
    exit 0
    ;;
  *)
    # 未知模式，保守地 exit 1
    echo "mock-claude: unknown MOCK_CLAUDE_MODE=${MODE}" >&2
    exit 1
    ;;
esac
