<!-- 上半：产品发布说明（GitHub / 对外口径）；下半：工作区长效记忆归档，规格以 README.md 与源码为准。 -->

<div align="center">

# 🜂 Scream-Code

**One terminal. One command. Local-first AI that actually ships.**

*纯本地优先 · 可编辑安装 · 极客向 TUI —— REPL、工具、记忆与视觉同一流水线。*

[![License](https://img.shields.io/badge/license-MIT-blue.svg?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-3776AB?style=flat-square&logo=python&logoColor=white)]()

</div>

---

## 🚀 The Magic Install · 一键开箱

**你唯一需要记住的安装动作：在仓库根目录执行**

```bash
chmod +x install.sh && ./install.sh
```

脚本会替你做完一整套「脏活累活」，用炫彩终端输出告诉你每一步在干什么：

| 阶段 | 行为 |
|------|------|
| 🐍 **环境探针** | 校验 `python3`（≥3.10）与 `python3 -m pip`，不满足则给出可复制的修复提示 |
| 📦 **隔离安装** | 自动创建/复用项目内 **`.venv`**，安装依赖、`pip install -e .`，避免污染系统 Python（兼容 PEP 668） |
| 👁️ **视觉内核** | 拉取 **Playwright Chromium**；若网络偶发失败，会降级为警告并提示手动补装 |
| 📁 **用户沙箱目录** | 创建 `~/.scream/skills`、`~/.scream/screenshots` |
| ✨ **首次启动** | 安装结束后 **直接 `exec` 启动 `scream`**，进入首次配置向导或主界面 |

> **产品话术**：这不是「下载完还要读十页 README」——这是 *Run one script, get a working neural terminal.*

---

## 🎛️ One Command to Rule Them All · 极简路由

**Setuptools 只注册一个全局入口：`scream`。**

| 你敲的 | 发生什么 |
|--------|-----------|
| `scream` | 检测大模型侧是否就绪（API Key 等）→ 未配置则走 **交互引导** → 直接进入 **Python TUI 主循环** |
| `scream config` | **强制**打开模型 / 密钥完整菜单；结束后可选择是否进入 TUI |
| `scream help` | 极客风 ASCII 帮助页 |

### 🔐 配置与仓库彻底脱钩：`~/.scream`

- **`~/.scream/llm_config.json`** — 多模型档案、当前激活项、沙箱/越狱开关等  
- **`~/.scream/.env`** — API Key 等敏感变量（安装脚本也会初始化用户目录结构）  
- **首次使用**若仓库里还躺着旧版根目录 `llm_config.json` / `.env`，会 **自动迁移** 到 `~/.scream`，避免误提交、误覆盖

> **产品话术**：你的密钥和模型配置住在 **用户主目录**，不是某个 `git clone` 的临时文件夹里。换项目、换目录，`scream` 仍然认得你。

**PATH 提示**：安装完成后可直接使用 `.venv/bin/scream`，或将 `.venv/bin` 加入 `PATH` 后随处执行 `scream`。

**进阶**：移植镜像子命令仍可通过 `python3 -m src.main …` 调用（CI / 脚本友好）。

---

## 💻 Ultimate TUI · 终极终端体验

面向 **prompt_toolkit + Rich** 的纯 Python 路径，规避部分平台原生 PTY 的坑，把「像在 IDE 里聊天」搬进终端。

| 能力 | 说明 |
|------|------|
| ⌨️ **打字机流式** | 模型输出经 **节流 + Rich `Live` 自动刷新**，避免整屏卡顿或「一次性吐完」；流式区 **尾部视口** 裁剪，scrollback 不乱跳、观感更稳 |
| 🪟 **防抖动视窗** | 未闭合 Markdown 代码围栏在渲染前 **软闭合**，避免 Pygments / Markdown 结构中途崩塌 |
| 📊 **全局状态仪表盘** | 底部 **神经状态栏**：当前模型、沙箱模式、记忆条目、Token 占用等 **一屏可读**；流式生成时在 `Live` 内同步叠加热力图式页脚，与输入态信息同源 |

**斜杠宇宙**：`/help`、`/look`、`/sandbox`、`/memory`、`/diff`、`/cost` … 补全菜单下 **Enter 只确认补全**，不误提交整行。

---

## 🧱 四大引擎（速览）

| 支柱 | 要点 |
|------|------|
| 🔌 **Skill Registry** | `BaseSkill` + `~/.scream/skills/` 热插拔；`/help` 与补全动态反映注册表 |
| 🛡️ **Docker Sandbox** | `/sandbox on` — 终端执行进容器，挂载 `/workspace` |
| 🧠 **Core Memory** | `SCREAM.md` 叙事 + 规则；工具与 **`/memory`** 运维 |
| 👁️ **Playwright Vision** | **`/look <url>`** 截图 + 多模态；与安装脚本中的 Chromium 初始化联动 |

---

## 📋 斜杠指令速查

| 指令 | 说明 |
|------|------|
| `/help` | 分组帮助 |
| `/team` / `$team …` | 群狼编排 |
| `/look <url> [说明]` | 网页截图 → 模型「看见」UI |
| `/sandbox` | `on` / `off` / `status` |
| `/memory` | `list` · `set` · `drop` |
| `/diff` | Git 工作区摘要 |
| `/memo` `/summary` | 写入或提炼长效记忆 |
| `/new` `/flush` | 硬重置 / 轻量清空 |
| `/sessions` `/load` | 会话存档 |
| `/stop` `/cost` `/doctor` `/status` | 中断 / 账单 / 体检 / 状态 |
| `/config` `/skills` | 配置 JSON / 技能图谱 |
| `/audit` `/report` `/subsystems` `/graph` | 开发者向硬核命令 |

---

> **以下章节为工作区长效记忆与历史归档**（用户偏好、技能交付物、`/summary` / `/memo` 快照等），**不是**产品规格的唯一事实来源；**对外规格以 `README.md` 与源码为准。**

---

## 项目核心记忆（尖叫 Code）

### 用户技术偏好（摘录）
- **输出格式**：单文件 HTML 网站  
- **风格定位**：赛博朋克 / 科技炫酷，深色 + 霓虹渐变  

### Skills · 地理素材核查助手-by李李老师（2026-04-11）
- **路径**：`skills/地理素材核查助手-by李李老师/`（`geo_fact_checker_by_lili.py`、`requirements.txt`、`README.md`）  
- **能力**：陈述提取、多源检索（DuckDuckGo）、权威性权重、客观率、Markdown 报告  

### 尖叫 REPL · 设计与偏好（摘录）
- 网站风：深色底、靛蓝主色、Inter / JetBrains Mono  
- 技术栈偏好：Rust 2021 edition、TypeScript 等（见历史 memo）  

### 最近更新（2026-04-11 摘录）
- 移除 `remotion_skill.py`；地理技能重命名与跨平台文档；打包 zip 交付  

### 长效记忆库 · `/memo`（2026-04-12 合并去重）
- 偏好与技术栈备注已合并；重复条目已清理。  
- Python 编码规范等团队约定若有变更，以仓库当前 `CLAUDE.md` / 代码审查为准。  

### 长效记忆库 · `/summary`（历史快照）
- 历史 `/summary` 大块清单与镜像命令/工具枚举已从本页移除，避免与当前 `src/` 树漂移；需要时可从会话落盘或重新执行 `python3 -m src.main summary` 生成最新摘要。

---

*Scream-Code — ship fast, stay local, look cool in the terminal.* 🜂
---

## 长效记忆库 · 尖叫 REPL（`/memo` · 2026-04-12 17:21）

- 偏好 A
---

## 长效记忆库 · 尖叫 REPL（`/memo` · 2026-04-13 14:02）

- 偏好 A
---

## 长效记忆库 · 尖叫 REPL（`/memo` · 2026-04-14 12:35）

- 偏好 A

- **用户称呼**：老师（从 2026-04-15 起生效）
---

## 长效记忆库 · 尖叫 REPL（`/memo` · 2026-04-15 10:42）

（本轮无项目级长效要点）
---

## 长效记忆库 · 尖叫 REPL（`/summary` · 2026-04-15 10:42）

### /summary 快照

```
# Python 移植工作区摘要

移植根目录: `/Users/tod/Desktop/ScreamCode/src`
Python 文件总数: **105**

顶层 Python 模块:
- `skills` (10 个文件) — Python 移植支撑模块
- `agent` (3 个文件) — Python 移植支撑模块
- `ui` (2 个文件) — Python 移植支撑模块
- `constants` (2 个文件) — Python 移植支撑模块
- `utils` (2 个文件) — Python 移植支撑模块
- `services` (2 个文件) — Python 移植支撑模块
- `projectOnboardingState.py` (1 个文件) — Python 移植支撑模块
- `repl_ui_render.py` (1 个文件) — Python 移植支撑模块
- `query_engine.py` (1 个文件) — 移植编排摘要层
- `task.py` (1 个文件) — 任务级规划结构
- `sandbox_env.py` (1 个文件) — Python 移植支撑模块
- `ink.py` (1 个文件) — Python 移植支撑模块
- `message_prune.py` (1 个文件) — Python 移植支撑模块
- `repl_slash_commands.py` (1 个文件) — Python 移植支撑模块
- `cost_tracker.py` (1 个文件) — Python 移植支撑模块
- `tasks.py` (1 个文件) — Python 移植支撑模块
- `models.py` (1 个文件) — 共享数据类
- `query.py` (1 个文件) — Python 移植支撑模块
- `transcript.py` (1 个文件) — Python 移植支撑模块
- `llm_onboarding.py` (1 个文件) — Python 移植支撑模块
- `repl_slash_helpers.py` (1 个文件) — Python 移植支撑模块
- `bootstrap_graph.py` (1 个文件) — Python 移植支撑模块
- `execution_registry.py` (1 个文件) — Python 移植支撑模块
- `_archive_helper.py` (1 个文件) — Python 移植支撑模块
- `claw_config.py` (1 个文件) — Python 移植支撑模块
- `llm_settings.py` (1 个文件) — Python 移植支撑模块
- `tools.py` (1 个文件) — 工具积压元数据
- `browser_vision.py` (1 个文件) — Python 移植支撑模块
- `remote_runtime.py` (1 个文件) — Python 移植支撑模块
- `memory_store.py` (1 个文件) — Python 移植支撑模块
- `__init__.py` (1 个文件) — 包导出面
- `system_init.py` (1 个文件) — Python 移植支撑模块
- `tools_registry.py` (1 个文件) — Python 移植支撑模块
- `interactiveHelpers.py` (1 个文件) — Python 移植支撑模块
- `model_manager.py` (1 个文件) — Python 移植支撑模块
- `channel_tools.py` (1 个文件) — Python 移植支撑模块
- `costHook.py` (1 个文件) — Python 移植支撑模块
- `port_manifest.py` (1 个文件) — 工作区清单生成
- `agent_cancel.py` (1 个文件) — Python 移植支撑模块
- `runtime.py` (1 个文件) — Python 移植支撑模块
- `project_memory.py` (1 个文件) — Python 移植支撑模块
- `context_compressor.py` (1 个文件) — Python 移植支撑模块
- `deferred_init.py` (1 个文件) — Python 移植支撑模块
- `dialogLaunchers.py` (1 个文件) — Python 移植支撑模块
- `skills_registry.py` (1 个文件) — Python 移植支撑模块
- `QueryEngine.py` (1 个文件) — Python 移植支撑模块
- `scream_theme.py` (1 个文件) — Python 移植支撑模块
- `setup.py` (1 个文件) — Python 移植支撑模块
- `context.py` (1 个文件) — Python 移植支撑模块
- `llm_client.py` (1 个文件) — Python 移植支撑模块
- `command_graph.py` (1 个文件) — Python 移植支撑模块
- `tui_app.py` (1 个文件) — Python 移植支撑模块
- `direct_modes.py` (1 个文件) — Python 移植支撑模块
- `permissions.py` (1 个文件) — Python 移植支撑模块
- `prefetch.py` (1 个文件) — Python 移植支撑模块
- `tool_pool.py` (1 个文件) — Python 移植支撑模块
- `parity_audit.py` (1 个文件) — Python 移植支撑模块
- `session_store.py` (1 个文件) — Python 移植支撑模块
- `main.py` (1 个文件) — CLI 入口
- `commands.py` (1 个文件) — 命令积压元数据
- `Tool.py` (1 个文件) — Python 移植支撑模块
- `mcp_manager.py` (1 个文件) — Python 移植支撑模块
- `agent_tools.py` (1 个文件) — Python 移植支撑模块
- `replLauncher.py` (1 个文件) — Python 移植支撑模块
- `history.py` (1 个文件) — Python 移植支撑模块
- `assistant` (1 个文件) — Python 移植支撑模块
- `vim` (1 个文件) — Python 移植支撑模块
- `upstreamproxy` (1 个文件) — Python 移植支撑模块
- `migrations` (1 个文件) — Python 移植支撑模块
- `coordinator` (1 个文件) — Python 移植支撑模块
- `types` (1 个文件) — Python 移植支撑模块
- `native_ts` (1 个文件) — Python 移植支撑模块
- `bootstrap` (1 个文件) — Python 移植支撑模块
- `keybindings` (1 个文件) — Python 移植支撑模块
- `plugins` (1 个文件) — Python 移植支撑模块
- `bridge` (1 个文件) — Python 移植支撑模块
- `memdir` (1 个文件) — Python 移植支撑模块
- `buddy` (1 个文件) — Python 移植支撑模块
- `cli` (1 个文件) — Python 移植支撑模块
- `state` (1 个文件) — Python 移植支撑模块
- `schemas` (1 个文件) — Python 移植支撑模块
- `screens` (1 个文件) — Python 移植支撑模块
- `components` (1 个文件) — Python 移植支撑模块
- `voice` (1 个文件) — Python 移植支撑模块
- `hooks` (1 个文件) — Python 移植支撑模块
- `entrypoints` (1 个文件) — Python 移植支撑模块
- `outputStyles` (1 个文件) — Python 移植支撑模块
- `reference_data` (1 个文件) — Python 移植支撑模块
- `moreright` (1 个文件) — Python 移植支撑模块
- `remote` (1 个文件) — Python 移植支撑模块

命令面: 207 个镜像条目
- add-dir [mirrored] — Command module mirrored from archived TypeScript path commands/add-dir/add-dir.tsx（来源：commands/add-dir/add-dir.tsx）
- add-dir [mirrored] — Command module mirrored from archived TypeScript path commands/add-dir/index.ts（来源：commands/add-dir/index.ts）
- validation [mirrored] — Command module mirrored from archived TypeScript path commands/add-dir/validation.ts（来源：commands/add-dir/validation.ts）
- advisor [mirrored] — Command module mirrored from archived TypeScript path commands/advisor.ts（来源：commands/advisor.ts）
- agents [mirrored] — Command module mirrored from archived TypeScript path commands/agents/agents.tsx（来源：commands/agents/agents.tsx）
- agents [mirrored] — Command module mirrored from archived TypeScript path commands/agents/index.ts（来源：commands/agents/index.ts）
- ant-trace [mirrored] — Command module mirrored from archived TypeScript path commands/ant-trace/index.js（来源：commands/ant-trace/index.js）
- autofix-pr [mirrored] — Command module mirrored from archived TypeScript path commands/autofix-pr/index.js（来源：commands/autofix-pr/index.js）
- backfill-sessions [mirrored] — Command module mirrored from archived TypeScript path commands/backfill-sessions/index.js（来源：commands/backfill-sessions/index.js）
- branch [mirrored] — Command module mirrored from archived TypeScript path commands/branch/branch.ts（来源：commands/branch/branch.ts）

工具面: 184 个镜像条目
- AgentTool [mirrored] — Tool module mirrored from archived TypeScript path tools/AgentTool/AgentTool.tsx（来源：tools/AgentTool/AgentTool.tsx）
- UI [mirrored] — Tool module mirrored from archived TypeScript path tools/AgentTool/UI.tsx（来源：tools/AgentTool/UI.tsx）
- agentColorManager [mirrored] — Tool module mirrored from archived TypeScript path tools/AgentTool/agentColorManager.ts（来源：tools/AgentTool/agentColorManager.ts）
- agentDisplay [mirrored] — Tool module mirrored from archived TypeScript path tools/AgentTool/agentDisplay.ts（来源：tools/AgentTool/agentDisplay.ts）
- agentMemory [mirrored] — Tool module mirrored from archived TypeScript path tools/AgentTool/agentMemory.ts（来源：tools/AgentTool/agentMemory.ts）
- agentMemorySnapshot [mirrored] — Tool module mirrored from archived TypeScript path tools/AgentTool/agentMemorySnapshot.ts（来源：tools/AgentTool/agentMemorySnapshot.ts）
- agentToolUtils [mirrored] — Tool module mirrored from archived TypeScript path tools/AgentTool/agentToolUtils.ts（来源：tools/AgentTool/agentToolUtils.ts）
- claudeCodeGuideAgent [mirrored] — Tool module mirrored from archived TypeScript path tools/AgentTool/built-in/claudeCodeGuideAgent.ts（来源：tools/AgentTool/built-in/claudeCodeGuideAgent.ts）
- exploreAgent [mirrored] — Tool module mirrored from archived TypeScript path tools/AgentTool/built-in/exploreAgent.ts（来源：tools/AgentTool/built-in/exploreAgent.ts）
- generalPurposeAgent [mirrored] — Tool module mirrored from archived TypeScript path tools/AgentTool/built-in/generalPurposeAgent.ts（来源：tools/AgentTool/built-in/generalPurposeAgent.ts）

会话 id: 3374fdeb612c486294d1b949fa7b069b
已存储对话轮次: 7
已记录权限拒绝: 0
用量累计: 入站=373350 出站=5437
最大轮次: 400
最大预算 token: 12000000
会话记录已落盘: 是
```
