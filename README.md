# 尖叫 Code · Scream Code

> **全能终端 AI OS 内核** —— 基于强大底层 **claw-code** 架构深度定制的 **本地 REPL 智能壳体**：在 **不替换** 镜像侧路由与回合语义的前提下，提供更好的中文 UI、**OpenAI / Anthropic 双核**适配、**SkillsRegistry**、斜杠原生桥接与 **多代理团队编排**（`/team`、`$team`）。

详细分层边界见根目录 **[ARCHITECTURE.md](./ARCHITECTURE.md)**。

---

## 核心特性

| 维度 | 说明 |
|------|------|
| **双核模型引擎** | 通过 `llm_config.json` 的 `api_protocol` 在 **OpenAI 兼容** 与 **Anthropic 兼容** 之间切换；流式解析统一为 `StreamPart`，`query_engine` 与工具链无感。 |
| **沙箱 / 全局越狱** | 根配置 `allow_global_access`：关则文件与 Bash 锁在工作区；开则路径 `~` 展开、系统级操作（配置菜单一键切换，工具 schema 与系统提示即时同步）。 |
| **动态技能** | `SkillsRegistry` 合并内置工具与项目根 **`skills/*.py`**；`findskills` 查看已加载列表；`install_local_skill` 或手动拷贝 + 热重载。 |
| **REPL 斜杠 / 团队** | `/help` 查看分类指令；`/doctor`、`/cost`、`/diff`、`/status` 等桥接原生体检与 Git；`/team` 或 **`$team` 前缀** 启用 **Planner→Coder→Reviewer** 三阶段编排（仍经 **`iter_agent_executor_events`**）。 |

---

## 架构一瞥

```text
用户（REPL） ──► PortRuntime.route_prompt（claw-code 镜像路由）
        ──► QueryEngine.iter_repl_assistant_events_with_runtime（可选 team 多阶段）
                      │
                      ├─► llm_client.iter_agent_executor_events（唯一多轮 tool 闭环）
                      │         └─► chat_completion_stream + SkillsRegistry.execute_tool
                      └─► 会话落盘 / Rich 流式渲染
```

- **配置**：`llm_config.json` + `.env` + 项目根 **`.claw.json`**（启动时加载缓存）+ **`SCREAM.md` / `CLAUDE.md`**（系统提示中的项目记忆）。
- **工具池**：`main tool-pool` 输出含镜像清单 + **SkillsRegistry** 运行时技能附录。

---

## 极速上手

### 1. 环境

```bash
cd /path/to/尖叫-code
python3 -m pip install -r requirements.txt
```

首次执行任意子命令时，入口会尝试自动安装缺失依赖（测试可设 `SCREAM_SKIP_DEPS_CHECK=1` 跳过）。

### 2. 建议 CLI 别名（可选）

```bash
alias scream='python3 -m src.main'
```

下文用 **`scream`** 指代 `python3 -m src.main`。

### 3. 配置模型与权限

```bash
scream config
```

在菜单中：添加/编辑模型（协议 → URL → 型号 → Key）、切换沙箱与越狱。

### 4. 终端对话

```bash
scream repl --llm
```

### 5. 技能

```bash
scream findskills
```

### 6. 常用子命令速查

| 命令 | 作用 |
|------|------|
| `scream summary` | 工作区 Markdown 摘要 |
| `scream manifest` | 模块清单 |
| `scream config` | 交互式配置中心 |
| `scream findskills` | 已注册技能表（Rich） |
| `scream repl --llm` | LLM 交互 REPL（内置 `/help` 斜杠菜单） |

### 7. 验证

```bash
python3 -m unittest discover -s tests -v
```

---

## 开发者：写一个 `skills/` 技能

1. 在仓库根目录 **`skills/`** 下新建 `my_tool.py`（文件名勿以 `_` 开头）。
2. 模块内必须导出：
   - **`TOOL_SCHEMA`**：`{"type":"function","function":{"name":"...","description":"...","parameters":{...}}}`（与 OpenAI Chat Tools 单项格式一致）。
   - **`execute`**：可调用对象，`**kwargs` 与 `parameters.properties` 对齐，返回 **`str`**（作为 tool 结果回给模型）。

示例：

```python
# skills/hello_demo.py
TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "hello_demo",
        "description": "返回一句固定问候，用于演示动态技能。",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "称呼"},
            },
            "required": ["name"],
        },
    },
}


def execute(*, name: str) -> str:
    return f"你好，{name}！（来自 skills/hello_demo.py）"
```

3. 保存后 **`SkillsRegistry.reload_all()`** 会自动加载（或通过模型调用内置工具 **`install_local_skill`** 从本机路径安装 `.py` 到 `skills/` 并热重载）。

**注意**：动态工具名 **不可与内置** `read_local_file` / `write_local_file` / `execute_mac_bash` / `install_local_skill` 重名。

---

## 无 `llm_config` 时的环境变量直连

若尚未配置 `llm_config.json` 激活项，会回退读取 **`BASE_URL`**、**`API_KEY`**、**`MODEL`**（建议在 `.env` 中显式设置，勿依赖默认占位）。

---

## 仓库其它说明

- 活跃实现位于 **`src/`**（Python），测试见 **`tests/`**。
- 若存在 **`rust/`** 工作区，见该目录内 `README.md` / 根目录 `USAGE.md`（与 Python 内核并行演进时参考）。

---

## 免责声明

本仓库为对公开形态的 **Claude Code 类工作流** 的镜像与学习向实现之一，**不隶属于 Anthropic**，亦不代表其对官方产品的背书。
