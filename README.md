# Company Deep Research Agent

固定财务表已增加季度／中期槽：单季度与年初累计分开。本次上传财报中，研究当年最新已披露累计期间及上年同期核心数据必须齐全并计算同比；历史季度未披露可留空。年报、季报、中报均由本次上传提供。期间编码、门槛与使用例见 [季度数据槽](docs/QUARTERLY_DATA_SLOTS.md)。更新后重启服务并新建研究。

真实模式已改为固定财务与证券填槽：七区 133 个原始字段，由程序实例化，plan 不再设计财务取数任务。证券仅从 local-datasource 获取，年报、季报、中报仅由用户为本次研究上传，不自动采纳本地目录财报或寻找替代财报；财务与债券只从本次财报提取，检查通过后锁定，不增加资料质量评分或重复人工确认。业务行业按“通用预设方向＋模型补充中性方向”组织资料包，默认每槽一次宽搜索加最多两次分组补查，允许缺口并记录停止原因，同一资料在本次研究内复用，不建设本地资料库。前端提供固定表及资料方向覆盖查看，模拟模式展示合成数据投影。使用合同、范围与验证见 [用户年报入口](docs/USER_ANNUAL_REPORTS.md)、[固定表实施验收](docs/FIXED_DATA_SLOTS_ACCEPTANCE.md) 和 [业务行业资料收集](docs/QUALITATIVE_COLLECTION.md)。更新后重启服务并创建新研究，旧断点不混用新规则。

启动页已提供“参考资料 / 添加文件”：上传年报、研报等材料并绑定新研究，真实模式优先提取上传资料，仅检索缺失数据和问题；任务刷新后保留附件列表。支持的格式、实际接口和模拟模式行为见 [参考资料上传](docs/REFERENCE_UPLOADS.md)。

当前需求见 [PRD v1.2](docs/PRD.md)。已在既有工程上实施 v1.1 的 A–D：版本化必需框架、有界取证与分析、核心同比硬门槛、局部修复和整体综合。离线、Mock HTTP 与浏览器验证记录见 [v1.1 实施验收](docs/V1_1_ACCEPTANCE.md)；E 阶段真实模型研究与成本对比尚未完成。v1.2 已实现“阶段成果获取与评估出口”，本地验收见 [v1.2 实施验收](docs/V1_2_ACCEPTANCE.md)，历史基线见 [PRD v1.1](docs/PRD_V1_1.md)。

上市公司深度研究 MVP：一个页面输入公司或代码，查看真实节点进度，阅读只读报告并下载 DOCX/PDF。默认 **模拟模式**，使用虚构 DEMO 制造企业的本地合成资料；任意输入都明确标记模拟，不代表该公司的真实情况。

运行进度区显示累计耗时、已完成阶段、并行任务及耗时、资料/证据/财务事实/计算/草稿数量、问题覆盖和取证批次。真实模式显示模型请求次数、处理中请求、服务商返回的输入/输出 Token 及最近请求；尚未返回或缺失用量会明确标注。可展开分析块状态和完整日志，并筛选提示与异常。状态每 3 秒刷新，细分事件通过 SSE 实时推送，刷新页面后恢复任务和事件记录。运行耗时包含排队及中断期间，不代表纯模型执行时间。

提速迭代已增加持续调度、批次/章节/假设的有界并行、完整请求容量组批及成功窗口复用，保持原有证据、审核和续跑要求。新任务自动启用，旧断点保留原策略；载入更新需要重启后端。验证与性能边界见 [提速验收](docs/PERFORMANCE_ACCEPTANCE.md)。

已实现 React/TypeScript/Vite/Tailwind 单页、FastAPI/SQLite/SSE、持久 LangGraph 主图与 Researcher/终审子图、OpenAI-compatible/Anthropic-native Gateway、Web/Local 适配、证据链、Decimal 公式与依赖图、五种收入模板、三表联动、Bear/Base/Bull、章节写作与反思、核心观点、定向返工、HTML/DOCX/PDF。无账户、聊天、侧边栏、Skills 创建、历史管理或额外金融 API。

## 启动

