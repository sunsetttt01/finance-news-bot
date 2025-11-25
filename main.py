import os
import time
import requests
import feedparser
from datetime import datetime, timedelta, timezone

# ================== 配置区域 ==================

# RSS 信息源（已经包含你要的那两个）
RSS_URLS = [
    "https://plink.anyfeeder.com/fortunechina",                 # FortuneChina
    "https://rss.sina.com.cn/roll/finance/hot_roll.xml",        # 新浪财经 要闻汇总
    "http://finance.ifeng.com/rss/headnews.xml",                # 凤凰财经 今日要闻
    "https://rsshub.app/eastmoney/report/strategyreport",       # 东方财富 策略报告（RSSHub）
]

# 最近几天内的新闻才推送（含当天）
RECENT_DAYS = 3

# 每天推送的最大条数
MAX_ITEMS = 20

# 如果关键词过滤后少于这个数，就启用兜底模式
MIN_ITEMS_AFTER_KEYWORDS = 5

# 只保留包含这些关键词的新闻（标题内包含任意一个即可）
KEYWORDS = [
    # 直接点名股市 / 公司
    "A股", "沪深", "沪深两市", "中国股市",
    "上市公司", "IPO", "首发上市", "再融资",
    "分红", "派息", "高股息", "回购", "减持", "增持",
    "业绩预告", "业绩快报", "年报", "中报", "三季报",
    "重组", "并购", "资产重组", "股权转让", "控股权",
    "退市", "摘牌",

    # 政策 / 市场环境
    "新国九条", "市值管理",
    "中证", "沪深300",
    "中特估", "中字头",
    "注册制", "北向资金",

    # 热门赛道 & 行业
    "新质生产力",
    "新能源", "光伏", "风电", "锂电",
    "新能源汽车", "智能汽车",
    "半导体", "芯片",
    "AI", "人工智能", "大模型", "算力",
    "高端制造", "机器人",
    "医药", "创新药",
    "消费电子",
]

# GitHub Actions 运行时是 UTC，这里设定北京时间（UTC+8）
BEIJING_TZ = timezone(timedelta(hours=8))

# ================== 功能函数 ==================


def matches_keywords(entry):
    """判断一条新闻是否包含指定关键词（目前只看标题）"""
    title = (entry.get("title") or "").strip()
    if not title:
        return False
    return any(k in title for k in KEYWORDS)


def has_chinese(title: str) -> bool:
    """判断标题里是否包含至少一个中文字符，用于兜底过滤"""
    return any("\u4e00" <= ch <= "\u9fff" for ch in title)


def fetch_all_entries():
    """
    抓取所有 RSS 源里的原始 entries，
    做时间过滤+排序+去重，但不按关键词筛。
    """
    items = []
    for url in RSS_URLS:
        if not url.strip():
            continue
        try:
            print(f"[INFO] 抓取 RSS: {url}")
            feed = feedparser.parse(url)
        except Exception as e:
            print(f"[WARN] 解析 RSS 失败: {url}，错误: {e}")
            continue

        for entry in feed.entries:
            items.append(entry)

    if not items:
        return []

    # 只要最近 RECENT_DAYS 天内的
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(days=RECENT_DAYS)

    filtered = []
    for e in items:
        # RSS 里的时间字段可能是 published_parsed / updated_parsed
        t_struct = e.get("published_parsed") or e.get("updated_parsed")
        if not t_struct:
            # 没时间就先保留，时间记成 None
            filtered.append((None, e))
            continue

        ts = datetime.fromtimestamp(time.mktime(t_struct), tz=timezone.utc)
        if ts >= cutoff:
            filtered.append((ts, e))

    if not filtered:
        return []

    # 按时间排序（新的在前），None 的排在后面
    filtered.sort(
        key=lambda x: x[0] or datetime.fromtimestamp(0, tz=timezone.utc),
        reverse=True,
    )

    # 去重（按 link）
    seen_links = set()
    unique_entries = []
    for _, e in filtered:
        link = (e.get("link") or "").strip()
        if link and link in seen_links:
            continue
        if link:
            seen_links.add(link)
        unique_entries.append(e)

    return unique_entries


def fetch_news():
    """先按关键词筛；太少就兜底不过滤关键词，但要求是中文标题"""
    all_entries = fetch_all_entries()
    if not all_entries:
        return []

    # 先按关键词过滤
    keyword_entries = [e for e in all_entries if matches_keywords(e)]

    if len(keyword_entries) >= MIN_ITEMS_AFTER_KEYWORDS:
        print(f"[INFO] 关键词过滤后条数：{len(keyword_entries)}，足够，直接使用。")
        return keyword_entries[:MAX_ITEMS]

    # 不足则兜底：不过滤关键词，但要求标题是中文（至少一个中文字符）
    print(
        f"[INFO] 关键词过滤后条数只有 {len(keyword_entries)}，"
        f"低于 {MIN_ITEMS_AFTER_KEYWORDS}，启用兜底模式（中文标题优先）。"
    )

    fallback_entries = []
    for e in all_entries:
        title = (e.get("title") or "").strip()
        if not title:
            continue
        if has_chinese(title):
            fallback_entries.append(e)
        if len(fallback_entries) >= MAX_ITEMS:
            break

    # 如果连兜底都凑不齐，就把已有的返回
    if fallback_entries:
        return fallback_entries[:MAX_ITEMS]
    else:
        return keyword_entries[:MAX_ITEMS]


def format_text(entries):
    bj_now = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")

    if not entries:
        return (
            f"{bj_now} 上市公司 / 财经新闻精选（最近{RECENT_DAYS}天）：\n\n"
            f"当前未找到符合条件的新闻。\n"
            f"（说明：先按关键词过滤，再按中文标题兜底，但源本身可能更新较少）"
        )

    lines = [
        f"{bj_now} 上市公司 / 财经新闻精选（最近{RECENT_DAYS}天）：\n",
        f"信息源：FortuneChina、新浪财经、凤凰财经、东方财富策略报告等；\n"
        f"优先按关键词过滤，如不足 {MIN_ITEMS_AFTER_KEYWORDS} 条，则按中文标题兜底补足。\n",
    ]

    for i, e in enumerate(entries, 1):
        title = (e.get("title") or "").strip()
        link = (e.get("link") or "").strip()

        # 尝试拿北京时间的发布时间（如果有的话）
        t_struct = e.get("published_parsed") or e.get("updated_parsed")
        if t_struct:
            dt = datetime.fromtimestamp(time.mktime(t_struct), tz=timezone.utc).astimezone(
                BEIJING_TZ
            )
            t_str = dt.strftime("%m-%d %H:%M")
            prefix = f"[{t_str}] "
        else:
            prefix = ""

        lines.append(f"{i}. {prefix}{title}\n{link}\n")

    return "\n".join(lines)


def send_to_feishu(text):
    webhook = os.environ.get("FEISHU_WEBHOOK")
    if not webhook:
        raise RuntimeError("请先在环境变量中设置 FEISHU_WEBHOOK（飞书机器人 Webhook 地址）")

    payload = {
        "msg_type": "text",
        "content": {
            "text": text
        }
    }

    resp = requests.post(webhook, json=payload, timeout=10)
    if resp.status_code != 200:
        print("飞书返回异常：", resp.status_code, resp.text)
        resp.raise_for_status()
    else:
        print("飞书消息发送成功。")


if __name__ == "__main__":
    news = fetch_news()
    msg = format_text(news)
    print("=== 将要发送的内容预览 ===")
    print(msg)
    print("==========================")
    send_to_feishu(msg)
