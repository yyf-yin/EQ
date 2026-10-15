# verified.md — 阶段 1.5 三重验证产出

> 候选池：`candidates/frameworks.md`(52) + `candidates/principles.md`(113) + `candidates/cases.md`(41) + `candidates/counter-examples.md`(25) + `candidates/glossary.md`(40)
> 合并后形成 **16 个能力单元**，全部通过 V1/V2/V3。未独立成能力的候选见文末「合并映射」与 `rejected/`。

## 验证口径

- **V1 跨域**：同一方法论在书中 ≥2 个独立章节/对象上有佐证（不同对象 + 不同结论，不是同一案例换说法）。
- **V2 预测力**：能用它回答一个书里没明说的新问题，且结论非平庸。
- **V3 独特性**：抹掉作者名字后，一个懂财务的聪明人**不会**自然想到 / 或会想到相反的结论。

---

## P1 · 价值核心：ROIC × 增长 → 价值

```yaml
id: cap.value.roic-growth-core
slug: roic-growth-value-core
merged_from: [f01, f02, f03, f04, f05, p04, p05, p06, p07, p09, p10, p110]
supporting_cases: [c01, c02, c03, c04, c05]
V1_cross_domain:
  passed: true
  evidence:
    - 第2章: 沃尔格林(增长12%/ROIC14%) vs 箭牌(增长9%/ROIC28%) — 增长更慢者 TRS 更高
    - 第2章: 金宝汤(增长4%/ROIC50%) vs 科尔士(增长15%/ROIC15%) — 市盈率相近
    - 第2章: 美国大公司(ROIC16%) vs 亚洲大公司(ROIC10%) — 解释跨市场市盈率差
    - 第2章: 通用电气工业(ROIC 13%→31%) 与金融(增长18%) — 同一公司内两种驱动分离
    - 附录A: 关键价值驱动公式的数学推导（独立的形式化证据）
V2_predictive_power:
  passed: true
  novel_question: "一家新能源车企年增 60%，但 ROIC 只有 5%、WACC 9%，扩产是在创造价值还是毁灭价值？"
  derived_answer: "ROIC<WACC，增长在毁灭价值。每 1 元增量收入需 IR=60%/5%=1200% 的投资——即增量投资远超增量利润，现金流为负。正确动作是先修单位经济与资本效率，不是继续抢份额。"
V3_exclusivity:
  passed: true
  why_not_common: "常识（及多数卖方模型）把增长当无条件利好。本书给出可计算的分界线 ROIC vs WACC，并给出'投资率=g/ROIC'把增长与资本消耗硬性绑定 — 反直觉点在于：低回报公司的增长是价值漏损。"
→ 进入阶段 2（promoted）
```

## P2 · 期望值跑步机：从股价逆向工程隐含预期

```yaml
id: cap.value.implied-expectations
slug: implied-expectations-reverse-dcf
merged_from: [f08, f09, f11, p18, p19, p20, p21, p22, p24, x20, x21]
supporting_cases: [c06, c07, c08, c09]
V1_cross_domain:
  passed: true
  evidence:
    - 第4章: 家得宝 — 1999 年市值 1320 亿反推需连续 15 年 26% 增长，实际 11%，市值跌至 800 亿
    - 第4章: 沃尔玛 vs 塔吉特 — 业绩更优者 TRS 更低，9 点差距中 7 点来自预期与市盈率变化
    - 第5章: 蒂娜的虚构案例（Widgets R Us）— 业绩持续超预期反而只能拿到行业平均回报
    - 第16章: Chemco 案例 — 用 DCF 反推"当前股价对应 2% 收入增长"，与同行隐含值比对
V2_predictive_power:
  passed: true
  novel_question: "某公司新管理层上任，市场一片看好、股价一年涨了 80%，现在还能买吗？"
  derived_answer: "先不判断管理层好坏，先反推：当前股价隐含的 ROIC 与增长率是多少？若隐含值已处于行业中枢之上（书中约 80% 公司股价已隐含合理预期），则未来超额回报只能来自'超越已植入的预期'，难度远高于'从低预期修复'。低预期 + 基本面改善的组合（大陆股份/塔吉特式）胜率更高。"
V3_exclusivity:
  passed: true
  why_not_common: "常识问'这家公司好不好'；本书问'当前价格已经假设它有多好'——把分析对象从公司换成价格与基本面之间的差额，且给出'80% 公司已隐含合理预期'这个可操作先验。"
→ 进入阶段 2（promoted）
```

