#!/usr/bin/env pwsh
# =============================================================================
#  Scream-Code · 开箱即用安装脚本（Windows PowerShell）
#  在仓库根目录执行:
#    powershell -ExecutionPolicy Bypass -File .\install.ps1
# =============================================================================

$ErrorActionPreference = "Stop"

function Write-Die {
    param([string]$Message)
    Write-Host ""
    Write-Host "💥 $Message" -ForegroundColor Red
    exit 1
}

function Write-Step {
    param([string]$Message)
    Write-Host "▶ $Message" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host "✅ $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "⚠️  $Message" -ForegroundColor Yellow
}

function Invoke-Safely {
    param(
        [string]$Title,
        [scriptblock]$Action,
        [string]$FixHint = "请检查网络、代理或权限后重试。"
    )
    try {
        & $Action
    } catch {
        Write-Die "$Title 失败。$FixHint"
    }
}

function Get-PythonCommand {
    $candidates = @(
        @("python"),
        @("py", "-3")
    )
    foreach ($cmd in $candidates) {
        $exe = $cmd[0]
        if (Get-Command $exe -ErrorAction SilentlyContinue) {
            try {
                & $exe @($cmd[1..($cmd.Length - 1)]) --version *> $null
                return ,$cmd
            } catch {
                continue
            }
        }
    }
    return $null
}

function Test-PythonVersion {
    param([string[]]$PythonCmd)
    try {
        & $PythonCmd[0] @($PythonCmd[1..($PythonCmd.Length - 1)]) -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
        return $true
    } catch {
        return $false
    }
}

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

Write-Host ""
Write-Host "╔══════════════════════════════════════════════════════════╗" -ForegroundColor Magenta
Write-Host "║  🜂 Scream-Code · Windows 一键安装                        ║" -ForegroundColor Magenta
Write-Host "╚══════════════════════════════════════════════════════════╝" -ForegroundColor Magenta
Write-Host "   $Root" -ForegroundColor DarkGray
Write-Host ""

Write-Step "🐍 检查 Python 环境（需要 3.10+）..."
$pythonCmd = Get-PythonCommand
if ($null -eq $pythonCmd) {
    Write-Die "未检测到 Python。请前往 https://www.python.org/downloads/windows/ 下载并安装，安装时务必勾选 Add Python to PATH。"
}
if (-not (Test-PythonVersion -PythonCmd $pythonCmd)) {
    Write-Die "检测到的 Python 版本低于 3.10。请升级 Python 后重试。"
}
$pythonVersion = (& $pythonCmd[0] @($pythonCmd[1..($pythonCmd.Length - 1)]) --version) 2>&1
Write-Ok "Python 就绪：$pythonVersion"

Write-Step "📎 检查 pip（python -m pip）..."
try {
    & $pythonCmd[0] @($pythonCmd[1..($pythonCmd.Length - 1)]) -m pip --version *> $null
} catch {
    Write-Die "无法使用 pip。请先执行 python -m ensurepip --upgrade，然后重试安装。"
}
Write-Ok "pip 可用"

if (-not (Test-Path ".\requirements.txt")) {
    Write-Die "未找到 requirements.txt，请在项目根目录运行本脚本。"
}
if (-not (Test-Path ".\setup.py")) {
    Write-Die "未找到 setup.py，请在项目根目录运行本脚本。"
}

$venvDir = Join-Path $Root ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$venvScream = Join-Path $venvDir "Scripts\scream.exe"

Write-Step "🔧 准备项目虚拟环境 (.venv)..."
if (-not (Test-Path $venvDir)) {
    Invoke-Safely -Title "创建虚拟环境" -FixHint "请确认当前目录可写，并以可写权限打开终端。" -Action {
        & $pythonCmd[0] @($pythonCmd[1..($pythonCmd.Length - 1)]) -m venv ".venv"
    }
    Write-Ok "已创建 .venv"
} else {
    Write-Ok "检测到现有 .venv，将复用并升级依赖"
}

if (-not (Test-Path $venvPython)) {
    Write-Die "虚拟环境损坏：未找到 $venvPython。请删除 .venv 后重试。"
}

Write-Host ""
Write-Host "📦 正在安装依赖与命令入口..." -ForegroundColor Cyan
Invoke-Safely -Title "升级 pip / setuptools / wheel" -Action {
    & $venvPython -m pip install --upgrade pip setuptools wheel
}
Invoke-Safely -Title "安装 requirements.txt" -FixHint "可能是网络问题，请检查代理或稍后重试。" -Action {
    & $venvPython -m pip install -r ".\requirements.txt"
}
Invoke-Safely -Title "安装 Scream-Code（pip install -e .）" -FixHint "请确认仓库完整且 setup.py 可用。" -Action {
    & $venvPython -m pip install -e "."
}
Write-Ok "依赖安装完成"

Write-Host ""
Write-Host "👁️ 正在初始化视觉内核（Playwright Chromium）..." -ForegroundColor Cyan
try {
    & $venvPython -m playwright install chromium
    Write-Ok "Chromium 内核已就绪（/look 功能可用）"
} catch {
    Write-Warn "Chromium 安装失败，通常是网络问题。你可稍后手动执行："
    Write-Host "   $venvPython -m playwright install chromium" -ForegroundColor Yellow
}

Write-Host ""
Write-Step "📁 初始化用户目录..."
$screamHome = Join-Path $HOME ".scream"
$skillsDir = Join-Path $screamHome "skills"
$shotsDir = Join-Path $screamHome "screenshots"
Invoke-Safely -Title "创建 ~/.scream 目录结构" -FixHint "请检查你的用户目录权限。" -Action {
    New-Item -ItemType Directory -Force -Path $skillsDir | Out-Null
    New-Item -ItemType Directory -Force -Path $shotsDir | Out-Null
}
Write-Ok "用户目录已就绪：$skillsDir / $shotsDir"

Write-Host ""
Write-Host "✅ 安装完成，正在启动 Scream-Code 首次配置向导..." -ForegroundColor Green
Write-Host "   （如需填写 API Key，按提示操作即可）" -ForegroundColor DarkGray
Write-Host ""

if (-not (Test-Path $venvScream)) {
    Write-Warn "未找到 $venvScream，尝试使用 Python 模块入口启动。"
    Invoke-Safely -Title "启动 scream" -Action {
        & $venvPython -m src.main
    }
    exit 0
}

Write-Host "下次可直接运行：" -ForegroundColor DarkGray
Write-Host "  $venvScream" -ForegroundColor Cyan
Write-Host ""
Write-Host "────────── 以下为 Scream 输出 ──────────" -ForegroundColor Magenta
& $venvScream
