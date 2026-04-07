# 尖叫 Code（Scream Code）· 使用教程

面向**第一次用终端 AI 编程助手**的开发者：从装环境到改模型、开 TUI、用斜杠命令，按顺序做即可。

## 这是什么？

**Scream Code** 是跑在你电脑**终端**里的 **AI 编程助手**：全中文界面，可以像聊天一样下指令，让它帮你读代码、改文件、跑终端命令。支持多家大模型（在配置里填自己的 API 即可）。

<img width="842" height="345" alt="image" src="https://github.com/user-attachments/assets/7172ac85-f837-4609-a7d1-8d45c81daf98" />

**如下图测试-通过对话发送需求：我想制作一个电商前端网页

<img width="1372" height="856" alt="image" src="https://github.com/user-attachments/assets/92c1885d-3d1b-47b6-b59a-3445f87e1f76" />

**适合谁？** 习惯用终端、想有一个「常驻命令行里」的 AI 搭档的开发者。

---

## 目录

1. [项目简介与特性](#1-项目简介与特性)
2. [极简安装指南](#2-极简安装指南)
3. [傻瓜式模型配置](#3-傻瓜式模型配置)
4. [启动与基础使用](#4-启动与基础使用)
5. [核心高阶玩法](#5-核心高阶玩法)
6. [斜杠命令大全](#6-斜杠命令大全)
7. [常见问题排查（FAQ）](#7-常见问题排查faq)
8. [延伸阅读](#8-延伸阅读)

---

## 1. 项目简介与特性

**尖叫 Code** 是一套跑在你电脑**终端里**的 **AI 编程助手**：用自然中文下指令，让模型帮你读项目、改文件、跑命令、查 Git、做总结。

它由**两条可配合使用的技术栈**组成（共用同一套项目根目录下的配置习惯，例如 `.env`、`llm_config.json`）：

| 栈 | 技术 | 典型入口 | 适合做什么 |
|----|------|----------|------------|
| **Rust 客户端** | `ratatui` 全屏 TUI + 运行时、工具、会话 | 编译后的 `scream` 二进制（`cargo install`） | **一键全屏界面**：大对话区、多行输入、底栏 Token/费用；适合日常「主控制台」 |
| **Python 镜像内核** | 中文 REPL、路由、`llm_client` 多轮工具闭环 | `python3 -m src.main` 或 `install.sh` 注入的 `scream` 函数 | **全中文镜像工作流**：`/memo`、`/team`、`.port_sessions` 自动续播等与 `ARCHITECTURE.md` 描述一致的链路 |

通俗理解：**Rust 端像「高颜值终端 IDE 面板」**；**Python 端像「中文说明书里写的那套大脑 + REPL」**。你可以只装其一，也可以两个都装，注意下文 [PATH 与 `scream` 重名](#user-guide-scream-path)。

**特性一览（概念层）**

- 多家模型：OpenAI 兼容接口、Anthropic 协议等（由 `llm_config.json` + `.env` 决定）。
- **工具调用**：模型可在权限允许时读写工作区、执行 shell（具体能力以当前模式与工具集为准）。
- **权限模式**（Rust 侧常用）：只读、工作区写入、完全访问等，防止误删系统文件。
- **长效记忆**：`SCREAM.md` / `CLAUDE.md` 与 `/memo`、`/summary`（Python REPL）配合。
- **多代理团队**（Python REPL）：`/team` 或 `$team` 前缀 → Planner → Coder → Reviewer 编排。

---

## 2. 极简安装指南

### 2.1 准备环境

| 依赖 | 说明 |
|------|------|
| **Python** | 建议 **3.10 及以上**（3.12、3.13、3.14 亦可）。终端执行 `python3 --version` 检查。 |
| **Rust / Cargo** | 仅在你需要 **Rust TUI 客户端**时安装。见 [rustup.rs](https://rustup.rs/)，安装后执行 `cargo --version`。建议 **stable** 最新版。 |
| **操作系统** | **macOS / Linux** 最省心；Windows 可用 WSL2 获得相近体验。 |
| **Git** | 克隆本仓库需要。 |

### 2.2 克隆仓库

```bash
git clone <你的仓库地址>
cd ScreamCode    # 以你本地目录名为准
```

### 2.3 安装 Python 依赖

**推荐：在项目根目录用虚拟环境**（与 `install.sh` 一致）：

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -U pip
pip install -r requirements.txt
```

依赖列表见根目录 [`requirements.txt`](./requirements.txt)（OpenAI / Anthropic SDK、Rich、prompt_toolkit、dotenv 等）。

### 2.4 一键脚本（可选）

在仓库根目录：

```bash
chmod +x install.sh
bash install.sh
```

脚本会：创建 `.venv`、安装 `requirements.txt`、在你 shell 配置里写入函数 **`scream`**（进入仓库并执行 `python3 -m src.main`）。  
装完后执行：

```bash
source ~/.zshrc    # 或 source ~/.bashrc
```

### 2.5 编译并「全局」安装 Rust TUI 客户端

在仓库内 **Rust 工作区**执行（从仓库根目录）：

```bash
cd rust
cargo install --path crates/rusty-claude-cli
```

- 默认会把名为 **`scream`** 的二进制安装到 `~/.cargo/bin`（请确保该目录在 `PATH` 中）。
- **注意**：若你已用 `install.sh` 定义了 shell 函数 `scream`，在交互式终端里**函数会优先于** `~/.cargo/bin/scream`，详见 [FAQ：scream 重名](#user-guide-scream-path)。

**本地调试不安装到全局**时：

```bash
cd rust
cargo build -p scream-cli
./target/debug/scream      # 或 release 路径
```

---

## 3. 傻瓜式模型配置

### 3.1 为什么需要 `.env` 和 `llm_config.json`？

- **`.env`**：放 **API Key** 和可选默认（无配置文件时的 `BASE_URL` / `API_KEY` / `MODEL`）。**不要提交到 Git。**
- **`llm_config.json`**（项目根目录，可由交互配置生成）：定义**多个模型配置档**、当前 **active** 档、每档对应的 **密钥环境变量名**、**base_url**、**api_protocol**（`openai` 或 `anthropic`）。

Rust 与 Python 都会从项目根向上查找 `llm_config.json`，并加载 `.env`（行为细节以代码为准）。

**仓库里不会提交你的真实 `llm_config.json`**（已在 `.gitignore` 中）。首次使用可复制脱敏样板：

```bash
cp llm_config.json.example llm_config.json
```

再运行 `python3 -m src.main config` 或按需编辑；**不要把含真实密钥或内网地址的自定义配置推送到 GitHub**。

### 3.2 创建 `.env`

1. 复制样板文件：

   ```bash
   cp .env.example .env
   ```

2. 用文本编辑器打开 `.env`，把占位符改成真实密钥（示例字段见 [`.env.example`](./.env.example)）。

**无 `llm_config.json` 时的兜底（OpenAI 兼容协议）**：

```env
BASE_URL=https://api.openai.com/v1
API_KEY=sk-xxxxxxxx
MODEL=gpt-4o-mini
```

### 3.3 交互式配置（推荐小白）

**Python 配置向导**（会维护 `llm_config.json` 并与 `.env` 协同）：

```bash
python3 -m src.main config
# 若已激活 venv 且安装了包，也可在包安装模式下使用等价入口
```

按屏幕提示添加：**别名、接口地址、模型名、协议类型、密钥环境变量名**，然后在 `.env` 里为**该变量名**填一行密钥。

### 3.4 接入不同厂商（概念对照）

| 厂商 | 常见方式 | 提示 |
|------|----------|------|
| **OpenAI** | `api_protocol: openai`，`BASE_URL` 指向官方或代理 | 官方一般为 `https://api.openai.com/v1` |
| **Anthropic** | `api_protocol: anthropic`，`base_url` 可默认或填兼容网关 | 密钥环境变量名在 `llm_config.json` 里配置 |
| **DeepSeek** | 多数走 **OpenAI 兼容**：`openai` 协议 + DeepSeek 提供的 **base_url** + **DEEPSEEK_API_KEY**（与 `.env.example` 一致） | 以厂商文档为准 |
| **其它国内/自建兼容** | 通常选 `openai` 协议 + 厂商 `base_url` + 对应 Key | `api_key_env_name` 与 `.env` 中变量名必须一致 |

**硬编码提示**：若某模型在界面里显示异常，先检查 **active 档**、`MODEL` 环境变量、以及 **Key 是否为空**。

### 3.5 可选环境变量（进阶）

见 [`.env.example`](./.env.example) 注释，例如：

- `SCREAM_WORKSPACE_ROOT`：固定工作区根（会话目录 `.port_sessions/`、文件工具等会与此对齐）。
- `SCREAM_MAX_AGENT_TOOL_ROUNDS`：限制单次用户消息内「模型 ↔ 工具」往返次数（防死循环；留空或 `0` 等表示不限制）。

---

## 4. 启动与基础使用

### 4.1 用 `scream` 打开 Rust 全屏 TUI

确保你启动的是 **Cargo 安装的二进制**（见 [FAQ：scream 重名](#user-guide-scream-path)），在项目目录下：

```bash
scream
```

常用参数：

```bash
scream --tui              # 显式全屏 TUI（多数情况下与默认相同）
scream --line-repl        # 行编辑 REPL（非全屏 TUI）
scream --permission-mode read-only
scream --permission-mode workspace-write
scream --permission-mode danger-full-access
scream --dangerously-skip-permissions   # 等同于最高危险模式，慎用
```

**退出 TUI**：一般 `Ctrl+C` 会保存并退出（以当前版本提示为准）；也可尝试输入 `/exit`、`/quit`（若当前 REPL 已解析斜杠命令）。

### 4.2 用 Python 打开中文 REPL

```bash
cd /path/to/ScreamCode
source .venv/bin/activate
python3 -m src.main repl
```

只看欢迎说明、不连模型：

```bash
python3 -m src.main repl --no-llm
```

### 4.3 TUI 界面图解（Rust）

```
┌─────────────────────────────────────────────────────────────┐
│  🚀Scream Code🚀  （顶栏：会话/品牌标题）                      │
│                                                             │
│                      对话区                                  │
│              （助手输出、工具结果、错误提示）                  │
│                                                             │
├─────────────────────────────────────────────────────────────┤
│  输入区 · 多行输入，Enter 发送，Shift+Enter 换行               │
│  尖叫> ...                                                  │
├─────────────────────────────────────────────────────────────┤
│ 底栏：模型 · 权限模式 · 分支 · 累计 Token · 估算费用 等        │
└─────────────────────────────────────────────────────────────┘
```

- **对话区**：滚动查看历史；**空会话**时在中间显示 **FIGlet `slant` 字样 `SCREAMCODE`**（与 `rust/crates/rusty-claude-cli/src/tui/mod.rs` 中 `SPLASH_SLANT` 一致），其下一行副标题为淡化样式：`>>> 🚀scream code🚀 | 基于 OpenClaw 架构的力量 <<<`（终端里对应 `DarkGray` + 暗淡修饰，非 Rich 标记）。

  ```text
     _____ __________  _________    __  _____________  ____  ______
    / ___// ____/ __ \/ ____/   |  /  |/  / ____/ __ \/ __ \/ ____/
    \__ \/ /   / /_/ / __/ / /| | / /|_/ / /   / / / / / / / __/
   ___/ / /___/ _, _/ /___/ ___ |/ /  / / /___/ /_/ / /_/ / /___
  /____/\____/_/ |_/_____/_/  |_/_/  /_/\____/\____/_____/_____/
  ```
- **输入区**：实际打字位置以界面为准（反色块为「逻辑光标」）。
- **底栏**：快速确认当前模型与消耗，便于控成本。

---

## 5. 核心高阶玩法

### 5.1 记忆管理：`SCREAM.md`、`CLAUDE.md` 与 `/memo`

- **`SCREAM.md`**：项目根下的**长效记忆文档**。Python REPL 的 **`/memo`** 会把整理后的要点**追加**进该文件（若不存在，可能优先使用已有 **`CLAUDE.md`**，否则新建 `SCREAM.md` —— 与实现一致）。
- **`/memo`**（两种用法）：
  - **不带参数**：单独调用模型，从当前会话摘录「技术偏好、架构决策、项目背景」等，再追加到记忆文件；**不污染**当前多轮对话历史。
  - **带文字**：直接把跟在后面的文字追加到记忆文件。
- **`/summary`**：除展示摘要外，可选择在确认后把摘要快照写入同一套记忆机制。
- **清除不需要的记忆**：用编辑器**手动编辑或删除** `SCREAM.md` / `CLAUDE.md` 中对应段落即可（当前设计为**追加块**，不会自动替你删旧内容）。

**会话硬重置与清空（Python REPL）**

- **`/new`**：硬重置会话、`session_id`、计数与部分展示缓存；**不删** `SCREAM.md` / `CLAUDE.md`。
- **`/flush`**：清空本轮对话与 token 累计等（相对 `/new` 较轻）。

### 5.2 「群狼」/ Agent：工具、读文件、长线任务与权限

**Python REPL · 多代理（`/team`）**

- **开启**：输入 **`/team`** 打开开关，或在提问前加 **`$team`** 仅对**这一条**启用。
- **流程**：**Planner（规划）→ Coder（实现，可调用工具）→ Reviewer（审查）**，减轻单模型一步到位时的幻觉与不连贯。
- **工具调用闭环**：由 `llm_client.iter_agent_executor_events` 统一驱动（见 [`ARCHITECTURE.md`](./ARCHITECTURE.md)），模型发起 `tool_calls` 后由 **SkillsRegistry** 执行并写回对话，再进入下一轮模型推理。

**Rust 客户端 · 工具与权限**

- 模型在允许范围内可调用注册工具（读文件、执行命令等，以实际启用列表为准）。
- **权限模式**控制「能写多少、能否出工作区」一类边界；**只读**最安全，**完全访问**适合信得过的本机环境。
- **高危操作**：若实现中包含「待批准」流程，可使用 **`/approve`**、**`/deny`**（及别名 **`/yes`**、**`/no`**）响应；日常请以界面提示为准。
- **中断**：Python 侧 **`/stop`** 可请求中断当前轮工具链；Rust 侧以 **Ctrl+C** 等为准。

**环境变量**：`SCREAM_MAX_AGENT_TOOL_ROUNDS` 可限制工具往返次数（见 [`.env.example`](./.env.example)）。

---

## 6. 斜杠命令大全

### 6.1 两条栈上的命令可能不同

- **Python REPL**（`python3 -m src.main repl`）：以中文 **`/help`** 为准，侧重镜像工作区能力。
- **Rust TUI / 行 REPL**：内置大量以 **`/`** 开头的命令（英文 `summary` 字段注册）；随时输入 **`/help`** 查看当前二进制支持的列表。

下面分块列出，避免混淆。

### 6.2 Python REPL 常用斜杠（`/help` 同步）

| 命令 | 作用 |
|------|------|
| `/help` | 显示分组帮助 |
| `/summary` | 项目与会话摘要；可确认后写入长效记忆 |
| `/memo [要点]` | 无参则模型提炼要点写入记忆；有参则直接追加 |
| `/new` | 硬重置会话与展示缓存 |
| `/flush` | 清空本轮对话与累计等 |
| `/sessions` | 列出 `.port_sessions` 下历史会话 |
| `/load <id>` | 按 id 恢复会话 |
| `/stop` | 中断当前轮工具链 |
| `/audit` | parity-audit |
| `/report` | setup-report |
| `/subsystems` | 列出顶层 Python 子系统 |
| `/graph` | bootstrap-graph + command-graph 总览 |
| `/doctor` | 环境/依赖体检 |
| `/cost` | 本会话 Token / 粗略费用 |
| `/diff` | `git diff --stat` |
| `/status` | 沙箱、工具数、模型、`.claw.json`、项目记忆等 |
| `/team` | 开关多代理编排 |
| `$team <提示>` | 仅本条走团队模式 |

### 6.3 Rust 客户端：内置 `/` 命令注册表（约 100 条）

下列命令在 **`rust/crates/commands/src/lib.rs`** 的 **`SLASH_COMMAND_SPECS`** 中注册；**英文说明**为源码中的 `summary` 字段，此处附上**简要中文意译**，参数见第三列 `argument_hint`。

> 若与运行中的 `scream --help` 或 REPL 内 `/help` 不一致，**以你本机编译版本为准**。

| 命令 | 中文意译 | 参数提示（若有） |
|------|----------|------------------|
| `/help` | 列出斜杠命令 | |
| `/status` | 当前会话状态 | |
| `/sandbox` | 沙箱隔离状态 | |
| `/compact` | 压缩本地会话历史 | |
| `/model` | 查看或切换模型 | `[model]` |
| `/permissions` | 查看或切换权限模式 | `read-only` / `workspace-write` / `danger-full-access` |
| `/clear` | 新建本地会话 | `[--confirm]` |
| `/cost` | 本会话累计 Token | |
| `/resume` | 加载已保存会话 | `<session-path>` |
| `/config` | 查看 Claude/项目配置 | 可选：`env`、`hooks`、`model`、`plugins` |
| `/mcp` | MCP 服务器 | `list` / `show <server>` / `help` |
| `/memory` | 已加载指令记忆文件 | |
| `/init` | 生成入门 `CLAUDE.md` | |
| `/diff` | Git 改动 | |
| `/version` | 版本与构建信息 | |
| `/bughunter` | 代码隐患扫描 | `[scope]` |
| `/commit` | 生成提交说明并提交 | |
| `/pr` | 起草/创建 PR | `[context]` |
| `/issue` | 起草/创建 GitHub Issue | `[context]` |
| `/ultraplan` | 深度规划 | `[task]` |
| `/teleport` | 按符号/路径跳转 | `<symbol-or-path>` |
| `/debug-tool-call` | 调试重放上次工具调用 | |
| `/export` | 导出对话 | `[file]` |
| `/session` | 管理本地会话 | `list` / `switch` / `fork` |
| `/plugin` | 插件（别名 `/plugins`、`/marketplace`） | 见帮助 |
| `/agents` | 已配置 agents | |
| `/skills` | 技能列表/安装 | |
| `/doctor` | 环境诊断 | |
| `/login` | 登录服务 | |
| `/logout` | 登出 | |
| `/plan` | 规划模式 | `on` / `off` |
| `/review` | 代码审查 | `[scope]` |
| `/tasks` | 后台任务 | `list` / `get` / `stop` |
| `/theme` | 终端主题 | `[theme-name]` |
| `/vim` | Vim 按键模式 | |
| `/voice` | 语音输入 | `on` / `off` |
| `/upgrade` | 检查更新 | |
| `/usage` | API 用量详情 | |
| `/stats` | 工作区与会话统计 | |
| `/rename` | 重命名会话 | `<name>` |
| `/copy` | 复制到剪贴板 | `last` / `all` |
| `/share` | 分享对话 | |
| `/feedback` | 反馈 | |
| `/hooks` | 生命周期钩子 | |
| `/files` | 上下文中的文件列表 | |
| `/context` | 上下文管理 | 子命令 `show` 或 `clear` |
| `/color` | 终端颜色 | `[scheme]` |
| `/effort` | 回答「用力程度」 | `low` / `medium` / `high` |
| `/fast` | 简洁模式 | |
| `/exit` | 退出 REPL | |
| `/branch` | Git 分支 | `[name]` |
| `/rewind` | 回滚对话 | `[steps]` |
| `/summary` | 生成对话摘要 | |
| `/desktop` | 桌面端集成 | |
| `/ide` | IDE 集成 | `vscode` / `cursor` |
| `/tag` | 标记对话点 | `[label]` |
| `/brief` | 简短输出 | |
| `/advisor` | 仅建议模式 | |
| `/stickers` | 贴纸包 | |
| `/insights` | 会话洞察 | |
| `/thinkback` | 回放思考过程 | |
| `/release-notes` | 从改动生成发布说明 | |
| `/security-review` | 安全审查 | `[scope]` |
| `/keybindings` | 快捷键 | |
| `/privacy-settings` | 隐私设置 | |
| `/output-style` | 输出样式 | `[style]` |
| `/add-dir` | 追加上下文目录 | `<path>` |
| `/allowed-tools` | 允许的工具列表 | |
| `/api-key` | 查看/设置 Anthropic Key | `[key]` |
| `/approve` | 批准待执行工具（`/yes`、`/y`） | |
| `/deny` | 拒绝（`/no`、`/n`） | |
| `/undo` | 撤销上次写文件 | |
| `/stop` | 停止生成 | |
| `/retry` | 重试上次失败 | |
| `/paste` | 粘贴剪贴板 | |
| `/screenshot` | 截图加入对话 | |
| `/image` | 图片路径加入对话 | `<path>` |
| `/terminal-setup` | 终端集成设置 | |
| `/search` | 工作区搜索 | `<query>` |
| `/listen` / `/speak` | 语音听/读 | |
| `/language` | 界面语言 | `[language]` |
| `/profile` | 用户配置档 | `[name]` |
| `/max-tokens` | 最大输出 token | `[count]` |
| `/temperature` | 采样温度 | `[value]` |
| `/system-prompt` | 查看系统提示 | |
| `/tool-details` | 工具详情 | `<tool-name>` |
| `/format` | 重排输出格式 | `markdown` / `plain` / `json` |
| `/pin` / `/unpin` | 固定/取消消息 | |
| `/bookmarks` | 书签 | |
| `/workspace`（`/cwd`） | 工作目录 | `[path]` |
| `/history` | 历史摘要 | `[count]` |
| `/tokens` | 当前对话 token 数 | |
| `/cache` | 提示缓存统计 | |
| `/providers` | 模型提供商列表 | |
| `/notifications` | 通知 | `on` / `off` / `status` |
| `/changelog` | 近期变更 | |
| `/test` / `/lint` / `/build` / `/run` | 测试/检查/构建/运行 | 各见 `argument_hint` |
| `/git` / `/stash` / `/blame` / `/log` | Git 相关 | |
| `/cron` | 定时任务 | |
| `/team` | 管理团队（Rust 语义，与 Python 多代理不同） | |
| `/benchmark` / `/migrate` / `/reset` / `/telemetry` | 基准/迁移/重置/遥测 | |
| `/env` / `/project` | 环境变量 / 项目探测 | |
| `/templates` / `/explain` / `/refactor` / `/docs` / `/fix` / `/perf` | 模板/解释/重构/文档/修复/性能 | |
| `/chat` / `/focus` / `/unfocus` | 聊天模式与聚焦上下文 | |
| `/web` | 抓取网页摘要 | `<url>` |
| `/map` / `/symbols` / `/references` / `/definition` | 代码地图与符号 | |
| `/hover` / `/diagnostics` / `/autofix` | LSP 相关 | |
| `/multi` / `/macro` / `/alias` | 组合命令与宏 | |
| `/parallel` / `/agent` / `/subagent` | 并行与子代理 | |
| `/reasoning` / `/budget` / `/rate-limit` / `/metrics` | 推理模式与预算 | |

### 6.4 自定义技能（Python 工具池）

在仓库根目录 **`skills/`** 下添加 `.py` 文件（实现约定的 `TOOL_SCHEMA` 与 `execute`），可在 `python3 -m src.main findskills` 中查看是否加载。

---

## 7. 常见问题排查（FAQ）

### 提示 `No module named pytest` / 缺库

在项目根、已激活 venv 时：

```bash
pip install -r requirements.txt
```

自动化场景可设 `SCREAM_SKIP_DEPS_CHECK=1` 跳过启动自检（见 `.env.example`）。

### 一直提示没有 API Key

1. 确认 `.env` 里变量名与 **`llm_config.json` 中 `api_key_env_name`** 一致。  
2. 执行 `python3 -m src.main config` 检查 **active** 模型。  
3. Rust 侧确认从**含配置的项目目录**启动，或已导出对应环境变量。

### `cargo: command not found`

未安装 Rust；请安装 rustup 后重开终端。

### `cargo install` 很慢或失败

检查网络；可配置国内 crates 镜像（视环境而定）。

<a id="user-guide-scream-path"></a>

### 尖叫：我输入 `scream`，进的不是 TUI，也不是 Python？

- **`install.sh`** 会定义 **shell 函数** `scream`，通常优先于 PATH 里的可执行文件。  
- **想用 Rust TUI**：临时用 **`command scream`** 或 **`~/.cargo/bin/scream`**，或从函数里去掉/改名。  
- **想用 Python**：保持函数，或显式 `python3 -m src.main repl`。

### TUI 花屏、乱码

- 终端尽量选 **UTF-8**、足够大的窗口。  
- 远程 SSH 可尝试 `TERM=xterm-256color`。

### 网络超时、模型报错

- 检查代理、`BASE_URL`、防火墙。  
- Python 路径下多数错误会变为 **`[LLM] ...`** 提示而不会直接崩进程；仍失败可把完整报错贴到 issue（注意打码密钥）。

### Git 相关命令在沙箱里失败

确认当前 **permission-mode** 是否允许访问 `.git` 与工作区；必要时在可信仓库使用 `workspace-write` 或更高（请自担风险）。

---

## 8. 延伸阅读

- [`ARCHITECTURE.md`](./ARCHITECTURE.md) — 架构边界与数据流（开发者向）。  
- [`.env.example`](./.env.example) — 环境变量样板。  
- [`CLAUDE.md`](./CLAUDE.md)（若存在）— 本仓库给 AI/工具的协作说明。

---

## 免责声明

本仓库是学习向的 **Claude Code 类工作流**实现之一，底层基座参考 claw-code 镜像契约，仅供学习与交流。使用第三方 API 时请遵守各厂商条款，**勿将真实密钥提交到 Git**。
