# Scream Code

> 一个中文友好、Local-First 的 AI 工程终端。  
> 目标不是“聊天更花哨”，而是让 AI 在你的机器上接管真实生产力链路。

Scream Code 面向开发者、知识工作者以及零基础开发者，提供：

- 本地优先：会话、记忆、技能、工具执行全部在你可控的工作区与主机环境
- 中文优先：交互文案、命令语义、错误提示对中文工作流做过深度适配
- 双通道网关：终端 TUI 主通道 + 飞书长连接侧车子通道，兼顾本地效率与移动协作
- 可扩展架构：`SkillsRegistry`（斜杠技能）与 `ToolsRegistry`（LLM 工具）分层解耦

---

## 愿景与定位

Scream Code 不是另一个“会说话的壳”。它的定位是：

- **个人本地生产力接管层**：从读写文件、执行命令、审查改动，到视觉分析、记忆注入，全链路闭环
- **面向真实项目的工作终端**：有状态会话、会话恢复、长期记忆、沙箱隔离、工具调用治理
- **中文工程团队默认入口**：降低英文 prompt 成本，让命令、反馈、排障都贴合中文开发语境

---

## 核心能力总览

### 1) 终端智能体（TUI REPL）

- 流式输出 + 终端 UI 状态栏
- 历史会话落盘与恢复（支持跨回合上下文管理）
- `/stop` 生成中断机制
- Slash 自动补全，按能力域分类

### 2) 本地工具执行与治理

- 内置工具：读写文件、执行命令、记忆操作、文件回传等
- 工具统一由 `src/tools_registry.py` 注册、分发与执行
- 技能层与工具层解耦：斜杠技能不直接污染 LLM 函数工具池

### 3) 长期记忆系统

- SQLite 长期记忆槽位（`/memory list/set/drop`）
- `/memo` 可把当前对话提炼后写入长期记忆
- 记忆内容可注入系统提示，形成“项目级个性化行为”

### 4) 视觉能力（Playwright）

- `/look <url> [说明]` 获取网页视觉快照
- 截图可直接进入多模态输入，供模型进行结构/UI/可访问性分析

### 5) 沙箱与系统控制

- `/sandbox on|off|status` 切换 Docker 隔离执行
- `/doctor`、`/report`、`/status` 提供运行与配置诊断

### 6) 双通道分布式网关（TUI + Feishu Sidecar）

- 主通道：本地终端高频交互
- 子通道：飞书侧车长连接，支持远程消息和附件收发
- 飞书会话与主会话隔离（`feishu_` 前缀会话、独立 inbox/outbox）
- 附件协议：通过 `[FEISHU_FILE:绝对路径]` 标签由侧车转发

---

## 快速开始

### 环境要求

- Python 3.10+
- Git
- 可选：Docker（启用沙箱时需要）

### 安装

在仓库根目录执行：

```bash
chmod +x install.sh && ./install.sh
```

Windows PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

安装脚本会自动完成：

- 虚拟环境创建与依赖安装
- `scream` 可编辑安装
- Playwright Chromium 准备（视觉能力）
- 用户目录初始化（`~/.scream`）

### 启动

```bash
scream
```

常用入口：

- `scream`：进入主交互
- `scream config`：配置模型与密钥
- `scream help`：查看 CLI 帮助

---

## 配置与安全边界

### 配置位置（用户级）

- `~/.scream/llm_config.json`：模型与路由配置
- `~/.scream/.env`：密钥等敏感配置

### 🛡️ 高危操作审批与白名单 (`.claw.json`)

Scream Code 默认启用 Human-in-the-loop (HITL) 审批机制：当 Agent 尝试执行写文件、打补丁、运行脚本等高危工具时，终端会弹出审批卡片，要求你手动 `y/n` 确认。

如果你对某些高频操作已完全信任，可在**项目根目录**的 `.claw.json` 配置自动放行白名单（仅对当前项目生效）：

```json
{
  "auto_approve_tools": ["write_local_file", "patch"]
}
```

配置后，命中的工具将跳过人工审批直接执行；未在白名单中的高危工具仍会继续弹窗拦截。

### 仓库忽略策略

仓库默认忽略敏感/运行态目录（如 `.env`、`/.scream_cache/`），避免误提交密钥和缓存。

### 飞书侧车缓存

- 入站：`.scream_cache/feishu_inbox/`
- 出站：`.scream_cache/feishu_outbox/`
- PID：`.scream_cache/feishu_sidecar.pid`

---

## 斜杠命令总表（完整）

> 说明：以下命令来自当前代码注册表；`/` 补全会按分类展示。

### Core

