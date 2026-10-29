"""Industry and third-party numbers admitted from located quotes.

Market size, capacity, prices, shares and institutions' forecasts are not company
financials: they never enter the fixed slots or calculations. Each one is kept with
its subject, period and original wording, and the writer cites it as [[ind:ID]],
which renders the original text. A value is admitted only when it appears verbatim
in a quote that is itself located in the source."""

import re
from typing import Literal

from pydantic import Field

from .agents import locate_quote
from .datasources import span_locator
from .framework import digest
from .schemas import EvidenceRecord, IndustryDatum, Schema, SourceRecord

# A number followed by at most a short unit: 263亿美元, 7.37%, 25.84万吨, 385元/公斤.
VALUE = re.compile(r'[-+]?\d[\d,，.]*\s*(?:%|个百分点|[^\d\s，,。；;、（）()]{0,8})')


class IndustryDataProposal(Schema):
    source_id: str
    subject: str = Field(min_length=1, max_length=60)
    metric: str = Field(min_length=1, max_length=30)
    period: str = Field(min_length=1, max_length=30)
    value_text: str = Field(min_length=1, max_length=30)
    quote: str
    actual_or_forecast: Literal['actual', 'forecast'] = 'actual'
    publisher: str = Field(default='', max_length=40)


def compact(text: str) -> str:
    return re.sub(r'[\s,，]', '', text)


def admit(p: IndustryDataProposal, source: SourceRecord) -> tuple[EvidenceRecord, IndustryDatum] | None:
    """Evidence for the quote and the datum citing it, or None when the value is not
    a single number with a unit, or is not written in the located quote."""
    value = ' '.join(p.value_text.split())
    if p.source_id != source.source_id or not VALUE.fullmatch(value):
        return None
    start, quote = locate_quote(p.quote, source.content) if p.quote.strip() else (-1, None)
    if start < 0 or compact(value) not in compact(quote):
        return None
    kind = 'forecast' if p.actual_or_forecast == 'forecast' else 'context'
    # The kind is part of the ID: the same quote may also be saved as context evidence.
    evidence = EvidenceRecord(
        evidence_id='ev-' + digest([source.source_id, quote, kind])[:24],
        source_id=source.source_id,
        claim=f'{p.subject}{p.metric}（{p.period}）：{value}',
        quote=quote,
        locator=span_locator(source, start, start + len(quote)),
        actual_or_forecast=kind,
        validation_status='verified',
    )
    datum = IndustryDatum(
        data_id='ind-' + digest([source.source_id, p.subject, p.metric, p.period, value])[:24],
        source_id=source.source_id,
        evidence_id=evidence.evidence_id,
        subject=p.subject,
        metric=p.metric,
        period=p.period,
        value_text=value,
        actual_or_forecast=p.actual_or_forecast,
        publisher=p.publisher,
        quote=quote,
        locator=evidence.locator,
    )
    return evidence, datum
