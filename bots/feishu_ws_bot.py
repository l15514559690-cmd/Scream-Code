import ssl

# SSL 破壁补丁（开发环境兜底）：必须在 lark/httpx 等网络库 import 之前执行
try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

import atexit
import os
import json
import threading
import subprocess
import warnings
import time
import re
from pathlib import Path
import lark_oapi as lark
from lark_oapi.api.im.v1 import *

# 屏蔽第三方弃用告警，保持日志极客洁癖
warnings.filterwarnings("ignore", category=DeprecationWarning)
warnings.filterwarnings("ignore", message=".*pkg_resources is deprecated.*")
warnings.filterwarnings("ignore", category=UserWarning)

APP_ID = os.getenv("FEISHU_APP_ID")
APP_SECRET = os.getenv("FEISHU_APP_SECRET")
ALLOW_INSECURE_SSL = os.getenv("FEISHU_INSECURE_SSL", "0").strip().lower() in ("1", "true", "yes")

# 初始化 API 客户端（仅用于发送回复）
api_client = lark.Client.builder().app_id(APP_ID).app_secret(APP_SECRET).build()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_PATH = _PROJECT_ROOT / "logs" / "feishu.log"
# 入站附件：与项目根隔离，避免污染仓库
DOWNLOAD_DIR = (_PROJECT_ROOT / ".scream_cache" / "feishu_inbox").resolve()
SCREAM_CACHE_OUTBOX = (_PROJECT_ROOT / ".scream_cache" / "feishu_outbox").resolve()
FEISHU_SIDECAR_PID = (_PROJECT_ROOT / ".scream_cache" / "feishu_sidecar.pid").resolve()
_FEISHU_FILE_TAG_RE = re.compile(r"\[FEISHU_FILE:\s*(.+?)\]")
_pending_receive_id_type = "open_id"
_pending_receive_id = ""


def _ensure_scream_cache_dirs() -> None:
    """创建入站/出站缓存目录（项目根 `.scream_cache/` 下）。"""
    try:
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        SCREAM_CACHE_OUTBOX.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass


def _write_feishu_sidecar_pid() -> None:
    """供 TUI 状态栏检测侧车是否存活（与 ``pgrep`` 互补）。"""
    try:
        _ensure_scream_cache_dirs()
        FEISHU_SIDECAR_PID.write_text(str(os.getpid()), encoding='ascii')
    except OSError:
        pass


def _remove_feishu_sidecar_pid() -> None:
    try:
        FEISHU_SIDECAR_PID.unlink(missing_ok=True)
    except OSError:
        pass


atexit.register(_remove_feishu_sidecar_pid)


def _gc_scream_cache_stale_files(max_age_days: int = 3) -> None:
    """删除 inbox/outbox 中超过 ``max_age_days`` 的文件，防止磁盘撑满。"""
    cutoff = time.time() - float(max(1, max_age_days)) * 86400.0
    for base in (DOWNLOAD_DIR, SCREAM_CACHE_OUTBOX):
        try:
            if not base.is_dir():
                continue
            for p in base.iterdir():
                if not p.is_file():
                    continue
                try:
                    if p.stat().st_mtime < cutoff:
                        p.unlink(missing_ok=True)
                except OSError:
                    pass
        except OSError:
            pass


def _log_error(text: str) -> None:
    try:
        LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")
    except OSError:
        pass


def send_feishu_msg(receive_id_type: str, receive_id: str, text: str) -> bool:
    try:
        request = (
            CreateMessageRequest.builder()
            .receive_id_type(receive_id_type)
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(receive_id)
                .msg_type("text")
                .content(json.dumps({"text": text}))
                .build()
            )
            .build()
        )
        response = api_client.im.v1.message.create(request)
        if not response.success():
            err = f"[回复失败] {response.code} - {response.msg}"
            print(err)
            _log_error(err)
            return False
        return True
    except Exception as exc:
        err = f"[回复异常] {type(exc).__name__}: {exc}"
        print(err)
        _log_error(err)
        return False


def send_feishu_structured_msg(
    receive_id_type: str,
    receive_id: str,
    *,
    msg_type: str,
    payload: dict,
) -> bool:
    try:
        request = (
            CreateMessageRequest.builder()
            .receive_id_type(receive_id_type)
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(receive_id)
                .msg_type(msg_type)
                .content(json.dumps(payload))
                .build()
            )
            .build()
        )
        response = api_client.im.v1.message.create(request)
        if not response.success():
            err = f"[结构化回复失败] {response.code} - {response.msg}"
            print(err)
            _log_error(err)
            return False
        return True
    except Exception as exc:
        err = f"[结构化回复异常] {type(exc).__name__}: {exc}"
        print(err)
        _log_error(err)
        return False


