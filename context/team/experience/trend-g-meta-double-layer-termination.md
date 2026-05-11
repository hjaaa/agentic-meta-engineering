# trend-G-meta 双层终结：governance gate self-coverage + ADR drift 脚本化

**沉淀原因**：跨需求会重复（A）+ AI 反复错（B）+ 跨会话需保留（C）

## 问题

review-loop 反复修代码层 finding 时，元信息层（governance gate / ADR / features.json touches / plan.md 数字）会**复发**——即"代码层修好了，但 governance test 自己被遗漏 / ADR 数字与代码漂移 / touches 字段与实际改动 set-equal 失败"。

REQ-2026-009 F-012 rev6 真审报告：
- rev5 修了 4 个 major（代码层）→ rev6 自引入 4 candidate major **集中元信息层**：
  - F-1 signoff.py 514 > 500 D-017 上限突破（plan.md ADR 数字过时）
  - F-4 _run_save CC=27 + 129 行 6 大职责（governance gate 漏检）
  - F-16 governance gate self-blind-spot（gate test 文件自身未在 touches 内）
  - F-22' D-016(6) ADR 撒谎回填（features.json touches 未同步）

## 根因

**单层 governance（只测代码逻辑）会让元信息漂移悄无声息**：
- governance test 自己写了断言但没断言"自己也在 touches 内"——self-blind-spot
- ADR 写"signoff.py < 495 行"是个数字，过段时间代码膨胀到 514 行，ADR 还在那儿——没人会去 grep ADR 数字 vs `wc -l` 实际值
- features.json touches 漏 governance test 文件 → review-critic 不会抓（只看代码层）

## 解法

**双层 governance** 同时跑（缺一不可）：

### 第 1 层：代码层 governance gate self-coverage 红线

新增 `tests/<...>/test_governance_self_coverage.py`：

```python
def test_gate_file_must_be_in_some_feature_touches_within_scope():
    """governance gate test 文件本身必须出现在 features.json 某个 feature 的 touches 内。
    避免 gate 漏抓 self-blind-spot——元信息层债务的零号 entry point。
    """
    governance_test_files = [
        "tests/lib/test_features_json_touches_consistency.py",
        # ... 其他 governance test
    ]
    features = json.load(open("requirements/REQ-XXXX/artifacts/features.json"))
    all_touches = {t for f in features["features"] for t in f.get("touches", [])}

    for gov_file in governance_test_files:
        assert any(gov_file in t or matches_glob(gov_file, t) for t in all_touches), (
            f"governance test {gov_file} 不在任何 feature touches 内 — self-blind-spot"
        )
```

### 第 2 层：元信息层 ADR drift 脚本化（±5 容差）

新增 `tests/<...>/test_adr_line_count_drift.py`：

```python
@pytest.mark.parametrize("file_path,adr_line_count,tolerance", [
    ("scripts/lib/save_review.py", 492, 5),
    ("scripts/lib/signoff.py", 434, 5),
    ("scripts/lib/save_review_validation.py", 47, 5),
])
def test_adr_line_count_in_sync(file_path, adr_line_count, tolerance):
    """plan.md ADR 中的行数声明 vs `wc -l` 实际值，±tolerance 容差。
    超容差时 fail，提示 ADR 与代码漂移——必须同 commit 同步。
    """
    actual = sum(1 for _ in open(file_path))
    assert abs(actual - adr_line_count) <= tolerance, (
        f"{file_path} 实际 {actual} 行，ADR 声明 {adr_line_count} ±{tolerance}；"
        f"漂移 {abs(actual - adr_line_count)} 行。"
    )
```

## 验证方法

应用双层后 trend-G-meta 应**真终结**：

- 真终结指标：rev N+1 的 trend-G-meta 不再复发元信息层 finding（即使代码层有新增也能维持 looks_clean ≥ 88）
- 假终结指标：只有第 1 层 → ADR 数字仍漂移；只有第 2 层 → governance gate 自身仍漏检

REQ-2026-009 F-012 rev6 应用后：rev5 84 → rev6 88（+4），元信息层 4 candidate major 全闭合 + 0 复发。

## 引用来源

- `requirements/REQ-2026-009/plan.md:201` — D-017 ADR（拆 signoff.py 子模块决策含行数声明）
- `requirements/REQ-2026-009/artifacts/review-20260511-085217.md` — F-012 rev6 报告 trend-G-meta 双层终结判定
- `tests/lib/test_features_json_touches_consistency.py` — governance gate self-coverage 实现参考
- `tests/lib/test_adr_line_count_drift.py` — ADR drift 脚本化校验实现参考
