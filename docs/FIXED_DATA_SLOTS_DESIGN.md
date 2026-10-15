# 固定财务与证券填槽表设计 v1

状态：固定字段已接入真实模式取数流程。实际范围、使用方式与验证见 [固定表实施验收](FIXED_DATA_SLOTS_ACCEPTANCE.md)。配套固定字段定义见 [fixed_data_slots.v1.json](fixed_data_slots.v1.json)。本稿是本轮财务、证券数据收集的设计依据；与旧 SOURCE_AUTHORITY_DESIGN.md 中自动覆盖、财务接口等设想冲突时，本稿采用用户最新要求。旧运行记录保留；旧断点不混用新取数规则。

## 1. 目标与边界

开发者人工预设字段表，程序按公司和期间生成槽，取数模块填槽，分析模块只读。plan 不设计、增删或重命名财务证券字段，不更改必需性、来源约束或完成状态。业务和行业资料包仍由研究计划组织，不混入这张定量表。

适用当前项目的 A 股非金融上市公司。每家公司采用相同字段结构；字段是否披露、是否适用通过状态表达，不创建公司专属 schema。业务、债券和多产品经营明细只能增加固定结构的记录。财务证券表中的字段齐全，不代表要求每个槽都有数字。

固定表在用户界面可展示为七个区域；内部使用固定字段字典与长表记录，不能把业务名称变成数据库列。只有开发者发布新的模板版本可以改变字段。

## 2. 固定展开与期间

| 区域 | 记录数量 | 取数入口 |
|---|---|---|
| 证券与股本 | 每个指定证券一个本次研究快照；默认研究主证券 | local-datasource，结构化字段直接导入 |
| 利润表、资产负债表、现金流、补充披露 | 每家公司每个历史期间一组 | 本任务指定年报 |
| 单业务 | 每个已披露业务每个期间一组 | 同一批年报中的业务表及附注 |
| 债券 | 每只债券每个期间一组；明确无债券时不生成空债券 | 同一批年报的债券表及附注 |

默认展示最近三个已披露完整财年，输入范围固定扩展一个前序年，以支持三年同比和平均余额。例如展示 2023A、2024A、2025A，输入范围为 2022A 至 2025A。是否已披露从任务指定报告清单判断，不由模型凭日期猜测。

年流量覆盖完整财年，资产负债表记录财年末日期；期初值可以由所选报告的期初列填入相应日期槽。一个报告中的本期、上期及期初列允许一次提取填多个槽。证券快照独立使用实际交易日，不能伪装成年报年度数据。

v1 不实例化季度、半年报及预测年度实际数据槽。需要扩展时由开发者预设同字段的期间模式；plan 不自动引入。这是本次“财务只用年报”的覆盖范围选择。

## 3. 必需性与缺失后果

必需性由模板静态规定，缺失后的影响由程序固定依赖规则判断；不能因为模型选择了某个公式就新增取数任务。

| 标记 | 意义 | 缺失后果 |
|---|---|---|
| I | 主体识别必需 | 无法确认研究主体，停止该主体的正式研究 |
| C | 核心历史比较必需 | 保留其余成果，但完整核心财务正式报告不能通过 |
| M | 三表模型依赖 | 关闭依赖该值的预测，显示具体缺口 |
| V | 估值依赖 | 关闭相关估值，不妨碍业务资料分析 |
| S | 业务结构或分业务预测依赖 | 保留可分析资料，关闭缺失业务的依赖计算 |
| D | 债务加总组件 | 明确无该项才能贡献零；未知则债务总额不完整 |
| B | 有债券时的识别字段 | 限制债券分析及依赖功能 |
| O | 可选披露 | 未披露即结束，不产生人工核验 |

M/V/S/D/B 缺失不自动询问人工；只有用户要求必须完成的核心功能受阻且原始材料确实无法确定时，才形成一次合并的缺失或提取待办。未披露的可选字段永不转人工。当前程序的旧门槛不因本设计文档自动改变，接入时需同步更新。

## 4. 固定原始字段表

单位：金额计算层统一人民币百万元，股数统一百万股，百分数统一 ratio（5% 为 0.05）。原值、原单位永久保留，换算结果单独保存。原币种非人民币时不自行换汇；原文提取正确仍可锁定原值，但人民币换算值为空并注明原因，停止依赖人民币金额的计算。固定字段覆盖本项目研究输入，不声称穷尽每家公司的全部附注项目。

annual_flow = 完整年度流量；year_end_stock = 财年末存量；snapshot = 证券数据时点；period_opening_stock = 期初存量；disclosed_period = 明确记录披露周期。金额符号遵循原表，不由模型修改。

每个字段的完整 ID 为“区域.字段代码”，因此公司收入 income.revenue 和业务收入 segment.revenue 不会混淆。下表为字段字典，实际填槽表按期间展开数值列，并在旁列显示状态与来源位置。

### 4.1 证券与股本

