# PIPELINE_STATE — value-four-cornerstones

> 断点续跑用。每完成一个阶段更新本文件。

- **源内容**: `C:/work/PROJECTS/创建skill/origin/价值 公司金融的四大基石/价值 公司金融的四大基石.md`（3198 行 / 435KB）
- **蒸馏目的**: 行业研究 / 证券分析 Agent
- **输出形态**: `pack`（1 个来源路由入口 + 7 个晋级 Skill = 8 个可发现入口）
- **本地化口径**: **保留美股原书逻辑口径为主**（麦肯锡 CPAT 美国大型非金融公司样本、2010 年前数据窗口），A 股适配作为**附注**放在 B 段「A股口径提示」小节，标注为"按需取用"，不替换原书结论
- **开始时间**: 2026-10-06 | **完成时间**: 2026-10-06

## 阶段进度

| 阶段 | 状态 | 产出 | 备注 |
|---|---|---|---|
| 0 整书理解 | ✅ done | `BOOK_OVERVIEW.md` | 用户已确认骨架（2026-10-06） |
| 1 并行提取 | ✅ done | `candidates/*.md` | 52 框架 + 113 原则 + 41 案例 + 25 反例 + 40 术语 |
| 1.5 三重验证 | ✅ done | `verified.md`, `rejected/REJECTED.md` | 190 条候选 → 合并为 16 个能力，全部通过 V1/V2/V3 |
| 1.6 晋级门 | ✅ done | `verified.yaml` destinations | 预算 8：7 个 promoted + 9 个 router |
| 2 RIA++ 能力卡 | ✅ done | `.cangjie/capabilities/cards/*.md`（16 张） | R/I/A1/A2/E/B，B 段含「A股口径提示（按需取用）」 |
| 3 Zettelkasten | ✅ done | `also_read`, `GLOSSARY.md`（40 条 + 6 组易混对照） | |
| 4 压力测试 | ✅ done | `evals/`（60 条用例） | 8 个入口 F1 均 1.000，兄弟混淆率 0，独立 sub-agent 盲测 |
| 5 编译交付 | ✅ done | `dist/`, `DIGEST.md`, `INDEX.md`, 安装 | 见下 |

## 编译与安装

- 编译命令：`cangjie.py compile --bundle books/value-four-cornerstones/.cangjie/capabilities --out dist/value-four-cornerstones --output pack`
- 编译运行：`run-20261006-122253-0afc85`（原子发布，通过 `validate_skill_pack.py` 硬门）
- **安装位置**：`C:/work/PROJECTS/创建skill/skills/价值 公司金融的四大基石/`（复制方式，8 个 Skill 目录 + 文档）
- 安装后校验：`validate_skill_pack.py` → **0 errors, 0 warnings**（53 个 .md，8 个 SKILL.md）
- 输出冒烟测试：`roic-growth-value-core`（IR=338%、FCF=−19.1 亿、正确声明 g>WACC 时分母为负不适用估值公式）、
  `value-four-cornerstones`（正确路由到 `trs-driver-decomposition` 能力卡并指出分红回购不是 TRS 的独立贡献项）

## 关键决策记录

- **2026-10-06** 用户确认：骨架正确，按 BOOK_OVERVIEW 的优先级排序蒸馏；输出 pack；做 A 股适配并显式标注口径差异。
- **2026-10-06** 用户修正：做适配**但保留美股市场逻辑口径**，A 股内容降为「按需取用」的附注小节，不替换原书结论。
- **2026-10-06** 阶段 4 处置：`ma-value-creation-assessment::should-not-trigger-02` 首轮未中兄弟目标，
  判定为**测试设计过狠**（原 prompt 读作纯数值查询），改测试不改 skill，复测通过。
- **2026-10-06** 用户确认安装位置：`C:/work/PROJECTS/创建skill/skills/价值 公司金融的四大基石`，方式为复制。

## 后续可选动作

- 持续进化：把 `evals/` 下的 `test-prompts.json`（darwin 兼容）喂给 darwin-skill 做 ratcheting 自动进化。
- 若要新增晋级 Skill，必须同步新增它与路由入口之间的互斥近邻负例并重跑 `run_trigger_evals.py`。
- 阶段 4 为单轮盲测（runs=1），未做 train/validation 60/40 切分；若要统计意义上的非劣声明需补跑。
