# Python 循环导入永久绑定 fallback stub 风险

**沉淀原因**：跨需求会重复（任何 Python 项目都可能踩）、AI 反复犯（典型 Python 陷阱，try/except ImportError 看似安全实则危险）、跨会话需保留（语言级 gotcha）。

## 问题

`scripts/lib/save_review.py` 顶层：

```python
try:
    from check_reviews import is_signed_off
except ImportError:
    def is_signed_off(verdict):
        return False  # 占位
```

`scripts/lib/check_reviews.py` 顶层 `import save_review`，`is_signed_off` 定义**在 import 之后**。当 check_reviews 是入口模块时：

1. check_reviews 加载到 `import save_review` 行
2. save_review 开始加载 → `from check_reviews import is_signed_off`
3. check_reviews 此时只加载到 line 28，`is_signed_off` 在 line 39 还没定义 → ImportError
4. fallback 触发 → save_review 永久绑定 stub `return False`
5. save_review 加载完成
6. check_reviews 继续，定义真 `is_signed_off`，但 save_review 已经 import 完了

后果：`save_review._check_cr_rules` 用的是 stub，CR-1 / CR-4 / R003（依赖 is_signed_off 判定签字状态）**永远走 False 分支**，规则静默失效。Codex Review 在 PR #48 inline comment P1 报告。

## 根因

Python 循环导入的"半成品模块"机制：A → B → A，第二次 import A 拿到的是部分加载的模块对象，未定义符号触发 ImportError。`try/except ImportError` 兜底常被当作"防御性编程"，实际上把"基础设施级 bug"(import 顺序错)伪装成"运行时正常"——更危险。

## 解法

**根治：重新组织模块依赖**，让一方真正不依赖另一方。具体到本案：

1. 把 `SIGNOFF_PASS` / `is_signed_off` 定义**移到** check_reviews.py 的 `import save_review` **之前**（is_signed_off 仅做 dict lookup，零依赖 save_review）
2. save_review.py 删 try/except fallback，直接 import：
   ```python
   from check_reviews import is_signed_off  # noqa: E402
   ```
3. 加注释说明顺序约束：

> 注意：SIGNOFF_PASS / is_signed_off 必须定义在 `import save_review` 之前——save_review 顶层会从本模块导入，若放后面循环导入会让 save_review 永久绑定 stub。

4. **加回归测试**强制两种 import 顺序都拿到真函数（`tests/lib/test_signoff_no_circular_import.py`）：
   ```python
   @pytest.mark.parametrize("import_first", ["check_reviews", "save_review"])
   def test_is_signed_off_returns_true_for_approved_after_either_import_order(...):
       assert save_review.is_signed_off is check_reviews.is_signed_off
   ```

**禁忌**：用 `try/except ImportError` 兜底是反模式——它把循环导入 bug 静默化，正确做法是消除循环。

## 验证方法

- 回归测试：`pytest tests/lib/test_signoff_no_circular_import.py`
- 手工：两种顺序 `import` 后比较 `module.fn is other_module.fn`，应同 ID

## 引用来源

- `scripts/lib/check_reviews.py:33-50` + `scripts/lib/save_review.py:33-37`
- 回归测试：`tests/lib/test_signoff_no_circular_import.py`
- Codex Review on PR #48（commit `e8fa757`）
