<!-- 上方为产品扉页；下方为工作区长效记忆与历史快照（/memo、/summary 等），与发布说明独立。 -->

# Scream-Code · 产品扉页与指令速查

> **定位**：极其锋利、**纯本地优先**、**高扩展性** 的 AI 编程终端 —— REPL、工具、记忆与视觉同一流水线。

---

## 四大引擎（与 README 同步）

| 支柱 | 要点 |
|------|------|
| 🔌 **Skill Registry** | `BaseSkill` + `~/.scream/skills/` 热插拔；`/help` 与补全 **动态** 反映注册表 |
| 🛡️ **Docker Sandbox** | `/sandbox on` — 终端执行进容器，挂载 `/workspace` |
| 🧠 **Core Memory** | `SCREAM.md` 叙事 + SQLite 规则；模型工具 **`memorize_project_rule`**；斜杠 **`/memory`** 运维 |
| 👁️ **Playwright Vision** | **`/look <url>`** 截图 + 多模态；**懒安装** pip / Chromium；Rich 进度与 Fatal Panel |

---

## 斜杠指令速查

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

**补全 UX**：`prompt_toolkit` 菜单打开时 **Enter 只确认补全 + 空格**，不提交整行。

---

> **以下章节为项目长效记忆与历史归档**（用户偏好、技能交付物、`/summary` 快照等），**非**产品规格单一事实来源；规格以仓库 **`README.md`** 与源码为准。

---

## 项目核心记忆（尖叫 Code）

### 用户技术偏好
- **输出格式**：单文件 HTML 网站
- **输出路径**：`~/Desktop/screamcode-official.html`
- **风格定位**：赛博朋克 + 科技炫酷，深色背景配霓虹渐变

---

## Skills 项目 · 地理素材核查助手-by李李老师（2026-04-11 完工）

### 项目信息
- **Skill 文件**: `~/Desktop/ScreamCode/skills/地理素材核查助手-by李李老师/geo_fact_checker_by_lili.py`
- **压缩包**: `~/Desktop/地理素材核查助手-by李李老师.zip`
- **依赖文件**: `~/Desktop/ScreamCode/skills/地理素材核查助手-by李李老师/requirements.txt`
- **说明文档**: `~/Desktop/ScreamCode/skills/地理素材核查助手-by李李老师/README.md`
- **状态**: ✅ 已完成并打包

### 核心功能
| 功能 | 说明 |
|------|------|
| 声明提取 | 从素材中智能提取可核查的陈述 |
| 多源检索 | DuckDuckGo 搜索，无需 API Key |
| 来源分类 | 7级权威性权重（官方1.0 → 未知0.3） |
| 客观率评分 | 0-100%量化评估 |
| Top3来源 | 最相关的3条来源及URL |
| 报告生成 | Markdown 格式完整报告 |

### 平台支持
- ✅ Windows（pip install ddgs）
- ✅ macOS
- ✅ Linux

### 来源权威性权重
```
官方机构 > 学术期刊 > 权威媒体 > 专业媒体 > 百科 > 社交媒体 > 未知
1.0        0.95       0.85        0.75          0.65    0.40        0.30
```

### 主函数调用
```python
from geo_fact_checker_by_lili import check_geography_material
check_geography_material(material="珠穆朗玛峰海拔8848米")
```

### 触发关键词
- 核查素材、验证素材、核实地理
- 素材查真、客观性分析、来源核查
- 地理核查

---

## 尖叫 REPL 长效记忆

### 技术偏好
- 记住当前使用 Rust 2021 edition
- 偏好 TS

