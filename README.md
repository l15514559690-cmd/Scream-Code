# 尖叫 Code（Scream Code）

终端里的中文 AI 编程助手（多模型、读写代码、跑命令）。

<img width="839" height="453" alt="image" src="https://github.com/user-attachments/assets/c01e6e29-f3aa-46a6-a5f5-fe727cb6f9a2" />

---

## 安装

在**仓库根目录**执行：

```bash
bash install.sh
```

然后加载 shell 配置（脚本写入的路径以终端提示为准，常见为 `~/.zshrc`）：

```bash
source ~/.zshrc
```

确保 **`~/.cargo/bin` 在 `PATH`**（`rustup` 一般会配好；若 `which scream` 找不到二进制，把 `export PATH="$HOME/.cargo/bin:$PATH"` 写进配置文件后重开终端）。

> `install.sh` 会创建 `.venv`、安装 `requirements.txt`、执行 `cargo install` 安装 **`~/.cargo/bin/scream`**，并写入 **`scream`** / **`scream-config`** 函数。升级过仓库后若命令异常，可再跑一次 `bash install.sh` 刷新函数块。

---

## 命令（逻辑说明）

`install.sh` 定义的 **`scream`**：先 `cd` 到仓库根并激活 `.venv`；**仅当没有任何参数**且存在 `~/.cargo/bin/scream` 时，才 **`exec` Rust 全屏 TUI**。  
只要有参数（例如 `repl`、`config`），一律走 **`python3 -m src.main <子命令> …`**。因此 **Rust 专有参数**（如 `--line-repl`、`--permission-mode`）不要写成 `scream --xxx`，应使用：

```bash
~/.cargo/bin/scream --help
```

或未装全局二进制时：在仓库内 `cd rust && cargo run -p scream-cli -- --help`。

| 用途 | 命令 |
|------|------|
| 全屏 TUI（Rust） | `scream`（**不要带参数**） |
| 配置大模型 | `scream-config` 或 `scream config` |
| Python 中文 REPL | `scream repl`（可加 `--no-llm` 仅看欢迎页） |
| 查看 Skills | `scream findskills` |

**可选**：在 `~/.zshrc` 里 `source "/你的路径/ScreamCode/scripts/screamcode-tui.sh"`，之后可用 **`screamcode-tui`**（或 **`scream-tui`**）从任意目录起 TUI；该脚本会把仓库根设为 `SCREAM_HOME`，并把参数原样交给 Rust `scream`。

**无 shell 函数时**：`cd` 到仓库根，`source .venv/bin/activate`，再执行 `python3 -m src.main repl|config|findskills|…`。仓库根也可运行 **`./start.sh`**（优先已安装的 Rust `scream`，否则尝试本地编译产物，最后回退 Python `repl`）。

退出 TUI：`Ctrl+C`、`Esc`，或 `/exit`、`/quit`（以当前版本为准）。

---

## 配置 API（`.env` / `llm_config.json`）

1. `cp .env.example .env`，按文件内注释填 Key 与地址；**勿提交 Git**。  
2. 多档模型：`cp llm_config.json.example llm_config.json`，再运行 **`scream-config`**，按提示操作；`llm_config.json` 里 **`api_key_env_name`** 必须与 `.env` 里变量名一致。  
3. 没有 `llm_config.json` 时，可在 `.env` 用 OpenAI 兼容兜底，例如：

```env
BASE_URL=https://api.openai.com/v1
API_KEY=sk-xxxxxxxx
MODEL=gpt-4o-mini
```

更多厂商变量名与进阶项见 [`.env.example`](./.env.example)。

---

## 斜杠指令（对话里输入）

完整列表以界面 **`/help`** 为准。常用：

| 指令 | 作用 |
|------|------|
| `/help` | 帮助 |
| `/memo` | 长效记忆 |
| `/team` | 多代理（群狼） |
| `/new` | 新会话 |
| `/stop` | 中断生成 |
| `/exit` | 退出（常同 `/quit`） |

---

## 免责声明

学习与交流用途；使用第三方 API 须遵守其条款，**勿将密钥推送到 Git**。开发向说明见 [`ARCHITECTURE.md`](./ARCHITECTURE.md)。
