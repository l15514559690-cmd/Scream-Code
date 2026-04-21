from __future__ import annotations

import copy
import asyncio
import json
import logging
import os
import traceback
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from openai import OpenAI

from . import agent_cancel
from .constants.messages import (
    MSG_LLM_NETWORK_ERROR,
    MSG_LLM_PROVIDER_KEY_MISSING,
    MSG_TOOL_EXCEPTION,
)
from .llm_settings import (
    LLM_CONNECT_TIMEOUT,
    LLM_READ_TIMEOUT,
    LlmConnectionSettings,
    expected_api_key_env_var,
    parse_model_route,
)
from .message_prune import prune_historical_messages

if TYPE_CHECKING:  # pragma: no cover
    from .mcp_manager import MCPClient


class LlmClientError(Exception):
    """配置缺失或调用方显式拒绝发起请求时使用。"""


def get_openai_agent_tools() -> list[dict[str, Any]]:
    """合并内置 Agent 工具与项目 ``skills/*.py`` 动态插件；每次调用刷新 schema（沙箱开关等即时生效）。"""
    from .tools_registry import get_tools_registry

    return get_tools_registry().get_all_schemas()


# 可选硬上限（防模型异常死循环）；默认 100 轮（1.0）；可用环境变量覆盖或关闭
_AGENT_TOOL_CAP_ENV = 'SCREAM_MAX_AGENT_TOOL_ROUNDS'
_AGENT_TOOL_CAP_MAX = 10_000_000
_DEFAULT_AGENT_TOOL_ROUNDS = 100

# 兼容旧文档/外部引用：与 :func:`agent_tool_iteration_cap` 默认一致
MAX_AGENT_TOOL_ROUNDS = _DEFAULT_AGENT_TOOL_ROUNDS
ANTHROPIC_STREAM_MAX_TOKENS = 65_536


def agent_tool_iteration_cap() -> int | None:
    """
    单次用户消息内「模型 ↔ 工具」闭环的最大迭代次数。

    - **默认**：``100``（未设置 ``SCREAM_MAX_AGENT_TOOL_ROUNDS`` 时）。
    - ``None``：不限制（直至 ``finish_reason != tool_calls``）。
    - 正整数：硬上限（最大 10_000_000）。

    以下环境变量取值视为**不限制**：``0``、``unlimited``、``none``、``inf``、``infinity``（大小写不敏感）。
    """
    raw = (os.environ.get(_AGENT_TOOL_CAP_ENV) or '').strip().lower()
    if raw in ('0', 'unlimited', 'none', 'inf', 'infinity'):
        return None
    if not raw:
        return _DEFAULT_AGENT_TOOL_ROUNDS
    try:
        n = int(raw, 10)
    except ValueError:
        return None
    if n <= 0:
        return None
    return min(n, _AGENT_TOOL_CAP_MAX)


def max_agent_tool_rounds() -> int:
    """兼容测试与旧代码：返回正整数；无上限时返回 ``10**9`` 作为占位。"""
    cap = agent_tool_iteration_cap()
    return cap if cap is not None else 10**9


@dataclass(frozen=True)
class StreamPart:
    """流式 Chat Completions 的单次产出：文本、工具调用增量、结束原因与用量。"""

    text_delta: str | None = None
    tool_index: int | None = None
    tool_id: str | None = None
    tool_name_fragment: str | None = None
    tool_arguments_fragment: str | None = None
    finish_reason: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


@dataclass
class ToolCallAccumulator:
    """按 OpenAI / Anthropic 流式 index 拼接完整 tool_calls。"""

    _by_index: dict[int, dict[str, str]] = field(default_factory=dict)

    def consume(self, part: StreamPart) -> None:
        if part.tool_index is None:
            return
        idx = part.tool_index
        slot = self._by_index.setdefault(idx, {'id': '', 'name': '', 'arguments': ''})
        if part.tool_id:
            slot['id'] = part.tool_id
        if part.tool_name_fragment:
            slot['name'] += part.tool_name_fragment
        if part.tool_arguments_fragment:
            slot['arguments'] += part.tool_arguments_fragment

    def has_tool_calls(self) -> bool:
        for slot in self._by_index.values():
            if (slot.get('name') or '').strip():
                return True
        return False

    def as_openai_tool_calls(self) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for idx in sorted(self._by_index):
            s = self._by_index[idx]
            name = (s.get('name') or '').strip()
            if not name:
                continue
            tid = (s.get('id') or '').strip() or f'call_{idx}'
            args = s.get('arguments') or '{}'
            out.append(
                {
                    'id': tid,
                    'type': 'function',
                    'function': {'name': name, 'arguments': args},
                }
            )
        return out