需要 Python 3.11+（已测 3.12）和 Node 22.12+（已测 24）。以下从仓库根目录运行，Windows PowerShell：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".\backend[test]"
Copy-Item .env.example .env
cd frontend
npm.cmd ci
cd ..
```

终端一：

```powershell
.\.venv\Scripts\python.exe -m uvicorn company_research.api:app --host 127.0.0.1 --port 8000
```

终端二，从仓库根目录：

```powershell
cd frontend
npm.cmd run dev
```

打开 http://127.0.0.1:5173 。默认无需真实密钥。输入公司名称后可看到模拟研究、完整报告及下载。后端仅一个 worker；浏览器刷新不会丢任务。Linux/macOS 可用 `.venv/bin/python` 和 `npm` 对应命令。

当前工程位于 `C:\work\PROJECTS\eq_new`，已安装本目录独立的 `.venv` 与前端依赖。也可在两个 PowerShell 终端直接运行 `./scripts/start_backend.ps1` 与 `./scripts/start_frontend.ps1`。后端启动脚本优先项目 `.venv`。需要更换端口时，后端使用 `-Port 8001`，前端使用 `-Port 5174 -BackendPort 8001`。迁移验证记录见 [MIGRATION.md](docs/MIGRATION.md)。

也可以使用一个总控启动脚本：

```powershell
.\start.bat
```

它会启动前后端、以独立 Chrome 应用窗口打开 `http://127.0.0.1:5173`，并在该窗口关闭后自动停止本次启动的前后端进程。可双击项目根目录的 `start.bat`，或在 PowerShell 中使用 `./start.bat -FrontendPort 5174 -BackendPort 8001` 改端口；Chrome 非标准安装位置时传入 `-ChromePath 'C:\path\to\chrome.exe'`。底层脚本为 `scripts/start.ps1`，启动日志保存于 `work\launcher-<会话 ID>`。

离线可重复依赖安装：先下载所需 wheel，再使用 backend/requirements.lock.txt；前端 package-lock.json 已锁定实际测试版本。锁文件记录了本环境包含的全部测试依赖，不包含凭证。

## 配置真实研究

```powershell
Copy-Item configs/models.example.yaml configs/models.yaml
```

在 models.yaml 填 Base URL、模型名称、协议及 Agent 路由。在 .env 填后端密钥并设 CDR_MODE=real。OpenAI-compatible 的 base_url 包含所需 /v1，系统追加 /chat/completions；Anthropic-native 系统追加 /messages，使用原生 x-api-key 与版本头。可单独配置 Writer/Reviewer 等角色。具体参数见 [LLM_CONFIGURATION.md](docs/LLM_CONFIGURATION.md)。

当前本地环境已预置 DeepSeek V4.1 Flash：`configs/models.yaml` 将全部角色路由至 `deepseek-flash`，`.env` 中的 `CDR_DEEPSEEK_API_KEY_FILE=keys.txt` 使后端在启动时读取根目录密钥文件。请不要将密钥填入 `models.yaml`、提交 `keys.txt`，或将其打印到终端。

CDR_SEARCH_URL 指向支持本文档 JSON 合同的搜索服务；CDR_SEARCH_KEY 是认证头的完整值。若真实服务请求合同不同，应实现 SearchProvider 适配后注入，不能只替换 URL。网页/公开文档由同一 Web Adapter 读取。**尚无真实模型、搜索凭证，外部在线联调与真实研报质量待验证；Mock HTTP 通过不代表真实联调成功。**

本地资料放 data/local_sources，或 CDR_LOCAL_SOURCES 指定绝对目录。支持 PDF/DOCX/XLSX/CSV/TXT/Markdown/HTML/JSON，精确财务字段见目录说明。扫描 PDF 需要 OCR。模拟资料位于 examples/fixtures，真实模式不会自动加载。

## API

|方法|路径|用途|
|---|---|---|
|POST|/api/research|请求 JSON 仅 `{"company":"公司或代码"}`|
|GET|/api/research/{run_id}|状态、限制及可下载格式|
|GET|/api/research/{run_id}/events|SSE，支持 Last-Event-ID/after|
|GET|/api/research/{run_id}/report|结构化 JSON，format=html 可获取安全 HTML|
|GET|/api/research/{run_id}/download|format=docx 或 pdf|
|GET|/api/research/{run_id}/work-product|已提交快照元数据、清单和分页预览；可指定 snapshot_id、page、page_size|
|GET|/api/research/{run_id}/work-product/download|评估包，format=zip/json/md；可指定 snapshot_id|
|GET|/api/health|服务状态及模式|
|POST|/api/research/{run_id}/cancel|pause 的兼容别名|
|POST|/api/research/{run_id}/resume|原任务断点继续，支持暂停、执行失败及预算造成的阻断|
|POST|/api/research/{run_id}/pause|暂停接收新工作，保存已发请求的结果，最长收尾 60 秒|
|GET|/api/research/{run_id}/recovery|恢复位置、已保存单元、累计预算与恢复条件|
|POST|/api/research/{run_id}/budget|提高原任务总调用、token 与每块调用上限，保留消耗记录|

