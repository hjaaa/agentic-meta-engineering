# clean_downloads — 下载目录清理脚本设计

> 日期:2026-07-16

## Part I 背景与目标

提供一个零第三方依赖的 Python 3 单文件脚本 `scripts/clean_downloads.py`:对目标目录(默认
`~/Downloads`)顶层的散落文件按扩展名归档到类别目录,重名文件加序号避让,收尾删除空目录,
让下载目录保持整洁且不破坏用户自建的子目录结构。

## Part II 系统设计

单文件脚本,标准库 pathlib / shutil / argparse。执行流程(单向,无状态流转,不画图):

1. 解析参数:位置参数 `target`(缺省 `~/Downloads`)、开关 `--dry-run`。
2. 规划:扫描 target 顶层文件(跳过隐藏文件与目录),按扩展名映射出 `(src, dst)` 移动清单;
   dst 重名时依次探测 `name_1.ext`、`name_2.ext`… 取第一个空位,绝不覆盖。
3. 执行:逐条 `shutil.move`;`--dry-run` 时只打印计划,零改动。
4. 清空壳:自底向上删除 target 内所有空子目录(嵌套空壳一并删净),target 本身不删。
   空目录判定与删除不豁免隐藏目录(如空的 .cache/ 同样会被删除);第 2 步跳过隐藏条目仅指归档扫描。

类别映射(内置 dict,大小写不敏感;未知扩展名与无扩展名归 `Others`):

| 目录 | 扩展名 |
|---|---|
| Images | jpg jpeg png gif webp heic svg bmp tiff |
| Documents | pdf doc docx xls xlsx ppt pptx txt md csv rtf epub |
| Videos | mp4 mov mkv avi wmv flv webm |
| Audio | mp3 wav flac m4a aac ogg |
| Archives | zip rar 7z tar gz bz2 xz |
| Installers | dmg pkg exe msi apk deb rpm |
| Code | py js ts sh json yaml yml html css sql |
| Others | 其余全部 |

结构上为可测性拆成纯函数 + 薄 main:

- `categorize(filename) -> str`:文件名 → 类别目录名。
- `unique_dest(dest_dir, filename) -> Path`:重名序号探测。
- `plan_moves(target) -> list[tuple[Path, Path]]`:纯规划,不动文件系统。
- `remove_empty_dirs(target, dry_run) -> list[Path]`:自底向上删空目录,返回删除清单。
- `main()`:参数解析、执行、dry-run 分支。

错误处理:target 不存在或不是目录 → stderr 提示、退出码 1;单个文件移动失败(权限等)打印
警告后继续处理其余文件,结束时退出码非 0。符号链接按普通条目移动链接本身,不跟随。

方案选型只保留有真实取舍的决策:

| 决策点 | 选项 A | 选项 B | 最终选择 | 原因 |
|---|---|---|---|---|
| 重名处理 | 加序号避让 | 覆盖或跳过 | 加序号 | 不丢数据也不留残余,行为可预期 |
| 子目录文件 | 仅顶层 | 递归掏空 | 仅顶层 | 不破坏用户自建的目录组织 |
| 隐藏文件 | 跳过 | 一并归档 | 跳过 | .DS_Store 等系统文件移走反而制造混乱 |

## Part III 质量保障

### 验收标准

正常路径:

| # | Given | When | Then |
|---|---|---|---|
| AC-01 | 顶层有 a.jpg、b.pdf、c.zip | 运行脚本 | 三个文件分别位于 Images/、Documents/、Archives/ 下,顶层不再有它们 |
| AC-02 | 顶层有无扩展名文件 README 与未知扩展名 foo.xyz | 运行脚本 | 两者都位于 Others/ 下 |

重名与边界:

| # | Given | When | Then |
|---|---|---|---|
| AC-03 | Documents/ 已有 report.pdf,顶层也有一个内容不同的 report.pdf | 运行脚本 | 顶层文件移为 Documents/report_1.pdf,原 Documents/report.pdf 内容不变 |
| AC-04 | Documents/ 已有 report.pdf 与 report_1.pdf,顶层有 report.pdf | 运行脚本 | 新文件为 Documents/report_2.pdf |
| AC-05 | 存在空目录 empty/ 与嵌套空壳 a/b/(b 为空,a 只含 b) | 运行脚本 | empty/、a/b/、a/ 均被删除 |
| AC-06 | 子目录 keep/ 内有文件 x.txt | 运行脚本 | keep/x.txt 原样保留,未被移动 |
| AC-07 | 顶层有隐藏文件 .secret | 运行脚本 | .secret 仍在顶层,未被移动 |

预览与异常:

| # | Given | When | Then |
|---|---|---|---|
| AC-08 | 顶层有待归档文件与一个空目录 | 加 --dry-run 运行 | 逐行打印计划的移动与删除,目录树与运行前完全一致 |
| AC-09 | 目标目录路径不存在 | 运行脚本 | stderr 输出提示,退出码 1 |

### 测试策略

`scripts/test_clean_downloads.py`,标准库 unittest + `tempfile.TemporaryDirectory`,每条 AC 对应
一个 `def test_ac{nn}_<slug>` 测试,在临时目录里搭建 Given 的文件布局后调用脚本函数验证。
不测 `~/Downloads` 默认值的真实执行(会触碰用户真实目录),默认值只在参数解析层面覆盖;
单文件移动失败(权限)场景依赖平台行为,不做自动化测试,由代码评审保证 try/except 存在。

## 附录 决策确认表

所有需用户拍板的决策集中在此,评审时逐行过:

| # | 待拍板 | 选项 | 建议与理由 | 结论 |
|---|---|---|---|---|
| 1 | 归类方式 | 按类别分组 / 按扩展名字面 / 两级 | 按类别分组,贴合人查找习惯 | ✅ 按类别分组 |
| 2 | 目标范围 | 参数+默认 ~/Downloads 仅顶层 / 递归 / 写死 | 仅顶层,不破坏用户目录结构 | ✅ 参数+默认 ~/Downloads,仅顶层 |
| 3 | 安全策略 | 默认执行+--dry-run / 默认 dry-run / 无预览 | 默认执行+--dry-run,符合 CLI 惯例 | ✅ 默认执行+--dry-run |
| 4 | 实现语言 | Python / Bash | Python,好测好维护且接入现有闸门 | ✅ Python |
| 5 | 类别目录命名 | 中文 / 英文 | — | ✅ 英文(Images/Documents/…) |
| 6 | 重名序号格式 | name_1.ext / name (1).ext | name_1.ext,终端友好 | ✅ name_1.ext |
| 7 | 空目录判定 | 完全空(含嵌套空壳)/ 含 .DS_Store 也算空 | 只删完全空的,规则最简单 | ✅ 完全空才删 |
