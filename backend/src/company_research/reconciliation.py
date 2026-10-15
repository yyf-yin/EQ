"""Conservative, deterministic financial adjudication; raw records remain immutable.

Neither model-provided supersedes nor publication dates authorize a replacement.
Only checked primary disclosures or explicit directional correction evidence do.
"""
import re
from decimal import Decimal
from urllib.parse import urlsplit
from .financials.formulas import FinancialDataProcessor, FinancialError, FIELD_MAP, UNIT_SCALE
from .framework import digest
from .schemas import FinancialFact

POLICY = 'financial-reconciliation-1'
IDENTITY = ('company_id','metric_code','period','unit','scope','segment_id','actual_or_forecast','currency')
PRIMARY_DOMAINS = ('sse.com.cn','szse.cn','cninfo.com.cn','bse.cn')


def group_key(fact):
    return {k:getattr(fact,k) for k in IDENTITY}


def metric_before(text, position, metric):
    labels=list(FIELD_MAP.items())+[(v,v) for v in set(FIELD_MAP.values())]
    found=[(m.end(),len(label),code) for label,code in labels for m in re.finditer(re.escape(label),text[:position])]
    return bool(found and max(found)[2]==metric)


def primary_proof(fact, sources, evidence, company):
    """Require original quotation, issuer, reporting period and metric disclosure."""
    s=sources.get(fact.source_id,{});e=evidence.get(fact.evidence_id,{})
    quote=e.get('quote','');body=s.get('content','')
    if (e.get('source_id')!=fact.source_id or e.get('validation_status')!='verified'
            or not quote or quote not in body):return False
    if fact.actual_or_forecast=='actual' and re.search(r'预计|预测|forecast|estimate',quote,re.I):return False
    try:
        url=urlsplit(s.get('source_url') or '')
        host=url.hostname or ''
        trusted=url.scheme=='https' and not url.username and any(host==d or host.endswith('.'+d) for d in PRIMARY_DOMAINS)
    except ValueError:return False
    if not trusted:return False
    issuer=company.get('name','')
    if not issuer or issuer not in s.get('title','')+' '+body:return False
    labels=[fact.metric_code]+[k for k,v in FIELD_MAP.items() if v==fact.metric_code]
    if not any(label in quote for label in labels) or fact.period[:4] not in quote:return False
    if len(set(re.findall(r'20\d{2}',quote)))!=1:return False # Ambiguous multi-year table needs a located single-period excerpt.
    # Annual and interim rows must not borrow one another's year heading.
    if fact.period.endswith('A') and not re.search(r'年度|年报|全年|annual|20\d{2}A',quote,re.I):return False
    if not fact.period.endswith('A') and fact.period not in quote:return False
    scope={'consolidated':r'合并|consolidated','parent':r'母公司|parent','segment':re.escape(fact.segment_id or '')}[fact.scope]
    if not re.search(scope,quote,re.I):return False
    # A number elsewhere in a document is insufficient; require the quoted unit.
    scales=dict(UNIT_SCALE)
    scales.update({'%':Decimal('.01'),'percent':Decimal('.01'),'ratio':Decimal(1)})
    for unit,scale in sorted(scales.items(),key=lambda x:-len(x[0])):
        if unit not in quote:continue
        for match in re.finditer(r'(?<![\d.])(-?\d[\d,]*(?:\.\d+)?)\s*'+re.escape(unit)+r'(?![A-Za-z_])',quote):
            if metric_before(quote,match.start(),fact.metric_code) and Decimal(match.group(1).replace(',',''))*scale==fact.value:return True
    return False


def correction_proof(new, old, sources, evidence, company):
    if new.accounting_basis!=old.accounting_basis or not primary_proof(new,sources,evidence,company):return False
    quote=evidence[new.evidence_id]['quote']
    # Deliberately narrow: directional, same-row values with explicit identical units.
    # A bare '更正公告', a date or an LLM supersedes assertion is insufficient.
    pattern=r'(?:由|更正前[:：]?|调整前[:：]?|重述前[:：]?)\s*(-?\d[\d,]*(?:\.\d+)?)\s*(CNY_million|百万元|亿元|万元|千元|元)\s*(?:更正为|调整为|重述为|[，,；;\s]*(?:更正后|调整后|重述后)[:：]?)\s*(-?\d[\d,]*(?:\.\d+)?)\s*\2'
    for match in re.finditer(pattern,quote):
        a,u,b=match.groups();scale=UNIT_SCALE[u]
        if metric_before(quote,match.start(),new.metric_code) and Decimal(a.replace(',',''))*scale==old.value and Decimal(b.replace(',',''))*scale==new.value:return True
    return False