完成=completed，核心要求通过且仅有非核心限制=limited，核心数据/同比或终审无法修复=blocked，执行故障=failed，中断=interrupted。blocked/failed 不提供正式报告下载，但可通过“查看阶段成果”和“导出评估包”获取已保存材料。新报告使用规则 1.1，导出检查有效快照；旧报告保留规则 1.0，不视为通过新验收。PDF 可选渲染失败时保留 DOCX 与线上报告，前端只显示实际生成的格式。

## 阶段成果与后续评估

### 暂停与断点续跑

进度区增加“暂停研究”；保存结束后可“继续研究”。可恢复的执行失败显示“从断点继续”，沿用原任务 ID、事件和已保存成果。程序启动后先检查最近创建、尚未完成且未选择放弃的任务；如存在，启动 CMD 窗口要求输入 Y/N。Y 校验并读取该原任务最近已保存的检查点和成功结果继续；N 返回初始页面，不创建或自动执行研究；用户输入公司后点击“开始研究”才新建任务。选 N 的旧任务保留成果，并标记为不再提示续跑。没有待处理任务时正常显示研究首页。只有明确选 Y 的原任务会被接入本次服务，其他旧任务不自动恢复，也不能通过前端继续接口绕过启动选择。原任务仍可查看和导出已保存成果。浏览器刷新不视为程序重启，只要后端仍在本次运行中，就可以继续原任务。浏览器断线只重连进度，不暂停后端研究。

新任务按研究任务、检索、取证步骤、完整结构化模型输出保存执行单元。预测、写作/反思与语义审核的已提交模型结果可复用；已提交的有效 DOCX/HTML/PDF 不重复生成。相同输入、模型和规则下，已提交成功的单元不再重复外部调用。这些记录用于当前程序中的继续、启动明确选择 Y 后的原任务恢复和阶段成果查看，不合并其他任务记录。

恢复仅使用原 `run_id` 的检查点和已提交结果；同公司其他任务的财务事实不再自动导入，网页与搜索缓存也按任务隔离。同一来源、证据或财务事实 ID 对应的内容发生变化时拒绝覆盖，需要使用新 ID/版本。旧真实任务如果已有历史复用记录，或保存成果没有新的隔离标记，会阻止续跑及正式报告下载；原记录和阶段成果导出保留，导出明确标注隔离问题，需要新建研究。不能仅删除复用记录后将旧检查点视为干净数据。

同一来源的标题、发布日期属于检索元数据：正文和来源位置一致时，固定本任务首次保存的信息，后续差异另存为 `source_metadata` 观察记录，不覆盖原来源，也不据此阻断。正文、引用和财务口径冲突仍需审核。真实质量阻断不开放继续入口；仅旧版发布日期元数据误阻断可在启动选择 Y 并通过隔离检查后恢复。

本次程序运行期间执行因预算耗尽停止后可“调整续跑预算”，保存后再点击继续；仅提高上限，不清零调用数、token 用量和既有成果。显式提高每块预算也覆盖本任务的角色块调用限额，不改 models.yaml。已发请求结果未知时保留估算预留，可能重试并再次计费；token 数不是费用账单。停止后端前，`start.bat` 尝试等待保存完成。

默认只以总 token 控制模型用量，调用次数保留统计；总调用和每块调用硬上限默认不启用，需要时设置 `CDR_ENFORCE_CALL_BUDGETS=true`。页面只显示生效的预算项，预算停止会指出实际耗尽的限制。上传资料全量预提取等 `global` 请求即使启用了次数限制，也不套用每块调用上限。旧版因次数限制提前停止的任务，重启并在启动窗口选择 Y 后可沿用原成果继续，不必提高 2000 万 token 总上限。研究轮数、重试和数据审核仍生效。