@dataclass
class ChatCompletionResult:
    text: str
    input_tokens: int
    output_tokens: int
    #: 供 ``QueryEnginePort`` 持久化多轮对话（含本轮 tool 往返）；无则未更新。
    conversation_messages: list[dict[str, Any]] | None = None


_KEY_SETUP_HINT = '未检测到密钥，请执行 scream config 进行设置'
_LLM_TRANSPORT_FUSE_MSG = MSG_LLM_NETWORK_ERROR


def _raise_if_missing_key(settings: LlmConnectionSettings) -> None:
    if (settings.api_key or '').strip():
        return
    bits: list[str] = [_KEY_SETUP_HINT]
    if settings.profile_alias:
        bits.append(f'当前模型：{settings.profile_alias}。')
    if settings.api_key_env_name:
        bits.append(f'请在项目根 `.env` 中配置 `{settings.api_key_env_name}`。')
    raise LlmClientError(' '.join(bits))


def _raise_if_missing_provider_key(
    settings: LlmConnectionSettings,
    *,
    provider: str,
) -> None:
    expected_env_var = expected_api_key_env_var(provider)
    if (settings.api_key or '').strip():
        return
    raise LlmClientError(
        MSG_LLM_PROVIDER_KEY_MISSING.format(
            provider=provider,
            expected_env_var=expected_env_var,
        )
    )


def _map_llm_auth_exception(exc: BaseException) -> LlmClientError | None:
    """将明显的鉴权失败映射为统一的中文引导（含无效 / 过期密钥）。"""
    try:
        import openai

        if isinstance(exc, openai.AuthenticationError):
            return LlmClientError(_KEY_SETUP_HINT)
    except ImportError:
        pass
    try:
        import anthropic

        if isinstance(exc, anthropic.AuthenticationError):
            return LlmClientError(_KEY_SETUP_HINT)
    except ImportError:
        pass
    status = getattr(exc, 'status_code', None)
    if status == 401:
        return LlmClientError(_KEY_SETUP_HINT)
    resp = getattr(exc, 'response', None)
    if resp is not None and getattr(resp, 'status_code', None) == 401:
        return LlmClientError(_KEY_SETUP_HINT)
    return None


def _is_timeout_or_network_exception(exc: BaseException) -> bool:
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return True
    try:
        import httpx

        if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError)):
            return True
    except ImportError:
        pass
    try:
        import openai

        timeout_err = getattr(openai, 'APITimeoutError', None)
        conn_err = getattr(openai, 'APIConnectionError', None)
        cls_list = tuple(c for c in (timeout_err, conn_err) if isinstance(c, type))
        if cls_list and isinstance(exc, cls_list):
            return True
    except ImportError:
        pass
    try:
        import anthropic

        timeout_err = getattr(anthropic, 'APITimeoutError', None)
        conn_err = getattr(anthropic, 'APIConnectionError', None)
        cls_list = tuple(c for c in (timeout_err, conn_err) if isinstance(c, type))
        if cls_list and isinstance(exc, cls_list):
            return True
    except ImportError:
        pass
    return False


def _build_httpx_timeout() -> Any:
    try:
        import httpx

        return httpx.Timeout(
            timeout=LLM_READ_TIMEOUT,
            connect=LLM_CONNECT_TIMEOUT,
            read=LLM_READ_TIMEOUT,
            write=LLM_READ_TIMEOUT,
            pool=LLM_CONNECT_TIMEOUT,
        )
    except ImportError:
        # 兜底：SDK 也接受 float 语义（总超时）
        return float(LLM_READ_TIMEOUT)


