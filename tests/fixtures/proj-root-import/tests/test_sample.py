# 闸门自测夹具:tests/ 导入项目根级包——闸门运行器的导入环境必须与测试命令一致
import unittest

from pkg import helper


class SampleTest(unittest.TestCase):
    def test_ac01_valid_table_to_csv(self):
        self.assertTrue(helper())

    def test_ac02_no_table_exit_code(self):
        self.assertTrue(helper())
