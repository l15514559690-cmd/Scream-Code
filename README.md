# 🚀 Scream-Code (尖叫Agent终端)v1.1

<img width="1085" height="438" alt="image" src="https://github.com/user-attachments/assets/d0d8a0f5-18d7-4575-a517-91d04d99b233" />


> **“让 AI 走出网页聊天框，真正接管你的本地生产力。”**

**Scream-Code** 是一款专为极客、开发者和高效办公族打造的**纯本地、全能力 AI Agent 终端**。它不仅能通过文字回答问题，更拥有“手”（执行代码）、“眼”（网页视觉）和“脑”（长期记忆）。

---

## 🛠️ 第一步：保姆级一键安装指南 (The Magic Install)

我们为所有用户（无论是小白还是大牛）准备了极其简单的安装流程，只需 3 分钟，即可完成部署。

### 1. 环境准备 (只需一次)
在开始之前，请确保你的 Mac 或 Linux 电脑上安装了：
* **Python 3.10+** (必选)
* **Git** (必选，用于下载代码)
* **Docker** (可选，若需开启“绝对安全沙箱”功能则必装)

### 2. 下载并执行“一键部署脚本”
打开你的终端（Terminal），依次输入以下三行命令：

```bash
# 1. 下载代码库
git clone https://github.com/LIUTod/Scream-Code.git

# 2. 进入项目文件夹
cd Scream-Code

# 3. 运行全自动安装脚本
bash install.sh
```

### Windows 用户一键安装（PowerShell）
如果你使用 Windows，请在项目根目录执行下面这行命令（可绕过执行策略限制）：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

> 若你的终端权限较严，可用“以管理员身份运行 PowerShell”后再执行。安装脚本会自动检测 Python / pip、创建 `.venv`、安装依赖、下载 Playwright Chromium，并在完成后自动启动 `scream`。

**☕ 这时脚本会自动完成以下动作：**
* 🔍 **环境体检**：自动检查 Python 和 Pip 是否就绪。
* 📦 **无污染安装**：创建一个隐藏的虚拟环境 (`.venv`)，绝不弄乱你电脑原本的 Python。
* 👁️ **视觉内核下载**：静默下载 Playwright 浏览器引擎（AI 的眼睛）。
* 📂 **私人空间创建**：在你的家目录生成 `~/.scream` 文件夹，用于存放你的 API 密钥和私人记忆。

### 3. 首次配置与唤醒
安装完成后，脚本会自动弹出**配置向导**：
1. 按照提示输入你的 **API Key** (推荐 GLM5.1 或 CLAUDE 系列)。
2. 配置完成后，直接输入 `scream` 即可起飞！

---

## 🎮 核心指令与使用姿势 (How to Play)

Scream-Code 的交互分为三个维度：**系统入口**、**超能力指令**和**人话任务**。

### 维度一：系统控制台 (CLI)
在任何文件夹下，你都可以直接通过系统命令调用：
* `scream` —— **启动终端**。一秒进入沉浸式 AI 交互界面。
* `scream config` —— **设置中心**。随时修改模型型号或更换 API Key。
* `scream help` —— **极客说明书**。查看更多进阶启动参数。

### 维度二：TUI 内置超能力 (斜杠指令)
进入 `scream` 终端后，输入 **`/`** 即可触发自动补全菜单：

| 指令 | 能力描述 | 💡 白话文示例 |
| :--- | :--- | :--- |
| `/look <网址>` | **视觉洞察** | “帮我看看 `https://apple.com` 最近有什么新产品？” (AI 会截图并分析) |
| `/mcp browser` | **浏览器MCP模式** | “开启浏览器实时联网控制。” 开启后模型会优先调用 Browser MCP 工具执行搜索/导航。 |
| `/sandbox on/off`| **物理沙箱** | “穿上防弹衣跑代码。” 开启后，AI 执行的所有危险命令都在 Docker 容器内，绝不伤及主机。 |
| `/team` | **群狼模式** | “我要打群架！” 召唤 Planner（规划师）和 Coder（程序员）多个 Agent 协作完成复杂大项目。 |
| `/memory` | **记忆管理** | “看看你记住了我什么偏好。” 查看、删除或清理 AI 学习到的私人开发规矩。 |
| `/diff` | **代码审计** | “帮我看看我刚才改了啥。” 自动对比 Git 变动，并为你写好 Commit 信息。 |
| `/clear` | **净化思绪** | “我们换个话题。” 清空当前会话的短期上下文，释放内存。 |

> 使用 `/mcp browser` 前，请先在浏览器扩展商店安装并连接 `browser-mcp` 插件（点击 Connect）。

