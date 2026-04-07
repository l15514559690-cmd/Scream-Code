#!/usr/bin/env bash
# Scream Code · 全局 TUI 启动函数（由 ~/.zshrc source，勿直接 chmod +x 执行）
#
# 安装：在 ~/.zshrc 末尾加一行（路径改为你的克隆目录）：
#   source "/Users/you/ScreamCode/scripts/screamcode-tui.sh"
#
# 使用：任意目录执行  screamcode-tui

if [ -n "${ZSH_VERSION:-}" ]; then
  _SC_SCRIPT_DIR="$(cd "$(dirname "${(%):-%x}")" && pwd)"
else
  _SC_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
fi
# 本文件在 scripts/ 下，仓库根为上一级
export SCREAM_HOME="$(cd "$_SC_SCRIPT_DIR/.." && pwd)"
unset _SC_SCRIPT_DIR

screamcode-tui() {
  local root="${SCREAM_HOME}"
  if [ ! -d "$root" ]; then
    echo "screamcode-tui: SCREAM_HOME 无效: $root" >&2
    return 1
  fi
  export SCREAM_WORKSPACE_ROOT="${SCREAM_WORKSPACE_ROOT:-$root}"
  local bin="${HOME}/.cargo/bin/scream"
  if [ -x "$bin" ]; then
    "$bin" "$@"
    return $?
  fi
  if [ -x "$root/rust/target/release/scream" ]; then
    "$root/rust/target/release/scream" "$@"
    return $?
  fi
  if [ -x "$root/rust/target/debug/scream" ]; then
    "$root/rust/target/debug/scream" "$@"
    return $?
  fi
  if command -v cargo >/dev/null 2>&1; then
    echo "screamcode-tui: 正在 cargo run（首次会编译）…" >&2
    (cd "$root/rust" && exec cargo run -q -p scream-cli -- "$@")
    return $?
  fi
  echo "screamcode-tui: 未找到 scream。请先: cd $root/rust && cargo install --path crates/rusty-claude-cli" >&2
  return 1
}

# 短别名（可选）
alias scream-tui=screamcode-tui
