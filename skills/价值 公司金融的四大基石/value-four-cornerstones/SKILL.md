---
name: value-four-cornerstones
description: "价值分析的补充方法路由：经营健康、财务弹性、财报预期更新、业务组合、风险、回报归因、市场估值及投资者行为；也用于整书概览。ROIC、增长、倍数、逆向 DCF 和并购等独立 skill 优先直接使用。"
metadata:
  cangjie.generated-by: "cangjie-tools v2.5.0"
  cangjie.variant: "router"
  cangjie.bundle-id: "bundle.value-four-cornerstones"
  cangjie.capability-count: "16"
  cangjie.entrypoint-count: "8"
  local.review-date: "2026-10-06"
  local.adaptation: "industry-company-research"
---
# 价值分析补充方法路由

## 使用方式

任务明确命中独立 skill 时直接调用，无需先读本入口。剩余意图按表加载相应卡片；完整研究按阶段组合所需内容，不设整项任务最多两张卡的硬上限，也不一次加载全部材料。

默认行业与公司经营研究，交付机制、证据、反证与缺口；只有用户要求投资判断才追加价格、市场预期、催化和推荐。缺数据或工具时完成可支持的部分；名称相邻的 skill 未安装不阻塞卡片执行。

共同原则：供需与份额约束、可追溯假设、现金流/资本/指标口径匹配、平均与新增回报分开、证据性质分开、概率有依据才赋值。历史案例与统计只作来源背景，不能直接当当前市场基准。金融机构采用专属框架。

## 按意图加载

