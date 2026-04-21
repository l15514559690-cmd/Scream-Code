# -*- coding: utf-8 -*-
"""
地理编辑素材核查助手 Skill v1.7.0
作者: 尖叫 Code

功能:
- 智能提取地理声明
- DuckDuckGo 多源检索（无需 API）
- 客观率评估 + Top3 来源

依赖: pip install ddgs
"""

import re
from datetime import datetime
from typing import List, Dict, Any

# ============================================================
# 来源类型
# ============================================================

SOURCE_TYPES = {
    "官方": 1.0, "学术": 0.95, "权威媒体": 0.85,
    "专业媒体": 0.75, "百科": 0.65, "社交媒体": 0.40, "未知": 0.30
}

# ============================================================
# 工具函数
# ============================================================

def extract_claims(material: str) -> List[str]:
    """提取可核查的地理声明"""
    geo_keywords = ['海拔', '高度', '面积', '人口', '长度', '距离', '温度', 
                   '位于', '最高峰', '最长', '最大', '最小', '河流', '山脉',
                   '湖泊', '岛屿', '沙漠', '平原', '高原', '盆地', '半岛',
                   '国家', '城市', '洲', '洋', '海', '峰', '峡', '运河',
                   '经度', '纬度', '坐标', '气候', '年', '月', '日',
                   '地震', '火山', '瀑布', '森林', '草原', '冰川']
    
    claims = []
    for sent in re.split(r'[。！？\n]', material):
        sent = sent.strip()
        if len(sent) < 5: continue
        
        if any(kw in sent for kw in geo_keywords) or re.search(r'[\d,.%％]+(?:米|公里|km|KM|℃|°|万|亿|千|ha|km²)', sent):
            cleaned = re.sub(r'^\d+[.、)）]\s*', '', sent)
            if 5 <= len(cleaned) <= 100:
                claims.append(cleaned)
    
    return claims[:5] if claims else [material[:100]]


def classify_source(url: str) -> Dict[str, Any]:
    """来源分类"""
    url_lower = url.lower()
    
    if any(d in url_lower for d in ['gov.cn', 'gov.', 'nasa.gov', 'noaa.gov', 'stats.gov.cn', 'cma.cn', 'un.org']):
        return {"type": "官方", "weight": 1.0}
    if any(d in url_lower for d in ['cnki.net', 'wanfangdata', 'springer', 'nature.com', 'sciencedirect', 'arxiv']):
        return {"type": "学术", "weight": 0.95}
    if any(d in url_lower for d in ['xinhuanet', 'people.com.cn', 'cctv', 'bbc.com', 'reuters', 'thepaper', 'caixin']):
        return {"type": "权威媒体", "weight": 0.85}
    if any(d in url_lower for d in ['sciencenet', 'dili', 'nationalgeographic', 'smithsonian', 'earth', 'space.com', 'dili360']):
        return {"type": "专业媒体", "weight": 0.75}
    if any(d in url_lower for d in ['wikipedia', 'wikimedia', 'baike.baidu', 'wikidata', 'britannica', 'baike.sogou', 'baike.qq', 'baike.360', 'osgeo']):
        return {"type": "百科", "weight": 0.65}
    if any(d in url_lower for d in ['weibo', 'weixin', 'douyin', 'zhihu', 'twitter', 'facebook', 'toutiao', 'bilibili']):
        return {"type": "社交媒体", "weight": 0.40}
    return {"type": "未知", "weight": 0.30}


def extract_domain_name(url: str) -> str:
    """提取域名"""
    match = re.search(r'(?:https?://)?(?:www\.)?([^/]+)', url)
    if match:
        domain = match.group(1)
        replacements = {
            'baike.baidu.com': '百度百科', 'zh.wikipedia.org': '维基百科', 'en.wikipedia.org': 'Wikipedia',
            'xinhuanet.com': '新华网', 'people.com.cn': '人民网', 'weibo.com': '微博', 'zhihu.com': '知乎',
            'cnki.net': '知网', 'sciencenet.cn': '科学网', 'sina.com.cn': '新浪', 'qq.com': '腾讯',
            'toutiao.com': '今日头条', 'thepaper.cn': '澎湃新闻', 'ifeng.com': '凤凰网', 'youtube.com': 'YouTube',
            'bilibili.com': '哔哩哔哩', 'cctv.com': '央视网', 'dili360.com': '中国国家地理',
            'baike.sogou.com': '搜狗百科', 'baike.qq.com': '腾讯百科', 'i.jandan.net': '煎蛋网',
            'osgeo.cn': '开源地理', 'baike.360.cn': '360百科',
        }
        return replacements.get(domain, domain)
    return "未知"


