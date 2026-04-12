#!/usr/bin/env bash
# =============================================================================
#  Scream-Code · 开箱即用安装脚本（macOS / Linux）
#  在仓库根目录执行:  bash install.sh   或   chmod +x install.sh && ./install.sh
# =============================================================================
set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
cd "$ROOT" || exit 1

# ── 终端样式（炫酷但可读）────────────────────────────────
RED='\033[0;31m'
GREEN='\033[1;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
BLUE='\033[0;34m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

die() {
  echo -e "${RED}${BOLD}💥${RESET} ${RED}$*${RESET}" >&2
  exit 1
}

warn() { echo -e "${YELLOW}${BOLD}⚠️${RESET}  $*"; }
ok()   { echo -e "${GREEN}${BOLD}✅${RESET} $*"; }
step() { echo -e "${CYAN}${BOLD}▶${RESET}  $*"; }

banner() {
  echo ""
  echo -e "${MAGENTA}${BOLD}  ╔══════════════════════════════════════════════════════════╗${RESET}"
  echo -e "${MAGENTA}${BOLD}  ║${RESET}  ${CYAN}${BOLD}🜂 Scream-Code${RESET}  ${DIM}·${RESET}  ${BOLD}傻瓜式安装${RESET}  ${MAGENTA}${BOLD}║${RESET}"
  echo -e "${MAGENTA}${BOLD}  ╚══════════════════════════════════════════════════════════╝${RESET}"
  echo -e "${DIM}     $ROOT${RESET}"
  echo ""
}

banner

# ── 1. Python & pip ───────────────────────────────────────
step "🐍 检查 Python 3 环境…"
if ! command -v python3 >/dev/null 2>&1; then
  die "未找到 python3。请先安装 Python ${BOLD}3.10+${RESET}：
  • macOS: ${CYAN}brew install python@3.12${RESET}
  • Debian/Ubuntu: ${CYAN}sudo apt install python3 python3-venv python3-pip${RESET}
  • 官网: ${CYAN}https://www.python.org/downloads/${RESET}"
fi

if ! python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  die "需要 Python ${BOLD}3.10+${RESET}，当前为：${BOLD}$(python3 --version 2>&1)${RESET}"
fi
ok "Python 就绪：${BOLD}$(python3 --version 2>&1)${RESET}"

step "📎 检查 pip（python3 -m pip）…"
if ! python3 -m pip --version >/dev/null 2>&1; then
  die "无法执行 ${BOLD}python3 -m pip${RESET}。请安装 pip：
  • ${CYAN}python3 -m ensurepip --upgrade${RESET}
  • 或 ${CYAN}sudo apt install python3-pip${RESET}"
fi
ok "pip 可用：${DIM}$(python3 -m pip --version 2>&1 | head -1)${RESET}"

[[ -f "$ROOT/requirements.txt" ]] || die "未找到 ${BOLD}requirements.txt${RESET}，请在仓库根目录运行本脚本。"
[[ -f "$ROOT/setup.py" ]] || die "未找到 ${BOLD}setup.py${RESET}，请在仓库根目录运行本脚本。"

# ── 虚拟环境（规避 PEP 668「外部管理环境」、不污染系统 Python）──
VENV="$ROOT/.venv"
PY="$VENV/bin/python3"
PIP="$VENV/bin/pip"

step "🔧 准备项目专用环境 ${DIM}(.venv)${RESET}…"
if [[ ! -d "$VENV" ]]; then
  python3 -m venv "$VENV" || die "无法创建虚拟环境：${BOLD}$VENV${RESET}"
  ok "已创建 .venv"
else
  ok "已存在 .venv，将复用并升级依赖"
fi

[[ -x "$PY" && -x "$PIP" ]] || die "虚拟环境异常：缺少 ${BOLD}$PY${RESET}"

# ── 2. pip install -e . ───────────────────────────────────
echo ""
echo -e "${BLUE}${BOLD}📦 正在将 Scream-Code 安装到全局环境…${RESET}"
echo -e "${DIM}   （实际为可编辑安装至本仓库 .venv，便于 scream 命令与依赖隔离）${RESET}"
"$PIP" install -q --upgrade pip setuptools wheel || die "pip / setuptools 升级失败"
"$PIP" install -q -r "$ROOT/requirements.txt" || die "安装 requirements.txt 失败"
"$PIP" install -q -e "$ROOT" || die "editable 安装失败（pip install -e .）"
ok "Scream-Code 已安装：${BOLD}scream${RESET} → ${DIM}$VENV/bin/scream${RESET}"

# ── 3. Playwright Chromium ────────────────────────────────
echo ""
echo -e "${BLUE}${BOLD}👁️ 正在初始化视觉引擎内核 (Playwright)…${RESET}"
if "$PY" -m playwright install chromium; then
  ok "Chromium 浏览器内核已就绪（/look 网页快照等能力）"
else
  warn "Playwright Chromium 安装未完全成功，可稍后手动执行："
  echo -e "   ${CYAN}$PY -m playwright install chromium${RESET}"
fi

# ── 4. 用户目录 ───────────────────────────────────────────
echo ""
step "📁 创建用户配置与技能目录…"
: "${HOME:?未设置 HOME，无法创建用户配置目录}"
mkdir -p "${HOME}/.scream/skills" "${HOME}/.scream/screenshots" || die "无法创建 ~/.scream 子目录"
ok "${DIM}~/.scream/skills${RESET} 与 ${DIM}~/.scream/screenshots${RESET} 已就绪"

# ── 5. 首次启动 ───────────────────────────────────────────
echo ""
echo -e "${GREEN}${BOLD}✅ 安装完成！正在启动 Scream-Code 首次配置向导…${RESET}"
echo -e "${DIM}   （若需配置 API Key，将随后进入交互；Ctrl+C 可中断）${RESET}"
echo ""

SCREAM_BIN="$VENV/bin/scream"
[[ -x "$SCREAM_BIN" ]] || die "未找到可执行文件：${BOLD}$SCREAM_BIN${RESET}"

echo -e "${DIM}下次可在终端直接运行：${RESET} ${CYAN}$SCREAM_BIN${RESET}"
echo -e "${DIM}或执行 ${CYAN}export PATH=\"$VENV/bin:\$PATH\"${RESET} ${DIM}后输入 ${CYAN}scream${RESET}"
echo ""
echo -e "${MAGENTA}${BOLD}────────── 以下为 Scream 输出 ──────────${RESET}"
exec "$SCREAM_BIN"
