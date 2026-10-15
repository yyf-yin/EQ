# 维护与验收

在工作区运行 `python maintenance/validate_skills.py`。脚本仅依赖 Python 标准库，检查入口的受限 YAML 格式、名称/描述、JSON、相对文件链接、独立入口与路由卡同步、测试副本和数值期望。当前入口采用简单键值、JSON 字符串和一层 metadata；脚本不是通用 YAML 解析器。skill-creator 的 quick_validate.py 因环境缺少 PyYAML 未运行。

`research-acceptance-cases.json` 是 20 个跨书/边界行为验收任务，含 8 个可复算的数值期望。算术期望校核只检查验收标准自洽，不执行 skill、工具或模型。

接入实际 agent 后，使用完整 skill 和可得工具运行这些任务，保存输入、输出、模型/配置及截止日期；按 expect/forbid 审核结果，再复跑原有触发套件。只在取得实际输出后记录行为通过率。测试采用同一资料和运行设置对比调整前后，以判断是否改善研究质量。

两套原有 123 个触发用例已同步到 0.2.0。历史结果保留但不作为当前通过证明；新版模型触发、执行质量和接入效果尚未验证。

`revision-files.json` 保存修改前后摘要；两本书 BUILD_MANIFEST 的 published_hashes 保留原生成基线，local_revision 记录当前内容。重新蒸馏/编译时须合并本次适配，避免被旧规则覆盖。
