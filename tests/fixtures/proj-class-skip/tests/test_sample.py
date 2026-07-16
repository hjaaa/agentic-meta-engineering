# 闸门自测夹具:整个 TestCase 被类级 skip,方法会被收集但零断言执行
import unittest


@unittest.skip("whole class disabled")
class SampleTest(unittest.TestCase):
    def test_ac01_valid_table_to_csv(self):
        self.assertTrue(True)

    def test_ac02_no_table_exit_code(self):
        self.assertTrue(True)
