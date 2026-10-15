"""Validate this workspace's simple frontmatter, links, copies and acceptance arithmetic.

No model is invoked. Numeric results validate expected answers, not skill execution.
"""
from pathlib import Path
import hashlib
import json
import math
import re
import sys
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
BOOKS = [(ROOT/'证券分析师的最佳实践指南','equity-research-best-practices'),
         (ROOT/'价值 公司金融的四大基石','value-four-cornerstones')]
errors = []
counts = {'skill_entrypoints':0,'capability_cards':0,'synced_promoted_cards':0,
          'json_files':0,'relative_links':0,'existing_trigger_cases':0,
          'acceptance_behavior_cases':0,'acceptance_arithmetic_cases':0}

def require(ok, message):
    if not ok: errors.append(message)

def read_frontmatter(path):
    text = path.read_text(encoding='utf-8')
    match = re.match(r'^---\n(.*?)\n---\n',text,re.S)
    require(bool(match),f'{path}: missing frontmatter')
    if not match: return {},text
    # Restrict to the exact unambiguous subset emitted by this workspace.
    obj = {}
    metadata = False
    for line in match.group(1).splitlines():
        if line == 'metadata:':
            obj['metadata'] = {}
            metadata = True
            continue
        if line.startswith('  '):
            require(metadata,f'{path}: unexpected indentation')
            target=obj.get('metadata',{})
            raw=line[2:]
        else:
            metadata=False
            target=obj
            raw=line
        pair=re.fullmatch(r'([a-zA-Z0-9_.-]+): (.+)',raw)
        require(bool(pair),f'{path}: unsupported frontmatter line {line!r}')
        if not pair: continue
        key,value=pair.groups()
        require(key not in target,f'{path}: duplicate key {key}')
        if value.startswith('"') or re.fullmatch(r'-?\d+',value):
            try: value=json.loads(value)
            except json.JSONDecodeError: errors.append(f'{path}: invalid quoted value {key}')
        else:
            require(bool(re.fullmatch(r'[a-z0-9-]+',value)),f'{path}: unsupported plain scalar {key}')
        target[key]=value
    require(set(obj)<= {'name','description','license','allowed-tools','metadata'},f'{path}: extra top level keys')
    name=obj.get('name','')
    desc=obj.get('description','')
    require(isinstance(name,str) and bool(re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*',name)) and len(name)<=64,f'{path}: invalid name')
    require(name==path.parent.name,f'{path}: name/path mismatch')
    require(isinstance(desc,str) and 0<len(desc)<=1024 and '<' not in desc and '>' not in desc,f'{path}: invalid description')
    require(isinstance(obj.get('metadata'),dict),f'{path}: invalid metadata')
    require(not re.search(r'^\s*\[TODO:',text,re.M),f'{path}: unfinished TODO')
    return obj,text[match.end():]

def check_links(path):
    text=path.read_text(encoding='utf-8')
    for target in re.findall(r'\[[^\]\n]+\]\(([^)\n]+)\)',text):
        target=target.strip().strip('<>')
        if re.match(r'^[a-zA-Z][a-zA-Z0-9+.-]*:',target) or target.startswith('#'): continue
        target=unquote(target.split('#')[0])
        counts['relative_links']+=1
        require((path.parent/target).is_file(),f'{path}: missing link {target}')

for book,router in BOOKS:
    skill_paths=sorted(book.glob('*/SKILL.md'))
    for p in skill_paths:
        counts['skill_entrypoints']+=1
        _,body=read_frontmatter(p)
        if p.parent.name != router:
            card=book/router/'references/capabilities'/f'{p.parent.name}.md'
            expected=body.replace('(references/background.md)',f'(../background/{p.parent.name}.md)').replace('[references/background.md]',f'[../background/{p.parent.name}.md]')
            require(card.is_file() and card.read_text(encoding='utf-8').strip()==expected.strip(),f'{p}: promoted card out of sync')
            counts['synced_promoted_cards']+=1
        for md in [p]+list((p.parent/'references').rglob('*.md')):
            check_links(md)
    counts['capability_cards']+=len(list((book/router/'references/capabilities').glob('*.md')))
    evals=list((book/'evals').glob('*.json')) if router.startswith('equity') else list((book/'evals').glob('*/test-prompts.json'))
    for p in evals:
        obj=json.loads(p.read_text(encoding='utf-8'))
        if 'test_cases' not in obj: continue
        counts['existing_trigger_cases']+=len(obj['test_cases'])
        require(obj.get('version')=='0.2.0' and obj.get('evaluation_status')=='not_run_after_revision',f'{p}: stale test status')
        if not router.startswith('equity'):
            for filename in ['test-prompts.json','trigger-suite.json']:
                a=p.parent/filename
                b=book/obj['skill']/filename
                require(json.loads(a.read_text(encoding='utf-8'))==json.loads(b.read_text(encoding='utf-8')),f'{b}: eval copy differs')

for p in ROOT.rglob('*.json'):
    counts['json_files']+=1
    try: json.loads(p.read_text(encoding='utf-8-sig'))
    except (ValueError,OSError) as exc: errors.append(f'{p}: {exc}')

def calc(c):
    i=c['input']; kind=c['kind']
    if kind=='bridge':
        equity=i['operating']+i['nonoperating']-i['debt']-i['nci']
        return {'equity':equity,'per_share':equity/i['shares']}
    if kind=='ebita': return {'ebita':i['ebit']+i['amortization'],'ebitda':i['ebit']+i['depreciation']+i['amortization']}
    if kind=='steady':
        if any(g>=i['wacc'] for g in i['growths']): raise ValueError('invalid perpetual growth')
        return {'values':[i['noplat1']*(1-g/i['return'])/(i['wacc']-g) for g in i['growths']]}
    if kind=='ma':
        net=i['gross_synergy']-i['included_cost']
        return {'net_synergy':net,'buyer_gain':i['standalone']+net-i['price']-i['additional_cost']}
    if kind=='margin': return {'points':[(b-a)*100 for a,b in i['margins']], 'profit_growth':[b/a-1 for a,b in i['margins']], 'cost_reduction':1-i['costs'][1]/i['costs'][0]}
    if kind=='noplat': return {'noplat':i['net_income']-i['nonoperating_after_tax']+i['financing_after_tax']}
    if kind=='real_return': return {'real':(1+i['nominal'])/(1+i['inflation'])-1}
    if kind=='weighted': return {'industry_growth':sum(x*g for x,g in zip(i['base'],i['growth']))/sum(i['base'])}
    raise ValueError(f'unknown arithmetic kind {kind}')

def equal_numbers(a,b):
    if isinstance(b,dict): return set(a)==set(b) and all(equal_numbers(a[k],v) for k,v in b.items())
    if isinstance(b,list): return len(a)==len(b) and all(equal_numbers(x,y) for x,y in zip(a,b))
    return math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-10)

suite=json.loads((ROOT/'maintenance/research-acceptance-cases.json').read_text(encoding='utf-8'))
names={p.parent.name for book,_ in BOOKS for p in book.glob('*/SKILL.md')}
ids=set()
for case in suite['cases']:
    counts['acceptance_behavior_cases']+=1
    require(case['id'] not in ids,f'duplicate acceptance id {case["id"]}')
    ids.add(case['id'])
    require(all(s in names for s in case['skills']),f'{case["id"]}: unknown skill')
    require(bool(case['prompt']) and bool(case['expect']) and bool(case['forbid']),f'{case["id"]}: incomplete acceptance criteria')
    if 'calculation' in case:
        counts['acceptance_arithmetic_cases']+=1
        require(equal_numbers(calc(case['calculation']),case['calculation']['expected']),f'{case["id"]}: inconsistent arithmetic expectation')

require(counts['skill_entrypoints']==19,'expected 19 entrypoints')
require(counts['capability_cards']==34,'expected 34 cards')
require(counts['synced_promoted_cards']==17,'expected 17 promoted-card pairs')
require(counts['existing_trigger_cases']==123,'expected 123 existing trigger cases')
require(counts['acceptance_behavior_cases']==20,'expected 20 acceptance cases')
require(counts['acceptance_arithmetic_cases']==8,'expected 8 numeric acceptance cases')
result={'date':'2026-10-06','checks':'passed' if not errors else 'failed','counts':counts,
        'errors':errors,'model_trigger_evaluation':'not_run','agent_behavior_evaluation':'not_run',
        'arithmetic_scope':'Expected answers only; no skill/model execution',
        'frontmatter_scope':'Unambiguous JSON-string/plain-name subset, not a general YAML parser',
        'official_quick_validate':'not_run_missing_PyYAML'}
(ROOT/'maintenance/validation-results.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
sys.exit(1 if errors else 0)
