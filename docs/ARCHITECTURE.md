# 架构及数据流

React 单页通过 POST 创建任务，使用 EventSource 接收 SQLite 事件，并以 GET 状态恢复刷新及断线期间的变化。报告以结构化 JSON 在 React 渲染，文本自动转义，目录来自章节树；独立 HTML 也逐项转义并设置 CSP。DOCX/PDF 通过审核后才允许下载。

FastAPI 使用单进程异步任务执行，SQLite WAL 保存 ResearchRun、ResearchEvent、来源、证据、事实、假设、计算和问题。LangGraph AsyncSqliteSaver 以同步 durability 保存主图控制流；execution_units 保存按输入/执行实例指纹和校验和匹配的节点增量、研究子步骤、完整任务结果与结构化模型结果。业务提交到图提交之间的故障可重放台账，避免重复外部调用，不能仅按节点名恢复循环节点。独立 checkpoints 继续用于阶段成果与兼容性检查。

pause/cancel 先进入 pausing，停止新工作，让已发请求提交结果，60 秒后取消未完成请求并保存 interrupted；resume 原子更新并继续同一 run。前端同一 ID 续跑通过 connection epoch 重建 SSE/轮询。进程崩溃遗留 running 在启动时继续；主动暂停或正常关闭后保持 interrupted。数据库条件更新及 task 身份校验防止单 worker 下重复调度；多进程/多机仍需执行者租约和队列。本版输入指纹改变时拒绝混用断点，自动输入修复/局部失效尚未开放，见 RESUME_ACCEPTANCE.md。

## 主图

resolve_company → research_brief → research_plan → calculation_plan → dependencies → supervisor → data_gaps。缺口触发 replan → supervisor，达到上限后保留诊断，不填零。接着 financial_analysis → assumptions → calculate → validate → analyze_blocks → write_sections → core_conclusion → assemble → final_review → render → deliver。错误触发有限 revise → final_review，核心同比或严重问题超过上限后 blocked。

程序按 framework.py 的 1.1 模板生成必需问题与依赖。11 类模板实例化为 9+2N 块：C01、F01–F05、V01、R01、X01 各一个，I01/B01 各业务一个。模型仅细化问题/检索词；Plan 语义遗漏、业务错配、环与预算错误定向修复，失败后回退标准骨架。Supervisor 确定性选择依赖已完成的任务，受 concurrency 限制。C01 → 独立财务/行业 → 对应 B01 → F04 → V01 → R01 → X01；F04 可在模板枚举中先于业务块列出，实际执行按依赖排序。

每个任务通过 Researcher StateGraph：retrieve → extract → gap → 补查或 compress。来源全文持久化，相关段落/表格带表头、单位、脚注和原文偏移进入 ExtractionBatch；跨页文档合并并保留页标记。输出逐项绑定原文，无效结果隔离。已拆父批次直接重建拆分结构，已验证子批次复用。覆盖矩阵独立核查问题相关证据和核心事实，调用完成不会自动变成问题覆盖。研究轮次、补查、拆批、主图递归、LLM 重试、工具轮次及终审修订有外置上限。Mock 运行相同图但使用显著标记的合成资料，不调用外部模型。

## 数据边界

UnifiedDatasource 只组合 LocalDatasource 与 WebAdapter。Web 的搜索 Provider 可注入，读取网页/公开文件时限制大小、重定向次数及公网地址；每次转向检查地址。材料只作为 JSON 数据进入 Prompt，不执行文档指令。生产部署还应在出口代理层拒绝内网以进一步防止 DNS 重绑定。

LocalDatasource 解析七种文件及 JSON，每段保存 page/table/row/cells 定位和内容哈希。CSV/JSON/规范化 XLSX 采用精确字段检索；PDF、普通文档与任意表格由模型提取，但逐字 quote 与数值必须能定位原文。模型提取不是独立事实来源。EvidenceStore 维护 source→evidence→fact 链；合并/母公司/分部、实际/预测、期间、单位不会静默合并。

## 财务与写作

Formula Registry 集中定义公式参数、版本、输出单位；DependencyResolver 确定性展开依赖和去重，拒绝未知公式及循环。FinancialDataProcessor 精确选择同公司、期间、单位和口径的数据。ForecastEngine 构造分部与三表计算，保留输入及引用；独立 Reviewer 复算，校验引用数值、EPS/PE、分部、现金流和三表。

contexts.py 按块筛选实际值、计算、比较、摘录与必要上游结论；独立财务块仅接收历史计算，行业块不接收无关财务事实。ContextPackage 与实际 sent_context 记录筛选理由、版本和容量。analyze_blocks 按必需问题核查答案，遗漏只补缺项；分析产出支持、反证、限制。预测假设按情景/年度调用，再由既有三表引擎计算。

真实 Writer 按块/小节调用并通过 Reflection 局部修订；财务章由 F01–F05 五次写作组装。Writer 使用数值占位引用，Python 填数并保存 number_bindings。comparisons.py 生成年度与中期独立同比表和实际数值正文，来自相同 Decimal 事实/公式，不能被模型降低要求。分部、资产负债、资本配置等非核心披露不足明确限制。

X01 在正文后综合，必须回答现金增长、预测总量、估值依据、资源集中度四类一致性检查。五维终审先执行确定性检查，再用对应章节包做证据、批判与编辑审核。ReviewIssue 关联责任块、规则、受影响引用和报告快照。上游更新使所选输入版本和依赖链失效；未变化块分析/章节复用，核心观点重新综合。文字修复重审小节与跨块一致性；数据修复重算依赖并重新终审。只有当前快照的批准才可导出，事实更新或旧批准不能交付新内容。

SQLite records 新增 block、coverage、batch、context、sent_context、block_analysis、section、comparison、call、approval、quarantine 等记录，沿用原表结构。复用历史事实时重新检查来源、原文证据、公司与口径；显式 supersedes/version 处理重述，冲突保留诊断。旧报告默认为 1.0 可读；旧检查点不混入 1.1 运行，保留并要求新建研究。

## 渲染

DOCX 使用标准标题样式、目录结构、三表、引用和图表；不输出未验证目录页码。PDF 使用 ReportLab 多遍布局，目录页码由实际排版位置产生。HTML、DOCX、PDF 使用同一 ReportDocument。PDF 可选失败降级到 DOCX，并发出可见警告。示例 Word 版面核查与独立 PDF 渲染结果见 TESTING.md。

## v1.2 阶段成果

`work_products.py` 提供与正式交付独立的读取及评估导出。Store 的单次 SQLite WAL 读事务读取所属 run 的事件、检查点、报告、注册成果与旁路材料；允许字段投影和脱敏后以内容摘要形成固定 snapshot_id，保存到 `work_product_snapshots`。后续指定该快照的分页或下载不再读最新研究结果，不调用研究节点或模型。

`work_product_reviews` 保存每轮送审稿与对应状态/意见；`work_product_materials` 保存提取及计算的已提交部分成果。旁路写入尽力完成，异常不改变原研究控制流。既有 records/ReportDocument/检查点的结构与正式交付门槛保留；模型日志和章节记录仅追加评估所需的版本元数据。快照兼容旧记录，缺失历史不补造。

在线预览结构化渲染且分页；JSON 面向机器，Markdown 面向人工，ZIP 含 manifest、摘要/草稿、分类 JSON 和诊断/送审历史。清单记录缺失、不可获取项、质量/版本状态、记录数及文件校验和。当前和失效章节分区，正式批准仅对应有效成稿快照。超限/打包故障可重试，不回写 run、报告或批准；不依赖 DOCX/PDF。