| 用户意图 | 先读 | 补读/备注 |
|---|---|---|
| 判断增长是在创造价值还是毁灭价值；用 ROIC 与增长两个变量解释或估算公司价值；检验公司增长目标在资本层面的自洽性；决定低回报公司应先修回报率还是继续扩张；计算投资率与自由现金流 | [roic-growth-value-core](references/capabilities/roic-growth-value-core.md) | 已晋级为独立 Skill `roic-growth-value-core`（已安装时优先直接使用；本卡提供同等方法，背景另按需读取） |
| 反推当前股价隐含的增长率与 ROIC；判断市场预期是否已经充分反映（price in）；判断高估值/低估值还剩多少预期差；比较同行业两个标的的预期差大小；为投资观点设定可证伪的验证信号 | [implied-expectations-reverse-dcf](references/capabilities/implied-expectations-reverse-dcf.md) | 已晋级为独立 Skill `implied-expectations-reverse-dcf`（已安装时优先直接使用；本卡提供同等方法，背景另按需读取） |
| 判断高 ROIC 是护城河还是周期/会计假象；论证竞争优势能否持续 3–5 年；解释同行业内 ROIC 差距巨大的原因；评估靠并购成长的公司内生回报有没有改善；设定合理的中期 ROIC 假设 | [roic-competitive-advantage-decomposition](references/capabilities/roic-competitive-advantage-decomposition.md) | 已晋级为独立 Skill `roic-competitive-advantage-decomposition`（已安装时优先直接使用；本卡提供同等方法，背景另按需读取） |
| 判断增长来源的价值含量；检验公司增速目标的可信度与天花板；行业内生增长 vs 并购增长的质量比较；判断行业高增长是品类扩张还是存量厮杀；设定估值模型的中长期增长率 | [growth-quality-ladder](references/capabilities/growth-quality-ladder.md) | 已晋级为独立 Skill `growth-quality-ladder`（已安装时优先直接使用；本卡提供同等方法，背景另按需读取） |
| 做可比公司估值并选倍数、选同行；解释个股相对同行的折溢价来源；跨市场比较同一行业估值；判断周期性行业当前 P/E 是真便宜还是周期陷阱；检验"被低估/被高估"的说法是否成立 | [valuation-multiple-traps](references/capabilities/valuation-multiple-traps.md) | 已晋级为独立 Skill `valuation-multiple-traps`（已安装时优先直接使用；本卡提供同等方法，背景另按需读取） |
| 判断回购/分拆/并表/证券化/售后回租是否创造价值；拆穿或验证"增厚 EPS""释放价值""估值重估"类说法；判断会计政策变更是否影响估值；判断金融工程是否真的降低了风险；识别"高 P/E 收购低 P/E"类的倍数扩展谬论 | [value-conservation-test](references/capabilities/value-conservation-test.md) | 已晋级为独立 Skill `value-conservation-test`（已安装时优先直接使用；本卡提供同等方法，背景另按需读取） |
| 评估一笔并购对收购方股东是创造还是毁灭价值；计算盈亏平衡改善率与合理溢价上限；判断并购叙事（协同、国际化、平台化）是否可信；判断行业整合能否真正改善回报；复盘中解释市场对某笔交易的正/负反应 | [ma-value-creation-assessment](references/capabilities/ma-value-creation-assessment.md) | 已晋级为独立 Skill `ma-value-creation-assessment`（已安装时优先直接使用；本卡提供同等方法，背景另按需读取） |
| 判断市场或行业估值由盈利驱动还是利率/风险偏好驱动；解释一段时期市场大涨或大跌的来源；给长期回报设定合理锚；判断周期性行业当前估值是否陷阱；判断盈利占 GDP 比重是否已到历史极端 | [market-valuation-drivers](references/capabilities/market-valuation-drivers.md) | [valuation-multiple-traps](references/capabilities/valuation-multiple-traps.md)、[bubble-vs-crisis-diagnosis](references/capabilities/bubble-vs-crisis-diagnosis.md)、[implied-expectations-reverse-dcf](references/capabilities/implied-expectations-reverse-dcf.md) |
| 复盘一只股票过去 N 年的回报来源；判断历史高回报是否可重复；评价管理层该给多少 credit；比较同行业两个标的的历史回报质量；判断该用绝对还是相对 TRS 做考核 | [trs-driver-decomposition](references/capabilities/trs-driver-decomposition.md) | [implied-expectations-reverse-dcf](references/capabilities/implied-expectations-reverse-dcf.md)、[market-valuation-drivers](references/capabilities/market-valuation-drivers.md) |
| 判断某类资金流入/流出的信息含量；判断"机构在买"是不是有效信号；验证"吸引成长型投资者能抬估值"是否成立；解释无消息时股价为何波动；判断卖方研报/评级上调的信号价值 | [investor-typology-pricing-power](references/capabilities/investor-typology-pricing-power.md) | [bubble-vs-crisis-diagnosis](references/capabilities/bubble-vs-crisis-diagnosis.md)、[market-valuation-drivers](references/capabilities/market-valuation-drivers.md) |
| 判断某行业/公司当前是否处于泡沫；判断大跌是泡沫破灭、外部冲击还是新信息重估；判断错价能否被纠正（套利可行性）；区分股市下跌与金融危机/系统性风险；判断高估值板块回调后能否抄底 | [bubble-vs-crisis-diagnosis](references/capabilities/bubble-vs-crisis-diagnosis.md) | [investor-typology-pricing-power](references/capabilities/investor-typology-pricing-power.md)、[market-valuation-drivers](references/capabilities/market-valuation-drivers.md)、[implied-expectations-reverse-dcf](references/capabilities/implied-expectations-reverse-dcf.md) |
| 判断 beat/miss 财报该不该改变观点；判断亮眼财报是真改善还是牺牲长期换来的；判断会计政策变更是否影响估值；判断盈利波动大是不是缺点；给一致预期定权重 | [earnings-expectations-relevance](references/capabilities/earnings-expectations-relevance.md) | [performance-health-metrics](references/capabilities/performance-health-metrics.md)、[value-conservation-test](references/capabilities/value-conservation-test.md)、[implied-expectations-reverse-dcf](references/capabilities/implied-expectations-reverse-dcf.md) |
| 判断出售/分拆/剥离是利好还是利空；做 sum-of-the-parts 与集团拆值；判断并购中买方是否真有最佳所有者优势；判断多元化集团总部是否在创造价值；寻找潜在剥离催化剂 | [best-owner-and-divestiture](references/capabilities/best-owner-and-divestiture.md) | [ma-value-creation-assessment](references/capabilities/ma-value-creation-assessment.md)、[value-conservation-test](references/capabilities/value-conservation-test.md)、[capital-structure-resilience](references/capabilities/capital-structure-resilience.md) |
| 判断某风险敞口该不该对冲；评估高风险高回报项目该不该做；判断某风险会不会危及公司存续；给 WACC 取值并判断哪些风险该计入；评价公司风险管理质量 | [risk-total-vs-price](references/capabilities/risk-total-vs-price.md) | [capital-structure-resilience](references/capabilities/capital-structure-resilience.md)、[bubble-vs-crisis-diagnosis](references/capabilities/bubble-vs-crisis-diagnosis.md) |
| 判断负债水平是否健康、还有多少财务弹性；评估加杠杆回购/分红/大额资本开支的风险；判断周期性行业公司能否撑过下行期或逆势扩张；评估复杂融资安排的真实代价；判断超额现金是否该返还股东 | [capital-structure-resilience](references/capabilities/capital-structure-resilience.md) | [risk-total-vs-price](references/capabilities/risk-total-vs-price.md)、[value-conservation-test](references/capabilities/value-conservation-test.md)、[best-owner-and-divestiture](references/capabilities/best-owner-and-divestiture.md) |
| 判断优秀财务表现是否可持续；设计前瞻性的跟踪指标体系；评价管理层披露质量与坦诚度；判断利润增长是提效还是透支（涨价/砍研发/砍营销/压货）；判断公司机制是否系统性产生短期主义 | [performance-health-metrics](references/capabilities/performance-health-metrics.md) | [earnings-expectations-relevance](references/capabilities/earnings-expectations-relevance.md)、[roic-competitive-advantage-decomposition](references/capabilities/roic-competitive-advantage-decomposition.md)、[best-owner-and-divestiture](references/capabilities/best-owner-and-divestiture.md) |

## 资料用途

- 方法概览需要时读取 [references/overview.md](references/overview.md)。
- 指标定义需要时读取 [references/glossary.md](references/glossary.md)，口径规则以修订能力卡为准。
- 简短规则见 [references/cheatsheet.md](references/cheatsheet.md)。
- 更多意图见 [references/capability-index.md](references/capability-index.md)。

研究顺序可为范围与证据→行业机制→公司增长/优势/财务→情景→按需投资价值→表达与更新；小任务跳过无关阶段。不因缺短期催化、无买卖评级或未获同事复核停止正常经营研究。
