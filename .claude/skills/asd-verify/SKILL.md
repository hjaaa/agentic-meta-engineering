---
name: asd-verify
description: 运行 ASD 交付管道(pipeline.sh)并汇报结果。用户说"跑闸门"/"验证一下",或任何阶段需要在声称完成前拿证据时使用。
---

# asd-verify — 闸门验证

1. 运行 `bash asd/kernel/delivery/pipeline.sh [spec 路径]`(缺省取 asd/specs/ 最新一份)。
2. 全绿:向用户贴出关键输出行,此时才允许说"通过"。
3. 失败:读失败输出定位根因 → 修复 → 重跑。**同一闸门连续失败 3 次即停止自修复**,
   向用户汇报:失败闸门、三次尝试各自改了什么、当前判断——不许通过改闸门/改 manifest 让灯变绿。
