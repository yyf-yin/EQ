# 工程迁移与运行验证

验证日期：2026-10-09（Asia/Shanghai）。

## 迁移结果

- 来源聊天：`构建上市公司深度研究 Agent`，ID `01a11eb1-b166-7463-a104-49513d4113ca`。
- 原工程：`C:\Users\Cliff\Documents\Codex\2026-10-09\codex-company-deep-research-agent-0\outputs\company-deep-research`。
- 新工程：`C:\work\PROJECTS\eq_new`。前后端、文档、配置模板、本地资料、示例报告及运行产物直接放在此目录。
- 新目录原有 `prd.md` 与 `skills/` 已保留；原工程保留作为备份。
- 通过 SHA-256 校验 129 个未修改文件。排除可重建的依赖、缓存、构建结果；启动脚本、端口配置和 README 按新目录调整。
- 两个 SQLite 数据库通过只读连接和 SQLite backup API 取得一致快照，完整性检查均为 `ok`。迁移快照包含 11 条研究记录、833 个事件、11 份报告、9,026 条研究数据记录、649 个 LangGraph 检查点及 1,969 条检查点写入。原有下载文件也已复制。
- 在新目录重建 `.venv`，使用锁文件安装依赖，并将 `backend` 可编辑安装到此环境；前端执行 `npm ci`。已创建默认模拟模式的 `.env`。
- 后端启动脚本不再查找原工程的 `work/venv`。核验 Python 模块、数据库、资料、产物及模型配置路径均指向新目录。

## 当前服务与启动

原工程占用 `8000/5173`，新工程采用 `8001/5174`，两套服务可以同时运行。

- 网页：<http://127.0.0.1:5174>
- 后端健康接口：<http://127.0.0.1:8001/api/health>
- 当前前端代理指向 `8001`。

后续在两个 PowerShell 终端分别执行：

```powershell
cd C:\work\PROJECTS\eq_new
.\scripts\start_backend.ps1 -Port 8001
```

```powershell
cd C:\work\PROJECTS\eq_new
.\scripts\start_frontend.ps1 -Port 5174 -BackendPort 8001
```

当前服务日志位于 `work/backend.stdout.log`、`work/backend.stderr.log`、`work/frontend.stdout.log`、`work/frontend.stderr.log`，启动进程记录位于 `work/migration-services.json`。

## 实测结果

| 检查 | 结果 |
|---|---|
| 后端 pytest 回归 | 58 项通过，65.71 秒 |
| 前端 Vitest 交互测试 | 3 项通过 |
| Chrome 端到端测试 | 3 项通过，26.9 秒 |
| TypeScript 与 Vite 生产构建 | 通过 |
| Python pip check | 无依赖冲突 |
| 后端健康接口、前端页面、前端 API 代理 | 均正常，HTTP 200 |
| 模拟研究、SSE、刷新恢复、断线重连 | 通过 |
| 报告正文、目录、财务表格、失败安全显示 | 通过 |
| 迁移前报告与新报告下载 | DOCX ZIP 内容有效；PDF 均可解析为 16 页 |
| 迁移前报告与新报告 SSE 重放 | 支持 Last-Event-ID，完成事件正常 |

验证命令：

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q --basetemp=work/pytest-migration-full
.\.venv\Scripts\python.exe -m pip check
cd frontend
npm.cmd test
npm.cmd run build
$env:CDR_E2E_BASE_URL='http://127.0.0.1:5174'
npm.cmd run test:e2e
```

迁移快照清单见 `work/migration-manifest.json`；旧、新报告与目录路径的额外核验见 `work/migration-verification.json`。浏览器完成页面截图见 `frontend/test-results/completed.png`。

## 运行范围

目前实际验证的是无需密钥的 Mock 模拟流程，报告会明确显示合成数据和研究限制。真实模型、搜索服务及真实 A 股资料仍需配置并联调；本次迁移没有改变这一状态。配置方法见 `LLM_CONFIGURATION.md`。

## 2026-10-10 v1.1 原地升级

在迁移后的既有工程复用 LangGraph、Gateway、SQLite、数据适配、三表与导出完成架构升级，无数据库清空或旧报告替换。新增运行与报告规则 1.1；旧字段缺省为 1.0 并在前端标记。旧检查点保留，但不跨版本恢复，需新建研究；新版本检查点可正常继续。

验证使用 work/pytest-v11-*、work/v11-example、work/v11-e2e 隔离数据库与输出，浏览器验证服务使用 18101/15174；本次未重启既有 8001/5174 服务。旧 examples/reference_reports 保留，新样例写入 v1_1 子目录。代码更新后既有服务需在用户方便时按原启动方式重启才加载新实现。本目录没有 Git 元数据，本次没有提交或 PR。

最新测试、导出视觉检查和真实验收缺口见 [V1_1_ACCEPTANCE.md](V1_1_ACCEPTANCE.md)，不以历史 58 项测试替代新版本验收。
