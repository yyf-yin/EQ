# 模型及搜索配置

复制 .env.example 为 .env，复制 configs/models.example.yaml 为 configs/models.yaml。默认 mock 不读取真实凭证。真实模式 CDR_MODE=real，修改后重启后端。

## OpenAI-compatible

配置 protocol: openai、base_url（包括所需 /v1）、model 和 api_key_env: CDR_OPENAI_API_KEY。密钥只放在后端 .env 或环境变量。也可以设置 `api_key_file_env`，让它引用一个保存密钥文件路径的环境变量；后端仅在运行进程中读取该文件并注入对应 `api_key_env`，不会写入日志、配置或运行记录。Gateway 追加 /chat/completions，使用 Bearer 认证。structured_mode 支持 tool（默认 schema 工具）、native（JSON Schema response_format）、json（JSON object + Pydantic 校验），按提供商实际支持选择。max_tokens 控制章节长度，达到长度上限报错，不把截断报告当成成功。

## Anthropic-native

配置 protocol: anthropic、base_url（包括所需 /v1）、model、api_key_env: CDR_ANTHROPIC_API_KEY、anthropic_version: 2023-06-01。Gateway 追加 /messages，使用 x-api-key 及 anthropic-version。system 独立于 messages，tool_use 与 tool_result 按原生内容块转换；结构化输出强制 schema 工具，并通过 Pydantic 检验。无真实厂商地址、模型名或密钥硬编码。

routes 可让 resolver/planner/researcher/writer/reviewer 使用不同配置项；未单独设置的角色回退到 default。LLM HTTP 错误、超时和格式异常受限重试；公开事件只包含阶段信息，不包含系统 Prompt、模型内部推理、密钥或供应商错误正文。Token 用量保存在后端 records 的 usage 记录。

## Web Search

CDR_SEARCH_URL 填入用户搜索服务的完整 URL，CDR_SEARCH_KEY 是该服务要求的认证头值，CDR_SEARCH_AUTH_HEADER 默认 Authorization。若服务采用 Bearer，请填完整 `Bearer <key>`。也可用 `CDR_SEARCH_KEY_FILE` 指向仅保存密钥的文件，后端在运行时读取它且不记录到运行数据。此地址只用于搜索结果获取，不是金融数据 API。

`CDR_SEARCH_PROVIDER=generic` 使用下方的通用 JSON 协议。`CDR_SEARCH_PROVIDER=bocha` 使用博查 Web Search：URL 为 `https://api.bochaai.com/v1/web-search`，密钥文件内容只写 API Key（不含 `Bearer `），适配器会发送博查的 `query`、`count`、`summary` 字段并标准化返回结果。

默认 Provider 合同：

```json
{"query":"公司 年报", "limit":6}
```

服务返回：

```json
{"results":[{"url":"https://公开来源/报告.pdf","title":"年度报告","publication_date":"2026-04-01"}]}
```

WebAdapter 从公开 URL 读取网页或文档并解析正文，搜索摘要不自动当作已验证事实。服务商的 API 若不符合上述 JSON 合同，应实现 SearchProvider.search(query,limit) 并注入 WebAdapter，不能只填任意搜索服务 URL 并假设协议兼容。代码已实现 HTTP 注入、缓存、下载、解析、重试与元数据，真实供应商联调待用户填写配置。

## 本地来源

data/local_sources 或 CDR_LOCAL_SOURCES 指定目录。规范化财务字段见该目录 README。真实模式不会加载 examples/fixtures 的模拟材料。模型可能无法提取某些复杂财务表，必须补查、提供规范化材料或输出限制，不能生成替代数字。

## v1.1 容量和预算

models.yaml 的 role_limits 支持 default 和具体角色（配置项使用一整组 RoleLimits，省略字段采用代码默认）：input_capacity、context_capacity、output_reserve、max_output_tokens、timeout、retries、concurrency、block_call_budget。角色并发同时受 CDR_CONCURRENCY 全局并发限制；显式启用次数限制时，角色块预算不能扩大全局块预算。配置示例不指定真实厂商/模型/价格。

| 环境项 | 默认 | 用途 |
|---|---:|---|
| CDR_EXTRACTION_INPUT_TOKENS | 16000 | 提取窗口/批次容量上限，Gateway 另检查完整请求 |
| CDR_ENFORCE_CALL_BUDGETS | false | 默认只统计次数；true 时才启用总调用与每块调用硬上限 |
| CDR_BLOCK_CALL_BUDGET | 40 | 显式启用时的单个分析块所有角色合计调用上限；无块 ID 的请求不受此项限制 |
| CDR_GLOBAL_CALL_BUDGET | 240 | 显式启用时的研究 HTTP 调用上限，失败/重试也计入 |
| CDR_GLOBAL_TOKEN_BUDGET | 2000000 | 已返回实际用量加未知请求预留的累计上限；发请求前另检查本次输入估算和输出预留 |
| CDR_MAX_BATCH_SPLITS | 2 | 原文提取批次的恢复拆分深度；分析/写作的截断和不完整输出拆分深度 |
| CDR_PLAN_REPAIRS | 2 | Plan/必需问题语义修复次数 |
| CDR_MAX_REPLANS | 2 | 研究缺口补查轮次 |
| CDR_MAX_REVISIONS | 2 | 终审定向返工轮次 |
| CDR_CACHE_TTL_HOURS | 6 | 搜索/文档缓存有效期，0 强制下一次读取刷新 |

