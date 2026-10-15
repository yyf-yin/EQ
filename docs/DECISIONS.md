# 工程决策

1. 工作区为空，根据用户完整要求创建 PRD；代码位于 outputs/company-deep-research。无其他已有 Skills 或业务代码需要复用。
2. 全新实现，参考 Open Deep Research 的 brief/supervisor/研究循环/并行/压缩/写作设计，没有复制源代码。参考仓库 MIT 许可，见 https://github.com/langchain-ai/open_deep_research 及其 LICENSE。FinAgent 仓库身份未确定，不假设其内部 API；金融模块独立可替换。
3. PyFin 采用发行身份 Finance-Python、import PyFin 的可选能力探测。官方 PyPI 可核实版本 0.9.10，2023-01-01；Windows 现成 wheel 为 CPython 3.9，当前测试 Python 3.12，不强制安装需编译扩展的旧库。另一个 pyfin 1.0.0a1 不自动安装。公司财务公式完全独立。来源：https://pypi.org/project/Finance-Python/ 、https://github.com/alpha-miner/Finance-Python 、https://pypi.org/project/pyfin/ 。
4. SQLite 单进程执行适合本地 MVP，无 Redis/Celery 或额外数据源。采用 LangGraph 原生持久检查点并补充节点快照，避免恢复时重复已提交节点。
5. 无真实凭证默认 mock。输入任意名称都显示模拟标识并映射虚构 DEMO，不把测试数据挂到真实公司身份下。合成材料单独位于 examples/fixtures。
6. 搜索注入采用明确的通用 JSON HTTP 合同，不预设供应商和凭证。不同供应商若请求协议不同，需要替换 SearchProvider 适配，不允许把金融 API 当作搜索来源。
7. 模型统一使用 Chat Completions 或原生 Messages。Anthropic 结构化输出通过强制 schema 工具返回，不依赖某个厂商版本专有 JSON 能力。OpenAI 兼容服务可选 native/tool/json。
8. Decimal 财务计算优先可靠性；缺失、冲突、零分母、错误单位和期间均不可用。原值与归一化值关系由来源和证据保留，未知指标不随意映射。
9. 简化三表模型使用合并净利润与统一股本，不自动处理少数股东、递延税、金融企业和复杂租赁。没有净利润与股本口径一致的来源时，EPS/估值需受限或阻断。税率只对正税前利润计税；亏损抵扣不自动推定。
10. DOCX 目录提供最终结构而不猜页码；PDF 支持实际排版页码。这样无需在后端安装 Office 也能下载完整报告。Word/LibreOffice 可进一步更新 DOCX 目录样式；本版并未伪称已生成 DOCX 的正式目录页码。
11. 升级 Vite、Vitest 和 Tailwind 后 npm audit 为零漏洞；配置示例无真实厂商、模型及密钥。
12. 实际测试环境 Windows 权限限制导致 Node realpath 与 SQLite 测试需要在沙箱外执行；pytest 临时目录明确放在工作区。该限制与应用代码无关，测试结果均来自实际执行。
