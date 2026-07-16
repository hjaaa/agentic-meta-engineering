# ASD Orchestrator 规则

以下规则是本项目的用户偏好,优先于 Superpowers 插件 skill 中的默认约定;
不修改 Superpowers 源码,五个注入点挂在其既有阶段上。

## 1. 知识前置(brainstorming 探索项目上下文时)

- 开始提问之前,先运行 `bash asd/kernel/knowledge/loader.sh "<需求关键词 3-5 个>"`,
  命中条目全文读入作为设计输入;无命中则照常继续。
- 知识条目中"禁止/勿"类事实,未经用户确认不得违反,也不得当作可推翻的猜测。

## 2. 产物位置与格式(Form Follows Reviewer)

- spec 写入 `asd/specs/YYYY-MM-DD-<topic>-design.md`,结构严格按
  `asd/kernel/orchestrator/templates/spec-template.md`(Part I-IV + 决策确认表);
  不写 `docs/superpowers/specs/`。
- plan 写入 `asd/plans/YYYY-MM-DD-<feature>.md`,不写 `docs/superpowers/plans/`。
- 呈现设计给用户评审时,决策确认表单独过一遍——需要拍板的判断不许淹没在正文里。

## 3. AC 命名律

- 验收标准必须是 Given-When-Then 表格,每行以 `| AC-NN |` 开头,编号从 AC-01 全局
  递增、不复用;正文引用场景时使用 AC 编号。
- plan 中每条 AC 至少对应一个测试,测试名匹配 manifest 的 `ac_test_pattern`
  (默认 `def test_ac{nn}_<slug>`);没有测试可对应的 AC 是坏 AC,在 spec 阶段就改掉。

## 4. 闸门验证(evidence before claims)

- 任何"完成/通过/修好了"的声明之前,必须运行
  `bash asd/kernel/delivery/pipeline.sh <spec 路径>` 且全绿,并贴出关键输出行;
  没跑过 = 未验证,不许声称。
- 管道失败:读失败输出 → 修复 → 重跑。**同一闸门连续失败 3 次即停止自修复**,向用户
  汇报失败闸门、三次尝试内容与当前判断;不许通过修改闸门脚本或 manifest 让灯变绿。
- 进入 finishing-a-development-branch 之前,pipeline 必须全绿。

## 5. 知识回流(开发收尾时)

- finishing-a-development-branch 收尾前问用户:"本次有没有'差点猜错'的事实值得沉淀?"
  有则用 asd-learn skill 落入 `asd/knowledge/` 并更新 index.md。
- 只沉淀"事实"(隐式依赖、历史坑、领域约束);"规矩"类改进建议写入 CLAUDE.md。