当前输入估算为 JSON 的 UTF-8 字节保守上界，不是把字符数当精确 token，通常会高估；尚未集成模型专用 tokenizer。完整协议 payload（包括系统指令、Schema）估算 + max(输出预留,最大输出) 必须符合容量。拆分前超容量不会发 HTTP；长度停止原因和不完整 JSON 不作为成功结果，不原样无限重试。

参考资料问题覆盖检查使用 `reference_planner`，未单独配置路由/容量时沿用 `default`，不再占用 `researcher` 的小批次提取容量。使用独立的覆盖判断提示词，保留全部证据的 claim、逐字 quote、来源/证据 ID 和实际/预测属性，以及财务事实的期间、金额、单位、范围、业务与版本口径；省去整份 PDF 页码列表、重复审计字段和旧搜索查询。完整出处仍保存在原始记录，固定指令和任务背景排在变化的证据列表之前。拆包合并时保留同一问题两部分的证据 ID，后续仍验证引用属于本任务上传资料。提取角色的容量和成功断点不变。

OpenAI 兼容响应记录供应商返回的 `prompt_cache_hit_tokens` / `prompt_cache_miss_tokens`，或 `prompt_tokens_details.cached_tokens`。字段缺失或计数不一致时视为未知，不能当作零命中。页面缓存比例为有有效缓存记录请求的命中输入 token 总和 / 输入 token 总和，按 token 加权；历史未记录调用不参与比例，显示统计样本量。缓存命中输入仍计入总 token 预算，缓存优惠不等于输入 token 消失。最近请求同时显示实际输入/输出、单次请求耗时、响应模型名及供应商提供的 reasoning token 计数；不保存原始推理文本。单次请求耗时不是整个研究任务耗时，也不能单凭速度判断是否开启思考。

压缩及其他使用 `ask_bounded` 的请求会先按完整协议 payload 检查容量，超限时继续拆分可拆列表，直到请求可容纳或只剩无法再拆的单条内容；容量拆分不占用输出截断的恢复深度。研究压缩同时拆分证据和缺口说明，输入包含全部去重证据，合并各部分摘要、证据引用和未解决问题；已提交成功的部分可在续跑时复用。单条内容或固定上下文仍超容量时明确报错，不能通过增加任务总 token 预算解决单次请求容量问题。

records/call 保存角色、块/批次、模型配置标识、耗时、重试、结果、停止原因、供应商 usage 与估算方法；records/usage 保存累计预留、供应商输入/输出和 usage 缺失调用数。恢复从已有 call 重建预算，不重置额度。未提供 usage 时明确 unavailable；Mock HTTP usage 是夹具测试值，不能当真实成本。日志不保存密钥或供应商错误正文。

续跑首版请求开始前持久化 running 调用及估算预留；恢复时结果仍为 running 的请求标为 uncertain。已有 provider usage 时，累计 token 记账使用输入+输出实际用量；未知/未返回 usage 保留原预留，恢复口径与当前执行一致。结构化成功结果独立保存在 execution_units，命中有效结果不发送 HTTP，也不新增调用记账。

默认以总 token 控制模型用量，调用次数仅统计，不因拆批产生大量小请求而提前停止。研究轮数、返工轮数、重试、图递归限制及数据审核仍生效。需要调用次数硬上限时设置 `CDR_ENFORCE_CALL_BUDGETS=true`，总调用和每分析块调用才成为独立停止条件。上传资料的全量预提取、公司识别等无块 ID 的请求记录为 `global`，不把全部请求视为一个分析块。预算停止明确显示触发的限制、用量与上限；下一请求预留不足也明确显示。预算停止保留成果并开放断点恢复，包括旧版误标为 blocked 的预算任务；数据质量与终审门槛仍在后续流程中校验。

新任务开始时保存该任务总预算；之后不会因重启或修改 .env 将其清零。暂停/可恢复失败后在页面调整总调用、总 token 和每块调用上限，保存后再继续。显式提高每块上限会覆盖本任务各角色的旧块限额，使调整可生效；原 models.yaml 不修改。预算变化与审计记录在同一事务提交。相同模型下更新密钥或执行并发可继续；资料、提示、模型身份/输出上限及研究轮数等变化需恢复原配置或新建任务。预算控制没有模型价格或搜索费用换算，token 记账不等于实际账单。

历史财务事实复用要求原始证据仍可定位、公司/期间/单位/口径一致；股价不作为持久历史事实直接复用，需由当前披露/搜索和明示估值时点重新取得。缓存有效期控制再次获取，不能保证搜索服务完整返回最新公告；真实最新披露发现率仍需 E 阶段验证。

研究目录、表格或极小上下文超出有限拆分能力时会明确失败/阻断，需要按实际模型限制配置容量，不能声称任意容量都能成功。真实验收须先提供有效模型、搜索服务、可追溯资料与明确预算，详见 [V1_1_ACCEPTANCE.md](V1_1_ACCEPTANCE.md)。
