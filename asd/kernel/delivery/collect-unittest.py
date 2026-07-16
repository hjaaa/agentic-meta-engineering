#!/usr/bin/env python3
"""打印 unittest discover 实际收集到的全部测试 id(每行一个)。
用法: collect-unittest.py <start_dir> <pattern>"""
import sys
import unittest


def walk(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from walk(t)
        else:
            yield t


def main():
    start_dir, pattern = sys.argv[1], sys.argv[2]
    suite = unittest.defaultTestLoader.discover(start_dir, pattern=pattern)
    for t in walk(suite):
        print(t.id())
    return 0


if __name__ == "__main__":
    sys.exit(main())
