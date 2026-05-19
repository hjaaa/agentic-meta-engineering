"""
测试 code-quality-reviewer Agent 的三档结论规则和明文禁止段。

验证：
1. 新三档枚举（looks_clean / needs_attention / blocked）出现在结论规则段
2. 旧三档映射（→ `approved` / → `needs_revision` / → `rejected`）不出现在结论规则段
3. 明文禁止段包含关键字（human_signoff + 卡点 B）
"""

import re
from pathlib import Path


def test_three_tier_conclusion_enum_present():
    """验证新三档枚举字面量在结论规则中出现。"""
    agent_file = Path(__file__).resolve().parents[2] / '.claude' / 'agents' / 'code-quality-reviewer.md'
    content = agent_file.read_text(encoding='utf-8')

    # 验证三个新枚举值在文件中出现
    assert '`looks_clean`' in content, "新枚举 looks_clean 缺失"
    assert '`needs_attention`' in content, "新枚举 needs_attention 缺失"
    assert '`blocked`' in content, "新枚举 blocked 缺失"


def test_old_conclusion_mapping_not_in_rules():
    """验证结论规则段中不含指向旧枚举的映射（→ `approved` 等）。"""
    agent_file = Path(__file__).resolve().parents[2] / '.claude' / 'agents' / 'code-quality-reviewer.md'
    content = agent_file.read_text(encoding='utf-8')

    # 搜索指向旧名的映射模式（→ `approved` 等）
    # 这个正则捕捉形如 "→ `approved`" 或 "→ approved" 的模式
    pattern = r'→\s*`?approved\b|→\s*`?needs_revision\b|→\s*`?rejected\b'
    matches = re.findall(pattern, content)

    # 不应该有任何结论规则的旧名映射
    assert len(matches) == 0, f"发现指向旧枚举的映射（结论规则段不应包含）：{matches}"


def test_explicit_prohibition_segment_present():
    """验证明文禁止段存在且包含关键约束（20260519-remove-human-signoff F-005 同步迁移）。

    历史：原断言含 `❌ 写入 human_signoff` + `卡点 B`；本期 F-001/F-002/F-003 下线
    human_signoff 字段与卡点 B 体系后，agent.md 同步删除，断言迁移到新口径
    （reviewer 只输出机器结论 + 软确认由用户在主对话进行）。
    """
    agent_file = Path(__file__).resolve().parents[2] / '.claude' / 'agents' / 'code-quality-reviewer.md'
    content = agent_file.read_text(encoding='utf-8')

    # 验证明文禁止段的存在
    assert '明文禁止' in content, "缺少明文禁止段标题"
    assert '❌ 输出 `approved`' in content, "缺少禁止输出 approved 的说明"
    assert '❌ 输出 `needs_revision` / `rejected`' in content, "缺少禁止输出旧枚举的说明"

    # 验证 reviewer 只输出机器结论（替代原 human_signoff / 卡点 B 表述）
    assert 'reviewer 只输出机器结论' in content, "缺少 'reviewer 只输出机器结论' 表述"


def test_equivalence_class_descriptions_present():
    """验证三档对应的等价类描述存在。"""
    agent_file = Path(__file__).resolve().parents[2] / '.claude' / 'agents' / 'code-quality-reviewer.md'
    content = agent_file.read_text(encoding='utf-8')

    # 验证结论规则的等价类描述
    assert '无 keep 的 critical' in content, "缺少 no_critical 等价类描述"
    assert '有 keep 的 major' in content, "缺少 has_major 等价类描述"
    assert '有 keep 的 critical' in content, "缺少 has_critical 等价类描述"


def test_conclusion_examples_updated():
    """验证示例中的 conclusion 字段值已从旧名改为新名。"""
    agent_file = Path(__file__).resolve().parents[2] / '.claude' / 'agents' / 'code-quality-reviewer.md'
    content = agent_file.read_text(encoding='utf-8')

    # 统计 "conclusion": "looks_clean/needs_attention/blocked" 出现次数
    looks_clean_count = content.count('"conclusion": "looks_clean"')

    # 至少应该有示例
    assert looks_clean_count >= 1, "示例中缺少 conclusion=looks_clean"

    # 验证示例中没有旧名
    # （注意：反义引用中的 approved 应该保留，但不应该在 conclusion 值中）
    assert '"conclusion": "approved"' not in content, "示例中不应包含旧的 conclusion=approved"
    assert '"conclusion": "needs_revision"' not in content, "示例中不应包含旧的 conclusion=needs_revision"
    assert '"conclusion": "rejected"' not in content, "示例中不应包含旧的 conclusion=rejected"


if __name__ == '__main__':
    test_three_tier_conclusion_enum_present()
    test_old_conclusion_mapping_not_in_rules()
    test_explicit_prohibition_segment_present()
    test_equivalence_class_descriptions_present()
    test_conclusion_examples_updated()
    print("✓ 所有测试通过")