资料、模型、提示或流程参数改变时，当前版本拒绝混用新旧断点，需保留原阶段成果并新建任务。数据/终审质量阻断不能直接点击继续绕过审核；自动局部失效及质量阻断后的输入修复暂未开放。当前程序中的继续依赖原业务数据库、同目录的 graph.sqlite 和原成果目录；备份须一起保留；启动选择 Y 仍须通过隔离、检查点和配置兼容检查，缺失或不兼容时拒绝恢复。实现范围和验证见 [续跑验收](docs/RESUME_ACCEPTANCE.md)，完整扩展方案见 [RESUME_DESIGN.md](docs/RESUME_DESIGN.md)。

任务进度区提供“查看阶段成果”和“导出评估包”，适用于运行中、审核阻断、执行失败、中断以及完成任务。默认 ZIP 包含清单、摘要、已保存草稿、结构化数据、脱敏诊断及新运行的每轮送审记录；也支持 JSON 和 Markdown。预览显示当前/失效版本、审核问题与缺失项；下载使用预览对应的固定快照，点击“获取最新阶段成果”才切换到新快照。

阶段获取只读取已提交内容，不调用模型、不恢复研究、不改变审核或任务状态。正式 report/download 接口保留原有门槛。评估包不要求已有完整 Report 或 DOCX/PDF。旧任务只能获取实际留存的材料，不补造旧送审历史、模型版本或未提交片段；所有包标明“阶段成果｜未经最终审核｜可能不完整，仅供研究流程评估”。若当前成稿已获有效批准，会单独标出成稿快照及批准范围，历史诊断不因此视为合格。

默认单包限制 50,000,000 字节，可通过 CDR_WORK_PRODUCT_MAX_BYTES 调整。超限会明确报错，不静默省略材料；打包失败可重试，不必重新研究。快照及评估旁路材料保存到原 SQLite 的独立表，不覆盖正式记录。后端部署新代码后需重启；原数据库自动增表，已有运行记录保留。完整合同见 PRD 第 13 节。

## 测试与示例

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q --basetemp=work/pytest
cd frontend
npm.cmd test
npm.cmd run build
npm.cmd run test:e2e
```

浏览器测试要求前后端已运行，默认使用本机 Chrome；没有 Chrome 时调整 playwright.config.ts 或安装 Playwright Chromium。测试均无需真实凭证。结果和环境限制见 [TESTING.md](docs/TESTING.md)。

v1.1 合成示例位于 examples/reference_reports/v1_1，含 DOCX、PDF、HTML、JSON 和 run-events.json；原目录的 v1.0 示例保留。JSON 保留完整来源、摘录、事实、计算、假设与审核记录。生成脚本使用 work/v11-example 隔离数据库，不写既有运行数据库：

```powershell
.\.venv\Scripts\python.exe scripts/create_fixture.py
.\.venv\Scripts\python.exe scripts/export_example.py
```

## 明确边界

财务核验已支持候选保留、单位与口径分离、原始披露及更正公告定向补查、证据裁决、局部失效与重算。阶段成果展示候选值及裁决理由；关键冲突未解决时保留其他研究成果，阻止正式交付。具体规则、配置和自动判定边界见 [财务核验说明](docs/FINANCIAL_RECONCILIATION.md)。

- 当前为本地单进程 MVP，不含公网认证、分布式队列或多用户隔离。不要直接作为公开服务部署。
- 三表是可追溯的非金融企业简化模型；少数股东、递延税、复杂租赁、并购和多币种需要进一步模型扩展。所有缺失值、口径冲突和资金缺口显式处理。
- PyFin 已核实为可选 Finance-Python 0.9.10；其旧 Windows wheel 不兼容本环境 Python 3.12，未强装或虚构接口，公司公式独立执行。
- 真实搜索服务默认支持通用 JSON 合同，特定供应商仍需对应适配；没有凭证时真实模式报错。
- DOCX 目录由结构生成，未标未经排版核实的页码；PDF 多遍布局生成实际目录页码。DOCX 完整报告与图表可在 Word 阅读，正式页码目录后处理属于后续扩展。
- 研究深度和语义证据支持取决于模型与原始资料。真实模式的章节长度、引用、反思和独立终审已实现，外部模型质量尚未实测。

设计依据与模块说明：[PRD](docs/PRD.md)、[ARCHITECTURE](docs/ARCHITECTURE.md)、[DECISIONS](docs/DECISIONS.md)、[FINANCIAL_MODELS](docs/FINANCIAL_MODELS.md)、[TASKS](docs/TASKS.md)。参考 Open Deep Research 的研究循环与调度设计，独立实现，未复制第三方源代码。
