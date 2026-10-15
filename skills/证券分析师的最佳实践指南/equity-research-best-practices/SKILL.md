---
name: equity-research-best-practices
description: "行业/公司研究的补充方法路由：资料台账、卖方研报筛选、研究预算、回归验证、问卷和沟通准备；也用于整书方法概览。已提供独立 skill 的任务优先直接使用；复杂任务按阶段组合，不作为所有研究的前置门。"
metadata:
  cangjie.generated-by: "cangjie-tools v2.5.0"
  cangjie.variant: "router"
  cangjie.bundle-id: "equity-research-best-practices"
  cangjie.capability-count: "18"
  cangjie.entrypoint-count: "11"
  local.review-date: "2026-10-06"
  local.adaptation: "industry-company-research"
---
# 证券研究补充方法路由

## 使用方式

任务明确命中独立 skill 时直接调用，无需先读本入口。剩余意图按表加载相应卡片；完整研究按阶段组合所需内容，不设整项任务最多两张卡的硬上限，也不一次加载全部材料。

默认行业与公司经营研究，交付机制、证据、反证与缺口；只有用户要求投资判断才追加价格、市场预期、催化和推荐。缺数据或工具时完成可支持的部分；名称相邻的 skill 未安装不阻塞卡片执行。

共同原则：供需与份额约束、可追溯假设、现金流/资本/指标口径匹配、平均与新增回报分开、证据性质分开、概率有依据才赋值。历史案例与统计只作来源背景，不能直接当当前市场基准。金融机构采用专属框架。

## 按意图加载

