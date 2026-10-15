import json
from decimal import Decimal
from .schemas import SourceRecord,EvidenceRecord,FinancialFact
from .storage import Store
from .financials.formulas import FinancialDataProcessor,FinancialError


class EvidenceStore:
    def __init__(self,store: Store,run_id: str):
        self.store,self.run_id=store,run_id
        self.sources: dict[str,SourceRecord]={}
        self.evidence: dict[str,EvidenceRecord]={}
        self.facts: dict[str,FinancialFact]={}
    def add_source(self,source: SourceRecord):
        saved = self.store.record(self.run_id,'source',source.source_id,source.model_dump(mode='json'))
        source = SourceRecord.model_validate(saved)
        self.sources[source.source_id]=source
    def add_evidence(self,evidence: EvidenceRecord):
        source=self.sources.get(evidence.source_id)
        if not source:raise FinancialError('证据引用未知来源')
        if not evidence.quote.strip() or evidence.quote not in source.content:
            evidence=evidence.model_copy(update={'validation_status':'unverified'})
        self.store.record(self.run_id,'evidence',evidence.evidence_id,evidence.model_dump(mode='json'),
                          identity_fields=('source_id','quote','actual_or_forecast','locator'))
        self.evidence[evidence.evidence_id]=evidence
    def add_fact(self,fact: FinancialFact):
        evidence=self.evidence.get(fact.evidence_id)
        if not evidence or evidence.source_id!=fact.source_id:raise FinancialError('财务事实引用无效证据')
        if evidence.validation_status!='verified':fact=fact.model_copy(update={'validation_status':'unverified'})
        fact=FinancialDataProcessor().normalize(fact)
        self.store.record(self.run_id,'fact',fact.fact_id,fact.model_dump(mode='json'), identity_fields=(
            'company_id','metric_code','period','unit','value','actual_or_forecast','scope','segment_id',
            'currency','accounting_basis','source_id','evidence_id','locator','version','supersedes',
            'slot_id','raw_value','raw_unit','locked_at','value_origin','derivation_id'))
        self.facts[fact.fact_id]=fact
    def ingest_structured(self,source: SourceRecord) -> None:
        """Precise local CSV/JSON fields; no vector guessing or scope merging."""
        self.add_source(source)
        try:
            data=json.loads(source.content)
            if not {'company_id','metric_code','period','unit','value','actual_or_forecast'}.issubset(data):return
            evidence=EvidenceRecord(source_id=source.source_id,claim=f"{data['metric_code']} {data['period']} {data['value']} {data['unit']}",quote=source.content,locator=source.locator,actual_or_forecast=data['actual_or_forecast'],validation_status='verified')
            from .framework import digest
            evidence.evidence_id='ev-'+digest([source.source_id,source.content])[:24];self.add_evidence(evidence)
            self.add_fact(FinancialFact(fact_id=data.get('fact_id') or 'fact-'+digest([source.source_id,data])[:24],company_id=data['company_id'],metric_code=data['metric_code'],period=data['period'],unit=data['unit'],value=Decimal(str(data['value'])),actual_or_forecast=data['actual_or_forecast'],scope=data.get('scope') or 'consolidated',segment_id=data.get('segment_id') or None,source_id=source.source_id,evidence_id=evidence.evidence_id,locator=source.locator,validation_status='verified',currency=data.get('currency','CNY'),accounting_basis=data.get('accounting_basis','reported'),version=data.get('version',1),supersedes=data.get('supersedes')))
        except (ValueError,TypeError,ArithmeticError):
            return
