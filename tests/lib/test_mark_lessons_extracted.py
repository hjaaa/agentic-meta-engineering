"""mark_lessons_extracted.py 单元测试。

覆盖：
  - 正常路径：lessons_extracted: false → true（changed=True）
  - 幂等：lessons_extracted: true → True（changed=False）
  - 字段缺失：视同 false，会被加上 true
  - meta.yaml 不存在 → exit 1 R-MARK-NO-META
  - yaml 解析失败 → exit 1 R-MARK-YAML
  - 写入失败（mock os.replace 抛 OSError）→ exit 1 R-MARK-WRITE
  - 原子写：临时文件 .tmp 不残留

外部依赖：纯 yaml + tempfile，无 subprocess / 网络。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "lib"))

import mark_lessons_extracted as mle  # noqa: E402


# ---------- fixture ----------


def _make_meta(tmp_path: Path, *, lessons_extracted=None) -> Path:
    req_dir = tmp_path / "REQ-2099-001"
    req_dir.mkdir()
    meta = {
        "id": "REQ-2099-001",
        "title": "测试需求",
        "phase": "testing",
        "branch": "feat/req-2099-001",
        "base_branch": "develop",
        "pr_number": 99,
        "created_at": "2026-05-04 19:00:00",
        "project": "agentic-meta-engineering",
    }
    if lessons_extracted is not None:
        meta["lessons_extracted"] = lessons_extracted
    (req_dir / "meta.yaml").write_text(
        yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)
    )
    return req_dir / "meta.yaml"


@pytest.fixture
def fake_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(mle, "REQUIREMENTS_DIR", tmp_path)
    return tmp_path


# ---------- 正常路径 ----------


def test_marks_false_to_true(fake_repo: Path) -> None:
    """lessons_extracted=False → 改为 True，返回 changed=True。"""
    meta_path = _make_meta(fake_repo, lessons_extracted=False)

    changed = mle.mark_lessons_extracted("REQ-2099-001")

    assert changed is True
    data = yaml.safe_load(meta_path.read_text())
    assert data["lessons_extracted"] is True


def test_idempotent_when_already_true(fake_repo: Path) -> None:
    """lessons_extracted=True → 不写文件，返回 changed=False。"""
    meta_path = _make_meta(fake_repo, lessons_extracted=True)
    mtime_before = meta_path.stat().st_mtime_ns

    changed = mle.mark_lessons_extracted("REQ-2099-001")

    assert changed is False
    # mtime 不变，证明文件未被重写
    assert meta_path.stat().st_mtime_ns == mtime_before


def test_missing_field_treated_as_false_and_set_to_true(fake_repo: Path) -> None:
    """缺 lessons_extracted 字段 → 视同 False，加上并设为 True。"""
    meta_path = _make_meta(fake_repo, lessons_extracted=None)
    data_before = yaml.safe_load(meta_path.read_text())
    assert "lessons_extracted" not in data_before

    changed = mle.mark_lessons_extracted("REQ-2099-001")

    assert changed is True
    data_after = yaml.safe_load(meta_path.read_text())
    assert data_after["lessons_extracted"] is True


# ---------- 错误路径 ----------


def test_no_meta_file_aborts_with_code(
    fake_repo: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """meta.yaml 不存在 → exit 1 + stderr 含 R-MARK-NO-META。"""
    with pytest.raises(SystemExit) as excinfo:
        mle.mark_lessons_extracted("REQ-2099-NOTEXIST")
    assert excinfo.value.code == 1
    assert "R-MARK-NO-META" in capsys.readouterr().err


def test_empty_req_id_aborts(capsys: pytest.CaptureFixture) -> None:
    """req_id 为空 → exit 1 + stderr 含 R-MARK-REQ-ID。"""
    with pytest.raises(SystemExit) as excinfo:
        mle.mark_lessons_extracted("")
    assert excinfo.value.code == 1
    assert "R-MARK-REQ-ID" in capsys.readouterr().err


def test_invalid_yaml_aborts(
    fake_repo: Path,
    capsys: pytest.CaptureFixture,
) -> None:
    """meta.yaml 解析失败 → exit 1 + stderr 含 R-MARK-YAML。"""
    req_dir = fake_repo / "REQ-2099-001"
    req_dir.mkdir()
    (req_dir / "meta.yaml").write_text("key: : invalid: : :\n  badly nested\n: : :")

    with pytest.raises(SystemExit) as excinfo:
        mle.mark_lessons_extracted("REQ-2099-001")
    assert excinfo.value.code == 1
    assert "R-MARK-YAML" in capsys.readouterr().err


def test_write_failure_aborts_and_cleans_tmp(
    fake_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    """os.replace 抛 OSError → exit 1 + stderr 含 R-MARK-WRITE，临时文件被清理。"""
    _make_meta(fake_repo, lessons_extracted=False)

    def _fail_replace(src, dst):
        raise OSError("disk full（mock）")

    monkeypatch.setattr(mle.os, "replace", _fail_replace)

    with pytest.raises(SystemExit) as excinfo:
        mle.mark_lessons_extracted("REQ-2099-001")
    assert excinfo.value.code == 1
    assert "R-MARK-WRITE" in capsys.readouterr().err
    # 没有 .tmp 残留
    leftover = list((fake_repo / "REQ-2099-001").glob("meta.yaml.*.tmp"))
    assert leftover == [], f"临时文件未清理：{leftover}"


# ---------- CLI 入口烟雾测试 ----------


def test_main_prints_marked_message(
    fake_repo: Path,
    capsys: pytest.CaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI 入口：false → true 时 stdout 含 'marked'。"""
    _make_meta(fake_repo, lessons_extracted=False)
    monkeypatch.setattr(sys, "argv", ["mark_lessons_extracted.py", "REQ-2099-001"])

    rc = mle.main()
    assert rc == 0
    assert "marked req=REQ-2099-001" in capsys.readouterr().out


def test_main_prints_already_true_for_idempotent(
    fake_repo: Path,
    capsys: pytest.CaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CLI 入口：已 true 时 stdout 含 'already-true'。"""
    _make_meta(fake_repo, lessons_extracted=True)
    monkeypatch.setattr(sys, "argv", ["mark_lessons_extracted.py", "REQ-2099-001"])

    rc = mle.main()
    assert rc == 0
    assert "already-true req=REQ-2099-001" in capsys.readouterr().out