| 用户意图 | 先读 | 补读/备注 |
|---|---|---|
| 分析一个行业的基本面与估值驱动；判断行业处于周期什么位置；拆解产业链与议价能力；进入新行业时如何快速建立全景认知；industry analysis, supply-demand, value chain, industry cycle | [equity-industry-analysis](references/capabilities/equity-industry-analysis.md) | 已晋级为独立 Skill `equity-industry-analysis`（已安装时优先直接使用；本卡提供同等方法，背景另按需读取） |
| 找出行业/公司关键经营驱动；股票任务另判计价影响；建立关键因素的监测清单与频率；重新审视已跟踪股票的研究起点；key factors, drivers, what moves the stock, monitor | [equity-key-factors](references/capabilities/equity-key-factors.md) | 已晋级为独立 Skill `equity-key-factors`（已安装时优先直接使用；本卡提供同等方法，背景另按需读取） |
| 开发和维护行业信息源/专家网络；设计一次专家访谈或管理层调研；验证一个传闻或行业数据；如何在不触碰披露红线的前提下获取信息；channel check, expert network, primary research, mosaic theory | [equity-source-and-interview](references/capabilities/equity-source-and-interview.md) | 已晋级为独立 Skill `equity-source-and-interview`（已安装时优先直接使用；本卡提供同等方法，背景另按需读取） |
| 审查一家公司的财报质量/盈利质量；识别可能的会计操纵或盈余管理；判断外部数据是否可信、能不能直接比较；净利润与经营现金流背离意味着什么；forensic accounting, earnings quality, accounting red flags, quarantine flags | [equity-financial-forensics](references/capabilities/equity-financial-forensics.md) | 已晋级为独立 Skill `equity-financial-forensics`（已安装时优先直接使用；本卡提供同等方法，背景另按需读取） |
| 建立或审查公司财务预测模型；做敏感性分析/情景分析；预测下季度或下年度收入与利润；检查一个预测假设是否合理；financial model, scenario analysis, sensitivity, forecasting | [equity-forecast-modeling](references/capabilities/equity-forecast-modeling.md) | 已晋级为独立 Skill `equity-forecast-modeling`（已安装时优先直接使用；本卡提供同等方法，背景另按需读取） |
| 给一家公司估值 / 选估值方法；确定合理的估值倍数或目标价；建立可比公司表；判断当前估值是否偏高或偏低；valuation, price target, comparable companies, multiples, DCF | [equity-valuation](references/capabilities/equity-valuation.md) | 已晋级为独立 Skill `equity-valuation`（已安装时优先直接使用；本卡提供同等方法，背景另按需读取） |
| 该不该给出买入/卖出推荐；我的观点和市场分歧在哪；判断一个投资逻辑是否成立；寻找催化驱动因素；分析市场情绪与持仓者心理；investment recommendation, differentiated view, catalyst, market sentiment | [equity-recommendation](references/capabilities/equity-recommendation.md) | 已晋级为独立 Skill `equity-recommendation`（已安装时优先直接使用；本卡提供同等方法，背景另按需读取） |
| 检查我的判断是否带了偏见；该不该止损 / 为什么舍不得卖；用技术面验证或择时一个基本面结论；技术面与基本面打架时怎么办；behavioral bias, loss aversion, sunk cost, technical analysis, momentum | [equity-bias-audit](references/capabilities/equity-bias-audit.md) | 已晋级为独立 Skill `equity-bias-audit`（已安装时优先直接使用；本卡提供同等方法，背景另按需读取） |
| 写行业报告、公司深度或投资报告；组织一次投资观点的表达；让报告更有说服力 / 砍掉冗余；做 PPT 或邮件推送投资观点；research report writing, investment memo, communicate a stock view | [equity-report-writing](references/capabilities/equity-report-writing.md) | 已晋级为独立 Skill `equity-report-writing`（已安装时优先直接使用；本卡提供同等方法，背景另按需读取） |
| 判断一个做法是否违反职业道德；处理利益冲突；判断某信息是否属于重大非公开信息；投行压力下的评级偏移怎么办；analyst ethics, conflict of interest, MNPI, compliance | [equity-ethics-review](references/capabilities/equity-ethics-review.md) | 已晋级为独立 Skill `equity-ethics-review`（已安装时优先直接使用；本卡提供同等方法，背景另按需读取） |
| 我该跟多少只股票；如何争取或调整覆盖范围；接手新领域从哪开始 | [analyst-coverage-scoping](references/capabilities/analyst-coverage-scoping.md) | [equity-industry-analysis](references/capabilities/equity-industry-analysis.md)、[equity-key-factors](references/capabilities/equity-key-factors.md) |
| 怎么安排研究时间；哪些工作可以外包或自动化；感觉很忙但没产出怎么办 | [analyst-time-allocation](references/capabilities/analyst-time-allocation.md) | [analyst-coverage-scoping](references/capabilities/analyst-coverage-scoping.md)、[equity-valuation](references/capabilities/equity-valuation.md) |
| 怎么让 PM 或客户采纳我的观点；如何影响管理层或内部同事；观点很好但没人听怎么办 | [analyst-stakeholder-influence](references/capabilities/analyst-stakeholder-influence.md) | [equity-report-writing](references/capabilities/equity-report-writing.md)、[sellside-research-screening](references/capabilities/sellside-research-screening.md) |
| 怎么整理研究资料；换了公司研究怎么不断档；访谈记录和调研数据怎么归档 | [research-information-center](references/capabilities/research-information-center.md) | [equity-key-factors](references/capabilities/equity-key-factors.md)、[equity-source-and-interview](references/capabilities/equity-source-and-interview.md) |
| 怎么筛选卖方研究报告；如何让卖方分析师为我定制服务；每天几十份研报看不完怎么办 | [sellside-research-screening](references/capabilities/sellside-research-screening.md) | [equity-source-and-interview](references/capabilities/equity-source-and-interview.md)、[analyst-stakeholder-influence](references/capabilities/analyst-stakeholder-influence.md) |
| 模型要不要做那么复杂；我的预测比市场高一点点要不要发；研究的精度到底重不重要 | [analyst-thinking-discipline](references/capabilities/analyst-thinking-discipline.md) | [equity-forecast-modeling](references/capabilities/equity-forecast-modeling.md)、[equity-recommendation](references/capabilities/equity-recommendation.md) |
| 用回归预测某个变量；回归结果怎么诊断；哪些宏观变量真正解释我的标的 | [regression-forecasting](references/capabilities/regression-forecasting.md) | [equity-forecast-modeling](references/capabilities/equity-forecast-modeling.md)、[equity-financial-forensics](references/capabilities/equity-financial-forensics.md) |
| 要不要发一轮问卷调查；怎么设计一份行业问卷；外部调查数据能不能信 | [primary-survey-design](references/capabilities/primary-survey-design.md) | [equity-source-and-interview](references/capabilities/equity-source-and-interview.md)、[equity-financial-forensics](references/capabilities/equity-financial-forensics.md) |

## 资料用途

- 方法概览需要时读取 [references/overview.md](references/overview.md)。
- 指标定义需要时读取 [references/glossary.md](references/glossary.md)，口径规则以修订能力卡为准。
- 简短规则见 [references/cheatsheet.md](references/cheatsheet.md)。
- 更多意图见 [references/capability-index.md](references/capability-index.md)。

研究顺序可为范围与证据→行业机制→公司增长/优势/财务→情景→按需投资价值→表达与更新；小任务跳过无关阶段。不因缺短期催化、无买卖评级或未获同事复核停止正常经营研究。
