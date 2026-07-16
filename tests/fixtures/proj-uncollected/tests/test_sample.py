# 闸门自测夹具:AC-01 是 TestCase 方法(会被收集);AC-02 是顶层函数,
# unittest discover 永远不会执行它
import unittest


class SampleTest(unittest.TestCase):
    def test_ac01_valid_table_to_csv(self):
        self.assertTrue(True)


def test_ac02_no_table_exit_code():
    assert False  # 永不运行,断言假也无人知晓