### 网站风格（科技炫酷风）
- 深色背景 (#0a0a0f / #050508)
- 主色：蓝色 #3b82f6 / #6366f1
- 辅助：橙色 #f97316 / #a855f7
- 点缀：青色 #22d3ee
- 成功：绿色 #10b981
- 英文正文：Inter
- 代码/终端：JetBrains Mono

---

## 长效记忆库 · 尖叫 REPL（`/summary` · 2026-04-11 19:41）

### /summary 快照

```
# Python 移植工作区摘要

移植根目录: `/Users/tod/Desktop/ScreamCode/src`
Python 文件总数: **81**

顶层 Python 模块:
- `skills` (2 个文件) — Python 移植支撑模块
- `projectOnboardingState.py` (1 个文件) — Python 移植支撑模块
- `repl_ui_render.py` (1 个文件) — Python 移植支撑模块
- `query_engine.py` (1 个文件) — 移植编排摘要层
- `task.py` (1 个文件) — 任务级规划结构
- `ink.py` (1 个文件) — Python 移植支撑模块
- `message_prune.py` (1 个文件) — Python 移植支撑模块
- `repl_slash_commands.py` (1 个文件) — Python 移植支撑模块
- `cost_tracker.py` (1 个文件) — Python 移植支撑模块
- `tasks.py` (1 个文件) — Python 移植支撑模块
- `models.py` (1 个文件) — 共享数据类
- `query.py` (1 个文件) — Python 移植支撑模块
- `transcript.py` (1 个文件) — Python 移植支撑模块
- `llm_onboarding.py` (1 个文件) — Python 移植支撑模块
- `bootstrap_graph.py` (1 个文件) — Python 移植支撑模块
- `execution_registry.py` (1 个文件) — Python 移植支撑模块
- `_archive_helper.py` (1 个文件) — Python 移植支撑模块
- `claw_config.py` (1 个文件) — Python 移植支撑模块
- `llm_settings.py` (1 个文件) — Python 移植支撑模块
- `tools.py` (1 个文件) — 工具积压元数据
- `remote_runtime.py` (1 个文件) — Python 移植支撑模块
- `__init__.py` (1 个文件) — 包导出面
- `system_init.py` (1 个文件) — Python 移植支撑模块
- `interactiveHelpers.py` (1 个文件) — Python 移植支撑模块
- `model_manager.py` (1 个文件) — Python 移植支撑模块
- `costHook.py` (1 个文件) — Python 移植支撑模块
- `port_manifest.py` (1 个文件) — 工作区清单生成
- `agent_cancel.py` (1 个文件) — Python 移植支撑模块
- `runtime.py` (1 个文件) — Python 移植支撑模块
- `project_memory.py` (1 个文件) — Python 移植支撑模块
- `deferred_init.py` (1 个文件) — Python 移植支撑模块
- `dialogLaunchers.py` (1 个文件) — Python 移植支撑模块
- `skills_registry.py` (1 个文件) — Python 移植支撑模块
- `QueryEngine.py` (1 个文件) — Python 移植支撑模块
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
- `constants` (1 个文件) — Python 移植支撑模块
- `memdir` (1 个文件) — Python 移植支撑模块
- `server` (1 个文件) — Python 移植支撑模块
- `buddy` (1 个文件) — Python 移植支撑模块
- `utils` (1 个文件) — Python 移植支撑模块
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
- `services` (1 个文件) — Python 移植支撑模块
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

会话 id: 73990624c9324997a5e28eefd598fa5e
已存储对话轮次: 3
已记录权限拒绝: 0
用量累计: 入站=1200847 出站=37619
最大轮次: 400
最大预算 token: 12000000
会话记录已落盘: 是
```

---

## 最近更新（2026-04-11 19:50）

### Skills 更新
- 🗑️ 删除了 `remotion_skill.py`
- ✏️ 重命名：`地理编辑素材核查助手` → `地理素材核查助手-by李李老师`
- 📦 新增跨平台说明文档（Windows/macOS/Linux）
- 📦 打包文件：`~/Desktop/地理素材核查助手-by李李老师.zip`

### 核查记录
- 测试素材：「中国1000年前的郑州其实是水乡」
- 核查结果：客观率 62%（部分客观）
- 报告路径：`~/Desktop/地理素材核查报告.md`
---

## 长效记忆库 · 尖叫 REPL（`/memo` · 2026-04-12 08:22）

记住当前使用 Rust 2021 edition
---

## 长效记忆库 · 尖叫 REPL（`/memo` · 2026-04-12 08:22）

记住当前使用 Rust 2021 edition
---

## 长效记忆库 · 尖叫 REPL（`/memo` · 2026-04-12 08:23）

记住当前使用 Rust 2021 edition
---

## 长效记忆库 · 尖叫 REPL（`/memo` · 2026-04-12 08:23）

- 偏好 A


## Python 编码规范（2026-04-12 强制要求）

### 必须遵守
| 规则 | 要求 |
|------|------|
| 类型注解 | 所有函数参数、返回值、变量都必须标注类型 |
| 引号规范 | 禁止单引号，统一使用双引号 "" |

### 示例
```python
# ✅ 正确
def greet(name: str) -> str:
    return f"Hello, {name}"

# ❌ 错误
def greet(name):
    return 'Hello, ' + name
```

---

## 长效记忆库 · 尖叫 REPL（`/memo` · 2026-04-12 10:29）

- 偏好 A
