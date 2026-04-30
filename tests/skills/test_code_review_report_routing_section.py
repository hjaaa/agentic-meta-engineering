"""
测试 code-review-report SKILL 和模板的路由说明段 + 待 sign-off 提示段。

验证：
1. SKILL.md 包含路由说明段（含 routing_confirmed_by / checker_route 占位）
2. SKILL.md 包含待 sign-off 提示段（含 /code-review:signoff 命令 + --trivial 选项）
3. 模板中包含警示内容（phase-transition / submit / 阻断）
4. 两个新段都在 verdict 摘要段之后
"""

from pathlib import Path


def test_routing_explanation_section_in_skill():
    """验证 SKILL.md 中包含路由说明段。"""
    skill_file = Path(__file__).resolve().parents[2] / '.claude' / 'skills' / 'code-review-report' / 'SKILL.md'
    content = skill_file.read_text(encoding='utf-8')

    # 验证路由说明段标题
    assert '### 路由说明' in content, "缺少路由说明段标题"

    # 验证关键占位字段
    assert 'routing_confirmed_by.decision' in content, "缺少 routing_confirmed_by.decision 占位"
    assert 'routing_confirmed_by.confirmed_by' in content, "缺少 routing_confirmed_by.confirmed_by 占位"
    assert 'routing_confirmed_by.confirmed_at' in content, "缺少 routing_confirmed_by.confirmed_at 占位"
    assert 'checker_route' in content, "缺少 checker_route 占位"
    assert 'skipped_checkers' in content, "缺少 skipped_checkers 占位"


def test_signoff_prompt_section_in_skill():
    """验证 SKILL.md 中包含待 sign-off 提示段。"""
    skill_file = Path(__file__).resolve().parents[2] / '.claude' / 'skills' / 'code-review-report' / 'SKILL.md'
    content = skill_file.read_text(encoding='utf-8')

    # 验证待 sign-off 提示段标题
    assert '### 待 sign-off 提示' in content, "缺少待 sign-off 提示段标题"

    # 验证命令示例
    assert '/code-review:signoff' in content, "缺少 /code-review:signoff 命令示例"
    assert '--trivial' in content, "缺少 --trivial 快速通道说明"

    # 验证警示内容
    assert 'phase-transition' in content or 'submit' in content, "缺少 phase-transition 或 submit 警示"
    assert '阻断' in content, "缺少阻断警示"


def test_routing_section_in_template():
    """验证 review-report.md.tmpl 中包含路由说明段。"""
    template_file = (
        Path(__file__).resolve().parents[2] /
        '.claude' / 'skills' / 'code-review-report' / 'templates' / 'review-report.md.tmpl'
    )
    content = template_file.read_text(encoding='utf-8')

    # 验证路由说明段标题和内容
    assert '## 路由说明' in content, "模板缺少路由说明段"
    assert '__ROUTING_DECISION__' in content or 'routing' in content.lower(), "模板缺少路由决策占位"


def test_signoff_prompt_section_in_template():
    """验证 review-report.md.tmpl 中包含待 sign-off 提示段。"""
    template_file = (
        Path(__file__).resolve().parents[2] /
        '.claude' / 'skills' / 'code-review-report' / 'templates' / 'review-report.md.tmpl'
    )
    content = template_file.read_text(encoding='utf-8')

    # 验证待 sign-off 提示段
    assert '## 待 sign-off 提示' in content, "模板缺少待 sign-off 提示段"
    assert '/code-review:signoff' in content, "模板缺少 /code-review:signoff 命令"
    assert '--trivial' in content, "模板缺少 --trivial 选项"

    # 验证警示内容
    assert 'feature-lifecycle-manager' in content or 'GATE-REVIEW-VERDICT' in content, "模板缺少下游门禁警示"


def test_conclusion_enum_updated_in_template():
    """验证模板中的 conclusion 描述已更新为新枚举。"""
    template_file = (
        Path(__file__).resolve().parents[2] /
        '.claude' / 'skills' / 'code-review-report' / 'templates' / 'review-report.md.tmpl'
    )
    content = template_file.read_text(encoding='utf-8')

    # 验证新枚举的说明
    assert 'looks_clean' in content, "模板缺少 looks_clean 说明"
    assert 'needs_attention' in content, "模板缺少 needs_attention 说明"
    assert 'blocked' in content, "模板缺少 blocked 说明"


def test_sections_after_verdict():
    """验证新两段在 verdict 摘要段之后。"""
    template_file = (
        Path(__file__).resolve().parents[2] /
        '.claude' / 'skills' / 'code-review-report' / 'templates' / 'review-report.md.tmpl'
    )
    content = template_file.read_text(encoding='utf-8')

    # 查找各段位置
    verdict_pos = content.find('## 结论')
    routing_pos = content.find('## 路由说明')
    signoff_pos = content.find('## 待 sign-off 提示')
    verdict_detail_pos = content.find('## 裁决明细')

    # 验证顺序：verdict -> routing -> signoff -> verdict_detail
    assert verdict_pos != -1, "模板缺少结论段"
    assert routing_pos != -1, "模板缺少路由说明段"
    assert signoff_pos != -1, "模板缺少待 sign-off 提示段"
    assert verdict_detail_pos != -1, "模板缺少裁决明细段"

    assert verdict_pos < routing_pos < signoff_pos < verdict_detail_pos, (
        "新段位置不正确，应该是：结论 -> 路由说明 -> 待 sign-off 提示 -> 裁决明细"
    )


if __name__ == '__main__':
    test_routing_explanation_section_in_skill()
    test_signoff_prompt_section_in_skill()
    test_routing_section_in_template()
    test_signoff_prompt_section_in_template()
    test_conclusion_enum_updated_in_template()
    test_sections_after_verdict()
    print("✓ 所有测试通过")
