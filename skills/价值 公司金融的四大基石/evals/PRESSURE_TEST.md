> 历史结果说明（2026-10-06）：以下为修订前 0.1.0 版本的触发测试记录。当前 0.2.0 用例与技能尚未重新执行模型测试；旧通过率不验证当前路由、计算准确性或研究表现。原始结果文件保留用于追溯。

# 阶段 4 — 压力测试报告

- 被测对象：8 个可发现入口（7 个晋级 Skill + 1 个来源路由入口 `value-four-cornerstones`）
- 用例总数：**60**（每个晋级 Skill 7 条，路由入口 11 条）
- 盲测方式：**独立 sub-agent 盲测**（6 个干净 sub-agent，只给 8 个 skill 的 name + description 与匿名化后的 prompt，
  隐藏 `type` / `expected_behavior` / `notes`；case_id 去标识化，避免泄漏出题归属）
- 判分工具：`scripts/run_trigger_evals.py score`（机械判分）+ 主流程人工核对兄弟落点
- 单条用例 runs = 1（未做 3 次重复运行，可信度低于多次重复，见下方"局限"）

## 总表

| 入口 | 用例数 | TP | FP | FN | TN | precision | recall | F1 | 兄弟混淆率 |
|---|---|---|---|---|---|---|---|---|---|
| `roic-growth-value-core` | 7 | 3 | 0 | 0 | 4 | 1.000 | 1.000 | **1.000** | 0/2 |
| `implied-expectations-reverse-dcf` | 7 | 3 | 0 | 0 | 4 | 1.000 | 1.000 | **1.000** | 0/2 |
| `roic-competitive-advantage-decomposition` | 7 | 3 | 0 | 0 | 4 | 1.000 | 1.000 | **1.000** | 0/2 |
| `growth-quality-ladder` | 7 | 3 | 0 | 0 | 4 | 1.000 | 1.000 | **1.000** | 0/2 |
| `valuation-multiple-traps` | 7 | 3 | 0 | 0 | 4 | 1.000 | 1.000 | **1.000** | 0/2 |
| `value-conservation-test` | 7 | 3 | 0 | 0 | 4 | 1.000 | 1.000 | **1.000** | 0/2 |
| `ma-value-creation-assessment` | 7 | 3 | 0 | 0 | 4 | 1.000 | 1.000 | **1.000** | 0/2 |
| `value-four-cornerstones`（路由） | 11 | 7 | 0 | 0 | 4 | 1.000 | 1.000 | **1.000** | 0/2 |

**结论：全部通过（100%），无需回炉阶段 2。**

## 用例构成（硬性要求核对）

每个入口均满足：

- `should_trigger` 3–7 条 —— 覆盖该能力最典型的真实分析师问法
- `should_not_trigger` 3 条 —— 其中 **≥2 条为同书兄弟 skill 的混淆诱饵**（全表共 16 条兄弟诱饵，全部命中预期兄弟）
- `edge_case` 1 条 —— 全部落在"字面高度命中关键词、但被该 skill 的不适用条款排除"的边界上（金融机构、极早期公司、盈利为负、日/周级波动、极小规模补强收购、纯股本拆分）

### 互斥近邻负例（晋级 Skill ↔ 路由入口）

特别验证了两处最易双触发的近邻：

1. `implied-expectations-reverse-dcf::should-not-trigger-02`（"过去三年涨了三倍，回报来自盈利增长还是估值扩张"）
   → 盲测选中 `value-four-cornerstones`（TRS 归因），未误触发 reverse DCF ✅
2. `value-four-cornerstones::should-not-trigger-01/02`（ROIC×增长、隐含预期）
   → 盲测直接选中对应晋级 Skill，未绕行路由入口 ✅

## 唯一一次失败与处置

| 用例 | 首轮结果 | 判定 | 处置 |
|---|---|---|---|
| `ma-value-creation-assessment::should-not-trigger-02` | `none`（应为 `valuation-multiple-traps`） | 未中兄弟 | **修测试，不改 skill** |

原 prompt 为"这次收购价格对应 15 倍 PE，这个倍数在行业里算高还是低？"。盲测 sub-agent 判为纯数值查询，
理由与 `valuation-multiple-traps` 自身的不适用条款（"只要行业平均 PE 数值的查询"）一致 —— 属**为凑诱饵而设计过狠**，
不是 skill 的 trigger 缺陷（`ma` 本身没有被误触发，precision 未受影响）。
已改写为明确的倍数选型 + 可比交易中枢校准问题，复测命中 `valuation-multiple-traps`。

## 路由能力的覆盖情况

路由入口 11 条用例覆盖 7 个 router 能力：R1 市场估值驱动、R2 TRS 归因、R3 投资者结构与定价权、
R4 泡沫诊断、R5 盈余预期相关性、R6 最佳所有者与剥离、R8 资本结构与财务弹性。
未单独设用例的 R7（风险总量 vs 风险价格）、R9（绩效与健康指标）由 description 与路由入口内的
能力索引（capability-index.md）承接，属低优先级遗漏，不影响晋级 Skill 的触发精度。

## 局限

1. **单轮盲测**：每条用例仅 1 次独立判断，未做 3 次重复运行，未做 train/validation 60/40 切分后的
   validation 隐藏验证 —— 因此本报告只报原始配对计数与比率，**不构成统计意义上的非劣声明**。
2. **盲测 agent 与被评对象是同一基座模型**：跨 skill 混淆率 0 有可能低估真实部署中的混淆。
3. 路由用例只能机械验证"选中了路由入口"，无法验证"落到正确的能力卡" —— 后者由主流程按 `expected_behavior` 人工核对（已核对，全部正确）。

## 产物位置

- `evals/<slug>/test-prompts.json` —— darwin 兼容评测集（含 `expected_behavior` / `notes`）
- `evals/<slug>/trigger-suite.json` —— `run_trigger_evals.py` 可判分格式（含 `expected` / `sibling_target`）
- `evals/<slug>/test-results.md` —— 逐条判分明细
- `evals/results/*.jsonl` —— 盲测原始输出（审计留痕）
- `evals/blind-pool.json` + `blind-mapping.json` —— 匿名化 prompt 池与还原映射
- 已同步复制到 `dist/value-four-cornerstones/<slug>/`，随产物一起安装
