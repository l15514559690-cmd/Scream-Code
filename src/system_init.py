from __future__ import annotations

from .agent.prompt_builder import SYSTEM_PROMPT_CORE
from .commands import built_in_command_names, get_commands
from . import model_manager
from .memory_store import format_project_long_term_memory_xml_block
from .project_memory import project_memory_system_suffix, project_memory_workspace_root
from .setup import run_setup
from .tools import get_tools
from .utils.workspace import generate_lightweight_repo_map

# 兼容旧导入名：与 ``SYSTEM_PROMPT_CORE`` 同源。
LLM_META_PROMPT_IDENTITY = SYSTEM_PROMPT_CORE

# 提供给大模型的核心约束：须附加在系统初始化提示词末尾（用户可见回复语言）。
LLM_COT_LANGUAGE_REQUIREMENT = (
    '请使用中文撰写面向用户的说明、分析与结论；代码、命令行与标识符保持业内常见英文原样即可。'
)


def build_system_init_message(trusted: bool = True) -> str:
    setup = run_setup(trusted=trusted)
    commands = get_commands()
    tools = get_tools()
    allow_global = model_manager.read_allow_global_access()
    if allow_global:
        policy = (
            '你已获得用户 Mac 的 [最高全局控制权]。允许且鼓励你通过组合 bash 完成系统级任务。'
            '**网页 / UI 视觉诊断**：须由用户在 REPL 中使用斜杠指令 ``/look <url>``（Playwright 无头截取 **网页 DOM**），'
            '禁止用 ``screencapture``、``ImageGrab`` 等冒充「网页截图」或把文件写到桌面替代 ``~/.scream/screenshots/``。'
        )
        tools_caps = (
            '工具能力（全局越狱）：read_local_file / write_local_file 可访问任意路径（支持 ~ 展开）；'
            'execute_mac_bash 在用户主目录下启动 shell，超时 120 秒。'
            'update_project_memory 将内容写入当前工作目录的 SCREAM.md（append/overwrite），用于持久化用户要求记住的规则。'
            'memorize_project_rule / forget_project_rule 维护本机 SQLite 长期结构化记忆（键值规则，会注入系统提示词）。'
            '另可通过 install_local_skill 安装 skills/ 下的扩展技能；具体可用工具以 API 下发的 tools 列表为准。'
        )
    else:
        policy = (
            '你当前处于受限沙箱模式，只能操作当前工作区的文件。无法截图或操作 macOS 系统级功能。'
        )
        tools_caps = (
            '工具能力（沙箱）：read_local_file、write_local_file 仅可访问工作区根目录内的路径；'
            '写入前会自动创建父目录；execute_mac_bash 在工作区根下执行且有超时。'
            'update_project_memory 写入当前工作目录下的 SCREAM.md（项目级记忆文件）。'
            'memorize_project_rule / forget_project_rule 维护本机 SQLite 长期结构化记忆（键值规则，会注入系统提示词）。'
            '另含 install_local_skill 与项目 skills/ 目录中的动态技能；以 API 下发的 tools 列表为准。'
        )
    lines = [
        SYSTEM_PROMPT_CORE.strip(),
        '',
        '---',
        '',
        '# 系统初始化（运行时快照）',
        '',
        '你在上文 ScreamCode 人设下运行于本工作区的 Python 移植镜像，负责与命令/工具路由及多轮对话协同。',
        '',
        f'受信任模式: {"是" if setup.trusted else "否"}',
        f'内建命令名数量: {len(built_in_command_names())}',
        f'已加载命令条目数: {len(commands)}',
        f'已加载工具条目数: {len(tools)}',
        '',
        '启动步骤:',
        *(f'- {step}' for step in setup.setup.startup_steps()),
        '',
        policy,
        tools_caps,
        '',
        LLM_COT_LANGUAGE_REQUIREMENT,
    ]
    base = '\n'.join(lines) + project_memory_system_suffix(project_memory_workspace_root())

    # ── Repo Map 注入 ─────────────────────────────────────────────────────────
    # 在 System Prompt 末尾注入当前工作区的轻量代码地图，
    # 让 Agent 在盲人摸象之前就能看到全局目录结构，不再瞎猜路径。
    _REPO_MAP_SECTION = '\n\n【当前工作区代码地图 (Repo Map)】\n以下是项目的目录结构（最大深度 3 层），请在打算读取或修改文件前，务必参考此地图，不要瞎猜路径：\n```text\n{repo_map}\n```'

    try:
        ws_root = project_memory_workspace_root()
        repo_map = generate_lightweight_repo_map(ws_root, max_depth=3)
    except Exception:
        repo_map = '（无法生成代码地图，工作区路径解析失败）'

    base += _REPO_MAP_SECTION.format(repo_map=repo_map)
    # ── /Repo Map 注入 ────────────────────────────────────────────────────────

    ltm = format_project_long_term_memory_xml_block()
    if ltm:
        return f'{base}\n\n{ltm}'
    return base
