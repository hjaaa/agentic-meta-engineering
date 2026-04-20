# 遍历 Markdown 同级 section 的边界问题

**沉淀原因**：跨需求重复出现（Phase 4 集成验收时踩到）

## 问题

用 awk 范围 `/^### N\./,/^###/` 想提取某个 section 的内容时，如果 section 在首或尾，范围内容为空——因为开始行本身满足模式，range 立即结束。

## 根因

awk 范围对"模式 A 和模式 B 相同"的情况处理异常：A 匹配即开始，下一行就检查 B 是否匹配，自身也算匹配。

## 解法

用 Python 正则按整个文本扫描所有 `^### N\.` 锚点，取锚点之间的内容：

```python
import re
with open('CLAUDE.md') as f:
    content = f.read()

sections = re.split(r'^### (\d+)\.', content, flags=re.MULTILINE)
# sections[0] = 前文, sections[1] = "1", sections[2] = section 1 内容, ...
```

## 验证方法

对已知有 N 个 section 的文件运行脚本，确认能正确提取全部 N 个 section（不漏首尾）。

## 引用来源

- `requirements/REQ-2026-001/notes.md`（Phase 4 Task 9 执行报告）