| 字段代码 | 固定名称 | 类型 / 计算单位 | 期间 | 标记 | 填槽说明 |
|---|---|---|---|---|---|
| company_name | 公司全称 | text / — | snapshot | I | 由本地证券主档确认 |
| ticker | 证券代码 | text / — | snapshot | I | 保留前导零 |
| security_name | 证券简称 | text / — | snapshot | I | 保留本次快照 |
| exchange | 交易所 | text / — | snapshot | I | 使用本地标准枚举 |
| listing_date | 上市日期 | date / — | snapshot | O | YYYY-MM-DD |
| security_type | 证券类别 | text / — | snapshot | I | 股票或其他类别；主估值证券明确指定 |
| quote_currency | 报价币种 | text / — | snapshot | V | 与价格绑定 |
| trading_status | 交易状态 | text / — | snapshot | V | 正常、停牌等按本地数据记录 |
| price | 未复权收盘价 | decimal / CNY/share | snapshot | V | 只取不晚于研究截止日的确定交易日；不以复权价估值 |
| quote_date | 价格交易日 | date / — | snapshot | V | 不得把取数日期当交易日 |
| shares | 公司总股本 | decimal / million_shares | snapshot | V | 保留股本生效日；不是加权平均股数 |
| shares_effective_date | 股本生效日 | date / — | snapshot | V | 与价格时点兼容，发生股本变动时不得混用 |
| listed_class_shares | 本证券类别股数 | decimal / million_shares | snapshot | O | 多类别股份估值使用，不默认等于公司总股本 |
| float_shares | 本证券流通股数 | decimal / million_shares | snapshot | O | 不得用于替代总股本 |
| multi_class_listing | 是否存在多类别或多市场股份 | boolean / — | snapshot | V | unknown 是缺失状态，不冒充 false |

### 4.2 利润表与核心盈利披露

| 字段代码 | 固定名称 | 类型 / 计算单位 | 期间 | 标记 | 填槽说明 |
|---|---|---|---|---|---|
| revenue | 营业收入 | decimal / CNY_million | annual_flow | C | 优先对应合并利润表；不等于营业总收入 |
| cost | 营业成本 | decimal / CNY_million | annual_flow | C | 不以营业总成本替代 |
| taxes_surcharges | 税金及附加 | decimal / CNY_million | annual_flow | O | 保留原表正负号 |
| selling_expense | 销售费用 | decimal / CNY_million | annual_flow | O | 不与管理费用合并提取 |
| administrative_expense | 管理费用 | decimal / CNY_million | annual_flow | O | 不自行扣除研发费用 |
| research_expense | 研发费用 | decimal / CNY_million | annual_flow | O | 指损益费用，不是研发投入总额 |
| finance_expense | 财务费用 | decimal / CNY_million | annual_flow | O | 不是利息支出；允许负数 |
| interest_expense | 利息费用 | decimal / CNY_million | annual_flow | O | 取附注明确披露值，不从财务费用反推 |
| interest_income | 利息收入 | decimal / CNY_million | annual_flow | O | 与利息费用分开 |
| other_income | 其他收益 | decimal / CNY_million | annual_flow | O | 不与营业外收入混用 |
| investment_income | 投资收益 | decimal / CNY_million | annual_flow | O | 保留原表符号 |
| fair_value_change | 公允价值变动收益 | decimal / CNY_million | annual_flow | O | 损失保留负号 |
| credit_impairment | 信用减值损失原表值 | decimal / CNY_million | annual_flow | O | 按原表符号记录，不统一改成正支出 |
| asset_impairment | 资产减值损失原表值 | decimal / CNY_million | annual_flow | O | 按原表符号记录 |
| disposal_income | 资产处置收益 | decimal / CNY_million | annual_flow | O | 与投资收益分开 |
| operating_profit | 营业利润 | decimal / CNY_million | annual_flow | O | 不直接映射 EBIT |
| nonoperating_income | 营业外收入 | decimal / CNY_million | annual_flow | O | 只取原表 |
| nonoperating_expense | 营业外支出 | decimal / CNY_million | annual_flow | O | 只取原表 |
| pretax_profit | 利润总额 | decimal / CNY_million | annual_flow | O | 税前利润 |
| income_tax_expense | 所得税费用 | decimal / CNY_million | annual_flow | O | 允许负数；不直接作为预测税率 |
| net_income | 合并净利润 | decimal / CNY_million | annual_flow | M | 不得替代归母净利润 |
| parent_net_income | 归母净利润 | decimal / CNY_million | annual_flow | C | 归属于母公司或上市公司股东 |
| minority_net_income | 少数股东损益 | decimal / CNY_million | annual_flow | O | 单列，不能隐含在归母中 |
| adjusted_parent_net_income | 扣非归母净利润 | decimal / CNY_million | annual_flow | C | 取年报主要财务指标，不由净利润推算 |
| basic_eps_reported | 年报披露基本每股收益 | decimal / CNY/share | annual_flow | O | 保留年报口径；不得用期末总股本倒算替代 |
| diluted_eps_reported | 年报披露稀释每股收益 | decimal / CNY/share | annual_flow | O | 与基本 EPS 分开 |

