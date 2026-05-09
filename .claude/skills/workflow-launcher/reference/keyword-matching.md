# 关键词匹配参考手册

本文件是 workflow-launcher Skill 的路由表。launcher 主入口 SKILL.md 交叉引用本文件。

---

## §4.1 字符长度计数规则

- 一个汉字 = 1（Python `len()` 计）
- 一个 ASCII 字符 = 1
- 空格 = 1
- 标点符号（如 `:`）= 1
- 统一使用 Python `len(s)` 计算，不使用 Unicode 字节数

---

## §4.1.1 六类关键词清单（含长度与映射命令）

| 类 | 关键词 | 长度 | 映射命令 |
|---|---|---:|---|
| **continue** | `继续之前的需求` | 7 | `/workflow:continue` |
| **continue** | `继续这个需求` | 6 | `/workflow:continue` |
| **continue** | `接着做` | 3 | `/workflow:continue` |
| **continue** | `继续` | 2 | `/workflow:continue` |
| **review** | `code review` | 11 | `/workflow:run code-review-embedded` |
| **review** | `跑下代码评审` | 6 | `/workflow:run code-review-embedded` |
| **review** | `跑代码评审` | 5 | `/workflow:run code-review-embedded` |
| **review** | `审一下` | 3 | `/workflow:run code-review-embedded` |
| **new** | `开个新需求` | 5 | `/workflow:new standard-8phase "<title>"` |
| **new** | `新建需求` | 4 | `/workflow:new standard-8phase "<title>"` |
| **new** | `创建需求` | 4 | `/workflow:new standard-8phase "<title>"` |
| **release** | `release` | 7 | `/workflow:run release-cut`（Post-MVP）|
| **release** | `我要发版` | 4 | `/workflow:run release-cut`（Post-MVP）|
| **release** | `打版本` | 3 | `/workflow:run release-cut`（Post-MVP）|
| **approve** | `approve` | 7 | `/workflow:approve` |
| **approve** | `批准` | 2 | `/workflow:approve` |
| **approve** | `通过` | 2 | `/workflow:approve` |
| **reject** | `reject:` | 7 | `/workflow:reject <reason>` |
| **reject** | `不通过` | 3 | `/workflow:reject <reason>` |
| **reject** | `驳回` | 2 | `/workflow:reject <reason>` |

---

## §4.1.2 按长度降序排列的最长匹配序

| 排序 | 关键词 | 长度 | 类 |
|---:|---|---:|---|
| 1 | `code review` | 11 | review |
| 2 | `继续之前的需求` | 7 | continue |
| 2 | `approve` | 7 | approve |
| 2 | `reject:` | 7 | reject |
| 2 | `release` | 7 | release |
| 6 | `继续这个需求` | 6 | continue |
| 6 | `跑下代码评审` | 6 | review |
| 8 | `开个新需求` | 5 | new |
| 8 | `跑代码评审` | 5 | review |
| 10 | `新建需求` | 4 | new |
| 10 | `创建需求` | 4 | new |
| 10 | `我要发版` | 4 | release |
| 13 | `接着做` | 3 | continue |
| 13 | `审一下` | 3 | review |
| 13 | `打版本` | 3 | release |
| 13 | `不通过` | 3 | reject |
| 17 | `继续` | 2 | continue |
| 17 | `批准` | 2 | approve |
| 17 | `通过` | 2 | approve |
| 17 | `驳回` | 2 | reject |

**length=7 等长冲突层**：`继续之前的需求` / `approve` / `reject:` / `release` 四条同长，当用户输入同时命中其中 ≥2 条时触发 ask 兜底。

---

## §4.2 匹配语义

| 关键词类型 | 匹配方式 | 正例 | 负例 |
|---|---|---|---|
| ASCII（如 `approve` / `release`） | `\b<keyword>\b` 词边界正则 | "please approve" → 命中 | "approved" / "releases" → 不命中 |
| 中文（如 `继续` / `审一下`） | substring（`kw in user_input`） | "我要继续之前的需求" → 命中"继续之前的需求" | — |
| 混合标点（如 `reject:`） | substring（`reject:` in user_input） | "reject:理由太弱" → 命中 | "rejected" → 不命中（无冒号） |
| 含空格 ASCII 短语（如 `code review`） | `\bcode review\b`（单空格字面量 + 词边界） | "please code review this" → 命中 | "code  review"（双空格）→ 不命中（保守） |

**匹配优先原则**：最长匹配优先（§4.1.2 序）；state tiebreaker 在前（§4.3）。

---

## §4.3 三步仲裁伪码（D-008）

```python
def match_keyword(
    user_input: str,
    active_runs: list,  # duck typing：只读 .state 属性
) -> tuple[Optional[str], Optional[str], Optional[ConflictReason]]:
    """
    返回：(command, args, conflict)
    - command: 匹配到的命令字符串，如 "/workflow:approve"
    - args:    附加参数（如 reject reason / new title），无则 None
    - conflict: ConflictReason(reason, candidates)，等长冲突时设置
    三项均为 None 表示无命中，launcher 不接管。
    """
    # Step 1：state tiebreaker
    has_approval_pending = any(r.state == "approval_pending" for r in active_runs)
    if has_approval_pending:
        for kw in [k for k in KEYWORDS if k.category in ("approve", "reject")]:
            if kw.matches(user_input):
                return kw.command, kw.extract_args(user_input), None

    # Step 2：最长匹配（降序扫描所有关键词）
    sorted_kws = sorted(KEYWORDS, key=lambda k: -k.length)
    hits = [kw for kw in sorted_kws if kw.matches(user_input)]

    # Step 3：等长冲突兜底
    if len(hits) >= 2 and hits[0].length == hits[1].length:
        equal_top = [h for h in hits if h.length == hits[0].length]
        return None, None, ConflictReason("equal_length", equal_top)

    # Step 4：有命中或无命中
    if hits:
        return hits[0].command, extract_args(user_input, hits[0]), None
    return None, None, None  # 无命中，launcher 不接管
```

---

## §4.4 等长冲突 ask 兜底模板

当 Step 3 触发时，向用户输出：

```
我同时检测到以下 N 个意图（关键词长度都为 K）：
  1. "<kw1>" → <command1>
  2. "<kw2>" → <command2>
  ...
请明示要执行哪一个，或换一种说法。
```

- N = 等长命中关键词数量
- K = 关键词长度（如 7）
- ask 后用户回复直接送回 launcher 进行二次匹配，**不引入轮次状态**
