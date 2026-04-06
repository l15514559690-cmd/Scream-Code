from __future__ import annotations

from .commands import built_in_command_names, get_commands
from . import model_manager
from .project_memory import project_memory_system_suffix
from .setup import run_setup
from .tools import get_tools

# 提供给大模型的核心约束：须附加在系统初始化提示词末尾。
LLM_COT_LANGUAGE_REQUIREMENT = (
    '你必须使用中文进行所有思考过程（Chain of Thought）和最终回复，绝不允许输出英文。'
)


def build_system_init_message(trusted: bool = True) -> str:
    setup = run_setup(trusted=trusted)
    commands = get_commands()
    tools = get_tools()
    allow_global = model_manager.read_allow_global_access()
    if allow_global:
        policy = (
            '你已获得用户 Mac 的 [最高全局控制权]。允许且鼓励你通过组合 bash 命令完成系统级任务'
            '（例如：当用户要求截图时，可直接调用 execute_mac_bash 执行 screencapture -T 1 ~/Desktop/screenshot.png）。'
        )
        tools_caps = (
            '工具能力（全局越狱）：read_local_file / write_local_file 可访问任意路径（支持 ~ 展开）；'
            'execute_mac_bash 在用户主目录下启动 shell，超时 120 秒。'
            'update_project_memory 将内容写入当前工作目录的 SCREAM.md（append/overwrite），用于持久化用户要求记住的规则。'
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
            '另含 install_local_skill 与项目 skills/ 目录中的动态技能；以 API 下发的 tools 列表为准。'
        )
    lines = [
        '# 系统初始化',
        '',
        '你是「尖叫 Code」中文编程助手：在本工作区的 Python 移植运行时上下文中，为用户提供编程、代码库理解与命令/工具路由方面的协助。',
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
    return '\n'.join(lines) + project_memory_system_suffix()