### 4.3 合并资产负债表及债务拆分

| 字段代码 | 固定名称 | 类型 / 计算单位 | 期间 | 标记 | 填槽说明 |
|---|---|---|---|---|---|
| cash | 货币资金 | decimal / CNY_million | year_end_stock | M | 不等于现金及现金等价物；限制资金在附注单列 |
| trading_financial_assets | 交易性金融资产 | decimal / CNY_million | year_end_stock | O | 不自动并入现金 |
| notes_receivable | 应收票据 | decimal / CNY_million | year_end_stock | O | 不与应收账款混合 |
| receivables | 应收账款 | decimal / CNY_million | year_end_stock | M | 取账面值；应收账款与票据合列时先查附注拆分 |
| receivables_financing | 应收款项融资 | decimal / CNY_million | year_end_stock | O | 单列 |
| prepayments | 预付款项 | decimal / CNY_million | year_end_stock | O | 单列 |
| other_receivables | 其他应收款 | decimal / CNY_million | year_end_stock | O | 不替代应收账款 |
| inventory | 存货 | decimal / CNY_million | year_end_stock | M | 净账面值 |
| contract_assets | 合同资产 | decimal / CNY_million | year_end_stock | O | 不默认映射应收账款 |
| current_assets | 流动资产合计 | decimal / CNY_million | year_end_stock | O | 用于流动性计算 |
| long_term_equity_investments | 长期股权投资 | decimal / CNY_million | year_end_stock | O | 用于资本结构分析 |
| ppe | 固定资产 | decimal / CNY_million | year_end_stock | M | 净账面值；不包含在建工程 |
| construction_in_progress | 在建工程 | decimal / CNY_million | year_end_stock | O | 单列 |
| right_of_use_assets | 使用权资产 | decimal / CNY_million | year_end_stock | O | 不默认并入固定资产 |
| intangible_assets | 无形资产 | decimal / CNY_million | year_end_stock | O | 单列 |
| goodwill | 商誉 | decimal / CNY_million | year_end_stock | O | 单列 |
| noncurrent_assets | 非流动资产合计 | decimal / CNY_million | year_end_stock | O | 保留报表合计 |
| assets | 资产总计 | decimal / CNY_million | year_end_stock | M | 用于期初模型及结构核对 |
| short_term_borrowings | 短期借款 | decimal / CNY_million | year_end_stock | D | 债务组件 |
| notes_payable | 应付票据 | decimal / CNY_million | year_end_stock | O | 不默认全部认定为有息债务 |
| payables | 应付账款 | decimal / CNY_million | year_end_stock | M | 应付票据与账款合列时查附注拆分 |
| contract_liabilities | 合同负债 | decimal / CNY_million | year_end_stock | O | 不默认映射应付账款 |
| employee_payables | 应付职工薪酬 | decimal / CNY_million | year_end_stock | O | 单列 |
| tax_payables | 应交税费 | decimal / CNY_million | year_end_stock | O | 与所得税费用分开 |
| other_payables | 其他应付款 | decimal / CNY_million | year_end_stock | O | 不自动计入有息债务 |
| current_debt_borrowings | 一年内到期的长期借款 | decimal / CNY_million | year_end_stock | D | 查一年内到期非流动负债附注，避免重复计入长期借款 |
| current_debt_bonds | 一年内到期的应付债券 | decimal / CNY_million | year_end_stock | D | 与应付债券非流动部分互斥 |
| current_debt_leases | 一年内到期的租赁负债 | decimal / CNY_million | year_end_stock | D | 债务政策选择是否纳入，但不重复计入租赁负债 |
| other_current_interest_debt | 其他明确有息流动债务 | decimal / CNY_million | year_end_stock | D | 须有附注明确列示；不由其他流动负债总额替代 |
| current_liabilities | 流动负债合计 | decimal / CNY_million | year_end_stock | O | 流动性计算 |
| long_term_borrowings | 长期借款 | decimal / CNY_million | year_end_stock | D | 非流动账面金额 |
| bonds_payable | 应付债券 | decimal / CNY_million | year_end_stock | D | 非流动账面金额；明细表不再加到这里 |
| lease_liabilities | 租赁负债 | decimal / CNY_million | year_end_stock | D | 非流动账面金额 |
| other_noncurrent_interest_debt | 其他明确有息非流动债务 | decimal / CNY_million | year_end_stock | D | 不与借款、债券、租赁重复 |
| noncurrent_liabilities | 非流动负债合计 | decimal / CNY_million | year_end_stock | O | 保留报表合计 |
| liabilities | 负债合计 | decimal / CNY_million | year_end_stock | M | 用于期初模型及结构核对 |
| parent_equity | 归属于母公司股东权益 | decimal / CNY_million | year_end_stock | O | 归母 ROE、PB 使用；不能替代权益合计 |
| minority_equity | 少数股东权益 | decimal / CNY_million | year_end_stock | O | 单列 |
| equity | 所有者权益合计 | decimal / CNY_million | year_end_stock | M | 对应合并净利润与合并模型 |

