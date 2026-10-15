import asyncio
import logging
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from .config import Settings
from .storage import Store
from .llm import Gateway,ConfigurationError,LLMError,BudgetError
from .graphs import ResearchWorkflow
from .financials import FinancialError
from .datasources import DatasourceError
from .execution import PauseRequested, RecoveryError, ensure_manifest, budget_limits, load_gateway
from .schemas import uid, now
from .human_intervention import HumanInputRequired
from .isolation import ensure_isolation

logger=logging.getLogger('company_research')


class Runner:
    def __init__(self,settings: Settings,store: Store):
        self.settings,self.store=settings,store
        self.limit=asyncio.Semaphore(settings.max_active_runs)

    async def run(self,run_id: str) -> None:
        async with self.limit:
            run=self.store.run(run_id)
            if not run:return
            session_id = getattr(self.store, 'service_session_id', None)
            if session_id is not None and self.store.execution_get(run_id, 'execution_meta', 'service-session') != {'session_id':session_id}:
                return
            attempt_id=uid()
            run=self.store.transition_run(run_id,{'queued','interrupted','failed','waiting_human'},status='running',error=None,
                failure_code=None,stop_reason=None,attempt_id=attempt_id,
                resume_count=run.resume_count+(1 if run.attempt_id else 0))
            if not run:return
            attempt={'attempt_id':attempt_id,'started_at':now(),'status':'running'}
            self.store.execution_put(run_id,'execution_attempts',attempt_id,attempt)
            for record in self.store.records(run_id,'call'):
                if record.get('result')=='running':
                    record['result']='uncertain';self.store.record(run_id,'call',record['call_id'],record)
            gateway=None
            try:
                ensure_isolation(self.store, run_id)
                limits=budget_limits(self.settings,self.store,run_id)
                self.store.execution_put(run_id,'execution_meta','budget',limits)
                if run.mode=='real':gateway=load_gateway(self.settings,self.store,run_id)
                ensure_manifest(self.settings,self.store,run_id,gateway)
                checkpoint=self.store.load_checkpoint(run_id)
                if not checkpoint:run.rules_version='1.1';self.store.save_run(run)
                workflow=ResearchWorkflow(self.settings,self.store,run_id,gateway)
                async with AsyncSqliteSaver.from_conn_string(str(self.settings.database.parent/'graph.sqlite')) as saver:
                    graph=workflow.build(saver)
                    config={'configurable':{'thread_id':run_id},'recursion_limit':150}
                    graph_state=await graph.aget_state(config)
                    if graph_state.values and (graph_state.values.get('context', {}).get('run_id') != run_id or
                                               graph_state.values['context'].get('input') != run.company_input):
                        raise RecoveryError('图检查点不属于当前任务或输入，拒绝恢复；原成果保留。')
                    if checkpoint and not graph_state.values:
                        raise RecoveryError('图检查点缺失，无法安全恢复；请恢复 graph.sqlite 或导出原阶段成果。')
                    checkpoint=graph_state
                    if checkpoint.values and not checkpoint.next:
                        context=checkpoint.values['context']
                        if context.get('report'):
                            await workflow.render(context);await workflow.deliver(context)
                        else:
                            raise RecoveryError('图已结束但缺少报告上下文，无法安全恢复；原阶段成果保留。')
                    else:
                        await graph.ainvoke(None if checkpoint.values else {'context':{'input':run.company_input,'run_id':run_id,'replans':0,'revisions':0}},config,durability='sync')
                if gateway:self.store.record(run_id,'usage','llm',gateway.usage)
                final=self.store.run(run_id)
                self.store.emit(run_id,'文档生成','delivery',final.status,'模拟报告已生成，可阅读和下载' if run.mode=='mock' else '报告已生成，可阅读和下载')
            except HumanInputRequired:
                self.store.transition_run(run_id,{'running'},status='waiting_human',failure_code=None,error=None,stop_reason='human')
                self.store.emit(run_id,'数据核验','run','waiting_human','其他采集已完成，关键数据待人工处理；计算分析尚未开始')
            except (asyncio.CancelledError,PauseRequested) as exc:
                run=self.store.run(run_id);run.status='interrupted';run.stop_reason=run.stop_reason or 'shutdown';self.store.save_run(run)
                self.store.emit(run_id,run.stage,'run','interrupted','研究已暂停，已提交成果保留，可从断点继续')
                if isinstance(exc,asyncio.CancelledError):raise
            except RecoveryError as exc:
                run=self.store.run(run_id);run.status='failed';run.failure_code='incompatible';run.error=str(exc)
                self.store.save_run(run);self.store.emit(run_id,run.stage,'run','failed',run.error)
            except (ConfigurationError,LLMError,FinancialError,DatasourceError,ValueError) as exc:
                run=self.store.run(run_id);run.status='blocked' if isinstance(exc,FinancialError) else 'failed'
                run.error=str(exc) if isinstance(exc,(ConfigurationError,LLMError,FinancialError,DatasourceError)) else '研究无法继续：身份、期间、引用或配置未通过检查。'
                run.failure_code='budget' if isinstance(exc,BudgetError) else 'quality' if isinstance(exc,FinancialError) else 'configuration' if isinstance(exc,ConfigurationError) else 'execution'
                self.store.save_run(run);self.store.emit(run_id,run.stage,'run',run.status,run.error)
                logger.warning('run=%s failed_type=%s',run_id,type(exc).__name__)
            except Exception as exc:
                run=self.store.run(run_id);run.status='failed';run.error='研究执行异常，请检查后端日志中的节点及异常类型。'
                run.failure_code='execution'
                self.store.save_run(run);self.store.emit(run_id,run.stage,'run','failed',run.error)
                logger.error('run=%s node=%s error_type=%s',run_id,run.stage,type(exc).__name__)
            finally:
                final=self.store.run(run_id)
                attempt.update(status=final.status,ended_at=now(),failure_code=final.failure_code)
                self.store.execution_put(run_id,'execution_attempts',attempt_id,attempt)
                if gateway:self.store.record(run_id,'usage','llm',{'roles':gateway.usage,'calls':gateway.calls,
                    'budget_tokens_reserved':gateway.reserved_tokens,'provider_input_tokens':sum(r.get('input_tokens') or 0 for r in gateway.call_records),
                    'provider_output_tokens':sum(r.get('output_tokens') or 0 for r in gateway.call_records),
                    'usage_missing_calls':sum(r.get('usage_source')!='provider' for r in gateway.call_records)})