| 命令 | 说明 | 典型用法 |
| --- | --- | --- |
| `/help` | 指令总览（别名 `/?`） | `/help` |
| `/clear` | 清屏（不等于清空会话） | `/clear` |
| `/exit` | 退出 | `/exit` |
| `/quit` | 退出（同 `/exit`） | `/quit` |

### Memory / Context

| 命令 | 说明 | 典型用法 |
| --- | --- | --- |
| `/summary` | 生成项目与会话摘要，可选择写入长期记忆 | `/summary` |
| `/memo` | 提炼并保存当前对话核心记忆；可直接写入文本 | `/memo` / `/memo 团队偏好：默认先写测试` |
| `/new` | 硬重置会话（新 session） | `/new` |
| `/flush` | 清空当前对话并重置 token 累计 | `/flush` |
| `/stop` | 中断当前生成/工具链 | `/stop` |
| `/sessions` | 查看本地会话列表 | `/sessions` |
| `/load <session_id>` | 加载指定会话 | `/load 8f2a...` |

### Vision

| 命令 | 说明 | 典型用法 |
| --- | --- | --- |
| `/look <url> [说明]` | 网页视觉快照并可触发后续分析 | `/look https://example.com 检查可读性` |

### System & Ops

| 命令 | 说明 | 典型用法 |
| --- | --- | --- |
| `/memory` | SQLite 长期记忆管理 | `/memory list` / `/memory set code_style 统一ruff` / `/memory drop code_style` |
| `/sandbox` | Docker 沙箱开关/状态 | `/sandbox status` / `/sandbox on` / `/sandbox off` |
| `/diff` | Git 工作区变更摘要 | `/diff` |
| `/mcp` | MCP 状态、重启、工具、浏览器模式 | `/mcp status` / `/mcp restart` / `/mcp tools` / `/mcp browser` |
| `/feishu` | 飞书侧车控制台 | 见下方子命令 |
| `/audit` | 项目对齐度审查 | `/audit` |
| `/report` | setup-report 体检 | `/report` |
| `/subsystems` | 顶层子系统视图 | `/subsystems` |
| `/graph` | bootstrap + command 图谱 | `/graph` |
| `/config` | 当前模型配置 JSON 展示 | `/config` |
| `/skills` | 已挂载技能/插件列表 | `/skills` |
| `/doctor` | 运行环境与依赖体检 | `/doctor` |
| `/cost` | token 与费用估算 | `/cost` |
| `/status` | 当前运行状态总览 | `/status` |
| `/team` | 切换多 Agent 团队模式 | `/team` |
| `$team <prompt>` | 单条消息走团队模式 | `$team 先评审再改` |

### `/feishu` 子命令

| 命令 | 说明 |
| --- | --- |
| `/feishu config <AppID> <AppSecret>` | 写入或更新飞书凭据 |
| `/feishu start` | 启动侧车（已运行则跳过） |
| `/feishu stop` | 停止侧车 |
| `/feishu delete` | 清理飞书会话与缓存 |
| `/feishu clear` | 同 `delete` |
| `/feishu status` | 查看侧车状态 |
| `/feishu log` | 查看侧车日志 |
| `/feishu help` | 查看帮助 |

> 建议：执行 `/feishu delete` 前先 `/feishu stop`，避免运行中的侧车继续写入缓存。

---

## 架构分层（实现视角）

- `src/main.py`：CLI 入口与路由
- `src/tui_app.py` / `src/replLauncher.py`：TUI 与 REPL 主循环
- `src/query_engine.py`：会话、模型交互、工具编排核心
- `src/skills_registry.py` + `src/skills/`：斜杠技能系统
- `src/tools_registry.py`：LLM 工具注册与执行
- `src/session_store.py`：会话落盘、索引、隔离与清理
- `bots/feishu_ws_bot.py`：飞书长连接侧车
- `src/services/feishu_manager.py`：侧车生命周期管理

---

## 可扩展性

### 自定义斜杠技能

将技能文件放入 `~/.scream/skills/`，重启后自动加载（覆盖同名内置技能）。

### 自定义 LLM 工具

将工具模块放到项目根 `skills/*.py`，导出：

- `TOOL_SCHEMA`
- `execute(**kwargs)`

工具会被 `ToolsRegistry` 自动发现并注册。

---

## 研发与验证

常用本地验证：

```bash
python3 -m pytest -q
```

Rust 工作区验证（如需）：

```bash
cd rust
cargo fmt
cargo clippy --workspace --all-targets -- -D warnings
cargo test --workspace
```

---

## 许可证

MIT License。详见 `LICENSE`。

---

Scream Code 的核心理念：**让 AI 真正成为你本地生产系统的一部分，而不是浏览器里的临时聊天窗口。**