### 4.4 合并现金流量表

| 字段代码 | 固定名称 | 类型 / 计算单位 | 期间 | 标记 | 填槽说明 |
|---|---|---|---|---|---|
| sales_cash_received | 销售商品、提供劳务收到的现金 | decimal / CNY_million | annual_flow | O | 用于收入现金匹配 |
| operating_cash_inflow | 经营活动现金流入小计 | decimal / CNY_million | annual_flow | O | 报表披露值 |
| purchase_cash_paid | 购买商品、接受劳务支付的现金 | decimal / CNY_million | annual_flow | O | 现金支出行保留正金额 |
| employee_cash_paid | 支付给职工以及为职工支付的现金 | decimal / CNY_million | annual_flow | O | 报表披露值 |
| tax_cash_paid | 支付的各项税费 | decimal / CNY_million | annual_flow | O | 不替代所得税费用 |
| operating_cash_outflow | 经营活动现金流出小计 | decimal / CNY_million | annual_flow | O | 报表披露值 |
| operating_cashflow | 经营活动现金流量净额 | decimal / CNY_million | annual_flow | C | 净流出保留负数 |
| purchase_long_lived_assets_cash | 购建固定资产、无形资产和其他长期资产支付的现金 | decimal / CNY_million | annual_flow | O | 可作为明确命名的现金资本开支代理值，不等于全部资本开支 |
| investment_cash_paid | 投资支付的现金 | decimal / CNY_million | annual_flow | O | 不并入现金资本开支代理值 |
| acquisition_cash_paid | 取得子公司及其他营业单位支付的现金净额 | decimal / CNY_million | annual_flow | O | 并购支出单列 |
| investing_cashflow | 投资活动现金流量净额 | decimal / CNY_million | annual_flow | O | 不以资本开支负值代替实际披露 |
| borrowing_cash_received | 取得借款收到的现金 | decimal / CNY_million | annual_flow | O | 与债券融资分开 |
| bond_issue_cash_received | 发行债券收到的现金 | decimal / CNY_million | annual_flow | O | 仅明确单列时填入 |
| debt_repayment_cash | 偿还债务支付的现金 | decimal / CNY_million | annual_flow | O | 不由债务余额变化推算 |
| dividend_interest_cash_paid | 分配股利、利润或偿付利息支付的现金 | decimal / CNY_million | annual_flow | O | 合列值不能直接当现金分红 |
| financing_cashflow | 筹资活动现金流量净额 | decimal / CNY_million | annual_flow | O | 原表净额 |
| fx_cash_effect | 汇率变动对现金及现金等价物的影响 | decimal / CNY_million | annual_flow | O | 用于现金衔接；不得任意归零 |
| cash_equivalent_change | 现金及现金等价物净增加额 | decimal / CNY_million | annual_flow | O | 原表披露值 |
| opening_cash_equivalents | 期初现金及现金等价物余额 | decimal / CNY_million | period_opening_stock | O | 用于现金衔接 |
| closing_cash_equivalents | 期末现金及现金等价物余额 | decimal / CNY_million | year_end_stock | O | 不覆盖货币资金 |

### 4.5 年报补充披露

| 字段代码 | 固定名称 | 类型 / 计算单位 | 期间 | 标记 | 填槽说明 |
|---|---|---|---|---|---|
| restricted_cash | 受限货币资金 | decimal / CNY_million | year_end_stock | O | 附注披露金额；没有披露不能推定为零 |
| depreciation_ppe | 固定资产折旧 | decimal / CNY_million | annual_flow | O | 现金流补充资料对应项目 |
| depreciation_rou | 使用权资产折旧 | decimal / CNY_million | annual_flow | O | 与固定资产折旧分开 |
| amortization_intangibles | 无形资产摊销 | decimal / CNY_million | annual_flow | O | 不重复加总已披露综合折旧摊销值 |
| amortization_long_term | 长期待摊费用摊销 | decimal / CNY_million | annual_flow | O | 单列 |
| cash_dividends_parent_paid | 实际支付的归母股东现金分红 | decimal / CNY_million | annual_flow | O | 明确支付期间，不能拿拟分红方案替代 |
| cash_interest_paid | 实际支付利息 | decimal / CNY_million | annual_flow | O | 明确拆分时填入，不使用股利利息合列值 |
| research_spending_total | 研发投入总额 | decimal / CNY_million | annual_flow | O | 与损益研发费用不同 |
| research_capitalized | 资本化研发投入 | decimal / CNY_million | annual_flow | O | 不从投入总额减费用反推原始事实 |
| employees | 员工人数 | integer / person | year_end_stock | O | 年末人数；平均人数不得填此槽 |

### 4.6 单业务财务与经营数据

