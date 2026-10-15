"""Research-method guidance distilled from the local `skills/` library.

The skills describe *how* an analyst should reason about each block (industry
supply/demand, growth quality, ROIC decomposition, forensics, valuation, bias
checks). Prompts in `prompts/` only state contracts (schema, citations, number
binding). This module appends the matching method steps to the system prompt of
analysis, writing and critical-review calls, so the model gets both.

Guidance goes into the system message on purpose: it is stable per role and
block template, which keeps the request prefix identical across calls and lets
provider prefix caching work. Missing skill files are skipped silently.
"""
import os
import re
from functools import lru_cache
from pathlib import Path

from .config import ROOT

BOOK_ERP = '证券分析师的最佳实践指南'
BOOK_VALUE = '价值 公司金融的四大基石'

SKILLS = {
    'industry': (BOOK_ERP, 'equity-industry-analysis'),
    'key_factors': (BOOK_ERP, 'equity-key-factors'),
    'forensics': (BOOK_ERP, 'equity-financial-forensics'),
    'forecast': (BOOK_ERP, 'equity-forecast-modeling'),
    'valuation': (BOOK_ERP, 'equity-valuation'),
    'bias': (BOOK_ERP, 'equity-bias-audit'),
    'writing': (BOOK_ERP, 'equity-report-writing'),
    'growth': (BOOK_VALUE, 'growth-quality-ladder'),
    'moat': (BOOK_VALUE, 'roic-competitive-advantage-decomposition'),
    'roic': (BOOK_VALUE, 'roic-growth-value-core'),
    'multiples': (BOOK_VALUE, 'valuation-multiple-traps'),
    'leverage': (BOOK_VALUE, 'value-four-cornerstones/references/capabilities/capital-structure-resilience.md'),
}

# Block template -> methods, most important first.
BLOCK_METHODS = {
    'C01': ['key_factors'],
    'F01': ['growth', 'forensics'],
    'F02': ['leverage', 'forensics'],
    'F03': ['forensics'],
    'F04': ['growth', 'key_factors'],
    'F05': ['roic', 'moat'],
    'I01': ['industry'],
    'B01': ['moat', 'key_factors'],
    'V01': ['forecast', 'valuation', 'multiples'],
    'R01': ['bias', 'key_factors'],
    'X01': ['writing', 'bias'],
}

ROLES = {'financial_analyzer', 'writer', 'core_writer', 'critical_reviewer', 'assumption_planner'}
MAX_CHARS_PER_METHOD = 1600

PREAMBLE = ('\n\n## 研究方法（来自本地方法库）\n'
            '以下方法用于组织分析思路和检查遗漏。输出仍只遵守上文 schema、引用与数值规则：'
            '方法中提到的指标或计算，输入未提供时作为限制或待验证项说明，不自行计算、不编造数字；'
            '方法中的数量或阈值只是参考，不是必须满足的门槛。\n')


def skills_dir() -> Path:
    configured = os.environ.get('CDR_SKILLS_DIR')
    return Path(configured) if configured else ROOT / 'skills'


def enabled() -> bool:
    return os.environ.get('CDR_METHOD_GUIDANCE', 'true').strip().lower() not in {'0', 'false', 'no', 'off'}


@lru_cache(maxsize=64)
def _method_text(key: str, root: str) -> str:
    book, name = SKILLS[key]
    path = Path(root) / book / name
    if path.is_dir():
        path = path / 'SKILL.md'
    try:
        text = path.read_text(encoding='utf-8')
    except OSError:
        return ''
    if text.startswith('---'):
        text = text.split('---', 2)[-1]
    # Keep the method body; drop shared hand-off boilerplate, book background
    # links and optional trading sections that do not apply to company research.
    text = re.split(r'^## (?:证据与交接|来源背景|可选)', text, maxsplit=1, flags=re.M)[0]
    lines = [line.rstrip() for line in text.strip().splitlines() if line.strip()]
    if lines and lines[0].startswith('# '):
        title, body = lines[0][2:].strip(), lines[1:]
    else:
        title, body = name, lines
    body = '\n'.join(line[3:] + '：' if line.startswith('## ') else line for line in body)
    if len(body) > MAX_CHARS_PER_METHOD:
        body = body[:MAX_CHARS_PER_METHOD].rsplit('\n', 1)[0]
    return f'### {title}\n{body}'


def template_of(block_id: str | None) -> str | None:
    match = re.match(r'[A-Z]\d{2}', block_id or '')
    return match.group(0) if match else None


def method_keys(role: str, block_id: str | None) -> list[str]:
    if role not in ROLES:
        return []
    if role == 'critical_reviewer':
        return ['bias']
    if role == 'assumption_planner':
        return ['forecast']
    return BLOCK_METHODS.get(template_of(block_id), [])


def guidance(role: str, block_id: str | None) -> str:
    """System-prompt suffix for this role and block, or '' when not applicable."""
    if not enabled():
        return ''
    texts = [t for t in (_method_text(k, str(skills_dir())) for k in method_keys(role, block_id)) if t]
    return PREAMBLE + '\n\n'.join(texts) if texts else ''
