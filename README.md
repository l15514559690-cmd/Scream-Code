# 尖叫 Code · Scream-Code

> **极其锋利、纯本地优先、高扩展性的 AI 编程终端。**  
> 把大模型、工具链、记忆与视觉塞进同一条 REPL —— 像黑客电影里的控制台，但是真的能写代码。

<img width="845" height="429" alt="Scream-Code REPL" src="https://github.com/user-attachments/assets/61e95b9f-b3aa-44ac-8682-25734b182f38" />

---

## 四大核心引擎（The Four Pillars）

四次架构演进，对应四类「基础设施级」能力 —— 不是插件堆砌，而是**可组合的运行时**。

### 🔌 插件化技能树 · Skill Registry

- **是什么**：基于 `BaseSkill` 的斜杠指令系统；`SkillsRegistry` 扫描 `src/skills/*.py` 与 **`~/.scream/skills/*.py`**，运行时装配，与 LLM 工具注册表正交。
- **解决的痛点**：硬编码菜单、发版才能加指令、团队私有能力与上游冲突。
- **价值**：**解耦**业务逻辑与 REPL 路由；用户目录技能可 **override** 包内同名技能；`/help` 与 **prompt_toolkit 补全** 均从注册表 **动态生成**。

### 🛡️ 安全沙箱 · Docker Sandbox

- **是什么**：`/sandbox on` 将 `execute_mac_bash` 等终端执行隔离到 **Docker** 容器（工作区挂载为 `/workspace`）。
- **解决的痛点**：模型误删宿主文件、危险管道与包管理器命令。
- **价值**：一键切换 **宿主 / 容器** 执行面；配合权限与越狱策略，形成纵深防御。

### 🧠 长期项目记忆 · Core Memory

- **双轨制**：
  1. **项目文件**：`update_project_memory` 写入工作区 **`SCREAM.md`**（Markdown 叙事记忆）。
  2. **结构化 SQLite**：`memorize_project_rule` / `forget_project_rule` 维护本机 **键值规则库**，注入系统提示词 —— 模型的「潜意识」。
- **REPL 面**：`/memory list` · `set <key> <content>` · `drop <key>` 直接运维该库；`/memo`、`/summary` 负责会话级沉淀。
- **价值**：跨会话、跨项目根目录切换时仍能保持 **可审计、可版本化** 的长期约束。

### 👁️ 浏览器视觉 · Playwright Vision

- **是什么**：`/look <url> [说明…]` —— **Playwright Chromium** 无头整页截图，**OpenAI/Anthropic 多模态** 注入当前对话，并可 **自动触发** 后续模型轮次做 UI 诊断。
- **解决的痛点**：「帮我看页面为啥歪了」只能口述、无法像素级对齐。
- **价值**：**首次调用懒安装**：缺失 `playwright` 或 Chromium 内核时，用当前 `sys.executable` 自动 `pip install` + `playwright install chromium`，Rich **status** 反馈进度；失败时深色 **Fatal Panel** 兜底。

---

## 指令速查手册（Cheatsheet）

> 输入 **`/`** 触发补全；**完整分组列表以 REPL 内 `/help` 为准**。下表为高频核心指令。