| 字段代码 | 固定名称 | 类型 / 计算单位 | 期间 | 标记 | 填槽说明 |
|---|---|---|---|---|---|
| segment_name | 业务原始名称 | text / — | annual_flow | S | 保留公司披露名称，不由 plan 发明 |
| classification_basis | 划分维度 | text / — | annual_flow | S | 业务、产品、行业；地域不混入主业务维度 |
| revenue | 业务收入 | decimal / CNY_million | annual_flow | S | 明确外部收入或含内部交易；不得重复汇总不同维度 |
| cost | 业务成本 | decimal / CNY_million | annual_flow | O | 未披露即终态，不以集团毛利率反推 |
| intersegment_revenue | 内部交易收入 | decimal / CNY_million | annual_flow | O | 只有明确披露才填 |
| segment_profit_reported | 披露的分部利润 | decimal / CNY_million | annual_flow | O | 保留利润口径；不冒充业务净利润 |
| volume | 销量 | decimal / source_native | annual_flow | O | 与产品和单位绑定；多产品用固定经营明细子表保存 |
| production | 产量 | decimal / source_native | annual_flow | O | 不以销量替代 |
| capacity | 产能 | decimal / source_native | year_end_stock | O | 记录年末年化产能或原文周期；不能默认全年可用产能 |
| users | 用户或客户数量 | decimal / source_native | disclosed_period | O | 记录期末、平均、付费、活跃等定义，禁止混用 |

### 4.7 逐只债券明细

| 字段代码 | 固定名称 | 类型 / 计算单位 | 期间 | 标记 | 填槽说明 |
|---|---|---|---|---|---|
| bond_name | 债券名称 | text / — | year_end_stock | B | 仅对存在的债券生成记录 |
| bond_code | 债券代码 | text / — | year_end_stock | O | 无公开代码时使用稳定的内部 bond_id |
| bond_type | 债券类型 | text / — | year_end_stock | B | 公司债、企业债、可转债等按披露记录 |
| issuer_name | 发行主体 | text / — | year_end_stock | B | 公司或子公司，记录是否进入合并范围 |
| issue_date | 发行日期 | date / — | year_end_stock | O | 按原文 |
| maturity_date | 到期日期 | date / — | year_end_stock | O | 永续债采用到期类型，不能虚构日期 |
| maturity_type | 到期类型 | text / — | year_end_stock | B | 固定到期、永续等 |
| outstanding_principal | 未偿本金 | decimal / CNY_million | year_end_stock | B | 不等于资产负债表账面余额 |
| carrying_amount | 账面余额 | decimal / CNY_million | year_end_stock | O | 与应付债券及一年内到期部分关联，不再次加入集团债务 |
| coupon_rate | 票面利率 | decimal / ratio | year_end_stock | O | 单一确定值才填；阶梯或浮动条款保存原文 |
| interest_terms | 利率及偿付条款 | text / — | year_end_stock | O | 保留阶梯利率、浮动基准及赎回回售条款 |
| accounting_class | 会计列报类别 | text / — | year_end_stock | B | 负债或权益；永续债不能仅凭名称计入债务 |
| conversion_terms | 转股条款 | text / — | year_end_stock | O | 仅可转债适用；无则不适用 |

### 4.8 业务与债券记录的特别规则

业务使用年报的主业务划分，产品、行业、地域三套表不能混合相加。保存 classification_basis 和范围定义；公司收入与分部收入不相等时保留披露差额与说明，不改任何原值、不创建虚构“其他业务”填平差额。年度业务划分变化保留各期原名和映射，跨期不可比标为不可比；无法对应的业务不强行计算同比。

若业务只有总收入而没有成本，成本为 not_disclosed，毛利率不可计算，不由集团毛利率或模型猜测补齐。业务含内部交易且没有外部收入拆分时，不能直接进入外部收入占比或分部收入合计预测。

销量、产量、产能、用户数保留原始数量单位和定义。若一项业务有多种产品，使用固定结构的 segment_operating_details 子表：segment_id、detail_id、product_name、metric_code、value、unit、quantity_kind、期间、scope、source_id、locator、state。metric_code 仅允许 volume/production/capacity/users。多产品时父级聚合槽若无法形成同单位、同定义合计，标 not_applicable 并说明“使用产品明细”，不重复提取。不相容单位不得求和，不能统一把吨、件、台、订单改成百万件。单价和利用率由兼容输入计算，不额外 web 取数。

债券 presence 记录为 present/absent/unknown，只有原报告明确说明或完整相关披露可确认无债券时才置 absent；unknown 不是无债券。历史年度有债券、最新年度无债券，仍保留历史记录。债券余额取年报，无债券行情 web 入口。债券明细用于解释集团债务，不与资产负债表债券余额重复相加；子公司与母公司范围分开，负债型与权益型工具分开。没有公开代码时，程序以发行主体、名称、发行日期生成稳定 bond_id。

## 5. 每个槽的共同列