## P3 · ROIC 竞争优势拆解与持续性

```yaml
id: cap.value.roic-decomposition
slug: roic-competitive-advantage-decomposition
merged_from: [f25, f26, f27, f28, p54, p55, p56, p57, p58, p59, p60, p61, p62, p63, p64]
supporting_cases: [c32, c33, c14, c20]
V1_cross_domain:
  passed: true
  evidence:
    - 第10章: eBay(ROIC>50%，可扩展性) vs Webvan(破产，资本密集无壁垒) — 同一时代相同叙事，相反结局
    - 第10章: 诺里尔斯克镍(67%，特有资源含钯) vs 淡水河谷(25%) — 同矿种，资源禀赋差
    - 第10章: 29 个行业 ROIC 中位数与四分位分布 — 行业结构黏着
    - 第10章: 1995—2005 公司 ROIC 转移概率矩阵 — 57% 的 <10% 公司十年后仍在 <10%
    - 第10章: 含商誉 ROIC 趋平 vs 不含商誉 ROIC 上升 — 双口径证据
V2_predictive_power:
  passed: true
  novel_question: "一家消费品公司说自己有'强品牌'，ROIC 30%，该不该给溢价？"
  derived_answer: "先做三件事：① 把 30% 拆成价格溢价还是成本优势，并归入 9 类来源之一（品牌需证明'质量差异之外的独立溢价'，如谷物>30% vs 肉类<15%）；② 查行业 ROIC 分位（第10章口径：中等以上需 >17%，前 25% 需 >25%，2004 年前只需 >10%）；③ 查'品牌+可扩展性'类优势的持久性——书中明确品牌/质量/可扩展性比资源型优势更持久。若 30% 主要来自一次性资源或周期价格，不给溢价。"
V3_exclusivity:
  passed: true
  why_not_common: "常识谈'护城河'是定性标签；本书强制拆到 9 类来源 + 行业分位 + 转移概率三重验证，并给出'含/不含商誉双口径'这个大多数分析师会忽略的陷阱（含商誉 ROIC 趋平 = 并购溢价吞噬了价值）。"
→ 进入阶段 2（promoted）
```

## P4 · 增长质量阶梯与天花板

```yaml
id: cap.value.growth-quality
slug: growth-quality-ladder
merged_from: [f29, f30, f31, f32, p08, p09, p10, p65, p66, p67, p68, p69]
supporting_cases: [c34, c35, c01, c04]
V1_cross_domain:
  passed: true
  evidence:
    - 第2章 图2.9: 消费品公司 8 类增长的每美元收入创造价值排序
    - 第11章 图11.1: 8 类增长 + "基本原理（谁受损）"的完整阶梯表
    - 第11章: 500 强实际收入增长中位数 5.9%；美国大公司 1965—2008 中位数 5.4%
    - 第11章 图11.4: 高增长公司 10 年后仅 25% 维持 ≥15%，44% 跌到 <5%
    - 第11章: 沃尔玛(35 年降到 10% 以下) vs eBay(12 年) 的 S 曲线对比
V2_predictive_power:
  passed: true
  novel_question: "两家公司都宣布明年收入增 20%，A 靠降价促销抢份额，B 靠把现有客户变成高频用户，谁更值钱？"
  derived_answer: "B。判定法=谁受损、能否反击：A 抢的是竞争者的份额，对手可快速反击（降价），且一旦成为常态则毁灭价值；B 让所有竞争者同时受益（宝洁说服人多洗手），无人反击，且边际成本极低。书中排序：创造新市场 > 提高现有客户频次 > 引入新客户 > 成长市场抢份额 > 补强并购 > 渐进创新抢份额 > 促销抢份额 > 大并购。"
V3_exclusivity:
  passed: true
  why_not_common: "常识按增长率高低排优劣。本书按'谁受损、受损者能否反击'排，结论反直觉：成熟市场抢份额（最常见的高增长）价值最低，甚至在价格战常态化时为负；并购垫底。"
→ 进入阶段 2（promoted）
```

## P5 · 估值倍数的正确使用与同行校准