| 指令 | 用法摘要 |
|------|-----------|
| `/help` | 分组展示全部斜杠技能与说明（别名 `/?` 仍可用，但不进补全菜单） |
| `/team` | 群狼多智能体编排开关；也可用 **`$team <提示>`** 仅单条走团队模式 |
| `/look` | **`/look <url> [说明]`** — 截图 + 多模态注入；例：`/look http://localhost:3000 按钮未居中` |
| `/sandbox` | `on` / `off` / `status` — Docker 沙箱 |
| `/memory` | `list` · **`set <key> <content>`** · **`drop <key>`** — SQLite 核心规则 |
| `/diff` | `git status --short` + `git diff --stat` 摘要 |
| `/memo` | 无参：模型提炼写入记忆；有参：直接写入 `SCREAM.md` 块 |
| `/summary` | 会话/工作区摘要，可选写入长效记忆 |
| `/new` | 硬重置会话（新 `session_id`、清空对话与计数） |
| `/flush` | 轻量清空本轮与 token 累计 |
| `/sessions` | 列出 `.port_sessions` 历史 |
| `/load <id>` | 恢复指定会话 |
| `/stop` | 中断当前生成与工具链 |
| `/cost` | 本会话 Token / 粗略费用 |
| `/doctor` | 依赖、路径、权限快检 |
| `/status` | 模型、沙箱、工具、`.claw.json`、记忆路径等 |
| `/config` | 打印当前 LLM 配置（JSON） |
| `/skills` | 命令图谱中的 Skill / Plugin 一览 |
| `/audit` `/report` | 归档一致性 / 环境体检 |
| `/subsystems` `/graph` | 子系统模块 / 引导关系图 |
| `/clear` | 清屏（TUI 补全桥接） |

---

## 进阶极客玩法

### 在 `~/.scream/skills/` 挂载自定义技能

1. 确保目录存在：`mkdir -p ~/.scream/skills`
2. 新建任意 `*.py`，定义 **`BaseSkill` 子类**（与包内技能相同契约：`name` / `description` / `category` / `execute` → `SkillOutcome`）。
3. **重启 REPL** 后注册表会加载用户目录（同名技能 **覆盖** 包内默认）。

极简示例（需与 `scream` 使用 **同一 Python 环境**，且能 `import src`）：

```python
# ~/.scream/skills/hello_skill.py
from __future__ import annotations
from typing import ClassVar

from src.repl_slash_helpers import msg
from src.skills.base_skill import BaseSkill, ReplSkillContext, SkillOutcome


class HelloSkill(BaseSkill):
    name: ClassVar[str] = 'hello'
    description: ClassVar[str] = '打个招呼（示例技能）'
    category: ClassVar[str] = 'system'

    def execute(self, context: ReplSkillContext, args: str) -> SkillOutcome:
        msg(context.console, '👋 Scream-Code 自定义技能已加载。', style='cyan')
        return SkillOutcome()
```

### Rich + prompt_toolkit：顺滑补全与「回车不提交」

- **Rich** 负责流式 Markdown、Panel、token 水位与 `/look` 安装进度等 **深色极客风** UI。
- **prompt_toolkit** 提供 **边输边补全**；补全菜单打开时，**Enter / Ctrl-M 仅确认补全并追加空格**，**不会**整行提交 —— 便于先选 `/look` 再输入 URL。
- 无 `prompt_toolkit` 的降级路径仍使用纯 `input()`（无图形补全）。

---

## 系统要求与依赖

| 能力 | 依赖 | 说明 |
|------|------|------|
| **沙箱** | **Docker** 已安装且可拉取配置镜像 | `/sandbox on` 时生效；离线环境请保持 `off` |
| **视觉** | **Playwright + Chromium** | 首次 `/look` 可 **自动** `pip install playwright` 与 `playwright install chromium`（需网络）；亦可手动预装 |
| **大模型** | API Key / Base URL（`.env` 或配置） | 支持 OpenAI 兼容与 Anthropic 协议（见 `llm_config.json`） |

---

## 快速开始

**下载**：克隆本仓库或下载 ZIP 解压。

**安装**（在项目根目录）：

```bash
bash install.sh
```

**配置**：

```bash
cp .env.example .env
# 编辑 .env 填入密钥与模型地址
```

**启动**（按安装脚本提示 `source` 对应 shell 配置后）：

```bash
scream
```

交互式修改模型也可使用 **`scream-config`**。

---

> **安全提示**：请勿将真实密钥提交到公开仓库。本项目基于 Claude Code 类工作流思路演进，仅供学习与研究；生产环境请自行审计依赖与网络出站策略。
