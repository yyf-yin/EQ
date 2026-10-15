# PRD v1.1 实施与验收记录

2026-10-10，在 `C:\work\PROJECTS\eq_new` 既有工程上完成 A–D 的代码升级和离线验收。复用原有 LangGraph、双协议 Gateway、Web/Local、SQLite、Decimal 注册公式、五种收入模板、三表、三情景、五维审核和单页流程。E 的代表性真实研究与成本比较未完成；本文件明确区分代码行为、合成验证和真实联调。

## 差距与落地

原工程已有任务与研究循环，但必需维度依赖模型 Plan；提取截取来源开头；部分分析/写作携带全公司材料；财务表不保证核心同比及实际数值正文；返工没有完整的块版本与批准快照门槛。升级新增三组核心模块 framework.py、contexts.py、comparisons.py，扩展现有图节点、Gateway、契约与存储，没有另建替代工程。

| 阶段/需求 | 实现位置（backend/src/company_research 下） | 验证依据与状态 |
|---|---|---|
| A 程序必需骨架 | framework.py / graphs.research_plan | 两业务 13 块、三业务 15 块；遗漏块/问题、错业务、依赖环、责任任务与预算错误均检出 |
| A Plan 修复 | graphs.research_plan / framework.validate_plan | 模型不能删改必需问题；语义修复受次数限制，失败回退已验证骨架 |
| A 覆盖矩阵 | schemas.CoverageEntry / framework.refresh_coverage | 事实/证据核查独立于任务完成；缺口明示，真实路径按问题分组补查 |
| B 完整来源与位置窗口 | datasources.join_document_chunks / contexts.locate_windows | 长材料不取固定开头；跨页标记、表头、单位、比较列、脚注和偏移保留；长表拆批测试 |
| B 提取与隔离 | researcher.py / agents.bind_extraction | 批次记录公司、业务、问题、范围、核心前序/中期比较期间；引用与原数值校验，非法提案进 quarantine |
| B 有界上下文 | contexts.block_context / agents.ask_bounded | 实际内容和选定 ID/版本持久化；小容量拆包测试；独立财务块只用历史计算，行业块不带无关财务事实 |
| B 预算与双协议 | llm.py / config.py | 角色容量/输出预留/超时/并发/重试/块预算及全局调用与预留预算；两协议长度截断识别，不完整 JSON 拆分，预算恢复与并发测试 |
| B 局部批次恢复 | researcher.run_batch / storage.py | 已拆父批次不重复请求，已验证子批次复用；图与节点检查点恢复沿用原实现 |
| B 历史复用与刷新 | storage.historical_facts / FinancialDataProcessor.get / graphs.resolve_company | 重新核对来源与原文证据；排除 Mock 和过期股价复用；缓存 TTL 可配置；重述版本/显式 supersedes 替代与冲突诊断 |
| C 核心比较 | comparisons.py / financials/formulas.py | 500→550、100→80、40→−10、−100→−60、0→10、百分点、中期口径专项通过 |
| C 五财务小节 | writers.make_report / comparisons.bind_financial_sections / supplemental_financial_tables | F01–F05；核心年度/中期分表、实际数字正文、来源与计算绑定；资产负债、FCF、分部毛利/占比、ROE/ROIC 等补充 |
| C 同比硬门槛 | comparisons.core_gate / reviewers.financial / graphs.final_review | 最早基数、归母口径、正文缺失、表值/增长率错误、错中期与比较遗漏均 critical；补查/修复耗尽 blocked 且无 DOCX |
| D 块分析与写作 | graphs.analyze_blocks / writers.write_one | 按问题分析、反证/支持/限制；缺答案定向修复；财务小节和各业务分别写作，章节按选定版本复用 |
| D 局部依赖失效 | contexts selected_versions / framework.descendants / graphs.revise | 单业务重述只重跑 B01-0、F04、V01、R01；其它业务/行业和独立财务块复用；范围/假设更新失效测试 |
| D 公司综合 | graphs.core_conclusion / writers.write_core / reviewers.critical | X01 最后执行，显式检查现金增长、预测总量、估值依据、资源集中度；综合后同步覆盖状态 |
| D 五维终审与快照 | reviewers.py / graphs.final_review/render/deliver / api.approved_report | 确定性先行；问题记录规则、责任块、修复引用与快照；上游事实或正文修改使旧批准失效，交付再次拒绝 |
| D 兼容与前端 | schemas / api / runner / frontend/src | 固定结构、原 API/SSE、DOCX/PDF 和三情景保留；状态增加块/批次/覆盖实际计数；旧报告标 1.0，旧检查点不跨规则恢复 |
| E 真实研究与成本 | 已有调用/usage 记录基础设施 | **未验收**：有效模型配置和搜索服务未提供，无真实外部调用或成本对比 |

