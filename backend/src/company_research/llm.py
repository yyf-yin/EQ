"""Protocol adapters accept canonical messages and never log provider bodies/keys."""
import asyncio
import json
import os
import time
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Literal, TypeVar
import httpx
import yaml
from pydantic import BaseModel, Field, SecretStr

T = TypeVar('T', bound=BaseModel)


class ConfigurationError(ValueError):
    pass


class LLMError(RuntimeError):
    pass

class CapacityError(LLMError):
    pass

class TruncatedOutput(LLMError):
    pass

class IncompleteOutput(LLMError):
    pass

class BudgetError(LLMError):
    pass

CALL_CONTEXT = ContextVar('call_context', default={})
RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504, 529}


def retry_delay(attempt: int, response: 'httpx.Response | None' = None) -> float:
    """Exponential backoff with jitter; honours Retry-After from rate limiters."""
    import random
    base = float(os.environ.get('CDR_RETRY_BASE_SECONDS', '1') or 1)
    cap = float(os.environ.get('CDR_RETRY_MAX_SECONDS', '30') or 30)
    if response is not None:
        header = response.headers.get('retry-after')
        try:
            if header is not None:
                return min(max(float(header), 0), cap)
        except ValueError:
            pass
    return min(cap, base * 2 ** attempt) * (0.5 + random.random() / 2)

import logging
logger = logging.getLogger(__name__)

class RoleLimits(BaseModel):
    input_capacity: int = Field(default=120000, ge=1000)
    context_capacity: int = Field(default=136000, ge=2000)
    output_reserve: int = Field(default=10000, ge=1)
    timeout: float = 45
    retries: int = Field(default=2, ge=1, le=3)
    max_output_tokens: int | None = None
    concurrency: int | None = Field(default=None, ge=1, le=8)
    block_call_budget: int | None = Field(default=None, ge=1)
    # Per-role sampling override, e.g. 0 for extraction/review, higher for writing.
    temperature: float | None = Field(default=None, ge=0, le=2)


class ModelConfig(BaseModel):
    protocol: Literal['openai', 'anthropic']
    base_url: str
    model: str
    api_key_env: str
    api_key_file_env: str | None = None
    max_tokens: int = 6000
    structured_mode: Literal['native', 'tool', 'json'] = 'tool'
    anthropic_version: str = '2023-06-01'
    # Model-level sampling default; omitted from the request when None.
    temperature: float | None = Field(default=None, ge=0, le=2)
    # Provider-specific request fields merged into every payload, e.g.
    # DeepSeek {"thinking": {"type": "disabled"}}, OpenAI {"reasoning_effort": "low"},
    # Anthropic {"thinking": {"type": "enabled", "budget_tokens": 4000}}.
    extra_body: dict[str, Any] = Field(default_factory=dict)
    # Anthropic: mark tools+system as a cacheable prefix (no effect below the
    # provider's minimum cacheable length). OpenAI-compatible providers such as
    # DeepSeek cache identical prefixes automatically.
    prompt_cache: bool = True

    def key(self) -> str:
        value = os.environ.get(self.api_key_env, '')
        if not value and self.api_key_file_env:
            key_file = os.environ.get(self.api_key_file_env, '').strip()
            if key_file:
                path = Path(key_file).expanduser()
                if not path.is_absolute():
                    path = Path(__file__).resolve().parents[3] / path
                try:
                    value = path.read_text(encoding='utf-8').strip()
                except OSError:
                    raise ConfigurationError('模型密钥文件不可读取') from None
                if value:
                    # Make the credential available to this backend process only. It is
                    # never written to logs, configuration files, or stored records.
                    os.environ[self.api_key_env] = value
        if not value or not self.base_url or not self.model:
            raise ConfigurationError('模型 Base URL、名称或环境变量密钥未配置')
        return value


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class LLMResponse(BaseModel):
    content: str = ''
    tool_calls: list[ToolCall] = Field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    finish_reason: str = ''


