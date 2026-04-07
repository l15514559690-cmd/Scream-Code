#!/usr/bin/env bash
# 尖叫 Code · 一键安装（macOS / Linux）
# 用法：在仓库根目录执行  bash install.sh

set -e

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
MARK_BEGIN='# >>> SCREAM_CODE_BEGIN >>>'
MARK_END='# <<< SCREAM_CODE_END <<<'

die() {
  echo "错误: $*" >&2
  exit 1
}

echo "==> 检查 python3 …"
command -v python3 >/dev/null 2>&1 || die "未找到 python3，请先安装 Python 3。"

echo "==> 创建虚拟环境 .venv …"
if [[ ! -d "$ROOT/.venv" ]]; then
  python3 -m venv "$ROOT/.venv" || die "无法创建 venv（部分系统需安装 python3-venv 包）。"
fi

PY="$ROOT/.venv/bin/python3"
PIP="$ROOT/.venv/bin/pip"
[[ -x "$PY" ]] || die "虚拟环境中缺少 python3：$PY"

echo "==> 安装依赖 requirements.txt …"
"$PY" -m pip install -q --upgrade pip
"$PIP" install -q -r "$ROOT/requirements.txt"

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
echo "==> 注册全局命令 scream → $RC"

# 用 Python 去掉旧块、写入新块，避免路径中的引号/空格/Unicode 拆坏 shell
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
    python3 -m src.main "$@"
  )
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

GREEN='\033[1;32m'
RESET='\033[0m'
CYAN='\033[0;36m'
echo ""
echo -e "${GREEN}✅ 安装成功！请执行 source ~/.zshrc（或 source 下方实际路径）刷新环境，然后直接输入 scream 开始体验！${RESET}"
echo -e "实际写入的配置文件: ${CYAN}source $RC${RESET}"
echo -e "之后在任意目录输入 ${CYAN}scream${RESET} 即可唤醒 Agent。"
echo ""
echo "提示: 配置模型与密钥请运行 scream config；本地保留 llm_config.json / .env（勿提交）。若无配置可先 cp llm_config.json.example llm_config.json。"