```yaml
id: cap.value.multiple-analysis
slug: valuation-multiple-traps
merged_from: [f51, p111, p112, p113, x19, x24(倍数部分)]
supporting_cases: [医药公司倍数收敛案例, 6家科技公司倍数 vs 绩效案例, P/E 折价25%实为杠杆差异案例]
V1_cross_domain:
  passed: true
  evidence:
    - 附录B: P/E 折价 25% 的公司，对等债务调整后与同行一致 — 差异纯数学而非投资者判断
    - 附录B 图B.1: 大型医药公司原始 P/E 12–28，改用前瞻 EV/EBITA 后收敛到 12–17
    - 附录B 图B.2: 6 家科技公司按"利润×增长"分三组后倍数 7 / 9 / 11–13，原本"荒谬"的折价变得合理
    - 第2章: 消费品行业按 g × ROIC 网格的市盈率矩阵
V2_predictive_power:
  passed: true
  novel_question: "某公司 P/E 11，同行 14，管理层说市场没看懂它，是买入机会吗？"
  derived_answer: "先做三步再下结论：① 用 EV/EBITA 剔除资本结构（高负债必然低 P/E）；② 用可持续盈利（剔一次性、周期位置、资本结构）而非报告盈利作分母；③ 按 g × ROIC 重新选可比同行——很可能折价完全由绩效差解释，不是错杀。书中原例：折价 25% 全部由杠杆解释。"
V3_exclusivity:
  passed: true
  why_not_common: "常识直接比 P/E。本书指出 P/E 是一个被资本结构、报告盈利口径、周期位置三重污染的数，必须换 EV/EBITA + 可持续盈利 + 绩效匹配同行；且明确'找到正确同行后，原本荒谬的倍数会变得合理'。"
→ 进入阶段 2（promoted）
```

## P6 · 价值守恒检验：指不出现金流增加就是幻觉

```yaml
id: cap.value.value-conservation-test
slug: value-conservation-test
merged_from: [f06, f07, p11, p12, p13, p14, p15, p16, p17, x01, x02, x04, x06, x07, x23]
supporting_cases: [c15, c16, c17, c18, c19]
V1_cross_domain:
  passed: true
  evidence:
    - 第3章: 员工股票期权费用化争论 — 会计变更，十年争论，实施后股价无变化
    - 第3章: 举债回购使 EPS +5%，但杠杆上升压低市盈率，净值为零
    - 第3章: 高 P/E 收购低 P/E 的"倍数扩展/重新衡量"谬论（150 vs 160 的 10 美元幻觉）
    - 第3/8章: 担保债务凭证(CDO) — 未增加现金流，风险总量不变，费用反而减少总现金流
    - 第15章: 默文(Mervyn) 房地产/运营拆分 — 所有者利益错配，2008 破产
    - 第9章: 商誉停止摊销使 EPS 上升，股价效应不到两周
V2_predictive_power:
  passed: true
  novel_question: "公司公告：拟分拆子公司 A 独立上市，称'将释放集团价值、提升 EPS'，怎么看？"
  derived_answer: "追问四个问题并逐项要现金流证据：① 合并实体总现金流会增加吗？来源是收入协同、成本协同还是资本效率？② 若只是把 A 按更高倍数重估（rerating），那是幻觉——同一资产不会因换了持有主体就产生更多现金；③ 若剥离的是低 ROIC 业务，可能真实创造价值（剩余实体 g 与 ROIC 提高，倍数上升），这是真来源；④ 分拆的税务/总部成本/失去协同，扣减后还剩多少。"
V3_exclusivity:
  passed: true
  why_not_common: "常识看到 EPS 增厚/分拆/回购/并表就调高预期。本书给出一条硬判据：总现金流不变 → 价值不变，它只是在股东之间搬运。反直觉点：'低估时回购创造价值'也是假的——只是从卖出股东转到留下股东。"
→ 进入阶段 2（promoted）
```

## P7 · 并购价值创造评估