def openai_payload(config: ModelConfig, messages: list[dict], tools: list[dict] | None = None, schema: type[BaseModel] | None = None) -> dict:
    payload = {'model': config.model, 'messages': messages, 'max_tokens': config.max_tokens}
    if config.temperature is not None:
        payload['temperature'] = config.temperature
    if tools:
        payload['tools'] = [{'type':'function', 'function':{'name':t['name'], 'description':t.get('description',''), 'parameters':t['input_schema']}} for t in tools]
    if schema:
        if config.structured_mode == 'native':
            payload['response_format'] = {'type':'json_schema', 'json_schema':{'name':schema.__name__, 'schema':schema.model_json_schema(), 'strict':True}}
        elif config.structured_mode == 'tool':
            payload['tools'] = [{'type':'function','function':{'name':'structured_output','description':'返回符合 schema 的结果','parameters':schema.model_json_schema()}}]
            payload['tool_choice'] = {'type':'function','function':{'name':'structured_output'}}
        else:
            payload['response_format'] = {'type':'json_object'}
            payload['messages'] = messages + [{'role':'user','content':'只返回 JSON，结构：'+json.dumps(schema.model_json_schema(),ensure_ascii=False)}]
    return payload | config.extra_body


def anthropic_payload(config: ModelConfig, messages: list[dict], tools: list[dict] | None = None, schema: type[BaseModel] | None = None) -> dict:
    converted, system = [], []
    for message in messages:
        role = message['role']
        if role == 'system':
            system.append(message['content'])
            continue
        if role == 'tool':
            blocks = [{'type':'tool_result','tool_use_id':message['tool_call_id'],'content':message['content']}]
            target_role = 'user'
        else:
            target_role = role
            blocks = [{'type':'text','text':message['content']}] if message.get('content') else []
            for call in message.get('tool_calls', []):
                blocks.append({'type':'tool_use','id':call['id'],'name':call['function']['name'],'input':json.loads(call['function']['arguments'])})
        if not blocks:
            continue
        if converted and converted[-1]['role'] == target_role:
            converted[-1]['content'].extend(blocks)
        else:
            converted.append({'role':target_role, 'content':blocks})
    system_text = '\n\n'.join(system)
    if config.prompt_cache and system_text:
        # Cache breakpoint after tools + system: the stable per-role prefix.
        system_value = [{'type':'text','text':system_text,'cache_control':{'type':'ephemeral'}}]
    else:
        system_value = system_text
    payload = {'model':config.model, 'max_tokens':config.max_tokens, 'system':system_value, 'messages':converted}
    if config.temperature is not None:
        payload['temperature'] = config.temperature
    if tools:
        payload['tools'] = tools
    if schema:
        payload['tools'] = [{'name':'structured_output','description':'返回符合 schema 的结果','input_schema':schema.model_json_schema()}]
        thinking = (config.extra_body.get('thinking') or {}).get('type') == 'enabled'
        # Extended thinking only allows tool_choice auto/none; the single tool and
        # the instruction still make the model answer through structured_output.
        payload['tool_choice'] = {'type':'auto'} if thinking else {'type':'tool','name':'structured_output'}
    return payload | config.extra_body


def parse_response(protocol: str, body: dict) -> LLMResponse:
    if protocol == 'openai':
        choice = body['choices'][0]
        message = choice['message']
        usage = body.get('usage', {})
        return LLMResponse(content=message.get('content') or '', tool_calls=[ToolCall(id=t['id'],name=t['function']['name'],arguments=json.loads(t['function']['arguments'])) for t in message.get('tool_calls',[])], input_tokens=usage.get('prompt_tokens',0), output_tokens=usage.get('completion_tokens',0), finish_reason=choice.get('finish_reason',''))
    blocks = body.get('content', [])
    usage = body.get('usage', {})
    return LLMResponse(content='\n'.join(b['text'] for b in blocks if b['type']=='text'), tool_calls=[ToolCall(id=b['id'],name=b['name'],arguments=b['input']) for b in blocks if b['type']=='tool_use'], input_tokens=anthropic_input_tokens(usage), output_tokens=usage.get('output_tokens',0), finish_reason=body.get('stop_reason',''))


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def anthropic_input_tokens(usage: dict) -> int:
    """Anthropic reports cached prefix tokens separately from input_tokens."""
    return _count(usage.get('input_tokens')) + _count(usage.get('cache_read_input_tokens')) + _count(usage.get('cache_creation_input_tokens'))


