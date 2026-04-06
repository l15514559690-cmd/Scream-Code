# 尖叫 Code · 架构说明书

本文档划定三层边界，确保 **claw-code 原生镜像链路** 与 **壳层扩展** 职责清晰：壳层只做中文体验、双核 LLM 适配与 **本地 REPL 展示**，**不另起一套「第二套 Agent 大脑」**。

---

## 一、[底层灵魂区] — 继承自 claw-code 镜像

**定位**：TypeScript 归档在 Python 中的 **行为与数据面镜像**，包含思考与调度的 **语义来源**（本仓库以 Python 复刻，而非运行时内嵌另一进程）。

| 组件 | 职责 |
|------|------|
| **`PortRuntime`** | `route_prompt`：基于 `PORTED_COMMANDS` / `PORTED_TOOLS` 的 **token 路由**；`bootstrap_session` / `run_turn_loop`：**多轮用户回合**与镜像命令/工具垫片执行。 |
| **`execution_registry`** | 将路由命中映射到镜像命令/工具的 **execute 垫片**。 |
| **`commands.py` / `tools.py`** | 归档侧命令与工具 **元数据清单**（与 `tool-pool` CLI 输出一致）。 |
| **`query_engine`（会话部分）** | 用户轮次上限、budget、transcript、`submit_message` 中非 LLM 路径、结构化输出封装；可选 **team** 多阶段编排（Planner → Coder → Reviewer），每阶段仍经 **`iter_agent_executor_events`**。 |

**原则**：不在此层之上用「另一套 while 循环」**替代** `PortRuntime` 的路由语义；新增能力应 **挂接** 到上述链路上的明确扩展点。

---

## 二、[适配与扩展区] — 壳层允许改动的范围

**定位**：把 **外部世界**（OpenAI/Anthropic API、`.env`、`llm_config.json`、项目根 **`.claw.json`**）与 **镜像内核** 接起来。

| 组件 | 职责 |
|------|------|
| **`llm_client`** | **LLM Provider**：`chat_completion_stream`、协议分流、流式 `StreamPart`；**唯一**承载 **`iter_agent_executor_events`**（多轮 `tool_calls` + 写回 `messages`）。此处调用 **SkillsRegistry.execute_tool**，与下游 API 格式翻译集中在一处。 |
| **`model_manager`** | 双核配置、`allow_global_access`、交互式 config、`.env` 同步。 |
| **`skills_registry`** | 内置四工具 + `skills/*.py` 动态加载；**`get_all_schemas()`** 即发给模型的 `tools`；**与 `tool_pool` 输出联动**（`ToolPool.as_markdown` 附录运行时技能表），避免与镜像工具池「两张皮」。 |
| **`llm_settings`** | 连接参数读取、dotenv。 |
| **`claw_config`** | 启动时读取并缓存项目根 **`.claw.json`**（与 `.env`、项目记忆并列的配置层）。 |
| **`agent_tools`** | 内置技能实现体（读写、bash、install_skill）；由 Registry 注册，而非散落调用。 |

**原则**：**禁止** 在 `replLauncher` 再写一套 tool 轮次循环；**禁止** 在 `query_engine` 复制 `MAX_AGENT_TOOL_ROUNDS` 逻辑（已迁至 `llm_client`）。

---

## 三、[展示区] — 纯消费者

**定位**：**只消费** 下层生成的事件或文本，**不做** 业务向的重试、tool 轮次决策。

| 组件 | 职责 |
|------|------|
| **`replLauncher`** | Rich / prompt_toolkit；通过 **`QueryEnginePort.iter_repl_assistant_events_with_runtime`** 取事件流，仅负责渲染与 Ctrl+C 关闭生成器；team 模式下消费 **`team_agent`** 等事件并着色前缀。 |
| **`repl_slash_commands.py`** | 斜杠指令拦截与 Rich 输出；**透传** 体检、Git、`/status` 等，不重复实现 LLM 闭环。 |

**原则**：路由必须来自 **`PortRuntime`**，经 **`QueryEnginePort.iter_repl_assistant_events_with_runtime`** 进入 LLM 链。

---

## 四、数据流简图（单轮用户消息 + LLM）

```text
用户输入（REPL）
  → PortRuntime.route_prompt（底层灵魂）
  → QueryEnginePort._build_llm_chat_messages（会话上下文）
  → llm_client.iter_agent_executor_events（唯一 tool 多轮闭环）
       → chat_completion_stream（OpenAI / Anthropic）
       → SkillsRegistry.execute_tool
  → QueryEnginePort 落盘 usage / transcript，yield finished
  → REPL 仅打印与流式渲染
```

---

## 五、与「原生 claw-code」的关系说明

本仓库 **不包含** 闭源的 TypeScript 运行时二进制；**原生** 指 **parity 镜像**（归档清单、路由形状、`turn-loop` CLI 等）所定义的 **契约**。壳层扩展 **不得破坏** 这些契约的可追踪性：新工具进 **SkillsRegistry** 并在 **tool-pool** 中可见。

若需调整多轮 tool 上限或协议细节，应优先修改 **`llm_client`** 中的单一闭环，并同步文档与本文件。
