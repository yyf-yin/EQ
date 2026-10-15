# 测试方法与实际执行记录

最新 v1.1 验收见本文末尾与 [V1_1_ACCEPTANCE.md](V1_1_ACCEPTANCE.md)。下列原 Phase 1–7、58 项回归和 18/16 页样例属于 v1.0 历史记录，保留但不代表新版本结果。

环境：Windows、Python 3.12.14、Node 24.19.0、Chrome、FastAPI、LangGraph 1.2.14。具体依赖版本保存 backend/requirements.lock.txt 与 frontend/package-lock.json。真实 API Key、模型及搜索服务未提供。

## 阶段记录

|阶段|实际执行|
|---|---|
|Phase 1|后端 2 测试、前端 3 交互测试及 Vite build 通过|
|Phase 2|6 项双协议 Mock HTTP 测试通过|
|Phase 3|30 项确定性财务与文件解析 Fixture 测试通过|
|Phase 4|3 项 LangGraph 主图、节点恢复及缺配置测试通过|
|Phase 5|2 项报告导出/数值绑定测试及 3 项图测试通过|
|Phase 6|11 项终审、九类故障注入及定向修复测试通过|
|浏览器端到端|3 项 Chrome Playwright 测试通过：完整流程/刷新/下载、SSE 断线恢复、失败状态/XSS 转义|
|工程|TypeScript/Vite build、npm audit 零漏洞、pip check 通过|

最终全量回归：58 项后端测试通过（63.70 秒），3 项前端交互测试通过，3 项 Chrome 浏览器测试通过，TypeScript/Vite 生产构建成功，npm audit 为零漏洞，pip check 无依赖冲突。单位专项新增测试验证商品单价 CNY/unit 与股票价格 CNY/share 不能混用。每个阶段均在实际测试成功后继续，没有把失败测试计入通过。

## 覆盖范围

- 双协议：请求路径、认证头、system、结构化工具、Tool Calls/Results、JSON Schema、Token 用量、429 重试、超时和缺配置。FastAPI ASGI Mock HTTP Server 与 httpx MockTransport 均为无凭证测试环境。
- 财务：全部最低指标、五种收入模型、Bear/Base/Bull、分部合计、资产负债与现金勾稽、零分母、缺失、错误单位、错误期间及冲突。
- 数据：PDF、DOCX、XLSX、CSV、TXT、Markdown、HTML、JSON，精确行读取、来源定位、不可信脚本移除、公网地址限制、搜索缓存及重试。
- 工作流：真实 LangGraph 主图和子图、源→证据→事实→结果链、节点事件、检查点中断恢复、依赖取数及重规划。真实模式代码路径通过脚本化模型和搜索 HTTP Fixture 运行，仍不是外部真实联调。
- 终审故障：EPS、PE、分部收入、三表不平衡、现金流、实际/预测混淆、关键来源缺失、核心观点冲突、目录缺失；定位 location 与 target_node，严重问题不交付。
- 前端：输入、提交、SSE 更新、刷新恢复、失败、报告、表格、来源、DOCX 文件下载、断网恢复及 XSS 文本转义。

## 文档视觉核查

标准 documents/render_docx.py 在本机发现缺少 LibreOffice，实际错误为 `LibreOffice soffice.exe was not found on PATH`。随后使用已安装的 Word 隐藏窗口只读 ExportAsFixedFormat，再复用该脚本的 rasterize 与 bundled Poppler 生成页面 PNG；独立正式 PDF 用 Poppler 渲染。逐页检查标题、表格、图表、目录、附录与分页。发现并修复了 DOCX 假设表等宽导致的过长行、重复证据及默认 Title 边框。完整数据仍在 JSON 中，纸面附录对长摘录做摘要。

最终 DOCX 在 Word 中排版为 18 页，正式 PDF 为 16 页，所有页面均经过视觉核查。PDF 目录与正文页码核对：公司简介第 2 页、财务分析第 3 页、业务第 4 页、预测估值第 6 页、风险及三表第 10 页、免责声明第 11 页。

Word 渲染用于 QA，不是正式 PDF 下载的来源。正式 PDF 由 ReportLab 多遍排版，目录实际页码经过正文核对。PNG/Word 中间 PDF 为工作区 QA 材料，不属于交付输出。

## 重跑

从仓库根目录：`python -m pytest backend/tests -q --basetemp=work/pytest`。前端目录运行 `npm test`、`npm run build`；先启动前后端，再 `npm run test:e2e`。Windows 当前沙箱对 Node realpath/SQLite 存在权限限制，本次实际运行在允许的外部执行环境中进行；这不代表需要将应用配置为管理员运行。

## 待验证

