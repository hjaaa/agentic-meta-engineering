# 闸门自测夹具:skipIf(False) 条件为假,测试实际执行——不得被当作禁用
import unittest


class SampleTest(unittest.TestCase):
    @unittest.skipIf(False, "condition is false, test runs")
    def test_ac01_valid_table_to_csv(self):
        self.assertTrue(True)

    def test_ac02_no_table_exit_code(self):
        self.assertTrue(True)
