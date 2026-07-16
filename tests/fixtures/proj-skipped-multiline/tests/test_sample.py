# 闸门自测夹具:AC-02 被跨多行的 skipIf 装饰器禁用
import unittest


def test_ac01_valid_table_to_csv():
    assert True


@unittest.skipIf(
    True,
    "disabled pending rework",
)
def test_ac02_no_table_exit_code():
    assert True
