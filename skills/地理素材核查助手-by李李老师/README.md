# 🌍 地理素材核查助手-by李李老师

> 基于 DuckDuckGo 多源检索的地理素材客观性核查工具

---

## 📦 安装与配置

### 1. 安装依赖

**Windows 用户：**
```bash
# 打开 cmd 或 PowerShell
pip install ddgs

# 如果遇到问题，尝试：
pip install ddgs --no-cache-dir
```

**macOS / Linux 用户：**
```bash
pip install ddgs
```

### 2. 验证安装
```python
from ddgs import DDGS
print("✅ 安装成功！")
```

---

## 🚀 快速开始

### 方法一：在尖叫 Code 中使用（推荐）

1. 确保 `geo_fact_checker_by_lili.py` 位于 `~/Desktop/ScreamCode/skills/` 目录
2. 在尖叫 Code 中直接调用：
```python
check_geography_material("珠穆朗玛峰海拔8848米，位于喜马拉雅山脉")
```

### 方法二：独立 Python 脚本使用

```python
# 保存为 check_geo.py
import sys
sys.path.insert(0, '/path/to/skills/')
from geo_fact_checker_by_lili import check_geography_material

# 执行核查
report = check_geography_material(
    material="中国陆地面积约960万平方公里",
    output_path="/Users/tod/Desktop/核查报告.md"
)
print(report)
```

### 方法三：命令行使用

```bash
python -c "
import sys
sys.path.insert(0, 'skills')
from geo_fact_checker_by_lili import check_geography_material
check_geography_material('长江全长约6300公里')
"
```

---

## 📖 功能说明

| 功能 | 说明 |
|------|------|
| 📝 声明提取 | 智能识别素材中的可核查陈述 |
| 🔍 多源检索 | DuckDuckGo 实时搜索，无需 API Key |
| 🏛️ 来源分类 | 7级权威性权重评估 |
| 📊 客观率评分 | 0-100% 量化评估 |
| 🔗 Top3 来源 | 最相关的权威来源推荐 |
| 📄 报告生成 | Markdown 格式完整报告 |

---

## 📊 来源权威性权重

```
官方机构    ████████████████  1.00  🏛️
学术期刊    ███████████████   0.95  📚
权威媒体    ██████████████    0.85  📰
专业媒体    ████████████      0.75  🔬
百科        ██████████        0.65  📖
社交媒体    ██████            0.40  💬
未知        ████              0.30  ❓
```

---

## 📋 使用示例

### 示例 1：核查山峰数据
```python
check_geography_material(
    material="珠穆朗玛峰海拔8848.86米，是世界最高峰，位于喜马拉雅山脉中段"
)
```

### 示例 2：核查河流数据
```python
check_geography_material(
    material="长江全长约6300余公里，发源于青藏高原，流经11个省市"
)
```

### 示例 3：核查国家面积
```python
check_geography_material(
    material="俄罗斯是世界上面积最大的国家，总面积约1709万平方公里"
)
```

---

## ⚠️ 常见问题

### Q1: Windows 上安装 ddgs 失败？
```
# 尝试使用管理员权限打开 PowerShell
pip install --user ddgs

# 或更新 pip
python -m pip install --upgrade pip
```

### Q2: 搜索结果为空？
- 检查网络连接
- 部分地区可能需要代理
- 可尝试更换网络环境

### Q3: 如何提高核查准确性？
- 提供更完整的素材内容
- 包含具体数字和来源标注的素材更易核查
- 避免模糊表述

### Q4: macOS 提示「无法打开」？
```
# 首次运行需允许 Python 通过防火墙
# 系统偏好设置 → 安全性与隐私 → 通用 → 允许
```

---

## 🔧 Windows 兼容配置

### 使用 Anaconda（推荐）
```bash
conda create -n geo_check python=3.9
conda activate geo_check
pip install ddgs
```

### 使用虚拟环境
```bash
python -m venv venv
venv\Scripts\activate
pip install ddgs
```

---

## 📄 输出报告示例

核查完成后会自动生成 Markdown 报告，包含：
- 📋 原始素材
- 📊 客观率评估（带可视化进度条）
- 📝 声明提取
- 🔗 Top 3 最相关来源
- 📚 完整搜索结果
- ✅ 核查结论与使用建议

---

## 📌 版本信息

- **版本**: 1.7.0
- **作者**: 李李老师
- **原名**: 地理编辑素材核查助手
- **更新**: 2024-04-11

---

## 📞 反馈与支持

如遇问题，请提供：
1. 操作系统版本（Windows 10/11, macOS, Linux）
2. Python 版本（`python --version`）
3. 错误信息截图
4. 核查的素材内容
