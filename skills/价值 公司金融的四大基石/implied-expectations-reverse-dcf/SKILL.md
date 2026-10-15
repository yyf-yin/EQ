---
name: implied-expectations-reverse-dcf
description: "从当前价格反推长期增长、利润率、回报和优势持续期的条件组合，判断估值隐含预期时使用。明确 FCFF/经营价值与 FCFE/股权价值桥接；不使用固定 80% 价格合理先验，也不解释日内盘口。"
metadata:
  cangjie.generated-by: "cangjie-tools v2.5.0"
  cangjie.capability-id: "cap.value.implied-expectations"
  cangjie.capability-revision: 2
  cangjie.bundle-id: "bundle.value-four-cornerstones"
  cangjie.source-title: "价值：公司金融的四大基石（修订本）"
  cangjie.tags: "valuation, expectations, reverse-dcf, equity-research"
  local.review-date: "2026-10-06"
  local.adaptation: "industry-company-research"
---
# 逆向 DCF 与条件隐含预期

## 执行

1. 固定估值日、价格、总股本/稀释口径、币种、现金与债务、非经营资产和其他请求权。不能用自由流通市值代替全部普通股权益；存在多类股时按各类经济权利分别处理。
2. 先选择模型：FCFF/WACC 得到经营资产价值 V_op；FCFE/股权成本 Ke 得到普通股价值。合并 FCFF 与少数股东、租赁、优先股等处理一致。桥接为 `普通股价值 = V_op + 非经营资产 − 债务 − 少数股东价值 − 其他请求权`，超额现金计入非经营资产，避免净债务与现金重复计算。不能直接令 V_op 等于股票市值。
3. 建显式预测与终值，固定其余参数后扫描增长、利润率、新增回报或持续期的多组组合，反解目标价值。两个单变量解仅是两点，不冒称完整曲线；无解、多解或边界解均报告。永续 g 低于相应折现率，高增长不作永久值。
4. 固定 NOPLAT_1、稳定 R 等条件时可用 `V_op = NOPLAT_1 × (1 − g/R)/(WACC − g)`。每次改变 g 都重新检查利润率、再投资与 NOPLAT 时间口径；不能把模型条件数当真实可观察市场信念。
5. 用市场规模、份额/产能、历史及可比公司检验组合，做 WACC/Ke、终值和优势持续期敏感性。不预设 80% 股票价格合理；说明何种证据支持或反驳各组假设。
6. 输出条件假设网格、价值桥接、可实现性、预期差方向及验证指标。公司好不代表价格有吸引力，但没有可靠模型时不能给精确隐含 g。

## 受限情况

暂时负现金流不自动排除 DCF；有可靠盈利路径和融资假设时用分阶段情景。早期模式不明时给条件区间/可比定位并说明识别不足。合理定价下普通股回报的要求对应 Ke，不能用 WACC 代替。估值诊断不自动构成推荐或择时。

## 证据与交接

保留研究对象、市场与截止日期、指标期间/单位/币种/会计口径、来源及页码或链接，区分实际值、他人预测和自己的假设；输出结论、反证、置信度理由、缺口与下一步。权威原始披露可以作为事实来源；重大推断按重要性寻找独立证据，转载同一消息不算第二源。资料不足时交付可支持的部分并标记未验证，不虚构数据或执行结果。

相邻能力用于分工；未安装时沿用本卡方法、记录缺口，不因缺少其他 skill 而拒绝整个任务。只在当前任务需要时读取背景材料；书中历史统计与建议数量不作为当前市场的通用阈值。

## 来源背景

需要原书案例和章节位置时读取 [references/background.md](references/background.md)。计算与执行规则已作行研适配；补充校核来源见下方（如有）。

口径校核：[CFA Institute 自由现金流估值](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/free-cash-flow-valuation)。
