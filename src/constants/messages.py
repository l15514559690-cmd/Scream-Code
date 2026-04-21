from __future__ import annotations

AGENT_EXEC_TIMEOUT_SEC = 60.0

MSG_TIMEOUT_FUSE = (
    '[System Error: Execution Timeout] 你的命令执行超过了 60 秒被系统强制熔断。'
    '这通常是因为代码中存在死循环，或者命令卡在了需要人工交互的输入上 (如 y/n)。'
    '请修改代码或加上 -y 参数后重试。'
)

MSG_TOOL_EXCEPTION = (
    '[Tool Execution Exception] 工具执行发生底层崩溃，错误信息: {error_trace}。'
    '请检查你传入的参数是否合法，或尝试使用其他策略。'
)

MSG_LLM_NETWORK_ERROR = '\n\n[💥 引擎熔断：网络请求超时或连接失败，请检查网络/代理设置后重试]'

MSG_LLM_PROVIDER_KEY_MISSING = (
    '[💥 引擎熔断：未检测到 {provider} 的环境变量密钥 (如 {expected_env_var})，请检查配置后重试。]'
)

