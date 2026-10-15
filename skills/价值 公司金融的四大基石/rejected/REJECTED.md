# rejected/ — 淘汰与降级清单（阶段 1.5 / 1.6 审计轨迹）

> 本目录记录**未通过三重验证（V1 跨域 / V2 预测力 / V3 独特性）或未通过晋级门**的候选。
> 保留它们的目的是让"为什么这本书只蒸馏出 16 个能力"这件事可追溯、可被事后质疑，而不是让结论看起来天衣无缝。
> 原始候选数：52 框架 + 113 原则 + 25 反例 = 190 条 → 合并为 16 个能力。

## 一、未通过验证 · 完全淘汰

| 候选 | 未通过项 | 原因 | 去向 |
|---|---|---|---|
| 「长期股东价值与就业/研发正相关」（p01） | V3 | 属立场辩护，非方法论 | 作为 P1 的背景注释保留 |
| 「价值管理需要勇气与独立性」（前言 / p03 部分） | V2 | 无法推出非平庸结论，属价值主张 | 不进产物 |
| 「利益相关者 / ESG 与社会价值」（第 1 章） | V3 + V2 | 作者仅做辩护性回应，未纳入估值框架，无法外推 | 写入阶段 0 批判与 DIGEST「作者的局限」，不成能力 |

## 二、未通过验证 · 降级为素材

| 候选 | 未通过项 | 原因 | 去向 |
|---|---|---|---|
| 「IR 操作细节：CEO/CFO 时间分配、卖方分析师取舍、指引话术」（第 16 章大部分） | V1（使用场景单一） | 面向管理层而非分析师 | 仅保留"放弃 EPS 指引、改给价值驱动区间"一条并入 R9 |
| 「薪酬与董事会治理设计」（第 17 章） | V1 | 使用场景单一，对证券研究价值低 | 仅保留"绝对 vs 相对 TRS"一条并入 R2 |
| 「1960–2009 美股五时期历史叙述」（第 7 章） | V3 | 叙述性内容，非方法论 | 降为 R1 的 A1 案例 |
| 「郁金香泡沫 / 非股市资产泡沫」（第 8 章） | V2 | 无内在价值锚，无法外推到股票分析 | 降为 R4 的对比说明 |
| 「汇总战略 / 转换合并 / 改善竞争行为」（f39 部分） | V2 | 作者明示"很少成功、难以执行" | 降为 P7 的 B 段警示 |
| 「水平 1/2/3 增长管道」（f34 / p76） | V3 | 通用战略常识（三层面增长），作者未加独特约束 | 降为 R6 的补充步骤 |

## 三、通过验证但未晋级（destination = router）

9 个能力单元通过 V1/V2/V3，但**未通过晋级门五判据**（其中 `independent_intent` 或 `independent_reuse` 为 false），
因此不成为独立 Skill，而是作为能力卡保留在来源路由入口 `value-four-cornerstones` 内：

| capability_id | slug | 未通过的判据 |
|---|---|---|
| cap.value.market-valuation-drivers | market-valuation-drivers | independent_intent: false, independent_reuse: false |
| cap.value.trs-driver-decomposition | trs-driver-decomposition | independent_intent: false, independent_reuse: false |
| cap.value.investor-typology-pricing-power | investor-typology-pricing-power | independent_intent: false, independent_reuse: false |
| cap.value.bubble-vs-crisis-diagnosis | bubble-vs-crisis-diagnosis | independent_intent: false, independent_reuse: false |
| cap.value.earnings-expectations-relevance | earnings-expectations-relevance | independent_intent: false, independent_reuse: false |
| cap.value.best-owner-and-divestiture | best-owner-and-divestiture | independent_intent: false, independent_reuse: false |
| cap.value.risk-total-vs-price | risk-total-vs-price | independent_intent: false, independent_reuse: false |
| cap.value.capital-structure-resilience | capital-structure-resilience | independent_intent: false, independent_reuse: false |
| cap.value.performance-health-metrics | performance-health-metrics | independent_intent: false, independent_reuse: false |

**说明**：这些不是"差一点"的能力。它们各自有独立契约、可独立运行、可独立评测，
但在真实分析师工作流中**几乎总是被某条更基础的问题触发**（例如"要不要上调长期看法"会先触发隐含预期分析），
独立成 Skill 会与已晋级的 7 个 Skill 抢调用，因此收在路由入口内由 `capability-index.md` 索引。

## 四、形式约束导致的取舍

- 可发现入口软预算默认 **8**（1 个路由入口 + 7 个晋级 Skill）。在用户已确认 pack 形态的前提下，
  这个预算不是硬上限，但继续晋级会显著增加跨入口混淆风险——阶段 4 已用 60 条用例验证当前 8 入口的混淆率为 0。
- 若未来要新增晋级 Skill，必须同步新增该 Skill 与路由入口之间的互斥近邻负例，并重跑 `run_trigger_evals.py`。
