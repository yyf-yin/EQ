"""Method guidance from skills/ is attached to analysis, writing and review prompts."""
from company_research.agents import request_messages
from company_research.methods import guidance, method_keys


def test_block_templates_map_to_methods():
    assert method_keys('writer', 'F05') == ['roic', 'moat']
    assert method_keys('financial_analyzer', 'I01-2') == ['industry']
    assert method_keys('critical_reviewer', 'F01') == ['bias']
    assert method_keys('researcher', 'F01') == []


def test_guidance_reaches_system_prompt_only_for_method_roles():
    writer = request_messages('writer', {'section': {'block_id': 'F02'}})[0]['content']
    assert '研究方法' in writer and '债务、偿债与财务弹性' in writer and '不自行计算' in writer
    researcher = request_messages('researcher', {'task': {'block_id': 'F02'}})[0]['content']
    assert '研究方法' not in researcher
    # Trading-only and hand-off boilerplate stay out of the prompt.
    assert '止损' not in guidance('critical_reviewer', 'R01') and '证据与交接' not in writer


def test_guidance_can_be_disabled_and_tolerates_missing_skills(monkeypatch, tmp_path):
    monkeypatch.setenv('CDR_METHOD_GUIDANCE', 'false')
    assert guidance('writer', 'F01') == ''
    monkeypatch.setenv('CDR_METHOD_GUIDANCE', 'true')
    monkeypatch.setenv('CDR_SKILLS_DIR', str(tmp_path))
    assert guidance('writer', 'F01') == ''