```yaml
id: cap.value.ma-value-creation
slug: ma-value-creation-assessment
merged_from: [f37, f38, f39, f40, p77, p78, p79, p80, p81, p82, x05, x12, x22]
supporting_cases: [c10, c11, c12, c13, c37, c38]
V1_cross_domain:
  passed: true
  evidence:
    - 第13章 图13.1/13.2: 价值创造 = 绩效改进现值 − 溢价（A 买 B：付 30% 溢价需改善 40%）
    - 第13章 图13.3: 四笔消费品并购的"改善% − 溢价% = 净创造%"
    - 第13章: 1415 笔并购研究，收购方+目标方平均增加约 4%，但收购方股东公告效应仅 1%–3%
    - 第13章 图13.5: 117 笔交易，EPS 增厚/稀释与市场反应无关（约 41% 正反应）
    - 第5章: 亚洲公司 vs 私募股权竞价案例 — 出价 1 亿击败 PE 并留 2000 万价值
V2_predictive_power:
  passed: true
  novel_question: "公司宣布 200 亿收购同行，溢价 35%，市场当天跌了 8%，是市场错了吗？"
  derived_answer: "用原型检验：这笔交易落在 5 个原型（改善绩效/移除过剩产能/加速市场准入/低成本获技术/早期挑选赢家）中的哪一个？若说不清，跌 8% 合理。再算账：35% 溢价意味着必须改善目标 ≥35% 才不亏；若目标本身 ROIC 已经很高，边际改善空间小（书中算例：6% 营业利润率降到成本 91% 就能增 50% 价值，而 30% 利润率需成本降 21% 才增 50%，几乎不可能）。另查三个实证特征：收购方是否是强运营商、溢价是否低、是否单一竞买者。"
V3_exclusivity:
  passed: true
  why_not_common: "常识（包括很多券商点评）用 EPS 增厚/稀释和'战略协同'判断并购。本书给出可算的三元式 + 5 个原型硬约束 + '溢价 30% 需改善 30%'的对称性，并指出赢家诅咒。"
→ 进入阶段 2（promoted）
```

## R1 · 市场估值驱动：P/E = f(g, ROIC, WACC) 与利率通胀

```yaml
id: cap.value.market-valuation-drivers
slug: market-valuation-drivers
merged_from: [f18, f19, f20, p34, p35, p36, p37]
supporting_cases: [c22, c23, c24, 1962—2009 P/E 拟合案例]
V1_cross_domain:
  passed: true
  evidence:
    - 第2章 图2.6: 1962—2009 预测 P/E 与实际 P/E 密切一致
    - 第7章 图7.5/7.7/7.8: 一年期市场模型，多数年份误差 <15%；趋势模型 vs 锚定模型
    - 第7章: 1983—1996 若利率通胀不降，实际回报仅 7%（实际 12%）— 利率的量化贡献
    - 第7章: 1969—1982 大通胀使 P/E 从 18 降到 10
    - 第7章: 周期性公司（化工、造纸）利润低时 P/E 高、利润高时 P/E 低
V2_predictive_power:
  passed: true
  novel_question: "全市场 P/E 从 15 涨到 22，是因为公司变好了还是因为利率降了？"
  derived_answer: "拆成三块：盈利（趋势 vs 当前锚定）+ 利率/通胀 + 风险偏好。用书中一年期模型算'基本面隐含 P/E'，与实际比：若模型值仍 15 而实际 22，差异来自贴现率或风险偏好而非盈利改善——那是不可持续的估值扩张，后续回归概率高。同时记住周期性行业要反向读 P/E。"
V3_exclusivity:
  passed: true
  why_not_common: "常识把 P/E 扩张归因为'景气/成长'。本书给出可复算的分解，并用 1983—1996 的反事实（无利率下降则只有 7%）量化了'利率贡献了多少'，还指出锚定模型拟合实际、趋势模型给出应然值这一对张力。"
→ 进入阶段 2（router）
```

## R2 · TRS 归因分解

```yaml
id: cap.value.trs-decomposition
slug: trs-driver-decomposition
merged_from: [f10, p22, p23]
supporting_cases: [c08]
V1_cross_domain:
  passed: true
  evidence:
    - 第4章 图4.3: 沃尔玛 vs 塔吉特 TRS 七项分解（收入增长/投资/利润率/零增长回报率/P-E 变化/杠杆/其他）
    - 第4章: 塔吉特 24% 中 5% 来自 P/E 从 11→18，3% 来自高杠杆
    - 第7章: 十年期实际 TRS 与 GDP 对比表（宏观层面的同类分解）
V2_predictive_power:
  passed: true
  novel_question: "某公司过去五年 TRS 年化 30%，管理层归功于卓越运营，该给多少 credit？"
  derived_answer: "按七项分解：收入增长贡献、为增长的投资（负项）、利润率变动 = 业绩部分；零增长回报率 + P/E 变化 = 预期部分；杠杆 = 财务放大。若大部分来自 P/E 变化与杠杆，则不可重复（塔吉特杠杆贡献 3%，且其高杠杆不可持续）。只有业绩部分才应给管理层 credit，且应与同业相对比。"
V3_exclusivity:
  passed: true
  why_not_common: "常识用绝对 TRS 评价管理层与公司。本书证明短期 TRS 主要由行业与大盘（利率）驱动，必须分解出'预期重估'与'杠杆'两个非业绩项，且薪酬应挂钩相对而非绝对 TRS。"
→ 进入阶段 2（router）。注：与 P2（隐含预期）共享"预期变化"概念但契约不同——P2 是前向反推，本能力是后向归因。
```

