# 闸门自测夹具:AC-02 有遗留 skip 测试 + 活性替代测试,应视为已覆盖
import unittest


def test_ac01_valid_table_to_csv():
    assert True


@unittest.skip("legacy, replaced below")
def test_ac02_no_table_exit_code_old():
    assert True


def test_ac02_no_table_exit_code():
    assert True