def cache_usage(usage: dict, protocol: str) -> dict:
    """Missing provider cache counters are unknown, never a measured zero hit."""
    if protocol == 'anthropic':
        if 'cache_read_input_tokens' not in usage and 'cache_creation_input_tokens' not in usage:
            return {}
        hit = _count(usage.get('cache_read_input_tokens'))
        return {'cache_hit_tokens': hit, 'cache_miss_tokens': anthropic_input_tokens(usage) - hit}
    if protocol != 'openai':
        return {}
    hit = usage.get('prompt_cache_hit_tokens', (usage.get('prompt_tokens_details') or {}).get('cached_tokens'))
    total = usage.get('prompt_tokens')
    miss = usage.get('prompt_cache_miss_tokens')
    if not isinstance(hit, int) or isinstance(hit, bool) or hit < 0:
        return {}
    if not isinstance(total, int) or isinstance(total, bool) or total < hit:
        return {}
    if miss is None:
        miss = total - hit
    if not isinstance(miss, int) or isinstance(miss, bool) or miss < 0 or hit + miss != total:
        return {}
    return {'cache_hit_tokens': hit, 'cache_miss_tokens': miss}


class Gateway:
    def __init__(self, models: dict[str, ModelConfig], routes: dict[str, str], client: httpx.AsyncClient | None = None, concurrency: int = 3, retries: int = 3, timeout: float = 45, role_limits=None, global_call_budget=240, global_token_budget=2000000, block_call_budget=40, enforce_call_budgets=False):
        self.models, self.routes = models, routes
        self.client = client
        self.semaphore = asyncio.Semaphore(concurrency)
        self.concurrency=concurrency;self.role_semaphores={}
        self.retries, self.timeout = retries, timeout
        self.usage: dict[str, dict[str, int]] = {}
        # Role entries inherit unspecified fields from the 'default' entry.
        base=dict((role_limits or {}).get('default') or {})
        self.role_limits={k:RoleLimits.model_validate(v if k=='default' else base|dict(v or {})) for k,v in (role_limits or {}).items()}
        self.global_call_budget,self.global_token_budget,self.block_call_budget=global_call_budget,global_token_budget,block_call_budget
        self.enforce_call_budgets=enforce_call_budgets
        self.calls=0;self.reserved_tokens=0;self.block_calls={};self.call_records=[]
        self.store=None;self.run_id=None
        self._owned_client=None

    def http_client(self) -> httpx.AsyncClient:
        """One pooled client per gateway: keeps TLS connections alive across calls."""
        if self.client:
            return self.client
        if self._owned_client is None or self._owned_client.is_closed:
            self._owned_client = httpx.AsyncClient(trust_env=False,
                limits=httpx.Limits(max_connections=32, max_keepalive_connections=16))
        return self._owned_client

    async def aclose(self):
        if self._owned_client is not None:
            await self._owned_client.aclose()
            self._owned_client = None

    def limits(self, role):
        return self.role_limits.get(role,self.role_limits.get('default',RoleLimits(timeout=self.timeout,retries=min(self.retries,3))))

    def attach_store(self, store, run_id):
        from .execution import accounted_tokens
        self.store,self.run_id=store,run_id
        self.call_records=store.records(run_id,'call')
        self.calls=len(self.call_records)
        self.reserved_tokens=sum(accounted_tokens(r) for r in self.call_records)
        for r in self.call_records:
            b=r.get('block_id','global');self.block_calls[b]=self.block_calls.get(b,0)+1
            if r.get('result')=='ok':
                bucket=self.usage.setdefault(r['role'],{'calls':0,'input_tokens':0,'output_tokens':0})
                bucket['calls']+=1;bucket['input_tokens']+=r.get('input_tokens') or 0;bucket['output_tokens']+=r.get('output_tokens') or 0

    def log_call(self, record):
        from .schemas import uid
        record.setdefault('call_id', uid());self.call_records.append(record)
        if self.store:self.store.record(self.run_id,'call',record['call_id'],record)

    @classmethod
    def from_file(cls, path: Path, **kwargs):
        from dotenv import load_dotenv
        load_dotenv(path.parent.parent / '.env', override=False)
        if not path.is_file():
            raise ConfigurationError('缺少 configs/models.yaml 模型路由配置')
        data = yaml.safe_load(path.read_text(encoding='utf-8'))
        gateway = cls({k:ModelConfig.model_validate(v) for k,v in data['models'].items()},data['routes'],role_limits=data.get('role_limits'),**kwargs)
        print(f'GATEWAY_INIT call_limits_enabled={gateway.enforce_call_budgets} block_call_budget={gateway.block_call_budget} role_limits={list(gateway.role_limits)} researcher_cap={min(gateway.block_call_budget, gateway.limits("researcher").block_call_budget or gateway.block_call_budget)}', flush=True)
        return gateway

    def resolve(self, agent: str) -> ModelConfig:
        name = self.routes.get(agent, self.routes.get('default'))
        if name not in self.models:
            raise ConfigurationError(f'Agent {agent} 未配置模型路由')
        config = self.models[name]
        config.key()
        return config

    def request_size(self, agent, messages, schema=None):
        """Use the same complete wire payload as the capacity gate, without I/O."""
        from .contexts import estimate_tokens
        config = self.models[self.routes.get(agent, self.routes.get('default'))]
        limits = self.limits(agent)
        config = config.model_copy(update={'max_tokens': limits.max_output_tokens or config.max_tokens})
        payload = (anthropic_payload if config.protocol == 'anthropic' else openai_payload)(config, messages, schema=schema)
        capacity = min(limits.input_capacity, limits.context_capacity - max(limits.output_reserve, config.max_tokens))
        return estimate_tokens(payload), capacity

    async def complete(self, agent: str, messages: list[dict], tools: list[dict] | None = None, schema: type[BaseModel] | None = None) -> LLMResponse:
        config = self.resolve(agent)
        limits=self.limits(agent)
        config=config.model_copy(update={'max_tokens':limits.max_output_tokens or config.max_tokens,
                                         'temperature':limits.temperature if limits.temperature is not None else config.temperature})
        key = config.key()
        native = config.protocol == 'anthropic'
        payload = (anthropic_payload if native else openai_payload)(config, messages, tools, schema)
        from .contexts import estimate_tokens
        estimate=estimate_tokens(payload)
        reserve=max(limits.output_reserve,config.max_tokens)
        if estimate>limits.input_capacity or estimate+reserve>limits.context_capacity:
            raise CapacityError('输入估算与输出预留超过角色容量：'+agent)
        endpoint = config.base_url.rstrip('/') + ('/messages' if native else '/chat/completions')
        headers = {'x-api-key':key, 'anthropic-version':config.anthropic_version} if native else {'Authorization':'Bearer '+key}
        role_semaphore=self.role_semaphores.setdefault(agent,asyncio.Semaphore(limits.concurrency or self.concurrency))
        async with role_semaphore,self.semaphore:
            for attempt in range(limits.retries):
                if self.store:
                    from .execution import check_pause
                    check_pause(self.store, self.run_id)
                meta=CALL_CONTEXT.get();block=meta.get('block_id') or 'global'
                block_cap=min(self.block_call_budget,limits.block_call_budget or self.block_call_budget)
                failure=None
                if self.enforce_call_budgets and self.calls>=self.global_call_budget:
                    failure={'kind':'calls','used':self.calls,'limit':self.global_call_budget}
                    message=f'总调用预算耗尽：{self.calls} / {self.global_call_budget} 次'
                elif self.reserved_tokens+estimate+reserve>self.global_token_budget:
                    failure={'kind':'tokens','used':self.reserved_tokens,'limit':self.global_token_budget,'request_tokens':estimate+reserve}
                    message=f'总 token 预算不足：已记账 {self.reserved_tokens} / {self.global_token_budget}，下一请求需预留 {estimate+reserve}'
                # Global work (including upload extraction) is not one analysis
                # block. It still consumes the task's call and token budgets.
                elif self.enforce_call_budgets and block!='global' and self.block_calls.get(block,0)>=block_cap:
                    failure={'kind':'block','block_id':block,'role':agent,'used':self.block_calls[block],'limit':block_cap}
                    message=f'分析块调用预算耗尽：{block} 已调用 {self.block_calls[block]} / {block_cap} 次'
                if failure:
                    logger.warning('budget trip kind=%s block=%s calls=%s/%s reserved=%s/%s block_calls=%s cap=%s', failure['kind'], block, self.calls, self.global_call_budget, self.reserved_tokens, self.global_token_budget, self.block_calls.get(block, 0), block_cap)
                    if self.store:self.store.execution_put(self.run_id,'execution_meta','budget_failure',failure)
                    raise BudgetError(message)
                self.calls+=1;self.block_calls[block]=self.block_calls.get(block,0)+1;self.reserved_tokens+=estimate+reserve
                started=time.monotonic();record={'role':agent,'block_id':block,'batch_id':meta.get('batch_id'),
                    'model_config':self.routes.get(agent,self.routes.get('default')),'attempt':attempt,'estimated_input_tokens':estimate,
                    'budget_tokens':estimate+reserve,'count_method':'char-class estimate (CJK/other); provider usage recorded separately'}
                from .framework import digest
                record.update(model=config.model,protocol=config.protocol,
                              prompt_version=digest([m for m in messages if m.get('role')=='system']))
                from .schemas import uid, now
                record.update(call_id=uid(), started_at=now(), result='running')
                if self.store:
                    from .execution import SCOPE
                    run=self.store.run(self.run_id)
                    record.update(unit_id=SCOPE.get(),run_attempt_id=run.attempt_id if run else None)
                if self.store:self.store.record(self.run_id,'call',record['call_id'],record)
                response=None
                try:
                    response = await self.http_client().post(endpoint,json=payload,headers=headers,timeout=limits.timeout)
                    if response.status_code >= 400:
                        record['http_status']=response.status_code
                        if response.status_code not in RETRYABLE_STATUS:
                            raise LLMError(f'模型请求被拒绝 HTTP {response.status_code}')
                        raise httpx.HTTPStatusError('retryable',request=response.request,response=response)
                    body=response.json()
                    usage=body.get('usage',{});stop=body.get('stop_reason','') if native else body.get('choices',[{}])[0].get('finish_reason','')
                    record.update(input_tokens=usage.get('input_tokens' if native else 'prompt_tokens'),output_tokens=usage.get('output_tokens' if native else 'completion_tokens'),
                        usage_source='provider' if usage else 'unavailable',finish_reason=stop)
                    record.update(cache_usage(usage, config.protocol))
                    record['response_model'] = body.get('model')
                    reasoning = (usage.get('completion_tokens_details') or {}).get('reasoning_tokens')
                    if isinstance(reasoning, int) and not isinstance(reasoning, bool) and reasoning >= 0:
                        record['reasoning_tokens'] = reasoning
                    if stop in {'length','max_tokens'}:raise TruncatedOutput('模型输出截断：必须拆分批次/问题，不重试原大请求')
                    try:result = parse_response(config.protocol,body)
                    except json.JSONDecodeError:raise IncompleteOutput('工具 JSON 不完整，需要拆批') from None
                    bucket = self.usage.setdefault(agent,{'calls':0,'input_tokens':0,'output_tokens':0})
                    bucket['calls'] += 1
                    bucket['input_tokens'] += result.input_tokens
                    bucket['output_tokens'] += result.output_tokens
                    if result.input_tokens and result.input_tokens > estimate * 1.15:
                        # Estimator under-counts for this model: requests may hit the real
                        # context limit. Raise CDR_TOKENS_PER_CJK / lower CDR_CHARS_PER_TOKEN.
                        logger.warning('token estimate low for %s: provider=%s estimate=%s', config.model, result.input_tokens, estimate)
                    if usage:
                        self.reserved_tokens-=estimate+reserve
                        self.reserved_tokens+=result.input_tokens+result.output_tokens
                    record['result']='ok'
                    return result
                except LLMError as exc:
                    record['result']=type(exc).__name__;raise
                except asyncio.CancelledError:
                    record['result']='interrupted';raise
                except (httpx.HTTPError, ValueError, KeyError, IndexError):
                    record['result']='transport_or_protocol_failure'
                    if attempt + 1 == limits.retries:
                        raise LLMError('模型调用失败：网络、超时或响应结构异常') from None
                    await asyncio.sleep(retry_delay(attempt, response if response is not None and response.status_code >= 400 else None))
                finally:
                    if record['result']=='running':record['result']='unexpected_failure'
                    from .execution import accounted_tokens
                    self.reserved_tokens += accounted_tokens(record) - record['budget_tokens'] if record['result'] != 'ok' else 0
                    record['duration_seconds']=round(time.monotonic()-started,4);self.log_call(record)
        raise LLMError('模型调用未返回结果')

    async def structured(self, agent: str, messages: list[dict], schema: type[T]) -> T:
        if self.store:
            from .execution import unit, SCOPE
            config = self.resolve(agent)
            identity = {'model': config.model, 'protocol': config.protocol, 'base_url': config.base_url,
                        'structured_mode': config.structured_mode,
                        'max_tokens': self.limits(agent).max_output_tokens or config.max_tokens}
            # Only non-default sampling settings join the identity, so committed
            # results from runs created before these options existed stay reusable.
            temperature = self.limits(agent).temperature if self.limits(agent).temperature is not None else config.temperature
            if temperature is not None:
                identity['temperature'] = temperature
            if config.extra_body:
                identity['extra_body'] = config.extra_body
            async def invoke():
                return (await self._structured(agent, messages, schema)).model_dump(mode='json')
            result = await unit(self.store, self.run_id, 'model', agent,
                                [SCOPE.get(), identity, schema.model_json_schema(), messages], invoke)
            return schema.model_validate(result)
        return await self._structured(agent, messages, schema)

    async def _structured(self, agent: str, messages: list[dict], schema: type[T]) -> T:
        retries=self.limits(agent).retries
        for attempt in range(retries):
            response = await self.complete(agent,messages,schema=schema)
            try:
                call = next((c for c in response.tool_calls if c.name=='structured_output'),None)
                return schema.model_validate(call.arguments) if call else schema.model_validate_json(response.content)
            except ValueError as exc:
                detail=' '.join(str(exc).split())[:500]
                try:json.loads(response.content) if response.content else None
                except json.JSONDecodeError:raise IncompleteOutput('结构化 JSON 不完整，需要缩小请求') from None
                if attempt+1 == retries:
                    raise LLMError('结构化输出未通过 Pydantic 校验：'+detail) from None
                messages = messages + [{'role':'user','content':'上次结果不符合 JSON Schema：'+detail+'。请重新返回完整且类型正确的对象。'}]
        raise LLMError('结构化输出失败')

    async def with_tools(self, agent: str, messages: list[dict], definitions: list[dict], handlers: dict, max_rounds: int = 3) -> LLMResponse:
        history = list(messages)
        for _ in range(max_rounds):
            result = await self.complete(agent,history,tools=definitions)
            if not result.tool_calls:
                return result
            history.append({'role':'assistant','content':result.content,'tool_calls':[{'id':c.id,'type':'function','function':{'name':c.name,'arguments':json.dumps(c.arguments)}} for c in result.tool_calls]})
            for call in result.tool_calls:
                if call.name not in handlers:
                    raise LLMError('模型请求了未注册工具')
                output = await handlers[call.name](**call.arguments)
                history.append({'role':'tool','tool_call_id':call.id,'content':json.dumps(output,ensure_ascii=False,default=str)})
        raise LLMError('工具调用达到轮次上限')