def reconcile(candidates, sources, evidence, company, checked_groups=()):
    processor=FinancialDataProcessor();groups={};decisions=[];active=[]
    sm={s['source_id']:s for s in sources};em={e['evidence_id']:e for e in evidence}
    for raw in sorted(candidates,key=lambda f:f['fact_id']):
        try:
            f=processor.normalize(FinancialFact.model_validate(raw))
        except (FinancialError,ValueError) as exc:
            decision={'policy':POLICY,'group_id':'invalid-'+raw['fact_id'],'identity':{},'candidate_ids':[raw['fact_id']],
                'candidates':[raw],'selected_ids':[],'status':'unresolved','rule':'invalid','reason':str(exc),'proof_evidence_ids':[]}
            decision['decision_id']='decision-'+digest([POLICY,decision])[:24];decisions.append(decision);continue
        if f.validation_status!='verified':continue
        e=em.get(f.evidence_id,{})
        if f.company_id!=company.get('company_id') or f.source_id not in sm or e.get('source_id')!=f.source_id or e.get('validation_status')!='verified':continue
        key=group_key(f);gid='group-'+digest(key)[:24]
        groups.setdefault(gid,(key,[]))[1].append(f)
    for gid,(key,items) in sorted(groups.items()):
        locked=[f for f in items if f.slot_id and f.locked_at]
        references=[f for f in items if sm[f.source_id].get('kind')=='upload' and sm[f.source_id].get('attachment_id')
                    and em[f.evidence_id].get('quote') and em[f.evidence_id]['quote'] in sm[f.source_id].get('content','')]
        effective=locked or references or items
        choices={(f.value,f.accounting_basis) for f in effective};selected=[];proof=[]
        status='unresolved';rule='conflict';reason='同期间、单位、主体及披露范围存在不同数值或会计口径，待原始披露核实'
        if len(choices)==1:
            selected=[effective[0]];status='consistent';rule='equivalent';reason='单位规范化后同口径候选一致'
            if locked:
                status='resolved';rule='locked-annual-slot';reason='已通过一次提取检查的固定年报槽只读，其他候选不参与裁决'
                proof=[selected[0].evidence_id]
            elif references:
                status='resolved';rule='reference-first';reason='用户上传参考资料最高优先级；其它来源候选保留但不采用'
                proof=[selected[0].evidence_id]
        elif references:
            rule='reference-conflict';reason='上传参考资料同一字段存在不同值或口径，请人工选择；不从外部渠道取数裁决'
        else:
            primary=[f for f in items if primary_proof(f,sm,em,company)]
            corrected=[f for f in primary if all(f.value==other.value and f.accounting_basis==other.accounting_basis
                         or correction_proof(f,other,sm,em,company) for other in primary) and
                         any(correction_proof(f,other,sm,em,company) for other in items)]
            if len({(f.value,f.accounting_basis) for f in corrected})==1 and corrected and len({f.accounting_basis for f in items})==1:
                selected=[corrected[0]];status='resolved';rule='explicit-correction';reason='原始更正披露逐项证明更正前后数值及相同口径'
            elif gid in checked_groups and primary and len({(f.value,f.accounting_basis) for f in primary})==1 and len({f.accounting_basis for f in items})==1:
                selected=[primary[0]];status='resolved';rule='checked-primary';reason='定向补查完成，取有期间、单位和范围证明的原始披露；其他候选保留'
            proof=[f.evidence_id for f in selected] if selected else []
        # Accepted immutable originals only; normalization is already done at extraction.
        active.extend(f.model_dump(mode='json') for f in selected)
        decision={'policy':POLICY,'group_id':gid,'identity':key,'candidate_ids':[f.fact_id for f in items],
            'candidates':[{'fact_id':f.fact_id,'value':str(f.value),'unit':f.unit,'accounting_basis':f.accounting_basis,
                           'source_id':f.source_id,'evidence_id':f.evidence_id} for f in items],
            'selected_ids':[f.fact_id for f in selected],'status':status,'rule':rule,'reason':reason,'proof_evidence_ids':proof}
        decision['decision_id']='decision-'+digest([POLICY,decision])[:24];decisions.append(decision)
    return active,decisions
