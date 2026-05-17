"""check_sourcing.py 反引号 / fenced code 屏蔽（D-015）单测。

覆盖：
  - TC-MASK-1：反引号包裹的「（来源：xxx）」不报 E002（描述性元字符）
  - TC-MASK-2：fenced code block 内「（来源：xxx）」不报 E002
  - TC-MASK-3：反引号外真实存在的「（来源：path）」仍报 E002（路径不存在）
  - TC-MASK-4：反引号包 [待补充] 段落不应触发 E001 + W001（元字符示例）
  - TC-MASK-5：行号定位仍然准确（mask 用空格保留长度）
  - TC-MASK-6：常规未含代码块的文档不受影响（回归保护）
"""
from __future__ import annotations

import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_LIB_DIR = _REPO_ROOT / "scripts" / "lib"
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import check_sourcing  # noqa: E402
from common import Report  # noqa: E402


def _run_check(tmp_path: Path, content: str, name: str = "doc.md") -> Report:
    md = tmp_path / name
    md.write_text(content, encoding="utf-8")
    report = Report()
    check_sourcing.check_file(md, report)
    return report


def _codes(report: Report) -> list[str]:
    return [code for _file, _sev, code, _msg in report.findings()]


def _messages_by_code(report: Report, code: str) -> list[str]:
    return [msg for _f, _s, c, msg in report.findings() if c == code]


def test_inline_code_masks_source_marker_no_e002(tmp_path):
    """given_inline_code_with_source_marker_when_check_then_no_e002（TC-MASK-1）。"""
    md = "# review\n\n格式约定：``（来源：xxx）`` 表示引用占位。\n"
    report = _run_check(tmp_path, md)
    assert "E002" not in _codes(report), (
        f"反引号内的元字符不应触发 E002，实际 codes={_codes(report)}"
    )


def test_fenced_code_block_masks_source_marker_no_e002(tmp_path):
    """given_fenced_code_with_source_marker_when_check_then_no_e002（TC-MASK-2）。"""
    md = "# spec\n\n示例代码块：\n\n```\n这里写（来源：xxx）格式占位。\n```\n"
    report = _run_check(tmp_path, md)
    assert "E002" not in _codes(report), (
        f"fenced code 内不应触发 E002，实际 codes={_codes(report)}"
    )


def test_real_source_marker_outside_code_still_reports_e002(tmp_path):
    """given_real_source_marker_outside_code_when_check_then_e002_kept（TC-MASK-3）。"""
    md = "# spec\n\n实测数据 A（来源：nonexistent/path.md）。\n"
    report = _run_check(tmp_path, md)
    assert "E002" in _codes(report), (
        f"反引号外真路径不存在仍应报 E002，实际 codes={_codes(report)}"
    )


def test_inline_code_masks_pending_marker_no_e001(tmp_path):
    """given_inline_pending_marker_when_check_then_no_e001_no_w001（TC-MASK-4）。

    场景：review 报告里说"`[待补充]` 是文档三态标记之一"——这是元字符示例，
    不是真正的待补充段落。不应触发 E001（要素 < 3）也不应触发 W001（缺章节）。
    """
    md = "# review\n\n三态标记示例：`[待补充]` 表示需要后续补完。\n"
    report = _run_check(tmp_path, md)
    codes = _codes(report)
    assert "E001" not in codes, f"反引号内的 [待补充] 不应触发 E001，实际 codes={codes}"
    assert "W001" not in codes, f"反引号内的 [待补充] 不应触发 W001，实际 codes={codes}"


def test_line_number_preserved_after_masking(tmp_path):
    """given_real_e002_after_inline_code_when_check_then_line_number_correct（TC-MASK-5）。

    保证 mask 用空格替换（保留长度）后，E002 报错的行号定位仍然精准。
    """
    md = (
        "# spec\n"                                  # 1
        "\n"                                        # 2
        "格式约定：``（来源：xxx）`` 是占位。\n"   # 3
        "\n"                                        # 4
        "实测引用（来源：nonexistent.md）。\n"      # 5
    )
    report = _run_check(tmp_path, md)
    e002_msgs = _messages_by_code(report, "E002")
    assert any("第 5 行" in m for m in e002_msgs), (
        f"E002 应定位在第 5 行，实际 messages={e002_msgs}"
    )


def test_plain_doc_unchanged_regression(tmp_path):
    """given_plain_valid_doc_when_check_then_no_findings（TC-MASK-6 回归保护）。"""
    md = "# 合法文档\n\n正文内容，没有约束断言也没有引用。\n"
    report = _run_check(tmp_path, md)
    assert _codes(report) == [], (
        f"合法文档不应有任何 finding，实际 codes={_codes(report)}"
    )