| 列 | 含义 |
|---|---|
| slot_id | 固定身份哈希，跨重试稳定；不含随机任务 ID |
| run_id、template_version | 任务隔离与模板版本 |
| company_id、field_id | 公司身份与固定字段 ID |
| period_start、period_end、period_kind | 完整日期及流量/存量/快照类型 |
| scope、segment_id、security_id、bond_id、detail_id | 合并/母公司/业务/证券/债券/产品明细身份；无则显式 null |
| currency、accounting_basis | 原币种和报告/重述等固定采用口径 |
| report_binding_id | 任务开始时选定的报告、列及版本绑定；证券绑定本地快照 |
| raw_value、raw_unit、raw_label | 来源原值、单位及原始名称 |
| normalized_value、normalized_unit | Decimal 确定换算结果，与原值分列 |
| state、reason | 槽状态及未填原因；空值不等于零 |
| source_id、content_hash、locator、evidence_id | 文件/本地记录身份、内容哈希和页/表/行/列位置 |
| precision | 来源披露精度，用于判断计算显示与勾稽误差 |
| source_as_of、effective_date | 数据截止日及股本等生效日 |
| extraction_receipt_id、attempt_count | 已完成提取和失败修复记录 |
| locked_at | 首次入库检查通过后的锁定时间 |

槽身份取 JSON 中 identity_fields 的确定序列，null 统一编码，使用 SHA-256；raw_value、状态、问题措辞、随机 task_id 不参与身份。报告绑定本身冻结，不能通过新增绑定规避已完成槽去重。母公司数据不能填合并槽；若后续确有母公司分析需求，必须由开发者新增固定实例化规则。

十进制值在 JSON 中使用精确字符串，计算时使用 Decimal；不使用二进制浮点。财务原始数值必须为单个确定值，区间、估计和占位符保存为原文证据，不能取中点或选端点填入数值槽。

## 6. 状态和锁定规则

| 状态 | 含义 | 自动后续行为 |
|---|---|---|
| pending | 尚未处理 | 可以领取一次填槽任务 |
| filling | 已领取，正在处理 | 其他工作只能等待或复用该任务，不重复领取 |
| locked | 原文定位、期间、口径、单位及数值检查通过 | 只读复用；禁止补查、再次提取、覆盖、转人工 |
| not_disclosed | 对已读取的完整相关表/附注确认未披露 | 本轮取数结束；不得换关键词反复搜索 |
| not_applicable | 明确不适用，如没有债券或字段不适用 | 本轮取数结束；不是数值零 |
| source_missing | 本任务指定资料不存在或缺页，无法判断披露情况 | 停止自动取数；核心依赖汇总提示缺哪份资料 |
| extraction_failed | 材料存在，但 OCR/表格对应/单位提取失败 | 仅修复失败窗口；默认首次失败后最多一次自动修复 |

not_disclosed 必须有检查范围与位置记录，不能仅因搜索不到关键词就判定。source_missing 与 extraction_failed 不得改写为 not_disclosed。

有据的原始数值 0 可以 locked；破折号、空白和未出现的项目不得自动填零。not_applicable 的债务组件仅在明确无对应负债时，计算层可按零贡献处理，并引用该“不存在”依据；原始槽仍然没有虚构的数值零。不能仅因某公司无债券就认定所有债务都不存在。

入库检查验证提取是否对应原报告，不重新调查营收是否真实。多年对比表按列定位，单位可以引用表头，不要求年度、单位和数值挤在同一短摘录内。年报通过此一次检查后直接作为确定输入；不得因第三方候选不同或其他来源不足而转人工。

锁定后任何新材料、重新分析、研报或网页均不能改变本次研究输入。人工也不能在同一锁定槽直接修改；如明确要求更改，保留旧值，建立用户明确授权的新研究数据版本或新任务。计算发现勾稽异常可以关闭受影响功能并给出诊断，不自动解锁、修改原值或泛化补查。

## 7. 报告与快照绑定

取数之前生成冻结的 source_manifest：公司、研究截止日、显示年度、输入年度、每个年度和口径采用的报告及列、报告版本/内容哈希、业务划分、债券存在状态、本地证券快照、主证券、估值股份口径、债务政策版本。绑定由程序按预设规则完成；明确歧义不能留给后续逐字段任意选数。

同一历史年度可以同时出现在多个年报中。默认在取数前从任务提供资料中选定对应数列：优先采用有明确重述说明的已选报告比较列，否则对应年度年报本期列；完整表头不足时不把比较列默认为更正。每个同比比较两端必须使用兼容口径，不同报表版本的重述关系须在绑定阶段说明。不能先锁定旧列、后看到新列就自动换数。

证券只从 local-datasource 取数；财务和债券只从任务指定的年报及已选正式更正披露取数，允许本地/上传方式提供这些报告。研报、一般上传文本和网页只能补充业务行业证据，不能以“上传资料优先”为由覆盖本表的年报数值。缺本地证券数据或年报则保留缺口，不开放通用 web 或其它财务 API 自动补数。

同一报告中若发现多个真正同身份不同值，先在锁定前确定原表与附注定位是否一致；仍无法确定且影响核心依赖，才合并为一次原始材料歧义待办。无需先创建反复交叉验证任务。

## 8. 固定派生结果表

