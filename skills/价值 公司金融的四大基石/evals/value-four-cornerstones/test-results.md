> 历史结果说明（2026-10-06）：以下为修订前 0.1.0 版本的触发测试记录。当前 0.2.0 用例与技能尚未重新执行模型测试；旧通过率不验证当前路由、计算准确性或研究表现。原始结果文件保留用于追溯。

# 触发评测判分 — value-four-cornerstones

- runs: 11（TP 7 / FP 0 / FN 0 / TN 4）
- precision 1.000 / recall 1.000 / **F1 1.000**
- 兄弟混淆率: 0.000（0/2）

| case | expected | selected | 判定 |
|---|---|---|---|
| value-four-cornerstones::should-trigger-02#r1 | should_trigger | value-four-cornerstones | TP |
| value-four-cornerstones::should-not-trigger-03#r1 | should_not_trigger | none | TN |
| value-four-cornerstones::should-trigger-03#r1 | should_trigger | value-four-cornerstones | TP |
| value-four-cornerstones::edge-01#r1 | edge_case | none | TN |
| value-four-cornerstones::should-trigger-04#r1 | should_trigger | value-four-cornerstones | TP |
| value-four-cornerstones::should-not-trigger-01#r1 | sibling | roic-growth-value-core | OK |
| value-four-cornerstones::should-trigger-01#r1 | should_trigger | value-four-cornerstones | TP |
| value-four-cornerstones::should-not-trigger-02#r1 | sibling | implied-expectations-reverse-dcf | OK |
| value-four-cornerstones::should-trigger-05#r1 | should_trigger | value-four-cornerstones | TP |
| value-four-cornerstones::should-trigger-06#r1 | should_trigger | value-four-cornerstones | TP |
| value-four-cornerstones::should-trigger-07#r1 | should_trigger | value-four-cornerstones | TP |

> 本报告只给原始配对计数与比率；统计非劣需预注册界值 + McNemar/配对 Bootstrap（§10.3），不在此自动宣布。
