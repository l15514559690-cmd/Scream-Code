#!/usr/bin/env bash
# 尖叫 Code · 仓库根一键启动（优先 Rust 全屏 TUI，否则尝试本地编译产物，最后回退 Python REPL）
# 用法：chmod +x start.sh && ./start.sh
#       ./start.sh --line-repl   # 传给 Rust 客户端（若走 Rust 路径）

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
cd "$ROOT"
export SCREAM_WORKSPACE_ROOT="${SCREAM_WORKSPACE_ROOT:-$ROOT}"

if [[ -x "${HOME}/.cargo/bin/scream" ]]; then
  exec "${HOME}/.cargo/bin/scream" "$@"
fi

if [[ -x "$ROOT/rust/target/release/scream" ]]; then
  exec "$ROOT/rust/target/release/scream" "$@"
fi

if [[ -x "$ROOT/rust/target/debug/scream" ]]; then
  exec "$ROOT/rust/target/debug/scream" "$@"
fi

if command -v cargo >/dev/null 2>&1; then
  echo "start.sh: 未找到已安装的 scream，使用 cargo run（首次会编译，稍候）…" >&2
  exec cargo run --manifest-path "$ROOT/rust/Cargo.toml" -p scream-cli -- "$@"
fi

echo "start.sh: 未检测到 cargo，使用 Python 交互 REPL（非全屏 TUI）…" >&2
if [[ -x "$ROOT/.venv/bin/python3" ]]; then
  exec "$ROOT/.venv/bin/python3" -m src.main repl
fi
exec python3 -m src.main repl