具体新增验收测试在 backend/tests/test_v11.py；原 test_graphs、test_reviewers、test_llm、test_reports、test_financials、test_datasources 等继续回归。脚本化完整路径在 test_real_pipeline_mock_http.py。所有代码位置均为模块/方法说明，不是外部模型成功的证据。

## 11 类块与顺序

C01、F01 财务增长、F02 偿债、F03 现金质量、F04 分业务表现、F05 资本配置、V01 预测估值、R01 风险反证、X01 整体综合各一个；I01 行业和 B01 公司业务按 segment 实例化。块是调度单位，并非固定一次模型调用。

C01 确定范围后，F01/F02/F03/F05 和各 I01 可并行；对应 I01 完成后执行 B01；F04 依赖 B01，再依次 V01、R01、X01。财务依赖取数按块合并，没有为每个简单指标独立启动模型。V01 假设按情景与年度有界生成，确定性汇总三表。

## 同比如何阻断交付

核心为营业收入、营业成本、归母净利润、扣非归母净利润、经营现金流。展示三个实际财年和已披露中期，额外取得最早展示年的前序基数；中期须同长度，A/E、累计/单季度、归母/合并、币种/单位不能混用。

两期真实披露值经验证后由 Decimal 注册公式产生增减额与同比/状态。财务章节表格和正文共享该结果；正文逐项包含本期、同期、金额变化、方向、同比或特殊状态。原因没有证据时明确尚未确认，真实 Writer 可增加证据支持的解释，终审再核查。

确定性 core_gate 复建预期比较/计算，并核对五小节、完整字段、公式引用及必需实际数字正文。失败定位 F01/F03、责任规则和修复节点。修复耗尽后 blocked，保存诊断、工作与问题，不生成正式报告下载；不能把核心问题降为 warning/limited。非核心分部或背景缺口保留披露限制。报告、批准和导出关联同一有效快照。

## 实际测试记录

| 检查 | 实际结果 |
|---|---|
| 后端完整回归 | 99 项通过，160.75 秒；最终命令与 JUnit 见下文 |
| 最终批次元数据与脚本化完整路径定向复核 | 2 项通过，31.43 秒 |
| 前端交互 | 3 项通过 |
| TypeScript / Vite 生产构建 | 通过 |
| Chrome Playwright | 最终 3 项通过，41.7 秒：14 张表、20 核心比较、9 个预测、批准快照、DOCX 下载、SSE 断线/刷新、失败及 XSS |
| pip check | No broken requirements found |
| 合成全图与导出 | limited；13 块、27 个必需问题，20 个核心比较，9 个预测，456 个注册计算；核心要求通过 |
| 实际模型、真实披露验收 | 未执行；不能据此认定模型研究质量或成本改善 |

