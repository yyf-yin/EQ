import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from company_research.agents import FactProposal, ResearchExtraction, bind_extraction
from company_research.schemas import SourceRecord


def fact(value, quote=None):
    return {'source_id':'s','quote':quote or f'营业收入 {value} 百万元',
            'metric_code':'revenue','period':'2025A','unit':'CNY_million',
            'value':value,'actual_or_forecast':'actual'}


@pytest.mark.parametrize('value', ['1787-1833','848-905','1787–1833','848~905',
                                 '848至905','>=848','≤905','100以下','1787-','N/A',None])
def test_non_scalar_values_never_become_point_facts(value):
    with pytest.raises(ValidationError):
        FactProposal.model_validate(fact(value))


def test_mixed_batch_preserves_valid_facts_and_range_evidence():
    raw={'evidence':[], 'facts':[fact('100'),fact('1787-1833'),fact('848-905')],
         'followup_queries':[], 'gaps':[]}
    output=ResearchExtraction.model_validate_json(json.dumps(raw))
    assert [f.value for f in output.facts] == [Decimal('100')]
    assert len(output.rejected_facts) == len(output.gaps) == 2
    assert output.rejected_facts[0]['proposal']['value'] == '1787-1833'
    assert output.rejected_facts[1]['proposal']['value'] == '848-905'
    source=SourceRecord(source_id='s',kind='local',title='资料',
                        content='营业收入 100 百万元\n营业收入 1787-1833 百万元\n营业收入 848-905 百万元')
    evidence,facts,warnings=bind_extraction(output,[source],'600519')
    assert len(facts) == 1 and facts[0].value == Decimal('100')
    assert len(evidence) == 3 and len(warnings) == 2
    # The cached validated batch must retain quarantine details without duplicating evidence.
    restored=ResearchExtraction.model_validate(output.model_dump(mode='json'))
    assert restored == output
    assert len(raw['facts']) == 3 and not raw['gaps']


def test_quarantined_quote_still_needs_source_verification():
    output=ResearchExtraction.model_validate({'evidence':[], 'facts':[fact('848-905')],
                                             'followup_queries':[], 'gaps':[]})
    source=SourceRecord(source_id='s',kind='local',title='资料',content='无此数据')
    evidence,facts,warnings=bind_extraction(output,[source],'600519')
    assert not evidence and not facts and len(warnings) == 2


def test_unrelated_schema_errors_still_fail_validation():
    bad=fact('1787-1833');del bad['period']
    with pytest.raises(ValidationError):
        ResearchExtraction.model_validate({'evidence':[], 'facts':[bad], 'followup_queries':[], 'gaps':[]})


@pytest.mark.parametrize(('value','expected'), [('1,234.50','1234.50'),('-100','-100'),('12.5%','0.125')])
def test_existing_scalar_formats(value, expected):
    assert FactProposal.model_validate(fact(value)).value == Decimal(expected)