def search_ddg(query: str, max_results: int = 10) -> List[Dict]:
    """DuckDuckGo 搜索 - v1.7.0 中文优化"""
    try:
        from ddgs import DDGS
        results = []
        with DDGS() as ddgs:
            # 使用纯中文关键词搜索（更有针对性）
            search_query = query
            for r in ddgs.text(search_query, max_results=max_results):
                url = r.get('href') or r.get('url', '')
                info = classify_source(url)
                results.append({
                    'title': r.get('title', '未命名'),
                    'url': url,
                    'name': extract_domain_name(url),
                    'snippet': re.sub(r'\s+', ' ', r.get('body', ''))[:250],
                    **info,
                    'relevance': '高' if info['weight'] >= 0.65 else '中'
                })
        return results
    except Exception as e:
        print(f"   ⚠️ 搜索异常: {e}")
        return []


def calculate_score(sources: List[Dict]) -> Dict[str, Any]:
    """计算客观率 v1.7.0"""
    if not sources:
        return {"score": 0, "level": "无法评估", "description": "未找到相关来源", "dist": {}}
    
    dist = {}
    total_weight = 0
    for s in sources:
        t = s.get("type", "未知")
        w = s.get("weight", 0.3)
        dist[t] = dist.get(t, 0) + 1
        total_weight += w
    
    avg = total_weight / len(sources)
    auth_types = ["官方", "学术", "权威媒体", "专业媒体", "百科"]
    auth_count = sum(dist.get(t, 0) for t in auth_types)
    auth_ratio = auth_count / len(sources)
    
    # 评分等级
    if auth_ratio >= 0.8:
        score = min(95, round((avg + 0.3) * 100))
    elif auth_ratio >= 0.5:
        score = min(85, round((avg + 0.2) * 100))
    elif auth_ratio >= 0.3:
        score = min(70, round((avg + 0.1) * 100))
    else:
        score = min(60, round(avg * 100))
    
    if score >= 85: level, desc = "高度客观", "多个权威来源支持，客观性很高"
    elif score >= 70: level, desc = "较为客观", "有可靠来源支撑，客观性较好"
    elif score >= 50: level, desc = "部分客观", "来源参差不齐，需谨慎参考"
    elif score >= 30: level, desc = "可信存疑", "缺乏权威来源支撑"
    else: level, desc = "难以判断", "未找到有效来源"
    
    return {"score": score, "level": level, "description": desc, "dist": dist}


def format_report(material: str, claims: List, results: List, score: Dict, top3: List) -> str:
    """生成报告"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    s = score["score"]
    bar = "█" * int(20 * s / 100) + "░" * (20 - int(20 * s / 100))
    dist_text = "、".join([f"{k}×{v}" for k, v in score.get("dist", {}).items()]) or "无"
    
    emoji = {"官方": "🏛️", "学术": "📚", "权威媒体": "📰", "专业媒体": "🔬", 
             "百科": "📖", "社交媒体": "💬", "未知": "❓"}
    
    md = f"""# 🔍 地理素材核查报告

> 📅 {ts} | 🎯 地理编辑素材核查

---

## 📋 原始素材
```
{material}
```

## 📊 客观率评估

| 指标 | 数值 |
|:----:|:----:|
| **客观率** | **{s}%** |
| 评级 | {score['level']} |
| 来源数 | {len(results)} 条 |
| 分布 | {dist_text} |

`[{bar}] {s}%`

{score['description']}