曾出现长表表头缺失、公司证据筛选、总审上下文超容量、局部缓存误带预测计算和测试事件字段错误，均修正后复跑；失败运行没有计为通过。中间 JUnit/pytest 目录保留，最新成功证据以最终文件为准。

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q --basetemp=work/pytest-v11-final-release --junitxml=work/v11-final-release-results.xml
.\.venv\Scripts\python.exe -m pip check
cd frontend
npm.cmd test
npm.cmd run build
$env:CDR_E2E_BASE_URL='http://127.0.0.1:15174'
npm.cmd run test:e2e
```

Windows 当前沙箱中 asyncio 初始化不能正常完成，后端/浏览器测试在自动审批允许的外部执行环境中运行；不是应用要求管理员权限。浏览器服务、样例及测试均使用隔离数据库，未重启用户原有 8001/5174 服务。

## 样例及导出核验

examples/reference_reports/v1_1 保存最终合成 JSON、HTML、DOCX、PDF、运行事件；原 v1.0 样例保留。脚本 export_example.py 使用 work/v11-example 独立数据库。示例最新财年由 Fixture 披露范围确定为 2023A–2025A，中期 2026H1 与 2025H1 比较，2022A 为额外基数；这些均是合成值，不是用户输入公司的真实财务。

合成样例覆盖 22 项 verified、5 项 missing；缺口在显著限制中保留，未把问题相关词匹配或 Mock 完成冒充真实语义覆盖，因此状态 limited。核心比较均通过。全文数值与来源一致性测试检查 DOCX 段落、PDF 比较引用、结构化表及有效快照。

标准 documents/render_docx.py 已实际尝试，但 bundled LibreOffice 缺失，不能按标准转换器渲染。随后以独立隐藏 Word 只读 ExportAsFixedFormat 排版 DOCX，使用 bundled Poppler 渲染；正式 PDF 仍由 ReportLab 生成，与 Word QA 中间 PDF 区分。表中长来源 ID 改为短标记、表后保留完整引用，修正窄列过度换行。最终 DOCX 在 Word 排版为 32 页，正式 PDF 为 25 页，全部页面已逐页检查，未见文字/表格重叠或裁切，目录、图表及来源说明可读。Poppler 报 STSong-Light 替代为 SimSun，以及 Symbol/ArialUnicode display font 提示，页面核查通过，不把警告写成无异常。

DOCX 目录不显示未经 Word 排版固化的页码；正式 PDF 多遍布局产生目录实际页码。页面 PNG、Word 中间 PDF 和统计保留 work/v11-qa/final，属于内部 QA。标准 LibreOffice 路径仍未验证，Word 及 ReportLab 路径已验证。

## 模型与 token 的真实状态

配置检查仅记录布尔状态，不读取或输出密钥：当前 mode=mock，configs/models.yaml 不存在，CDR_SEARCH_URL 未配置。默认上限为每块 40 调用、全局 240 调用与 2,000,000 个“输入保守估算 + 输出预留”单位，不能当作美元费用或精确实际 token。

脚本化 HTTP 夹具完整路径记录 148 次成功请求，响应故意固定每次输入/输出各 10，因此合计 1480/1480 是**测试值**。累计预留估算 5,691,058，最大单次输入估算 116,699；该测试显式设置 10,000,000 预留预算，不声称默认 2,000,000 能完成同样路径。它只证明记录、容量与图执行，不证明真实 token 成本或模型能力。统计见 work/v11-qa/final/statistics.json。

真实供应商输入/输出 token、真实截断/遗漏/返工率、同数据集旧新架构成本及交付质量：**未取得**。真实验收须覆盖两业务公司、三业务以上公司和负利润/负经营现金流基数，有可靠披露和明确可执行预算后开展。目前不宣称 token 下降、质量提升比例或任何真实模型必然胜任。

## 仍未完成与适用限制

- E 代表性真实公司研究、真实模型/搜索协议联调及旧新架构成本比较：缺少有效配置，没有发起外部付费研究。
- 表格定位和定性覆盖初筛使用启发式规则；复杂扫描 PDF、合并单元格、业务口径调整需可读/OCR/规范化资料及披露支持。真实提取准确率未测，模型必需问题答案仍由语义终审验证。
- 容量使用 UTF-8 字节保守估算，未集成模型专用 tokenizer；有限拆分仍可能不足，届时明确失败/阻断，不能保证任意小上下文成功。
- 历史复用保留原始证据和重述链、搜索/文档 TTL 可配置；最新公告发现是否完整、资料时效及真实复用成本尚未实测。
- 标准 LibreOffice DOCX 渲染尚不可用；替代 Word QA 不代表 LibreOffice 已验收。
- 原服务保留运行，重启后才能加载新代码。本目录没有 Git 仓库，本次无 commit 或 PR。

运行说明、预算示例与任务状态已同步 README.md、ARCHITECTURE.md、FINANCIAL_MODELS.md、LLM_CONFIGURATION.md、TASKS.md、TESTING.md、MIGRATION.md 和 PRD 状态说明，需求门槛没有下调。
