from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path


class FeishuManager:
    _instance: 'FeishuManager | None' = None

    def __new__(cls) -> 'FeishuManager':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._bot_process = None
            cls._instance._log_file_handle = None
        return cls._instance

    def __init__(self) -> None:
        # 单例场景下，实例状态在 __new__ 中初始化，__init__ 保持幂等。
        pass

    @property
    def _project_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    @property
    def _env_path(self) -> Path:
        return self._project_root / '.env'

    @property
    def _bot_script_path(self) -> Path:
        return self._project_root / 'bots' / 'feishu_ws_bot.py'

    @property
    def _log_path(self) -> Path:
        return self._project_root / 'logs' / 'feishu.log'

    def config(self, app_id: str, app_secret: str) -> None:
        app_id = (app_id or '').strip().strip("<>'\"")
        app_secret = (app_secret or '').strip().strip("<>'\"")
        if not app_id or not app_secret:
            raise ValueError('app_id 和 app_secret 不能为空')

        self._env_path.parent.mkdir(parents=True, exist_ok=True)
        current = ''
        if self._env_path.is_file():
            current = self._env_path.read_text(encoding='utf-8')

        def _upsert(body: str, key: str, value: str) -> str:
            line = f'{key}={value}'
            pattern = re.compile(rf'(?m)^{re.escape(key)}\s*=.*$')
            if pattern.search(body):
                return pattern.sub(line, body)
            sep = '' if not body or body.endswith('\n') else '\n'
            return f'{body}{sep}{line}\n'

        updated = _upsert(current, 'FEISHU_APP_ID', app_id)
        updated = _upsert(updated, 'FEISHU_APP_SECRET', app_secret)
        self._env_path.write_text(updated, encoding='utf-8')

        os.environ['FEISHU_APP_ID'] = app_id
        os.environ['FEISHU_APP_SECRET'] = app_secret

    def start(self) -> None:
        script = self._bot_script_path
        if not script.is_file():
            raise FileNotFoundError(f'未找到飞书侧车脚本: {script}')
        if self._bot_process is not None and self._bot_process.poll() is None:
            return
        logs_dir = self._project_root / 'logs'
        os.makedirs(logs_dir, exist_ok=True)
        log_file = open(self._log_path, 'a', encoding='utf-8')
        log_file.write(f'\n--- 侧车启动时间: {time.ctime()} ---\n')
        log_file.flush()

        self._bot_process = subprocess.Popen(
            [sys.executable, str(script)],
            cwd=str(self._project_root),
            env=os.environ.copy(),
            stdout=log_file,
            stderr=log_file,
        )
        self._log_file_handle = log_file

    def stop(self) -> None:
        proc = self._bot_process
        if proc is None:
            return
        if proc.poll() is None:
            proc.terminate()
        self._bot_process = None
        if self._log_file_handle is not None:
            try:
                self._log_file_handle.close()
            except OSError:
                pass
            self._log_file_handle = None

    def status(self) -> str:
        proc = self._bot_process
        if proc is not None and proc.poll() is None:
            return f'🟢 运行中 (PID: {proc.pid})'
        return '🔴 已停止'

    def tail_log(self, lines: int = 15) -> str:
        n = max(1, int(lines))
        path = self._log_path
        if not path.is_file():
            return '暂无日志文件'
        try:
            content = path.read_text(encoding='utf-8')
        except OSError:
            return '日志读取失败'
        rows = content.splitlines()
        if not rows:
            return '日志为空'
        return '\n'.join(rows[-n:])


feishu_manager = FeishuManager()