### 维度三：自然语言下达任务
**除了斜杠指令，你完全可以用“人话”吩咐它：**
* *“帮我把下载文件夹里所有的 PDF 文件按日期重命名。”*
* *“在我当前目录下建一个 FastAPI 的 Demo，并写好 Dockerfile。”*
* *“以后你写代码时，必须使用 Google 的缩进规范，帮我记住这条。”* (它会自动永久保存进记忆库)

---

## 🌟 四大核心引擎：Scream-Code 为什么牛逼？

1.  **🛡️ 绝对安全的 Docker 沙箱 (The Shield)**
    AI 的代码执行能力是双刃剑。我们通过底层 `sandbox_env.py` 实现了一套镜像隔离系统。AI 在里面随便折腾，你的本地文件系统依然安全。
2.  **👁️ 睁眼看世界的视觉引擎 (The Vision)**
    基于 Playwright 深度定制。当 AI 遇到无法通过代码获取的网页信息时，它会主动通过视觉快照捕捉 DOM 结构和 UI 布局。
3.  **🧠 越用越聪明的长期记忆 (The Brain)**
    不同于普通的 Chat 机器人，我们内置了 SQLite 数据库。你的每一条反馈、每一个纠正，都会被转化为“潜意识”注入 System Prompt，实现真正的**个性化定制 AI**。
4.  **⚡ 极速 TUI 交互 (The Interface)**
    我们解决了终端渲染“抖动”的难题。通过 30fps 的流式缓冲和虚拟代码块闭合技术，让 AI 吐字像丝绸般顺滑，不再有屏幕狂闪的困扰。

---

## 🧩 近期引擎层能力（长会话 · 流式 · 稳定）

以下为 Python TUI / `query_engine` 路径上的增强，便于你理解「后台在干什么」：

| 能力 | 说明 |
| :--- | :--- |
| **无感上下文压缩** | 当发往模型的非 `system` 消息条数超过阈值时，会在**本轮用户消息写入会话前**对 `llm_conversation_messages` 做摘要折叠（`src/context_compressor.py` + `check_and_compress_history`）。成功则落盘会话 JSON，终端可出现一行 `[🧠 历史记忆已折叠，释放上下文空间...]`；摘要请求失败则静默跳过，不影响当轮对话。 |
| **流式时仍可打断** | 大模型生成时底部输入区保持可用；仅允许提交 `/stop` 终止当前生成（`replLauncher` 并发路径）。回合结束后会清空 `PromptSession.validator`，避免下一轮仍卡在「只能输 /stop」的假象。 |
| **LLM 网络熔断** | `llm_settings` 中配置连接/读超时；超时或网络异常时以友好文案结束当轮，而不是无限挂死（详见 `llm_client`）。 |
| **助手定稿去重** | 流式结束写入 scrollback 前，对相邻重复的段落/行做一次折叠，减轻自我介绍等内容的「重影」感。 |
| **人设与系统提示** | 核心人格与工具纪律集中在 `src/agent/prompt_builder.py` 的 `SYSTEM_PROMPT_CORE`，由 `system_init.build_system_init_message` 与项目记忆、沙箱策略等运行时片段拼接后注入每条 system。 |

---

## 👨‍💻 开发者进阶：定制你的专属 Skill

仓库根目录下的 `skills/` **默认可为空**（仅保留占位 `.gitkeep`）；推荐把自定义斜杠技能放在用户目录 **`~/.scream/skills/`**，与项目仓库解耦、升级时不易冲突。

你可以像堆乐高一样给 Scream-Code 加功能。在 `~/.scream/skills/` 下新建一个 Python 文件，例如：

```python
from src.skills.base_skill import BaseSkill

class MyCoolTool(BaseSkill):
    name = "coffee"  # 指令词：/coffee
    description = "帮我点一杯咖啡"
    
    def execute(self, flavor: str):
        # 在这里写你的自动化逻辑
        return f"已为你下单一杯 {flavor} 咖啡！"
```

**重启 `scream`，你的 AI 就瞬间进化了。**

---

## 📜 结语
**Scream-Code** 不只是一个工具，它是你的**数字分身**。它在你的终端里静静待命，懂你的规矩，看你的屏幕，干你的苦活。

*现在，可以尝试运行 `./install.sh`，感受本地 AI 的终极力量吧！*

## ☀️ 关于
**Scream-Code**  中的部分逻辑，参考了Claude、Claw、Hermes等Agent，并加以改进，强化了中文场景下的各类指令调用与工作流定制，本项目仅供学习参考，欢迎大家交流沟通
