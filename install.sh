#!/usr/bin/env bash
# 尖叫 Code · 单指令全自动安装（macOS / Linux）
# 用法：在仓库根目录执行  bash install.sh

set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
MARK_BEGIN='# >>> SCREAM_CODE_BEGIN >>>'
MARK_END='# <<< SCREAM_CODE_END <<<'

# ── 终端颜色 ─────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

die() {
  echo -e "${RED}${BOLD}✗${RESET} ${RED}$*${RESET}" >&2
  exit 1
}

info() { echo -e "${CYAN}${BOLD}▶${RESET} $*"; }
ok() { echo -e "${GREEN}${BOLD}✓${RESET} $*"; }
warn() { echo -e "${YELLOW}${BOLD}!${RESET} $*"; }

echo ""
echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════${RESET}"
echo -e "${BOLD}  尖叫 Code (Scream Code) · 自动安装${RESET}"
echo -e "${DIM}  $ROOT${RESET}"
echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════${RESET}"
echo ""

# ── 环境检查 ─────────────────────────────────────────
info "${BOLD}[环境检查]${RESET} 查找 python3 …"
if ! command -v python3 >/dev/null 2>&1; then
  echo ""
  die "未找到 python3。请先安装 Python 3.10+。
  • macOS（Homebrew）: ${CYAN}brew install python@3.12${RESET}
  • 官网: ${CYAN}https://www.python.org/downloads/${RESET}
  • Debian/Ubuntu: ${CYAN}sudo apt install python3 python3-venv${RESET}"
fi
ok "python3 已就绪 ${DIM}$(python3 --version)${RESET}"

info "${BOLD}[环境检查]${RESET} 查找 cargo（Rust）…"
if ! command -v cargo >/dev/null 2>&1; then
  echo ""
  die "未找到 cargo。Scream Code 的终端界面需要 Rust 工具链。
  • 一键安装: ${CYAN}curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh${RESET}
  • 说明页: ${CYAN}https://rustup.rs/${RESET}
  安装后请${BOLD}重新打开终端${RESET}，再运行本脚本。"
fi
ok "cargo 已就绪 ${DIM}$(cargo --version)${RESET}"

CLI_CRATE="$ROOT/rust/crates/rusty-claude-cli"
[[ -d "$CLI_CRATE" ]] || die "未找到 Rust 工程路径：$CLI_CRATE（请在仓库根目录执行本脚本）"
[[ -f "$ROOT/requirements.txt" ]] || die "未找到 requirements.txt（请在仓库根目录执行本脚本）"

# ── 运行中实例：避免旧 scream 占用二进制或残留 Python 后端 ──
info "${BOLD}[运行检查]${RESET} 是否已有 scream 进程…"
if command -v pgrep >/dev/null 2>&1 && pgrep -x scream >/dev/null 2>&1; then
  warn "检测到已有名为 ${BOLD}scream${RESET} 的进程在运行；继续安装可能使旧进程仍驻留或干扰新版本。"
  if [[ -t 0 ]]; then
    read -r -p "是否执行 killall scream 后继续？[Y/n] " _scream_kill_choice || true
    case "${_scream_kill_choice:-Y}" in
      [nN]|[nN][oO])
        warn "已跳过 killall；若安装或启动异常，请先手动结束 scream 再试。"
        ;;
      *)
        if command -v killall >/dev/null 2>&1; then
          if killall scream 2>/dev/null; then
            ok "已结束 scream 进程"
          else
            warn "killall scream 未成功（权限或进程名不同）；请手动检查后重试。"
          fi
        else
          warn "系统未提供 killall，请手动结束 scream 进程后再安装。"
        fi
        ;;
    esac
  else
    warn "非交互环境未自动结束进程；若需干净安装请先执行 ${CYAN}killall scream${RESET} 再运行本脚本。"
  fi
else
  ok "无已运行的 scream 进程"
fi

# ── Python：虚拟环境与依赖 ───────────────────────────
info "${BOLD}[Python]${RESET} 创建虚拟环境 .venv …"
if [[ ! -d "$ROOT/.venv" ]]; then
  python3 -m venv "$ROOT/.venv" || die "无法创建 venv（部分系统需安装 python3-venv 包）。"
  ok "已创建 .venv"
else
  ok "已存在 .venv，跳过创建"
fi