## R3 · 投资者结构与定价权

```yaml
id: cap.value.investor-typology
slug: investor-typology-pricing-power
merged_from: [f15, f16, f17, p31, p32, p33]
supporting_cases: [c20, c21]
V1_cross_domain:
  passed: true
  evidence:
    - 第6章 图6.1: 两类投资者(A 研究型 / B 趋势型)市场模型 — 无新信息也会波动，A 决定价格区间
    - 第6章: 成长/价值标签证伪 — 成长型 ROIC 中位 35%，价值型 15%，增长率分布无统计差异
    - 第6章 图6.3: 内在投资者持有 20% 资产、10% 交易量，但单笔交易量大、被模仿 — 定价权证据
    - 第16章: 类指数基金（强生权重 1.4% 与指数一致）不代表对估值的判断
V2_predictive_power:
  passed: true
  novel_question: "某股票放量上涨、多家卖方上调评级，这是'聪明钱进场'吗？"
  derived_answer: "先分投资者：交易型投资者贡献 35% 市场、交易量最大但只关注短期事件，他们'对价格变化做出反应'而非'引起变化'；内在投资者只占 20% 资产却是长期价格水平的决定力量。放量上涨若由交易型驱动，可持续性弱。另注意：从'价值型'转入'成长型'指数时成长型投资者才买入——是反应不是原因，不能据此预期估值抬升。"
V3_exclusivity:
  passed: true
  why_not_common: "常识按'成长/价值'或'机构/散户'分投资者。本书证明这两个标签都错——真正的区分是策略（是否做深度尽调、持仓集中度、周转率），且结论反直觉：交易量最大的那群人对长期价格影响最小。"
→ 进入阶段 2（router）
```

## R4 · 泡沫诊断与危机红线

```yaml
id: cap.value.bubble-diagnosis
slug: bubble-vs-crisis-diagnosis
merged_from: [f21, f22, p38, p39, p40, p41, x03, x11, x17, x25]
supporting_cases: [c25, c26, c27, c28, c24]
V1_cross_domain:
  passed: true
  evidence:
    - 第8章: 泡沫定义（远高于全信息理性投资者估值）+ 3Com/Palm（无券可融，套利失败）
    - 第8章: 3560 家公司筛查，25 年中仅 123 家曾泡沫化，其中 92 家是 1999—2001 科技股 — 泡沫罕见且集中
    - 第8章: 1999 前 30 大公司 P/E 46 vs 其余 470 家 23 — 泡沫集中于大市值
    - 第8章: 新药临床失败致股价跌 61% 不算泡沫（概率加权重估）— 泡沫的反面界定
    - 第8章: 金融危机 vs 泡沫的区分（短债买非流动资产）
V2_predictive_power:
  passed: true
  novel_question: "某板块一年涨了 150%，然后腰斩。当初是泡沫吗？现在能抄底吗？"
  derived_answer: "三步：① 用 DCF 算'理性全信息投资者'估值（如 1999 十大科技股隐含需占全美利润 1/3），若价格远超该值 → 当时是泡沫；② 检查是否存在结构性限制（不可卖空/无券可融/流通盘小/跨市场套利受阻）——书中指出 A 股式限制正是泡沫温床；③ 区分泡沫与危机：若下跌由外部冲击或新信息重估引起，不是泡沫破灭，也不适用'均值回归'逻辑。腰斩后是否可抄底，取决于是否回到长期 DCF 趋势，而非跌幅。"
V3_exclusivity:
  passed: true
  why_not_common: "常识把'大涨后大跌'都叫泡沫，把危机期下跌也归入泡沫破灭。本书给出严格定义（相对理性估值）、发生条件（羊群 + 结构性套利限制）、分布特征（罕见、行业级、集中于大市值），并明确列出三类不算泡沫的情形。"
→ 进入阶段 2（router）
```

## R5 · 盈余预期与盈利管理陷阱

