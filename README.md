# 尖叫 Code · Scream Code

## 这是什么？

**尖叫 Code** 是跑在你电脑**终端**里的 **AI 编程助手**：全中文界面，可以像聊天一样下指令，让它帮你读代码、改文件、跑终端命令。支持多家大模型（在配置里填自己的 API 即可）。
<img width="842" height="345" alt="image" src="https://github.com/user-attachments/assets/7172ac85-f837-4609-a7d1-8d45c81daf98" />

**适合谁？** 习惯用终端、想有一个「常驻命令行里」的 AI 搭档的开发者。

---

## 怎么安装？

在 **Mac 或 Linux** 上，打开终端，按顺序执行（把仓库地址换成你的）：

```bash
git clone https://github.com/l15514559690-cmd/Scream-Code.git
cd Scream-Code
chmod +x install.sh
bash install.sh
```

装完后执行下面**其中一个**（看你用哪种终端）：

```bash
source ~/.zshrc
```

或

```bash
source ~/.bashrc
```

之后，在**任意文件夹**里输入 **`scream`** 就能用。

> **注意**：若以前用过仓库里的 `install_mac.py` 往 `~/.zshrc` 里写过东西，最好先删掉里面带「Scream Code」的旧段落，再跑一遍 `install.sh`，避免重复。

**没有一键脚本时**，也可以在仓库根目录手动：

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m src.main
```

---

## 怎么用？

### 第一步：配上模型和密钥

```bash
scream config
```

按屏幕提示添加模型（接口地址、模型名、API Key 等）。也可以复制仓库里的 **`.env.example`** 为 **`.env`**，按说明填环境变量。

### 第二步：开始聊天

```bash
scream
```

出现 **`尖叫>`** 就可以输入问题。输入 **`/help`** 可看内置快捷指令（例如摘要、体检、清空会话等）。

### 老友模式 · 自动续播与长效记忆

- **自动续播**：启动 REPL 时，若项目下存在 **`.port_sessions/`** 里**最近修改过**的会话 JSON，会**自动 `load_session` 恢复**上下文（无需先 `/load`）。终端会提示：`已自动恢复上次会话记忆 (ID: …)`；若要**完全新开窗口式对话**，输入 **`/new`**。
- **`/new`（硬重置）**：清空当前对话、**新 `session_id`**、用量计数，并清空 REPL 里与 token 水位相关的展示缓存；比 **`/flush`** 多一步「展示层缓存」清理。不会删除或改写 **SCREAM.md / CLAUDE.md**。
- **`/memo`**：用**单独一次模型调用**（不写入当前多轮对话历史）根据当前会话摘录，整理「技术偏好、架构决策、项目背景」等要点，并以独立小节**安全追加**到 **`SCREAM.md`**（若不存在则优先已有 **`CLAUDE.md`**，否则新建 **`SCREAM.md`**）。下次对话会通过项目记忆机制进入系统提示，相当于「潜意识」长期生效。
- **`/summary`**：除展示摘要外，会询问是否**将摘要快照写入**上述长效记忆文件；确认后写入方式与 `/memo` 同属追加块，不覆盖你原有文档正文。

### 核心特性

**🐺 群狼模式 (Multi-Agent Team Mode)**

面对网页重构、复杂算法或跨模块开发等高难度任务，单模型往往力不从心。「尖叫 Code」内置了基于原生架构的团队协作编排：

- **激活方式**：在对话时输入 **`/team`** 或在提问前加上 **`$team`** 前缀。
- **运作逻辑**：系统会自动启动 **Planner（架构师）→ Coder（程序员）→ Reviewer（代码审计）** 三位一体的工作流。
  - **架构师**：负责拆解需求，制定执行计划。
  - **程序员**：根据计划，精准编写或修改代码。
  - **审计员**：最后检查逻辑漏洞与规范，确保代码一次性跑通。
- **使用建议**：当你要写一个完整的登录页面、或者重构核心逻辑时，请务必开启此模式。它能显著降低「幻觉」，提升生成代码的健壮性。

只想看欢迎图、不连网络模型时：

```bash
scream repl --no-llm
```

### 常用命令一览

| 你输入 | 作用 |
|--------|------|
| `scream` | 进入对话（默认已开模型） |
| `scream config` | 改模型、密钥等设置 |
| `scream summary` | 看一下当前项目文字摘要 |
| `scream findskills` | 列出当前可用的「技能」扩展 |
| **`/team`** / **`$team …`** | **群狼模式**：开关或使用多代理编排（Planner → Coder → Reviewer），见上文「核心特性」 |

对话里还有很多以 **`/`** 开头的指令（含 **`/team`**、**`/new`**、**`/memo`**、**`/summary`** 等），进 REPL 后输入 **`/help`** 最省事。

---

## 想自己加「技能」？

在仓库根目录的 **`skills/`** 文件夹里放一个 `.py` 文件（名字不要以下划线开头），里面写好说明里要求的 **`TOOL_SCHEMA`** 和 **`execute`** 函数即可。具体格式可打开仓库里现有示例或文档里的简短样例对照。

---

## 遇到问题？

- **提示缺库**：在项目目录执行 `pip install -r requirements.txt`（或再跑一次 `bash install.sh`）。
- **一直说没密钥**：检查 `llm_config.json` 里当前模型是否配对，以及 `.env` 里变量名是否和配置一致。
- **想研究实现细节**：开发者可看仓库里的 [ARCHITECTURE.md](./ARCHITECTURE.md)（偏技术，新手可跳过）。

---

## 免责声明

本仓库是学习向的 **Claude Code 类工作流** 实现之一，**不隶属于 Anthropic**，也不代表其对官方产品的背书。
