#!/usr/bin/env bash
# ASD 知识检索自测:命中/未命中/空库
set -u
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/.." && pwd)
loader="$root/asd/kernel/knowledge/loader.sh"
fx="$here/fixtures/kb"

pass=0; fail=0
check() { # check <描述> <期望包含> <命令...>
  local desc=$1 want=$2; shift 2
  local out
  out=$("$@" 2>&1)
  if echo "$out" | grep -q "$want"; then
    echo "✓ $desc"; pass=$((pass + 1))
  else
    echo "✗ $desc(输出未包含: $want)"; fail=$((fail + 1)); echo "$out" | head -3
  fi
}

check "关键词命中条目"      "命中:"        env ASD_KB="$fx" bash "$loader" "订单 幂等"
check "命中输出条目正文"    "唯一索引"      env ASD_KB="$fx" bash "$loader" "幂等"
check "大小写不敏感"        "命中:"        env ASD_KB="$fx" bash "$loader" "RPC"
check "无命中给出提示"      "无命中"       env ASD_KB="$fx" bash "$loader" "不存在的词"
check "元字符按字面处理不通配" "无命中"      env ASD_KB="$fx" bash "$loader" "r.c"
check "空库不报错"          "知识库不存在"  env ASD_KB="$fx-nonexist" bash "$loader" "任意"

echo "── 结果:$pass 通过,$fail 失败 ──"
exit "$fail"
