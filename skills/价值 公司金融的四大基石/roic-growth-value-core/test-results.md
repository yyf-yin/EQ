> 历史结果说明（2026-10-06）：以下为修订前 0.1.0 版本的触发测试记录。当前 0.2.0 用例与技能尚未重新执行模型测试；旧通过率不验证当前路由、计算准确性或研究表现。原始结果文件保留用于追溯。

# 触发评测判分 — roic-growth-value-core

- runs: 7（TP 3 / FP 0 / FN 0 / TN 4）
- precision 1.000 / recall 1.000 / **F1 1.000**
- 兄弟混淆率: 0.000（0/2）

| case | expected | selected | 判定 |
|---|---|---|---|
| roic-growth-value-core::should-trigger-01#r1 | should_trigger | roic-growth-value-core | TP |
| roic-growth-value-core::should-not-trigger-03#r1 | should_not_trigger | none | TN |
| roic-growth-value-core::should-trigger-02#r1 | should_trigger | roic-growth-value-core | TP |
| roic-growth-value-core::edge-01#r1 | edge_case | none | TN |
| roic-growth-value-core::should-trigger-03#r1 | should_trigger | roic-growth-value-core | TP |
| roic-growth-value-core::should-not-trigger-01#r1 | sibling | implied-expectations-reverse-dcf | OK |
| roic-growth-value-core::should-not-trigger-02#r1 | sibling | growth-quality-ladder | OK |

> 本报告只给原始配对计数与比率；统计非劣需预注册界值 + McNemar/配对 Bootstrap（§10.3），不在此自动宣布。