def _download_attachment_to_local(
    message_id: str,
    message_type: str,
    content_dict: dict,
) -> str:
    try:
        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        key = ""
        if message_type == "image":
            key = str(content_dict.get("image_key") or "").strip()
        elif message_type == "file":
            key = str(content_dict.get("file_key") or "").strip()
        if not key:
            return ""
        ext = ".png" if message_type == "image" else ".bin"
        out_path = (DOWNLOAD_DIR / f"{message_id}_{key[:10]}{ext}").resolve()
        req_builder = GetMessageResourceRequest.builder()
        req = req_builder.message_id(message_id).type(message_type).file_key(key).build()
        resp = api_client.im.v1.message_resource.get(req)
        if not resp.success():
            _log_error(f"[附件下载失败] {resp.code} - {resp.msg}")
            return ""
        body = getattr(resp, "raw", None) or getattr(resp, "file", None) or getattr(resp, "data", None)
        raw_bytes: bytes | None = None
        if isinstance(body, (bytes, bytearray)):
            raw_bytes = bytes(body)
        elif hasattr(body, "read"):
            raw_bytes = body.read()
        if not raw_bytes:
            _log_error("[附件下载失败] 响应体为空")
            return ""
        out_path.write_bytes(raw_bytes)
        return str(out_path)
    except Exception as exc:
        _log_error(f"[附件下载异常] {type(exc).__name__}: {exc}")
        return ""


def _upload_attachment(path_text: str) -> tuple[bool, str]:
    p = Path(path_text).expanduser()
    if not p.is_file():
        return False, "文件不存在"
    ext = p.suffix.lower()
    try:
        if ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}:
            with p.open("rb") as f:
                req = (
                    CreateImageRequest.builder()
                    .request_body(
                        CreateImageRequestBody.builder()
                        .image_type("message")
                        .image(f)
                        .build()
                    )
                    .build()
                )
                resp = api_client.im.v1.image.create(req)
            if not resp.success():
                return False, f"{resp.code} - {resp.msg}"
            image_key = str(getattr(getattr(resp, "data", None), "image_key", "") or "")
            if not image_key:
                return False, "未返回 image_key"
            return send_feishu_structured_msg(
                _pending_receive_id_type,
                _pending_receive_id,
                msg_type="image",
                payload={"image_key": image_key},
            ), "image"

        with p.open("rb") as f:
            req = (
                CreateFileRequest.builder()
                .request_body(
                    CreateFileRequestBody.builder()
                    .file_name(p.name)
                    .file(f)
                    .build()
                )
                .build()
            )
            resp = api_client.im.v1.file.create(req)
        if not resp.success():
            return False, f"{resp.code} - {resp.msg}"
        file_key = str(getattr(getattr(resp, "data", None), "file_key", "") or "")
        if not file_key:
            return False, "未返回 file_key"
        return send_feishu_structured_msg(
            _pending_receive_id_type,
            _pending_receive_id,
            msg_type="file",
            payload={"file_key": file_key},
        ), "file"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"

# ==========================================
# 核心逻辑：后台执行 Scream Code，防止飞书 3 秒超时重推
# ==========================================
def process_and_reply_in_background(
    user_text: str,
    receive_id_type: str,
    receive_id: str,
    session_id: str = "",
    message_type: str = "text",
    message_id: str = "",
    message_content: str = "{}",
):
    global _pending_receive_id_type, _pending_receive_id
    _pending_receive_id_type = receive_id_type
    _pending_receive_id = receive_id
    print(f"\n[飞书长连接] 收到消息: {user_text}")
    print("[飞书长连接] 正在唤醒 Scream Code 引擎...")
    
    try:
        effective_user_text = (user_text or "").strip()
        if message_type in ("image", "file"):
            if not effective_user_text:
                effective_user_text = "请分析我刚发送的这个附件。"
            try:
                content_dict = json.loads(message_content or "{}")
            except json.JSONDecodeError:
                content_dict = {}
            local_path = _download_attachment_to_local(message_id, message_type, content_dict)
            if local_path:
                effective_user_text = f"{effective_user_text}\n\n[用户上传了附件]: {local_path}"
            else:
                effective_user_text = (
                    f"{effective_user_text}\n\n[用户上传了{message_type}，下载失败，请查看日志。]"
                )

        wrapped_prompt = f"""[SYSTEM_OVERRIDE: 飞书通道]
注意：你正在飞书独立通道中与用户对话。

【入站附件协议 (最高优先级)】：
若下方用户的消息中包含 `[用户上传了附件]: <本地绝对路径>`，这代表物理文件已经被下载到了你的运行环境（.scream_cache/feishu_inbox/）中。
1. 你【必须】立刻使用你的本地工具（如 bash、python、read_file 等）去主动读取、解压或分析这个路径下的文件！
2. 绝不允许回答“我无法访问你电脑上的文件”或“我看不到文件”，文件就在你本地！
3. 如果是压缩包请先用工具解压；如果是代码/文本请直接读取；如果是图片，请尝试使用你的视觉能力或图像处理工具进行分析。

【出站文件协议】：
若需发送文件给用户，请保存在 .scream_cache/feishu_outbox/ 中并严格输出 [FEISHU_FILE:/绝对路径]。

[USER_MESSAGE]:
{effective_user_text}"""

        cwd = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        cmd = ["python3", "-m", "src.main", "repl", wrapped_prompt]
        current_session_id = (session_id or "").strip()
        if current_session_id:
            cmd.extend(["--session-id", current_session_id])

        env = os.environ.copy()
        env["SCREAM_FRONTEND"] = "feishu"

        process = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            env=env,
        )
        
        reply_text = process.stdout.strip()
        if not reply_text:
            reply_text = "Scream Code 暂时没有返回内容，请稍后重试。"
        if process.returncode != 0:
            reply_text = "❌ 引擎执行出错，请查看终端或日志。"

    except Exception as e:
        reply_text = "❌ 引擎执行出错，请查看终端或日志。"
        _log_error(f"[子进程异常] {type(e).__name__}: {e}")

    attach_err = ""
    m = _FEISHU_FILE_TAG_RE.search(reply_text or "")
    if m:
        file_path = m.group(1).strip()
        reply_text = _FEISHU_FILE_TAG_RE.sub("", reply_text).strip()
        ok_attach, detail = _upload_attachment(file_path)
        if not ok_attach:
            attach_err = "❌ 尝试发送附件失败，文件可能不存在或超出大小限制。"
            _log_error(f"[附件上传失败] {detail}")

    print("[飞书长连接] 执行完毕，发送回复...")

    if attach_err:
        reply_text = f"{reply_text}\n\n{attach_err}".strip()
    ok = send_feishu_msg(receive_id_type, receive_id, reply_text)
    if ok:
        print(f"[回复成功] 通过 {receive_id_type}={receive_id} 完成回复。")