```yaml
id: cap.value.earnings-expectations
slug: earnings-expectations-relevance
merged_from: [f23, f24, p44, p45, p46, p47, p48, p49, p50, p51, p52, p53, x08, x18, x19]
supporting_cases: [c29, c30, c31]
V1_cross_domain:
  passed: true
  evidence:
    - 第9章 图9.2: 25 年中仅 7 年一致预期误差 <5%，16 年偏高，从不预测拐点
    - 第9章 图9.3: 5 年期滚动增长预期系统性 >10%，实际几乎全部低于预期
    - 第9章 图9.4: 欧洲 595 家 — 两年预期修正比当期超预期更能驱动股价
    - 第9章: 盈利意外对四周股价波动解释力 <2%；>40% 的正意外公司回报为负
    - 第9章 图9.5: 盈利波动性与 TRS/倍数无关（135 家对照）
    - 第9章: 商誉停止摊销、GAAP 披露、期权费用化 — 会计变更无持续股价效应
V2_predictive_power:
  passed: true
  novel_question: "公司 beat 了市场预期 10%，股价却跌了，为什么？该不该加仓？"
  derived_answer: "看两件事：① 分析师是否同时下修了未来两年预期——下修才是主导因素（当期超预期+下修 = 平均跌 0.6%）；② 这份 beat 是'高成本换来的'吗（削减营销/研发、渠道压货），市场会识别并对这类增长折价。另：连续 beat 一年以上才会形成溢价，且一旦中断回撤更剧烈。不要基于单季 beat 加仓。"
V3_exclusivity:
  passed: true
  why_not_common: "常识把'超预期'当利好、把'盈利稳定性'当优点。本书用三组数据反驳：意外解释力 <2%、波动性与回报无关、一致预期几乎从不预测拐点；真正重要的是长期（两年）预期修正的方向。"
→ 进入阶段 2（router）
```

## R6 · 最佳所有者与剥离 / 组合管理

```yaml
id: cap.value.best-owner-portfolio
slug: best-owner-and-divestiture
merged_from: [f12, f13, f14, f33, f34, f35, p25, p26, p27, p28, p29, p30, p70, p71, p72, p73, p74, p75, p76, x10, x13, x22]
supporting_cases: [c12, c18, c36, 化学/制药拆分案例]
V1_cross_domain:
  passed: true
  evidence:
    - 第5章: 通用磨坊 vs 帝亚吉欧买皮尔斯伯里（104 亿，现金流 +4 亿/年，经营利润 +70%）
    - 第5章: 最佳所有者生命周期（创始人→VC→上市→大公司→PE→低增长运营者）
    - 第12章: 通用动力先剥离(TRS 58%)后收购(>20%)
    - 第12章: 三类持有成本（总部成本/部门成本/退出价格低迷）+ "尽早卖"
    - 第12章: 多元化三重反驳（现金流未平滑、未加杠杆、未在周期底部投资）
V2_predictive_power:
  passed: true
  novel_question: "集团宣布要卖掉一个还在赚钱、但增长很慢的业务，是利空吗？"
  derived_answer: "通常不是。判断框架：① 该业务的最佳所有者还是不是它（5 个增值来源：业务联系/独特技能/洞察力/治理/政商资源）？成熟业务常已不是。② 三类持有成本是否已超过收益（占用总部管理时间、战略不匹配、拖累估值倍数）。③ 时点：书中实证是越早卖价格越高，多数公司卖得太晚（被剥离业务前 7 年利润已低于同行）。④ 卖掉低倍数业务会稀释 EPS，但剩余实体 g 与 ROIC 上升、倍数上升——这正是价值来源。"
V3_exclusivity:
  passed: true
  why_not_common: "常识认为卖资产=收缩=利空，且用 EPS 稀释判断。本书证明剥离常被市场正面反应（三年内拆分业务利润率平均提升 1/3），且给出'最佳所有者是流动的'这一动态视角——同一业务在不同生命周期属于不同所有者。"
→ 进入阶段 2（router）
```

## R7 · 风险：总量 vs 价格，与承受边界