真实模型协议兼容性、上下文长度与研究质量、真实搜索服务协议和资料可得性、真实 A 股年报提取准确性、真实财务预测假设与估值合理性。上述内容只有用户配置后才能进行，不在本次已通过的 Mock 测试范围内。
# 迁移后验证

2026-10-09 在 `C:\work\PROJECTS\eq_new` 重建独立环境并重新验证：后端 58 项、前端交互 3 项、Chrome 端到端 3 项全部通过；TypeScript/Vite 构建与 pip check 通过。新工程运行于前端 5174、后端 8001。完整迁移范围和证据见 [MIGRATION.md](MIGRATION.md)。

## 2026-10-10 v1.1

后端完整回归 99 项通过（160.75 秒）；新增框架、语义遗漏、长表/跨页、截断拆批、角色并发、预算恢复、特殊基数/百分点、中期口径、成稿硬门槛、重述局部复用、旧批准失效、历史证据复用与缓存刷新。前端交互 3 项和生产构建通过。最终 Chrome 3 项通过（41.7 秒），检查 14 张表、20 项核心比较、9 个预测、刷新/SSE/下载/失败与 XSS。pip check 无依赖冲突。

最新全量命令与机器记录：`--basetemp=work/pytest-v11-final-release --junitxml=work/v11-final-release-results.xml`。最后批次范围定向复核另有 2 项通过（31.43 秒），记录 work/v11-batch-scope-results.xml。所有测试均为离线/合成/Mock HTTP，不是真实外部模型验收。

版本化样例 examples/reference_reports/v1_1 核心年度与中期分别成表，含实际金额正文与完整来源。DOCX 标准渲染器缺少 bundled LibreOffice，已用隐藏 Word 只读排版、bundled Poppler 渲染；正式 PDF 为独立 ReportLab 输出。最终 Word 排版 32 页、正式 PDF 25 页，全部页面已逐页检查：正文、表格、图表、来源说明及分页可读，无重叠或裁切。PDF 目录核对：公司简介第 2 页、财务第 3 页、F01 第 4 页、F02 第 7 页、F03 第 8 页、F04 第 10 页、F05 第 11 页、业务第 12 页、预测第 14 页、风险/三表第 17 页、免责声明第 18 页。Poppler 字体替代/提示保留在日志，未把警告描述为无异常。QA 材料位于 work/v11-qa/final；不会用 Word 中间 PDF 替代正式 PDF。

真实模型/搜索配置缺失；实际供应商 token、真实财报提取/变化解释质量、代表性公司和同范围成本比较未取得。记录详细区分 UTF-8 保守容量估算与供应商 usage；脚本化服务固定 usage 不计真实成本。

## 2026-10-10 v1.2

完整后端回归 114 项通过（244.21 秒），补充边界测试 3 项通过（1.32 秒）。前端交互 7 项与 TypeScript/Vite build 通过；Chrome 原有 3 项及新增 2 项共 5 项通过（35.1 秒）。最终页面改动后新增浏览器 2 项再次通过（4.7 秒）。阶段专项覆盖固定快照、三种导出与 ZIP 校验和/记录数、写作前/终审/渲染/导出故障、空成果、重启、跨任务隔离、损坏记录、脱敏、预算/实际用量区别、事实重述与依赖失效。正式审核条件不因阶段获取而放行。

完整命令记录：`--basetemp=work/pytest-v12-regression --junitxml=work/v12-regression-results.xml`；补充故障记录 `work/v12-extra-results.xml`。最终阶段专项复核另见 [V1_2_ACCEPTANCE.md](V1_2_ACCEPTANCE.md)。浏览器使用 work/v12-browser 隔离数据库、8012/5182 端口；未访问既有真实研究配置。所有验证为离线/合成/Mock HTTP，E 阶段真实联调结论不变。

## 2026-10-11 运行信息展示

新增运行耗时、并行任务及耗时、已保存材料数、问题覆盖/批次/分析块状态、真实模式模型调用和服务商 Token、完整日志及异常筛选。模型请求开始时持久化处理中记录，返回或取消时更新同一记录；状态接口仅返回白名单元数据和计数。阶段材料与正式记录按 kind/id 去重，统计读取不改变研究状态。结束任务刷新后仍重放 SSE 历史；返工时完成阶段计数可回退，终止后不继续显示旧运行任务。

前端 11 项交互测试通过：`npm.cmd test -- --pool=threads --maxWorkers=1`；TypeScript/Vite build 通过。Chrome 4 项通过：`CDR_E2E_BASE_URL=http://127.0.0.1:5183 npm.cmd run test:e2e -- e2e/research.spec.ts e2e/runtime-progress.spec.ts`，覆盖原有模拟流程/下载/断线/XSS、新增运行信息/日志筛选/刷新/390px 窄屏。桌面与手机截图位于 `frontend/test-results/runtime-desktop.png`、`frontend/test-results/runtime-mobile.png`，已检查布局无横向溢出。

