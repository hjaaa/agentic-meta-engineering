# 示例功能设计

> ASD-INJECTION: active

## 目标

闸门自测用最小 spec。

## 验收标准

| # | Given | When | Then |
|---|---|---|---|
| AC-01 | 输入合法 markdown 表格 | 调用转换 | 输出对应 CSV |
| AC-02 | 输入不含表格 | 调用转换 | stderr 提示且退出码 1 |

错误处理细节见 AC-02。