```yaml
id: cap.value.risk-boundary
slug: risk-total-vs-price
merged_from: [f41, f42, f43, f44, p83, p84, p85, p86, p87, p88, p89, p90, x14, x15]
supporting_cases: [c39, 喜力汇率案例, 碳税对铝企的非对称影响案例]
V1_cross_domain:
  passed: true
  evidence:
    - 第14章 图14.1: 组合波动随持股数下降 — 可分散风险不进资本成本
    - 第14章: 大型非金融公司股权成本集中在 8%–10%（金宝汤 vs 谷歌差距小）— 风险价格的实证
    - 第14章 图14.3: 项目 A（60% 概率值 8000 万 / 40% 概率亏 2000 万，期望 4000 万但概率为零）
    - 第14章 图14.4: 核电项目（期望 +70 亿，但 20% 概率破产，失败会波及整个公司）
    - 第14章: 黄金/石油公司不应套保（投资者就是来买价格敞口的）
V2_predictive_power:
  passed: true
  novel_question: "公司说要全额套保外汇与大宗商品价格以'消除业绩波动'，是加分还是减分？"
  derived_answer: "分三步：① 分风险总量与风险价格——投资者已分散化，可分散风险不进资本成本，消除它不创造价值；② 看投资者是不是冲着这个敞口来的（金矿/油公司套保反而让投资者难以判断）；③ 看结构性错配——喜力（荷兰生产、全球销售）汇率风险远大于本地化生产的啤酒商，该套保的是喜力不是别人。另注意套保通常只能覆盖 12–18 个月，且占用抵押品、放弃上行。"
V3_exclusivity:
  passed: true
  why_not_common: "常识把波动当风险、把消除波动当风险管理。本书分离'总量'与'价格'，指出多数可分散风险不值得花钱消除；并用核电案例给出真正的红线——不是波动大小，而是最差结果会不会危及存续（负溢出）。"
→ 进入阶段 2（router）
```

## R8 · 资本结构与财务弹性

```yaml
id: cap.value.capital-structure
slug: capital-structure-resilience
merged_from: [f45, f46, f47, p91, p92, p93, p94, p95, p96, p97, x02, x23]
supporting_cases: [c40, 化学制品/纸制品反周期投资案例]
V1_cross_domain:
  passed: true
  evidence:
    - 第15章 图15.1: 杠杆双向放大（无债 ±10%；50% 债 → +16%/−24%）
    - 第15章 图15.2: BBB–A 级区间内（利息覆盖 4.5–10 倍）价值差异 <10% — 优化空间有限
    - 第15章: 2008—2009 信用危机中低投资级债务无法滚动
    - 第15章: 周期性行业反周期资本结构（别人不能投时你能投）
    - 第15章: IBM 5 年 FCF 550 亿、返还股东 610 亿
V2_predictive_power:
  passed: true
  novel_question: "投行建议公司加杠杆到净负债/EBITDA 5x 以回购股票、增厚 EPS，该支持吗？"
  derived_answer: "不支持。三条检查：① 是否掉到投资级以下（书中底线 BBB+，掉下去会有条款限制且危机时无法再融资）；② 债务的节税价值在 BBB–A 区间内很小（覆盖 4.5x 与 10x 的价值差 <10%），远小于失去灵活性的代价；③ 周期性行业应反周期——在底部有弹药才能投，满杠杆会在最坏时刻失去选择权。杠杆不是价值创造工具，只是收益放大器和风险放大器。"
V3_exclusivity:
  passed: true
  why_not_common: "常识追求'最优资本结构'与'税盾最大化'。本书反直觉地指出：正确结构不创造多少价值，错误结构毁灭巨大价值；因此目标不是最优而是'够用+有弹性'，且周期性行业要主动保守。"
→ 进入阶段 2（router）
```

## R9 · 绩效指标 + 健康指标与组织颗粒度

```yaml
id: cap.value.performance-health
slug: performance-health-metrics
merged_from: [f48, f49, f50, f52, p98, p99, p100, p101, p102, p103, p104, p105, p106, p107, p108, p109, x16]
supporting_cases: [c41, 某业务部门靠涨价+砍广告维持利润最终丢失份额案例, 可再生能源研发被砍案例]
V1_cross_domain:
  passed: true
  evidence:
    - 第17章: 某部门四年高利润高 ROIC，实则靠涨价+砍广告，份额持续流失后发现已晚
    - 第17章 图17.1: 绩效指标 + 短/中/长期 + 组织健康 五类指标体系
    - 第17章: 10 亿美元以上公司应拆 20–50 个执行单位（可再生能源技术案例）
    - 第16章 图16.2: 全食品按店龄披露 ROIC（78%→−2%）
    - 第16章: 可口可乐 2002 停止季度 EPS 指引，股价稳定
V2_predictive_power:
  passed: true
  novel_question: "某公司连续 8 个季度利润与 ROIC 双升，为什么反而要警惕？"
  derived_answer: "财务结果是滞后指标。必须问'这些数字是怎么达成的'：涨价的份额代价、砍营销/研发的未来代价、压货的渠道代价。书中案例正是'利润与 ROIC 上升的同时份额在流失'。健康指标（份额/溢价能力、品牌力与客户满意度、成本结构、资产健康、长期战略健康、组织健康）就是用来提前暴露这一点的。另：若公司披露颗粒度到业务单元/店龄（全食品式），可信度显著更高。"
V3_exclusivity:
  passed: true
  why_not_common: "常识用财务结果评价公司质量。本书要求结果指标必须配'健康指标'，并给出 8 类通用类别与'20–50 个核算单元'的组织前提；关键反直觉点：对高绩效部门要像对困境部门一样质疑。"
→ 进入阶段 2（router）
```