# ==========================================
# 事件监听器：必须在 3 秒内 return
# ==========================================
def do_p2_im_message_receive_v1(data: P2ImMessageReceiveV1) -> None:
    try:
        raw_content = data.event.message.content or "{}"
        content_dict = json.loads(raw_content)
        user_text = content_dict.get("text", "").strip()
        message_type = str(data.event.message.message_type or "text").strip().lower()
        message_id = str(data.event.message.message_id or "").strip()
        open_id = (data.event.sender.sender_id.open_id or "").strip()
        chat_id = (data.event.message.chat_id or "").strip()
        receive_id_type = "chat_id" if chat_id else "open_id"
        receive_id = chat_id or open_id
        feishu_session_id = f"feishu_{open_id or chat_id}".strip()

        # 纯图片/文件无配文时不能当空消息丢弃；后台会再拼接入站附件行
        if message_type in ("image", "file") and not user_text:
            user_text = "请分析我刚发送的这个附件。"
        
        if message_type == "text" and not user_text:
            print("[飞书长连接] 空文本消息，忽略。")
            return
        if not receive_id:
            print("[飞书长连接] 未提取到 chat_id/open_id，忽略该消息。")
            return
        send_feishu_msg(receive_id_type, receive_id, "🤔 Scream Code 正在接收信号并思考中...")

        # ⭐️ 异步脱壳：开新线程跑大模型，主函数立刻 return 防止超时重推
        threading.Thread(
            target=process_and_reply_in_background,
            args=(
                user_text,
                receive_id_type,
                receive_id,
                feishu_session_id,
                message_type,
                message_id,
                raw_content,
            ),
            daemon=True,
        ).start()

    except Exception as e:
        print(f"[解析消息失败] {e}")

# 注册事件
event_handler = lark.EventDispatcherHandler.builder("", "") \
    .register_p2_im_message_receive_v1(do_p2_im_message_receive_v1) \
    .build()


def _build_ws_client_options() -> list[object]:
    """
    开发环境可选：注入自定义 HTTP 客户端并关闭证书校验。
    生产环境请勿启用 FEISHU_INSECURE_SSL。
    """
    if not ALLOW_INSECURE_SSL:
        return []
    with_http_client = getattr(lark, "WithHttpClient", None)
    if not callable(with_http_client):
        print("[飞书长连接] 当前 SDK 不支持 WithHttpClient，跳过自定义 HTTP 客户端注入。")
        return []
    try:
        import httpx

        http_client = httpx.Client(verify=False)
        print("[飞书长连接] 开发模式: 已启用 FEISHU_INSECURE_SSL (verify=False)。")
        return [with_http_client(http_client)]
    except Exception as exc:
        print(f"[飞书长连接] 自定义 HTTP 客户端注入失败，回退默认连接器: {exc}")
        return []

if __name__ == "__main__":
    _ensure_scream_cache_dirs()
    _gc_scream_cache_stale_files(max_age_days=3)
    _write_feishu_sidecar_pid()
    print("🚀 Scream Code 飞书长连接侧车正在启动...")
    ws_options = _build_ws_client_options()
    cli = lark.ws.Client(
        APP_ID,
        APP_SECRET,
        *ws_options,
        event_handler=event_handler,
        log_level=lark.LogLevel.INFO,
    )
    cli.start()
