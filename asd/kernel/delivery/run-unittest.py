#!/usr/bin/env python3
"""运行 unittest discover 套件,逐测试输出「<测试id> <结局>」(ok|skipped|failed|error)。
被收集但被跳过(含类级 skip)/失败/根本未收集,在输出中一目了然。
用法: run-unittest.py <start_dir> <pattern>"""
import os
import sys
import unittest


class OutcomeResult(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.buffer = True  # 静音被测代码的 stdout/stderr

    def addSuccess(self, test):
        super().addSuccess(test)
        self.rows.append((test.id(), "ok"))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.rows.append((test.id(), "skipped"))

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.rows.append((test.id(), "failed"))

    def addError(self, test, err):
        super().addError(test, err)
        self.rows.append((test.id(), "error"))


def main():
    start_dir, pattern = sys.argv[1], sys.argv[2]
    # 对齐 `python -m unittest discover` 的导入环境:cwd(项目根)入 sys.path,
    # 否则本脚本以绝对路径调用时 sys.path[0] 是脚本目录,tests/ 导入根级包会失败
    sys.path.insert(0, os.getcwd())
    suite = unittest.defaultTestLoader.discover(start_dir, pattern=pattern)
    result = OutcomeResult()
    suite.run(result)
    for tid, status in result.rows:
        print(tid, status)
    return 0


if __name__ == "__main__":
    sys.exit(main())
