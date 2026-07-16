#!/usr/bin/env bash
# ASD 闸门自测:正例全绿 + 负例必红(负例红不了 = 闸门失明)
set -u
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/.." && pwd)
fx="$here/fixtures"
gates="$root/asd/kernel/delivery/gates"
pipeline="$root/asd/kernel/delivery/pipeline.sh"
export ASD_MANIFEST="$fx/manifest.yaml"

pass=0; fail=0
expect() { # expect <期望rc> <描述> <命令...>
  local want=$1 desc=$2; shift 2
  "$@" >/dev/null 2>&1
  local got=$?
  if [ "$got" -eq "$want" ]; then
    echo "✓ $desc"; pass=$((pass + 1))
  else
    echo "✗ $desc(期望 rc=$want,实际 rc=$got)"; fail=$((fail + 1))
  fi
}

echo "── spec-lint ──"
expect 0 "正例通过"           bash "$gates/spec-lint.sh" "$fx/spec-good.md"
expect 1 "缺必备章节必红"      bash "$gates/spec-lint.sh" "$fx/spec-missing-section.md"
expect 1 "AC 重复定义必红"     bash "$gates/spec-lint.sh" "$fx/spec-dup-ac.md"
expect 1 "引用未定义 AC 必红"  bash "$gates/spec-lint.sh" "$fx/spec-undef-ref.md"
expect 1 "AC 编号断续必红"     bash "$gates/spec-lint.sh" "$fx/spec-gap-ac.md"

echo "── ac-coverage ──"
expect 0 "正例通过"           bash "$gates/ac-coverage.sh" "$fx/spec-good.md" "$fx/proj-good"
expect 1 "AC 无测试必红"       bash "$gates/ac-coverage.sh" "$fx/spec-good.md" "$fx/proj-missing"
expect 1 "测试被注释掉必红"     bash "$gates/ac-coverage.sh" "$fx/spec-good.md" "$fx/proj-commented"
expect 1 "测试被 skip 装饰器禁用必红" bash "$gates/ac-coverage.sh" "$fx/spec-good.md" "$fx/proj-skipped"
expect 0 "skip 遗留+活性替代测试应通过" bash "$gates/ac-coverage.sh" "$fx/spec-good.md" "$fx/proj-skipped-with-live"
expect 1 "多行 skip 装饰器必红"    bash "$gates/ac-coverage.sh" "$fx/spec-good.md" "$fx/proj-skipped-multiline"
expect 1 "文档字符串提及不算覆盖"   bash "$gates/ac-coverage.sh" "$fx/spec-good.md" "$fx/proj-doc-mention"
expect 1 "未被运行器收集必红"       env ASD_MANIFEST="$fx/manifest-unittest.yaml" bash "$gates/ac-coverage.sh" "$fx/spec-good.md" "$fx/proj-uncollected"
expect 0 "TestCase 方法收集通过"    env ASD_MANIFEST="$fx/manifest-unittest.yaml" bash "$gates/ac-coverage.sh" "$fx/spec-good.md" "$fx/proj-collected"
expect 1 "类级 skip 必红"          env ASD_MANIFEST="$fx/manifest-unittest.yaml" bash "$gates/ac-coverage.sh" "$fx/spec-good.md" "$fx/proj-class-skip"
expect 1 "活性文本+被跳过收集交叉必红" env ASD_MANIFEST="$fx/manifest-unittest.yaml" bash "$gates/ac-coverage.sh" "$fx/spec-good.md" "$fx/proj-cross-skip"
expect 0 "skipIf(False) 实际执行应通过" env ASD_MANIFEST="$fx/manifest-unittest.yaml" bash "$gates/ac-coverage.sh" "$fx/spec-good.md" "$fx/proj-skipif-false"
expect 0 "tests 导入根级包应通过"      env ASD_MANIFEST="$fx/manifest-unittest.yaml" bash "$gates/ac-coverage.sh" "$fx/spec-good.md" "$fx/proj-root-import"

echo "── pipeline ──"
expect 0 "正例全通"           env ASD_ROOT="$fx/proj-good" bash "$pipeline" "$fx/spec-good.md"
expect 1 "坏 spec 首步即停"    env ASD_ROOT="$fx/proj-good" bash "$pipeline" "$fx/spec-missing-section.md"

echo "── 结果:$pass 通过,$fail 失败 ──"
exit "$fail"