"""
    
    if claims:
        md += "## 📝 声明提取\n"
        md += "".join([f"{i}. **{c}**\n" for i, c in enumerate(claims, 1)]) + "\n"

    if top3:
        md += "## 🔗 Top 3 最相关来源\n\n"
        for i, src in enumerate(top3, 1):
            md += f"### {i}. {emoji.get(src.get('type', '未知'), '📌')} {src.get('title', '未命名')}\n\n"
            md += f"| 类型 | 网站 | 相关度 |\n|:----:|:----:|:----:|\n"
            md += f"| {src.get('type', '未知')} | {src.get('name', '未知')} | {src.get('relevance', '中')} |\n\n"
            md += f"🔗 **链接**: {src.get('url', '#')}\n\n"
            if src.get('snippet'):
                md += f"> 📝 {src['snippet'][:200]}\n\n"

    if results:
        md += f"## 📚 完整搜索结果 ({len(results)} 条)\n\n"
        for i, r in enumerate(results, 1):
            md += f"**{i}.** {emoji.get(r.get('type', '未知'), '📌')} **{r.get('title', '未命名')}**  \n"
            md += f"   - {r.get('name', '未知')} | {r.get('type', '未知')}  \n"
            md += f"   - 🔗 {r.get('url', '#')}\n\n"

    md += "## ✅ 核查结论\n\n"
    md += f"**客观率: {s}%** — **{score['level']}**\n\n"
    md += "🎉 可直接使用\n" if s >= 85 else "👍 建议注明来源\n" if s >= 70 else "⚠️ 建议补充权威来源\n" if s >= 50 else "🚨 建议核实后使用\n"
    md += f"""
### 💡 使用建议
1. 优先引用 Top3 来源中的权威信息
2. 涉及具体数据建议注明官方/学术来源
3. 对存疑内容添加限定语（如「资料显示」）
"""
    md += f"\n---\n*🤖 地理编辑素材核查助手 v1.7.0*\n"
    return md


def fact_check_material(material: str) -> Dict[str, Any]:
    """核查主函数"""
    claims = extract_claims(material)
    print(f"📝 提取到 {len(claims)} 个声明")
    
    all_results = []
    for claim in claims:
        # 构造中文搜索词
        search_term = claim
        print(f"🔍 搜索: 「{search_term[:25]}...」")
        results = search_ddg(search_term, max_results=8)
        print(f"   → {len(results)} 条")
        all_results.extend(results)
    
    seen = set()
    unique = [r for r in all_results if not (r['url'] in seen or seen.add(r['url']))]
    unique = [r for r in unique if r['url'] and len(r['url']) > 10]
    
    score_result = calculate_score(unique)
    sorted_r = sorted(unique, key=lambda x: x.get('weight', 0.3), reverse=True)
    top3 = sorted_r[:3]
    
    return {
        "material": material, "claims": claims, "search_results": unique,
        "total": len(unique), "score": score_result, "top3": top3,
        "report": format_report(material, claims, unique, score_result, top3)
    }


def check_geography_material(material: str, output_path: str = None) -> str:
    """入口函数"""
    print("=" * 60)
    print("🔍 地理编辑素材核查助手 v1.7.0")
    print("=" * 60)
    
    result = fact_check_material(material)
    
    if output_path is None:
        output_path = "/Users/tod/Desktop/地理素材核查报告.md"
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(result["report"])
    
    print(f"\n✅ 报告已保存: {output_path}")
    print(f"📊 客观率: {result['score']['score']}% | 🔗 来源: {result['total']} 条")
    
    return result["report"]


SKILL_METADATA = {
    "name": "地理编辑素材核查助手", "version": "1.7.0",
    "description": "基于 DuckDuckGo 多源检索，核查地理素材客观性",
    "triggers": ["核查素材", "验证素材", "核实地理", "素材查真", "来源核查"],
    "features": ["声明提取", "ddgs搜索", "权威分类", "客观率评估", "Top3来源", "报告输出"],
    "usage": 'check_geography_material("珠穆朗玛峰海拔8848米")'
}

__all__ = ["check_geography_material", "fact_check_material", "SKILL_METADATA"]


if __name__ == "__main__":
    print("🔍 地理编辑素材核查助手 v1.7.0")
