# 合并区间 diff 看不见"引入后又还原"的中间提交变更

关键词: 合并区间 diff, review-package, 复审误报, 净零变更, git show

对一段提交区间做整体 diff(如 `review-package BASE..HEAD`、`git diff BASE..HEAD`)时,
若某行在区间内被中间提交改坏、又被后续提交改回,净变化为零——该行在合并 diff 里
显示为普通上下文行,完全不出现 `+`/`-` 标记。复审者只看合并 diff 会得出
"报告声称的修复没有 diff 证据"的结论,把真实发生过的修复误判为虚假声明。

**为什么**: clean_downloads 终审复审真实发生过一次:b3fca5e 把 docstring 的
"subdirectories" 改成了单数(笔误),5d69e91 改回复数;复审看 1071853..5d69e91
的合并 diff,该行是 context,遂给出 Important 级"修复声明无证据"——实为误报,
controller 用 `git show 5d69e91` 查证单个提交后仲裁澄清。

**怎么应用**: 复审多提交区间时,凡是"报告声称改了 X 但合并 diff 里 X 是上下文行"
的矛盾,先 `git show <单个提交> -- <文件>` 逐提交查证再下结论;controller 收到
此类 finding 也应先按单提交仲裁,不要直接派修复。
