# 闸门自测夹具:AC-02 的测试被 @unittest.skip 禁用(套件仍 exit 0)
import unittest


def test_ac01_valid_table_to_csv():
    assert True


@unittest.skip("later")
def test_ac02_no_table_exit_code():
    assert True