PY="$ROOT/.venv/bin/python3"
PIP="$ROOT/.venv/bin/pip"
[[ -x "$PY" ]] || die "虚拟环境中缺少 python3：$PY"

info "${BOLD}[Python]${RESET} 静默安装 requirements.txt …"
"$PY" -m pip install -q --upgrade pip
"$PIP" install -q -r "$ROOT/requirements.txt"
ok "Python 依赖安装完成"

# ── Rust：编译并安装 scream 到 ~/.cargo/bin ─────────
info "${BOLD}[Rust]${RESET} cargo install（可能需要几分钟）…"
( cd "$ROOT/rust" && cargo install -q --path crates/rusty-claude-cli --force )
ok "Rust 客户端已安装到 ~/.cargo/bin/scream（请确保 ~/.cargo/bin 在 PATH 中）"

# ── 注册 shell 函数 scream ───────────────────────────
pick_rc_file() {
  case "${SHELL:-}" in
    */zsh)
      echo "${ZDOTDIR:-$HOME}/.zshrc"
      ;;
    */bash)
      if [[ -f "$HOME/.bashrc" ]]; then
        echo "$HOME/.bashrc"
      elif [[ -f "$HOME/.bash_profile" ]]; then
        echo "$HOME/.bash_profile"
      else
        echo "$HOME/.bashrc"
      fi
      ;;
    *)
      if [[ -f "$HOME/.zshrc" ]]; then
        echo "$HOME/.zshrc"
      elif [[ -f "$HOME/.bashrc" ]]; then
        echo "$HOME/.bashrc"
      else
        echo "$HOME/.zshrc"
      fi
      ;;
  esac
}

RC="$(pick_rc_file)"
info "${BOLD}[Shell]${RESET} 注册命令 scream → ${DIM}$RC${RESET}"

"$PY" - "$ROOT" "$RC" "$MARK_BEGIN" "$MARK_END" <<'PY'
import pathlib
import sys

root = pathlib.Path(sys.argv[1]).resolve()
rc_path = pathlib.Path(sys.argv[2]).expanduser()
begin, end = sys.argv[3], sys.argv[4]
act = root / ".venv" / "bin" / "activate"

block = f"""{begin}
scream() {{
  (
    cd {root.as_posix()!r} || {{ echo "scream: 无法进入安装目录" >&2; return 1; }}
    # shellcheck source=/dev/null
    . {act.as_posix()!r}
    RUST_SCREAM="${{HOME}}/.cargo/bin/scream"
    if [ "$#" -eq 0 ] && [ -x "$RUST_SCREAM" ]; then
      export SCREAM_WORKSPACE_ROOT="${{SCREAM_WORKSPACE_ROOT:-$PWD}}"
      exec "$RUST_SCREAM"
    fi
    python3 -m src.main "$@"
  )
}}
# 配置大模型（等同于 scream config）
scream-config() {{
  scream config "$@"
}}
{end}
"""

text = rc_path.read_text(encoding="utf-8") if rc_path.is_file() else ""
lines = text.splitlines(keepends=True)
out = []
skipping = False
for line in lines:
    if line.rstrip("\n") == begin:
        skipping = True
        continue
    if skipping:
        if line.rstrip("\n") == end:
            skipping = False
        continue
    out.append(line)

if text and not text.endswith("\n"):
    out.append("\n")
out.append("\n")
out.append(block)
if not block.endswith("\n"):
    out.append("\n")

rc_path.parent.mkdir(parents=True, exist_ok=True)
rc_path.write_text("".join(out), encoding="utf-8")
PY

ok "已在配置文件中写入 scream、scream-config 函数"

# ── 大功告成 ─────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}"
echo "  ╔═══════════════════════════════════════════════════════════╗"
echo "  ║  🎉 尖叫 Code (Scream Code) 安装成功！                     ║"
echo "  ║  请配置好 .env 文件后，随时在终端输入 scream 唤醒它！       ║"
echo "  ╚═══════════════════════════════════════════════════════════╝"
echo -e "${RESET}"
warn "请执行 ${CYAN}source $RC${RESET}（或新开一个终端）以加载 scream 函数。"
echo -e "  ${DIM}· 确保 ~/.cargo/bin 已在 PATH（rustup 安装时会提示）${RESET}"
echo -e "  ${DIM}· 模型与密钥：cp .env.example .env 后编辑；可选 scream config${RESET}"
echo ""