派生结果不属于原始取数槽，使用独立计算表保存公式版本和输入引用。模型不能自行把派生结果写成新的年报事实。

| 代码 | 结果 | 固定依据 | 单位 | 限制 |
|---|---|---|---|---|
| gross_profit | 毛利 | revenue - cost | CNY_million | 公司和业务分别计算 |
| gross_margin | 毛利率 | (revenue - cost) / revenue | ratio | 收入为零则不适用 |
| opex | 销售管理研发费用合计 | selling_expense + administrative_expense + research_expense | CNY_million | 明确不含财务费用及税金；不把缺失项当零 |
| capex_cash_proxy | 现金资本开支代理值 | purchase_long_lived_assets_cash | CNY_million | 仅是该现金流项目的代理口径，兼容适配不能丢失标签 |
| fcf_cash_proxy | 现金自由现金流代理值 | operating_cashflow - capex_cash_proxy | CNY_million | 不是全部资本开支口径的自由现金流 |
| debt | 固定政策下有息债务 | 互斥借款、债券、租赁及其他明确有息债务组件求和 | CNY_million | 政策明确含租赁；未知组件阻止完整加总；债券明细不重复相加 |
| unrestricted_cash | 非受限货币资金 | cash - restricted_cash | CNY_million | 受限金额未知则不可用；不直接等同 EV 的现金扣减范围 |
| depreciation | 折旧摊销组件合计 | depreciation_ppe + depreciation_rou + amortization_intangibles + amortization_long_term | CNY_million | 缺失组件不得补零；避免重复合计；模型简化适用性单独判断 |
| other_assets | 简化模型其余资产 | assets - cash - receivables - inventory - ppe | CNY_million | 只是固定归类结果，不是为平衡三表而修改的插入项 |
| other_liabilities | 简化模型其余负债 | liabilities - payables - debt | CNY_million | 须采用与 debt 一致的互斥归类 |
| average_balances | 资产权益应收存货平均余额 | (同口径期初余额 + 期末余额) / 2 | CNY_million | 须有真实期初值；不能用期末代替平均 |
| effective_tax_rate | 历史有效税率 | income_tax_expense / pretax_profit | ratio | 非正税前利润默认不适用；不自动成为预测税率 |
| yoy_and_share | 同比、增减额及业务占比 | 固定比较规则及同口径收入占比 | ratio / CNY_million | 负基数与零基数沿用项目比较规则 |
| market_cap | 市值 | 同日兼容的未复权价 × 对应股份数量 | CNY_million | 多类别股份必须分价格计算或标为不可用；不直接乘所有股份 |
| pe_pb | PE / PB | 兼容市值 / 归母利润或归母权益 | times | 亏损 PE、非正权益 PB 不适用；全公司口径与证券类别口径必须匹配 |
| roe_roic | ROE / ROIC | 同归属利润与平均权益；固定政策 NOPAT / 平均投入资本 | ratio | ROIC v1 无完整固定 NOPAT/投入资本定义，禁用自由取数补齐 |


年报另有直接披露的 ROE、毛利率等，可随原表保存为证据，v1 不为它们再开独立取数任务；分析显示固定程序计算值并注明算法。基本/稀释 EPS 已单列年报事实，不能与期末股本计算 EPS 混同。行业规模、市场份额、预测参数不是本财务表字段，依然属于业务行业证据或预测假设表。

EBIT/EBITDA、ROIC 的完整口径需要开发者另外锁定计算政策，v1 不开放模型通过任意检索获取它们来补齐公式输入。固定字段足以支持的计算才启用，不足则明确受限。股数多类别、利润归属、折旧范围及受限现金等未被现有简化模型处理的情形，应关闭不适用功能，而不是改原值来适配模型。

## 9. 一次提取、多槽分发与去重

1. 先从本地证券主档确认公司身份，读取冻结的报告清单，程序生成固定槽。
2. 结构化本地证券字段直接映射导入，不交给 LLM 重新解释同一数字。
3. 以报告内容和表格窗口为提取单元，一次读取年报可以填利润、资产负债、现金流、补充、业务及债券多个区域；不能按每个字段或分析章节重复读同一份报告。
4. 每次调度只领取一个确定的处理单元，领取操作原子化；一份资料产出的多槽结果可以一次提交。槽的逻辑完成单位与模型批次不是同一概念。
5. 文档按内容哈希及固定解析版本复用；提取按内容哈希、页/表/窗口位置和固定提取合同版本复用，合同身份不含随机 task_id、分析问题或 plan 文本。首次就提取该窗口支持的固定字段集合，不事后为每个新任务再读窗口。
6. 提取结果在同一 run_id 内持久化。已完成窗口、locked 槽和已明确缺失的终态在暂停/恢复/重规划时均复用；不跨任务偷偷导入其他公司研究成果。
7. 分析依赖用 slot_id/计算结果 ID 引用，禁止把原始年报全文重复送入每个分析块。必要的定性摘录来自共用证据库。
8. extraction_failed 只修复失败窗口；成功字段立即锁定，修复结果只填未完成槽。网络/模型请求结果未知的技术重试单独记录，不能承诺外部接口绝对零重复计费。

