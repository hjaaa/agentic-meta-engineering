# 闸门自测夹具:AC-01 有"活性"顶层函数(不被收集)+ 被 skip 的 TestCase 方法(被收集不执行),
# 两个检查各自都能骗过,交叉却无任何真实执行
import unittest


def test_ac01_valid_table_to_csv():
    assert True


class SampleTest(unittest.TestCase):
    @unittest.skip("disabled")
    def test_ac01_valid_table_to_csv(self):
        self.assertTrue(True)

    def test_ac02_no_table_exit_code(self):
        self.assertTrue(True)
