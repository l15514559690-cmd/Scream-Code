# 尖叫 Code（Scream Code）

跑在终端里的 **AI 编程助手**：中文界面、多模型、读写代码与运行命令。

---

## 安装（一行）

下载或克隆本仓库后，在**项目根目录**执行：

```bash
bash install.sh
```

脚本会自动检查 `python3` 与 `cargo`、创建 `.venv` 并安装依赖、编译安装 `scream`。完成后按屏幕提示执行 `source ~/.zshrc`（或脚本给出的配置文件路径），并确保 `~/.cargo/bin` 在 `PATH` 中。

---

## 配置模型（`.env`）

1. 复制环境变量样板：`cp .env.example .env`
2. 用编辑器打开 `.env`，把 API Key、接口地址等改成你的真实配置（字段说明见 `.env.example`）。
3. （推荐）多模型档：`cp llm_config.json.example llm_config.json`，再运行 `scream config` 按提示配置；**勿把含密钥的文件提交到 Git**。

没有 `llm_config.json` 时，可用 `.env` 兜底（OpenAI 兼容示例）：

```env
BASE_URL=https://api.openai.com/v1
API_KEY=sk-xxxxxxxx
MODEL=gpt-4o-mini
```

---

## 常用斜杠指令

对话里输入以 `/` 开头的命令；**完整列表以界面里 `/help` 为准**。

| 指令 | 作用 |
|------|------|
| `/help` | 查看帮助与全部命令 |
| `/memo` | 长效记忆（整理或追加要点） |
| `/team` | 多代理编排（「群狼」模式开关） |
| `/new` | 新开会话 |
| `/stop` | 中断当前生成 |
| `/exit` | 退出（亦常见 `/quit`） |

配置好 `.env` 后，在终端输入 **`scream`** 即可启动（默认优先进入 Rust 全屏 TUI）。

---

## 免责声明

本仓库为学习向的 Claude Code 类工作流实现之一，仅供学习与交流。使用第三方 API 时请遵守各厂商条款，**勿将真实密钥提交到 Git**。

更多架构与开发说明见 [`ARCHITECTURE.md`](./ARCHITECTURE.md)。