## 10. 空表展示与填槽例子

以下仅演示结构，假定研究显示 2023A—2025A；金额为人民币百万元，实际表另展示来源位置。示例非真实公司数据。

| 区域 | 字段 | 2022A（辅助） | 2023A | 2024A | 2025A |
|---|---|---|---|---|---|
| 利润 | 营业收入 | 待填 | 待填 | 待填 | 待填 |
| 利润 | 营业成本 | 待填 | 待填 | 待填 | 待填 |
| 利润 | 归母净利润 | 待填 | 待填 | 待填 | 待填 |
| 利润 | 扣非归母净利润 | 待填 | 待填 | 待填 | 待填 |
| 现金流 | 经营现金流净额 | 待填 | 待填 | 待填 | 待填 |
| 业务 A | 收入 | 待填 | 待填 | 待填 | 待填 |
| 业务 A | 成本 | 待填 | 待填 | 待填 | 待填 |
| 业务 B | 收入 | 待填 | 待填 | 待填 | 待填 |
| 业务 B | 成本 | 待填 | 待填 | 待填 | 待填 |

槽样例：income.revenue / 2025A 原表披露 1,234,567,890.00 元，则 raw_value 保存去千位分隔符后的精确原值文本、raw_unit=元，normalized_value=1234.56789、normalized_unit=CNY_million，附上页表行列位置后 locked。其他研报给出 1,235 百万元只记录为未采用的外部证据，既不改值也不产生人工待办。

若业务 A 的成本未披露，该槽 not_disclosed，毛利率结果 unavailable。若年报明确没有债券，presence=absent，债券区域显示“不适用”，不生成一只名称为空的债券，也不向网页搜索债券。

## 11. 与现有项目的接入差异

| 现有位置 | 后续实现要求 |
|---|---|
| ResearchPlan / framework.skeleton | 移除财务、证券逐问题检索任务；固定定量表独立于非量化研究问题 |
| graphs.dependencies / calculation_planner | 依赖只能读取固定槽及固定派生表；公式选择不能创建新财务需求或提高必需性 |
| LocalDatasource / UnifiedDatasource | 分离本地证券与指定年报入口；财务证券调用不得经过通用 local+web 合并检索 |
| researcher / contexts | 财务提取缓存按内容窗口和固定合同复用，多槽分发；定性资料共享一次提取结果 |
| FinancialFact / RequiredData | 增加原值、原单位、日期、绑定及终态元数据；精确事实和槽不再仅用 missing/found/conflict 表达 |
| reconciliation / HumanInterventionAgent | locked 年报槽退出候选冲突与人工发布路径；低优先级差异只留诊断 |
| formulas / forecast | 新增确定映射和派生计算；不能把营业利润当 EBIT、货币资金当现金等价物、分红利息合列值当分红 |
| API / work-products / 前端 | 展示固定表、缺失终态、来源位置、模型受限原因与填槽进度；不以字段全满作为完成标准 |
| resume manifest | 固定模板和数据绑定进入兼容性签名；旧断点不静默混用新规则 |

当前 OPENING_KEYS 中 other_assets、other_liabilities 应由固定归类公式生成；debt 从固定互斥组件生成，不能作为三个新的“缺失财务问题”去搜索。现有 EPS/PE 使用合并净利润的简化逻辑，后续须按归母及股份口径适配，不能直接声称本设计已修复现有估值。现有模型把货币资金与预测现金流衔接，适用性须显式校验，不通过修改历史货币资金消除不一致。

固定字段和锁定规则已接入真实模式；模拟模式投影同一固定表，保留合成数据说明。部分派生政策尚未启用，具体边界见实施验收文档。

## 12. 后续实现验收场景

| 场景 | 应有结果 |
|---|---|
| 相同营收先后被两个分析块需要 | 同一个 locked 槽，只引用、不取数 |
| 一份年报覆盖多表和两个业务 | 共用已完成的文档/窗口提取，不按槽重复发送 |
| 年报多年表，单位只在表头 | 正确按列定位并锁定，不因短摘录缺单位转人工 |
| 研报营收与年报略有差异 | 年报输入不变，零人工待办 |
| 业务缺少成本 | 成本终态未披露，毛利率不可用，不补造 |
| 无债券 / 债券情况未知 | 分别显示不适用 / 缺失，不能等同 |
| 债券明细与应付债券总额均存在 | 解释关联，集团债务不重复相加 |
| 多产品销量单位不同 | 明细原单位保留，不做无意义合计 |
| 三个显示财年需要同比 | 固定前序年已实例化，不由补充 plan 临时新增 |
| 暂停恢复或同任务重规划 | 完成槽、成功窗口和终态缺失均复用 |
| 最新股价搭配旧股本 / 多类股份 | 禁止错误市值计算，保留输入并标明受限 |
| 新报告或模型给出新的历史值 | 锁定槽不变化；只有明确授权的新数据版本可采用 |
