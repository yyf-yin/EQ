"""Fixed-table number extraction runs under its own role, inheriting researcher's."""
from pathlib import Path

import yaml

from company_research.fixed_collection import EXTRACTOR, SlotExtraction, periods as input_periods
from company_research.llm import Gateway, ModelConfig, openai_payload
from company_research.schemas import SourceRecord
from test_fixed_collection import prepared, context

EXAMPLE = Path(__file__).parents[2] / 'configs' / 'models.example.yaml'


def model(name, **extra):
    return ModelConfig(protocol='openai', api_key_env='UNUSED_TEST_KEY', base_url='https://fixture.invalid',
                       model=name, max_tokens=32000, structured_mode='json', **extra)


def test_slot_extractor_inherits_researcher_route_and_limits():
    limits = {'default': {'input_capacity': 120000, 'context_capacity': 160000, 'timeout': 120},
              'researcher': {'input_capacity': 36000, 'context_capacity': 68000, 'max_output_tokens': 32000,
                             'temperature': 0}}
    gateway = Gateway({'base': model('base'), 'research': model('research')},
                      {'default': 'base', 'researcher': 'research'}, role_limits=limits)
    assert gateway.route(EXTRACTOR) == 'research'
    assert gateway.limits(EXTRACTOR) == gateway.limits('researcher')
    # Without a researcher route either, the default route applies.
    assert Gateway({'base': model('base')}, {'default': 'base'}).route(EXTRACTOR) == 'base'


def test_slot_extractor_overrides_only_what_it_sets():
    limits = {'default': {'input_capacity': 120000, 'context_capacity': 160000, 'timeout': 120},
              'researcher': {'input_capacity': 36000, 'context_capacity': 68000, 'max_output_tokens': 32000},
              'slot_extractor': {'max_output_tokens': 16000}}
    gateway = Gateway({'base': model('base'), 'research': model('research'), 'extract': model('extract')},
                      {'default': 'base', 'researcher': 'research', 'slot_extractor': 'extract'},
                      role_limits=limits)
    assert gateway.route(EXTRACTOR) == 'extract'
    assert gateway.route('researcher') == 'research'
    own = gateway.limits(EXTRACTOR)
    assert own.max_output_tokens == 16000
    assert (own.input_capacity, own.context_capacity, own.timeout) == (36000, 68000, 120)
    assert gateway.limits('researcher').max_output_tokens == 32000


def test_example_no_thinking_entry_routes_only_slot_extraction():
    lines = EXAMPLE.read_text(encoding='utf-8').splitlines()
    # Uncomment the optional entry and its route exactly as a user would.
    start = next(i for i, line in enumerate(lines) if line.strip() == '# deepseek_flash_extract:')
    block = []
    for line in lines[start:]:
        if not line.strip():
            break
        block.append(line.replace('  # ', '', 1))
    entry = yaml.safe_load('\n'.join(block))['deepseek_flash_extract']
    route = next(line for line in lines if line.strip().startswith('# slot_extractor: deepseek_flash_extract'))
    routes = yaml.safe_load(EXAMPLE.read_text(encoding='utf-8'))['routes'] | yaml.safe_load(route.strip()[2:])
    assert entry['extra_body'] == {'thinking': {'type': 'disabled'}}
    assert routes['slot_extractor'] == 'deepseek_flash_extract'
    assert routes['researcher'] == 'deepseek_flash'
    config = ModelConfig.model_validate(entry | {'model': 'fixture'})
    payload = openai_payload(config, [{'role': 'user', 'content': '{}'}], schema=SlotExtraction)
    assert payload['thinking'] == {'type': 'disabled'}


async def test_fixed_extraction_calls_use_slot_extractor_role(tmp_path):
    w, g, store, run = prepared(tmp_path, rows=[])
    c = await context(w)
    w.fixed_collection.initialize(c)
    title = '固定测试公司2025年年度报告'
    source = SourceRecord(kind='upload', title=title, content=title + '\n合并利润表\n单位：元\n2025年 2024年\n营业收入 100 90\n')
    store.execution_put(run.run_id, 'execution_meta', 'fixed-source-manifest',
                        {'bindings': {p: [source.source_id] for p in input_periods(c['brief'])}})
    roles = []
    original = g.structured

    async def record_role(role, messages, schema):
        roles.append((role, schema.__name__))
        return await original(role, messages, schema)

    g.structured = record_role
    await w.fixed_collection.extract_document(c, source, True)
    assert roles and all(role == EXTRACTOR for role, name in roles if name == 'SlotExtraction')
