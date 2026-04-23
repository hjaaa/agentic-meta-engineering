# 时间戳统一约定

本项目所有**写入文件**的时间戳统一使用：

| 项 | 值 |
|---|---|
| 格式 | `YYYY-MM-DD HH:MM:SS` |
| 时区 | Asia/Shanghai（UTC+8，CST） |
| 不带时区后缀 | 默认由本规范界定，不在每行显式标注 `+0800` |

## 适用范围

- `requirements/<id>/process.txt` 的每一行（语义事件）
- `requirements/<id>/process.tool.log` 的每一行（工具日志）
- `requirements/<id>/notes.md` 的 `- [时间戳] [phase] 内容`
- `meta.yaml` 的 `created_at` / `completed_at`
- Skill / Agent / Command 里所有文本格式时间戳

## 生成命令

**Shell**（Hook / Skill 推荐）：

```bash
TZ=Asia/Shanghai date +"%Y-%m-%d %H:%M:%S"
# 输出: 2026-04-23 15:10:40
```

**Python**（scripts/lib/*.py）：

```python
from datetime import datetime, timezone, timedelta
CST = timezone(timedelta(hours=8))
datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
```

## 文件名/目录名里的紧凑变体

涉及文件系统（避免空格）的时间戳用 **`YYYYMMDD-HHMMSS`**（东八区）：

- 代码审查报告：`review-YYYYMMDD-HHMMSS.md`
- 回退归档目录：`artifacts/.rollback-YYYYMMDD-HHMMSS/`

## 例外

- 分支名：`chore/sync-skeleton-$(date +%Y%m%d)` 只用到"天"精度，本地时间可接受（跨时区偏差 ≤ 1 天无实质影响）
- 绝对不能出现：单纯的 Unix 时间戳字符串、`YYYY/MM/DD`、`MM-DD-YYYY` 等任意其他格式

## 向后兼容

历史需求（`log_layout=legacy` 时代）写入的时间戳为 UTC ISO 8601（带 `T` 和 `Z`）。以下场景**必须同时接受新旧两种**：

- `scripts/lib/check_meta.py` 对 `created_at` / `completed_at` 的解析
- `scripts/lib/check_plan.py` 对 `process.txt` 里 `phase-transition` 时间戳的解析
- Skill 读取历史数据时（例如 session-restorer）

新写入**必须**统一为新格式。

## 事实源

本约定是 `meta-schema.yaml` 的 `format.created_at` / `format.completed_at` 枚举语义的事实源；Hook / Skill / Agent 引用此文档即可。