def openai_tools_to_anthropic(openai_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """将 OpenAI ``tools`` JSON 转为 Anthropic ``tools``（name / description / input_schema）。"""
    out: list[dict[str, Any]] = []
    for block in openai_tools:
        fn = block.get('function') if isinstance(block, dict) else None
        if not isinstance(fn, dict):
            continue
        name = str(fn.get('name', '')).strip()
        if not name:
            continue
        desc = str(fn.get('description', '') or '')
        params = fn.get('parameters')
        if not isinstance(params, dict):
            params = {'type': 'object', 'properties': {}}
        out.append(
            {
                'name': name,
                'description': desc,
                'input_schema': params,
            }
        )
    return out


def _parse_tool_arguments(raw: str | dict[str, Any] | None) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw) if isinstance(raw, str) and raw.strip() else {}
    except json.JSONDecodeError:
        return {}


_MCP_BROWSER_TIMEOUT_MSG = '[系统] 浏览器响应超时，建议检查网络或重启 MCP 引擎'
_log = logging.getLogger(__name__)


def _summarize_tool_arg_value(val: Any, *, max_len: int = 160) -> str:
    if val is None:
        return 'null'
    if isinstance(val, bool):
        return 'true' if val else 'false'
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        s = val.replace('\n', ' ').strip()
        if len(s) > max_len:
            return s[: max_len - 1] + '…'
        return s
    try:
        s = json.dumps(val, ensure_ascii=False, separators=(',', ':'))
    except (TypeError, ValueError):
        s = str(val)
    if len(s) > max_len:
        return s[: max_len - 1] + '…'
    return s


def _format_tool_call_progress_hint(name: str, args: dict[str, Any]) -> str:
    n = (name or '').strip() or 'tool'
    if not args:
        return f'[🌐 MCP 正在执行: {n}()]'
    parts: list[str] = []
    for k, v in list(args.items())[:6]:
        key = str(k)
        if not key:
            continue
        parts.append(f'{key}={_summarize_tool_arg_value(v)}')
    inner = ', '.join(parts)
    if len(args) > 6:
        inner += ', …'
    return f'[🌐 MCP 正在执行: {n}({inner})]'


def _mcp_client_error_is_timeout(msg: str) -> bool:
    s = (msg or '').lower()
    return '超时' in msg or 'timeout' in s


def _mcp_client_error_is_disconnect(msg: str) -> bool:
    s = (msg or '').lower()
    keys = (
        'pipe',
        'broken pipe',
        'connection reset',
        'connection closed',
        'disconnect',
        '未连接',
        'stopped',
    )
    return any(k in s for k in keys)


def _short_exception_trace(exc: BaseException, *, max_lines: int = 6) -> str:
    lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
    merged = ''.join(lines).strip().splitlines()
    if len(merged) > max_lines:
        merged = merged[:max_lines]
    return '\n'.join(merged).strip()


def _parse_data_url_image(url: str) -> tuple[str | None, str | None]:
    """解析 ``data:image/png;base64,...`` → ``(media_type, base64_payload)``。"""
    if not isinstance(url, str) or not url.startswith('data:'):
        return None, None
    try:
        meta, _, b64 = url.partition(',')
        if 'base64' not in meta.lower():
            return None, None
        semi = meta.find(';')
        mt = meta[5:semi].strip() if semi > 5 else 'image/png'
        return mt, b64.strip()
    except (ValueError, IndexError):
        return None, None