后端相关回归共 38 项在分批验证中通过（不是全量回归）：test_runtime_progress.py、test_llm.py、test_phase1.py、test_graphs.py、test_work_products.py 共 33 项，以及 test_v11.py 中 5 项预算/角色相关验证。首次运行的 test_mock_flow 受本机 .env 的 real 模式影响失败；显式设置 `CDR_MODE=mock` 后补跑通过。新增测试验证请求等待期间可见、返回/中断后更新同一记录、Token 统计、部分材料去重及白名单投影。所有调用均为合成或 Mock HTTP。

Windows 沙箱内 Python asyncio 的 socketpair 初始化阻塞，后端与 Chrome 验证在允许的沙箱外执行；前端默认 fork 测试池遇到沙箱临时路径 ENOENT，改用 threads 测试池通过。浏览器后端使用 `work/runtime-browser` 隔离数据库和模拟模式（8013/5183），没有发起真实研究。

## 2026-10-11 断点续跑

最终完整后端回归 153 项通过（326.75 秒），原始结果 `work/resume-final-results.xml`；前端 14 项通过及 TypeScript/Vite build 通过；Chrome 5 项通过、2 项需要额外阶段成果样例 ID 的可选场景跳过。新增验证包括并行成功任务复用、子步骤恢复、跨库提交窗口、强制结束子进程、预测 7 组成功后失败、Reflection 失败时保留草稿、主动暂停后重启、同 ID SSE 重连、预算追加/累计用量/角色块限额和输入不兼容保护。浏览器已检查暂停→刷新→继续→同一任务交付，390px 无横向溢出。

测试全部使用隔离数据库、合成资料或 Mock HTTP，没有调用真实模型/搜索。前端使用 threads 单 worker；后端/Chrome 使用获准的沙箱外运行。浏览器独立服务位于 `work/resume-browser`、8014/5184，已停止；截图在 `frontend/test-results/resume-paused.png` 与 `resume-mobile.png`。完整实现范围与剩余扩展见 [RESUME_ACCEPTANCE.md](RESUME_ACCEPTANCE.md)。


## 2026-10-12 财务核验优化

已实现候选数据保留、单位规范化、期间/主体/披露范围/实际与预测/币种隔离、会计口径冲突识别、定向检索原始披露与更正公告、保守证据裁决、成功补查重放及每组累计轮次限制。第二轮使用不同的定向查询，避免重复消费缓存搜索。未选用事实不进入计算；关键预测输入未核实时不生成假设/预测，其他块继续研究，最终审核阻止正式交付。受影响计算和依赖块失效，无关输入快照复用。来源/事实原记录不可覆盖。

最终验证由完整后端回归 240 项（work/financial-final-results.xml，412.24 秒），补充财务/公式/v1.1 回归 90 项（work/financial-supplement-results.xml），最终核验与审计导出回归 40 项（work/financial-audit-final-results.xml）共同覆盖；这些集合有重叠，不应相加。前端 18 项交互测试和 TypeScript/Vite build 通过；Chrome 7 项通过，2 项需额外持久化故障样例的可选导出场景跳过，对应后端导出保护已有独立回归。

覆盖包括：不同单位但数值等价；不同期间/范围/实际预测分组；同数值不同会计口径仍冲突；伪造域名、搜索发布日期、多数票和模型 supersedes 均不能裁决；原始披露与明确方向更正；新候选撤销此前选择并在剩余轮次内核实；中断后补查成功结果重放；关键冲突保留独立块及阶段成果、拒绝正式报告；裁决策略版本随评估包导出；已选事实被数据库异常修改时旧审核失效。

前端阶段成果可展开候选值、来源/证据 ID、选择结果和理由。桌面和 390px 截图已检查无横向溢出：frontend/test-results/financial-conflict-desktop.png、financial-conflict-mobile.png。浏览器使用 work/resume-browser 独立模拟数据库及 8014/5184 服务，验收后已停止。全部验证使用合成资料、模拟搜索/模型或 Mock HTTP；没有调用真实模型和搜索，没有改动真实研究任务。

本机 .env 默认真实模式；运行验收时在测试进程设置 CDR_MODE=mock，并使用独立 --basetemp 目录，不修改 .env。财务核验策略及补查配置进入断点兼容性校验，旧策略任务不可绕过新规则交付。自动裁决支持范围和安全保留的复杂披露情形见 FINANCIAL_RECONCILIATION.md。