---

## 合并映射总表

| 能力 | slug | 并入的框架 | 并入的原则 |
|---|---|---|---|
| P1 | roic-growth-value-core | f01–f05 | p04–p07, p09, p10, p110 |
| P2 | implied-expectations-reverse-dcf | f08, f09, f11 | p18–p22, p24, x20, x21 |
| P3 | roic-competitive-advantage-decomposition | f25–f28 | p54–p64 |
| P4 | growth-quality-ladder | f29–f32 | p08, p10, p65–p69 |
| P5 | valuation-multiple-traps | f51 | p111–p113 |
| P6 | value-conservation-test | f06, f07 | p11–p17, x01, x02, x04, x06, x07, x23 |
| P7 | ma-value-creation-assessment | f37–f40 | p77–p82, x05, x12, x22 |
| R1 | market-valuation-drivers | f18–f20 | p34–p37 |
| R2 | trs-driver-decomposition | f10 | p22, p23 |
| R3 | investor-typology-pricing-power | f15–f17 | p31–p33 |
| R4 | bubble-vs-crisis-diagnosis | f21, f22 | p38–p43, x03, x11, x17, x25 |
| R5 | earnings-expectations-relevance | f23, f24 | p44–p53, x08, x18, x19 |
| R6 | best-owner-and-divestiture | f12–f14, f33–f35 | p25–p30, p70–p76, x10, x13, x22 |
| R7 | risk-total-vs-price | f41–f44 | p83–p90, x14, x15 |
| R8 | capital-structure-resilience | f45–f47 | p91–p97, x02, x23 |
| R9 | performance-health-metrics | f48–f50, f52 | p98–p109, x16 |

**统计**：52 框架 + 113 原则 + 25 反例 = 190 条原始候选 → 合并为 16 个能力（通过率 100%，因合并阶段已把弱候选并入强候选而非单列）；41 案例 + 40 术语作为素材库（A1 / GLOSSARY）不参与能力计数。

---

## 淘汰与降级（写入 `rejected/`）

| 候选 | 未通过项 | 原因 |
|---|---|---|
| 「长期股东价值与就业/研发正相关」（p01） | V3 | 属立场辩护，非方法论；作为 P1 的背景注释保留 |
| 「价值管理需要勇气与独立性」（前言/p03 部分） | V2 | 无法推出非平庸结论，属价值主张 |
| 「利益相关者/ESG 与社会价值」（第1章） | V3 + V2 | 作者仅辩护性回应，未纳入估值框架，无法外推 → 写入阶段 0 批判，不成能力 |
| 「IR 操作细节：CEO/CFO 时间分配、卖方分析师取舍、指引话术」（第16章大部分） | V1（使用场景单一） | 面向管理层而非分析师；仅保留"放弃 EPS 指引、改给价值驱动区间"一条并入 R9 |
| 「薪酬与董事会治理设计」（第17章） | V1 | 使用场景单一，对证券研究价值低；仅保留"绝对 vs 相对 TRS"一条并入 R2 |
| 「1960–2009 美股五时期历史叙述」（第7章） | V3 | 叙述性内容，非方法论 → 降为 R1 的 A1 案例 |
| 「郁金香泡沫 / 非股市资产泡沫」（第8章） | V2 | 无内在价值锚，无法外推到股票分析 → 降为 R4 的对比说明 |
| 「汇总战略 / 转换合并 / 改善竞争行为」（f39 部分） | V2 | 作者明示"很少成功、难以执行" → 降为 P7 的 B 段警示 |
| 「水平 1/2/3 增长管道」（f34/p76） | V3 | 通用战略常识（三层面增长），作者未加独特约束 → 降为 R6 的补充步骤 |

---

## ✅ 用户轻确认

**16 个能力进入阶段 2；其中 7 个晋级为独立 Skill（P1–P7），9 个经来源路由入口访问（R1–R9）。**