def openai_user_content_to_anthropic(content: Any) -> Any:
    """
    OpenAI Chat ``user`` 的 ``content``（字符串或多模态 part 列表）→ Anthropic ``content``。
    支持 ``text`` 与 ``image_url``（仅处理 ``data:...;base64,...`` 形式）。
    """
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content or '')
    blocks: list[dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        ptype = part.get('type')
        if ptype == 'text':
            blocks.append({'type': 'text', 'text': str(part.get('text', '') or '')})
        elif ptype == 'image_url':
            iu = part.get('image_url')
            url = ''
            if isinstance(iu, dict):
                url = str(iu.get('url', '') or '')
            elif isinstance(iu, str):
                url = iu
            mt, b64 = _parse_data_url_image(url)
            if mt and b64:
                blocks.append(
                    {
                        'type': 'image',
                        'source': {
                            'type': 'base64',
                            'media_type': mt,
                            'data': b64,
                        },
                    }
                )
    if not blocks:
        return ''
    if len(blocks) == 1 and blocks[0].get('type') == 'text':
        return str(blocks[0].get('text', '') or '')
    return blocks


def openai_messages_to_anthropic_messages(
    messages: list[dict[str, Any]],
) -> tuple[str | None, list[dict[str, Any]]]:
    """
    提取全部 ``role: system`` 拼接为顶层 ``system`` 文本，并转换为 Anthropic ``messages``。
    将 OpenAI 的 ``tool`` 轮次合并为单条 user 消息（``tool_result`` 块列表）。
    """
    system_chunks: list[str] = []
    rest: list[dict[str, Any]] = []
    for m in messages:
        if not isinstance(m, dict):
            continue
        if m.get('role') == 'system':
            c = m.get('content')
            if isinstance(c, str) and c.strip():
                system_chunks.append(c)
        else:
            rest.append(m)
    system_text = '\n\n'.join(system_chunks) if system_chunks else None

    anth: list[dict[str, Any]] = []
    i = 0
    while i < len(rest):
        m = rest[i]
        role = m.get('role')
        if role == 'user':
            content = m.get('content')
            anth.append({'role': 'user', 'content': openai_user_content_to_anthropic(content)})
            i += 1
        elif role == 'assistant':
            blocks: list[dict[str, Any]] = []
            txt = m.get('content')
            if isinstance(txt, str) and txt.strip():
                blocks.append({'type': 'text', 'text': txt})
            for tc in m.get('tool_calls') or []:
                if not isinstance(tc, dict):
                    continue
                fn = tc.get('function') if isinstance(tc.get('function'), dict) else {}
                name = str(fn.get('name', '') or '')
                tid = str(tc.get('id', '') or '')
                inp = _parse_tool_arguments(fn.get('arguments'))
                blocks.append({'type': 'tool_use', 'id': tid, 'name': name, 'input': inp})
            if not blocks:
                blocks.append({'type': 'text', 'text': ''})
            anth.append({'role': 'assistant', 'content': blocks})
            i += 1
        elif role == 'tool':
            results: list[dict[str, Any]] = []
            while i < len(rest) and rest[i].get('role') == 'tool':
                t = rest[i]
                results.append(
                    {
                        'type': 'tool_result',
                        'tool_use_id': str(t.get('tool_call_id', '') or ''),
                        'content': str(t.get('content', '') or ''),
                    }
                )
                i += 1
            anth.append({'role': 'user', 'content': results})
        else:
            i += 1
    return system_text, anth


def _anthropic_stop_to_finish(stop_reason: str | None) -> str:
    if stop_reason == 'tool_use':
        return 'tool_calls'
    return 'stop'


def _open_chat_stream(
    client: OpenAI,
    *,
    use_model: str,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
) -> Iterator[Any]:
    create_kw: dict[str, Any] = {
        'model': use_model,
        'messages': messages,
        'stream': True,
    }
    if tools is not None:
        create_kw['tools'] = tools
        create_kw['tool_choice'] = 'auto'
    try:
        return client.chat.completions.create(
            **create_kw,
            stream_options={'include_usage': True},
        )
    except TypeError:
        return client.chat.completions.create(**create_kw)


def _stream_parts_from_openai_chunk(chunk: Any) -> list[StreamPart]:
    parts: list[StreamPart] = []
    choices = getattr(chunk, 'choices', None) or []
    if not choices:
        return parts
    c0 = choices[0]
    delta = getattr(c0, 'delta', None)
    if delta is not None:
        piece = getattr(delta, 'content', None) or ''
        if piece:
            parts.append(StreamPart(text_delta=piece))
        tool_calls = getattr(delta, 'tool_calls', None) or []
        for tc in tool_calls:
            idx = getattr(tc, 'index', None)
            tid = getattr(tc, 'id', None) or None
            fn = getattr(tc, 'function', None)
            name_frag = ''
            args_frag = ''
            if fn is not None:
                n = getattr(fn, 'name', None)
                if n:
                    name_frag = n
                a = getattr(fn, 'arguments', None)
                if a:
                    args_frag = a
            eff_idx: int | None = idx if isinstance(idx, int) else None
            if eff_idx is None and (name_frag or args_frag or tid):
                eff_idx = 0
            if eff_idx is None:
                continue
            parts.append(
                StreamPart(
                    tool_index=eff_idx,
                    tool_id=tid if isinstance(tid, str) else None,
                    tool_name_fragment=name_frag or None,
                    tool_arguments_fragment=args_frag or None,
                )
            )
    fr = getattr(c0, 'finish_reason', None)
    if fr:
        parts.append(StreamPart(finish_reason=fr))
    return parts


def _chat_completion_stream_openai(
    messages: list[dict[str, Any]],
    settings: LlmConnectionSettings,
    *,
    use_model: str,
    tools: list[dict[str, Any]] | None,
) -> Iterator[StreamPart]:
    client = OpenAI(
        base_url=settings.base_url,
        api_key=settings.api_key,
        timeout=_build_httpx_timeout(),
    )
    stream = _open_chat_stream(
        client, use_model=use_model, messages=messages, tools=tools
    )
    for chunk in stream:
        for p in _stream_parts_from_openai_chunk(chunk):
            yield p
        usage = getattr(chunk, 'usage', None)
        if usage is not None:
            pt = getattr(usage, 'prompt_tokens', None)
            ct = getattr(usage, 'completion_tokens', None)
            if pt is not None or ct is not None:
                yield StreamPart(
                    prompt_tokens=int(pt) if pt is not None else 0,
                    completion_tokens=int(ct) if ct is not None else 0,
                )


def _chat_completion_stream_anthropic(
    messages: list[dict[str, Any]],
    settings: LlmConnectionSettings,
    *,
    use_model: str,
    tools: list[dict[str, Any]] | None,
) -> Iterator[StreamPart]:
    from anthropic import Anthropic

    system_text, anth_msgs = openai_messages_to_anthropic_messages(messages)
    anth_tool_list = (
        openai_tools_to_anthropic(tools) if tools else None
    )

    base_kw: dict[str, Any] = {
        'api_key': settings.api_key,
        'timeout': _build_httpx_timeout(),
    }
    if settings.base_url and str(settings.base_url).strip():
        base_kw['base_url'] = str(settings.base_url).strip().rstrip('/')
    client = Anthropic(**base_kw)

    req: dict[str, Any] = {
        'model': use_model,
        'max_tokens': ANTHROPIC_STREAM_MAX_TOKENS,
        'messages': anth_msgs,
    }
    if system_text and system_text.strip():
        req['system'] = system_text
    if anth_tool_list:
        req['tools'] = anth_tool_list
        req['tool_choice'] = {'type': 'auto'}

    last_in = 0
    last_out = 0
    finish_emitted = False

    # 使用 create(..., stream=True) 迭代 RawMessageStreamEvent，避免 messages.stream() 封装层缓冲
    stream = client.messages.create(**req, stream=True)
    try:
        for event in stream:
            et = getattr(event, 'type', None)
            if et == 'message_start':
                msg = getattr(event, 'message', None)
                u = getattr(msg, 'usage', None) if msg is not None else None
                if u is not None:
                    last_in = int(getattr(u, 'input_tokens', 0) or 0) + int(
                        getattr(u, 'cache_read_input_tokens', 0) or 0
                    ) + int(getattr(u, 'cache_creation_input_tokens', 0) or 0)
                    last_out = int(getattr(u, 'output_tokens', 0) or 0)
            elif et == 'content_block_start':
                idx = int(getattr(event, 'index', 0))
                blk = getattr(event, 'content_block', None)
                btype = getattr(blk, 'type', None) if blk is not None else None
                if btype == 'tool_use':
                    tid = str(getattr(blk, 'id', '') or '')
                    name = str(getattr(blk, 'name', '') or '')
                    yield StreamPart(
                        tool_index=idx,
                        tool_id=tid or None,
                        tool_name_fragment=name or None,
                    )
            elif et == 'content_block_delta':
                idx = int(getattr(event, 'index', 0))
                d = getattr(event, 'delta', None)
                if d is None:
                    continue
                dt = getattr(d, 'type', None)
                if dt == 'text_delta':
                    tx = getattr(d, 'text', None) or ''
                    if tx:
                        yield StreamPart(text_delta=tx)
                elif dt == 'input_json_delta':
                    pj = getattr(d, 'partial_json', None) or ''
                    if pj:
                        yield StreamPart(
                            tool_index=idx,
                            tool_arguments_fragment=pj,
                        )
            elif et == 'message_delta':
                u = getattr(event, 'usage', None)
                if u is not None:
                    if getattr(u, 'input_tokens', None) is not None:
                        last_in = int(u.input_tokens or 0) + int(
                            getattr(u, 'cache_read_input_tokens', 0) or 0
                        ) + int(getattr(u, 'cache_creation_input_tokens', 0) or 0)
                    last_out = int(getattr(u, 'output_tokens', 0) or last_out)
                delta = getattr(event, 'delta', None)
                sr = getattr(delta, 'stop_reason', None) if delta is not None else None
                if sr:
                    yield StreamPart(finish_reason=_anthropic_stop_to_finish(str(sr)))
                    finish_emitted = True
    finally:
        try:
            stream.close()
        except Exception:
            pass

    if not finish_emitted:
        yield StreamPart(finish_reason='stop')
    yield StreamPart(
        prompt_tokens=last_in,
        completion_tokens=last_out,
    )


def chat_completion_stream(
    messages: list[dict[str, Any]],
    settings: LlmConnectionSettings,
    *,
    model: str | None = None,
    tools: list[dict[str, Any]] | None = None,
) -> Iterator[StreamPart]:
    """按模型前缀路由（provider/model_id）严格分发到对应客户端。"""
    # 内存修剪：不修改调用方传入的 messages（深拷贝在 prune 内完成）
    api_messages = prune_historical_messages(messages)
    raw_model = (model or settings.model).strip() or settings.model
    route = parse_model_route(
        raw_model,
        default_provider=settings.default_provider or settings.api_protocol or 'openai',
    )
    _raise_if_missing_provider_key(settings, provider=route.provider)
    try:
        if route.provider == 'anthropic':
            yield from _chat_completion_stream_anthropic(
                api_messages, settings, use_model=route.model_id, tools=tools
            )
        elif route.provider in ('openai', 'deepseek'):
            yield from _chat_completion_stream_openai(
                api_messages, settings, use_model=route.model_id, tools=tools
            )
        else:
            raise LlmClientError(f'[LLM] 不支持的 provider 路由: {route.provider}')
    except Exception as exc:
        mapped = _map_llm_auth_exception(exc)
        if mapped is not None:
            raise mapped from exc
        if _is_timeout_or_network_exception(exc):
            raise LlmClientError(_LLM_TRANSPORT_FUSE_MSG) from exc
        raise


def iter_agent_executor_events(
    messages: list[dict[str, Any]],
    settings: LlmConnectionSettings,
    *,
    model: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    mcp_client: 'MCPClient | None' = None,
) -> Iterator[dict[str, Any]]:
    """
    **LLM Provider 侧唯一的多轮工具闭环**（本仓库对 claw-code 链路的 Python 镜像实现）。

    职责边界（不可下沉到 REPL / 通道）：

    - 按 ``api_protocol`` 流式调用 OpenAI 或 Anthropic；
    - 解析 ``tool_calls``，经 **ToolsRegistry**（与 ``tool-pool`` 展示的运行时工具面同源）执行并写回 ``messages``；
    - 向外产出 ``text_delta`` / ``tool_delta`` / ``api_tool_op`` / ``llm_error``，以及终结事件 ``executor_complete``。

    不负责：会话 transcript、路由摘要、Rich 渲染。调用方须传入已构造好的 ``messages``（含 system/user）。
    """
    from .tools_registry import get_tools_registry

    reg = get_tools_registry()
    use_tools = tools if tools is not None else get_openai_agent_tools()
    use_model = (model or settings.model).strip() or settings.model
    msgs = messages
    in_tok = 0
    out_tok = 0
    text_slices: list[str] = []
    local_tool_names = {
        str(row.get('name') or '').strip()
        for row in reg.list_tool_rows()
        if isinstance(row, dict)
    }

    cap = agent_tool_iteration_cap()
    n_iter = 0
    while cap is None or n_iter < cap:
        n_iter += 1
        if agent_cancel.agent_cancel_requested():
            yield {
                'type': 'executor_complete',
                'assistant_text': '用户已中断当前任务。',
                'input_tokens': in_tok,
                'output_tokens': out_tok,
                'conversation_messages': copy.deepcopy(msgs),
                'stop_reason': 'user_interrupt',
            }
            return

        acc = ToolCallAccumulator()
        round_buf: list[str] = []
        finish_reason: str | None = None
        round_in = 0
        round_out = 0
        stream_cancelled = False
        try:
            for part in chat_completion_stream(
                msgs, settings, model=use_model, tools=use_tools
            ):
                if agent_cancel.agent_cancel_requested():
                    stream_cancelled = True
                    break
                if part.text_delta:
                    round_buf.append(part.text_delta)
                    yield {'type': 'text_delta', 'text': part.text_delta}
                if part.tool_arguments_fragment:
                    yield {'type': 'tool_delta', 'fragment': part.tool_arguments_fragment}
                acc.consume(part)
                if part.finish_reason:
                    finish_reason = part.finish_reason
                if part.prompt_tokens is not None:
                    round_in = part.prompt_tokens
                if part.completion_tokens is not None:
                    round_out = part.completion_tokens
        except LlmClientError as exc:
            msg = str(exc)
            if msg == _LLM_TRANSPORT_FUSE_MSG:
                yield {'type': 'llm_error', 'output': msg}
            else:
                yield {'type': 'llm_error', 'output': f'[LLM] {msg}'}
            return
        except Exception as exc:  # pragma: no cover - 网络/供应商错误
            if _is_timeout_or_network_exception(exc):
                yield {'type': 'llm_error', 'output': _LLM_TRANSPORT_FUSE_MSG}
                return
            yield {'type': 'llm_error', 'output': f'[LLM] 请求异常: {exc}'}
            return

        in_tok += round_in
        out_tok += round_out

        if stream_cancelled:
            partial = ''.join(round_buf).strip()
            tail = (
                partial + '\n\n用户已中断当前任务。'
                if partial
                else '用户已中断当前任务。'
            )
            yield {
                'type': 'executor_complete',
                'assistant_text': tail,
                'input_tokens': in_tok,
                'output_tokens': out_tok,
                'conversation_messages': copy.deepcopy(msgs),
                'stop_reason': 'user_interrupt',
            }
            return

        assistant_round = ''.join(round_buf).strip()

        if finish_reason == 'tool_calls' and acc.has_tool_calls():
            if assistant_round:
                text_slices.append(assistant_round)
            tool_calls = acc.as_openai_tool_calls()
            assistant_msg: dict[str, Any] = {
                'role': 'assistant',
                'tool_calls': tool_calls,
            }
            if assistant_round:
                assistant_msg['content'] = assistant_round
            msgs.append(assistant_msg)
            interrupt_from_here: int | None = None
            for idx, tc in enumerate(tool_calls):
                fn = tc['function']['name']
                raw_args = tc['function']['arguments']
                parsed_args = _parse_tool_arguments(raw_args)
                progress_hint: str | None = None
                if mcp_client is not None and getattr(mcp_client, 'is_running', False) and fn not in local_tool_names:
                    progress_hint = _format_tool_call_progress_hint(fn, parsed_args)
                ev_tool: dict[str, Any] = {
                    'type': 'api_tool_op',
                    'tool_name': fn,
                    'arguments': raw_args,
                }
                if progress_hint is not None:
                    ev_tool['progress_hint'] = progress_hint
                yield ev_tool
                if agent_cancel.agent_cancel_requested():
                    interrupt_from_here = idx
                    break
                try:
                    if fn in local_tool_names:
                        result = reg.execute_tool(fn, raw_args)
                    elif mcp_client is not None and getattr(mcp_client, 'is_running', False):
                        from .mcp_manager import MCPClientError

                        args = parsed_args
                        try:
                            mcp_resp = mcp_client.call_tool(fn, args)
                            mcp_result = mcp_resp.get('result')
                            if isinstance(mcp_result, (dict, list)):
                                result = json.dumps(mcp_result, ensure_ascii=False)
                            elif mcp_result is None:
                                result = ''
                            else:
                                result = str(mcp_result)
                            if not result.strip():
                                result = '[MCP] 工具执行完成（无文本输出）'
                        except MCPClientError as exc:
                            msg = str(exc)
                            if _mcp_client_error_is_timeout(msg):
                                result = _MCP_BROWSER_TIMEOUT_MSG
                            else:
                                if _mcp_client_error_is_disconnect(msg):
                                    _log.warning(
                                        'MCP bridge disconnected while calling %s: %s',
                                        fn,
                                        msg,
                                    )
                                result = f'[MCP错误] {msg}'
                    else:
                        result = f'[错误] 未知工具: {fn}'
                except Exception as exc:
                    err = f'{type(exc).__name__}: {exc}'
                    trace = _short_exception_trace(exc)
                    result = MSG_TOOL_EXCEPTION.format(error_trace=err)
                    if trace:
                        result = f'{result}\n{trace}'
                msgs.append(
                    {
                        'role': 'tool',
                        'tool_call_id': tc['id'],
                        'content': result,
                    }
                )
            if interrupt_from_here is not None:
                for tc2 in tool_calls[interrupt_from_here:]:
                    msgs.append(
                        {
                            'role': 'tool',
                            'tool_call_id': tc2['id'],
                            'content': agent_cancel.INTERRUPT_TOOL_MESSAGE,
                        }
                    )
                continue

            continue

        if assistant_round:
            text_slices.append(assistant_round)
        llm_text = '\n\n'.join(text_slices).strip()
        yield {
            'type': 'executor_complete',
            'assistant_text': llm_text,
            'input_tokens': in_tok,
            'output_tokens': out_tok,
            'conversation_messages': copy.deepcopy(msgs),
            'stop_reason': 'completed',
        }
        return

    yield {
        'type': 'llm_error',
        'output': (
            '[LLM] 工具调用轮次超过配置上限（环境变量 '
            f'{_AGENT_TOOL_CAP_ENV}），请简化任务。'
        ),
    }


def chat_completion(
    messages: list[dict[str, Any]],
    settings: LlmConnectionSettings,
    *,
    model: str | None = None,
    tools: list[dict[str, Any]] | None = None,
    mcp_client: 'MCPClient | None' = None,
) -> ChatCompletionResult:
    """非流式：消费 :func:`iter_agent_executor_events` 直至得到最终文本。"""
    for ev in iter_agent_executor_events(
        messages,
        settings,
        model=model,
        tools=tools if tools is not None else get_openai_agent_tools(),
        mcp_client=mcp_client,
    ):
        if ev['type'] == 'executor_complete':
            cm = ev.get('conversation_messages')
            return ChatCompletionResult(
                text=str(ev['assistant_text']).strip(),
                input_tokens=int(ev['input_tokens']),
                output_tokens=int(ev['output_tokens']),
                conversation_messages=cm if isinstance(cm, list) else None,
            )
        if ev['type'] == 'llm_error':
            return ChatCompletionResult(
                text=str(ev['output']),
                input_tokens=0,
                output_tokens=0,
                conversation_messages=None,
            )
    return ChatCompletionResult(
        text=f'[LLM] 工具调用轮次超过配置上限（{_AGENT_TOOL_CAP_ENV}），请简化任务。',
        input_tokens=0,
        output_tokens=0,
        conversation_messages=None,
    )
