import os
import time
import requests
import feedparser
from datetime import datetime, timedelta, timezone

# ======= RSS 信息源（已帮你换成真实目标地址）=======
RSS_URLS = [
   RSS_URLS = [
    # FortuneChina（你之前实测是能推送出来的）
    "https://plink.anyfeeder.com/fortunechina",

    # 凤凰财经：今日要闻
    "http://finance.ifeng.com/rss/headnews.xml",

    # 东方财富：策略报告（RSSHub 提供）
    "https://rsshub.app/eastmoney/report/strategyreport",

]

# 最近几天内的新闻才推送（含当天）
RECENT_DAYS = 3

# 每天推送的最大条数
MAX_ITEMS = 20

# 只保留包含这些关键词的新闻（标题内包含任意一个即可）
KEYWORDS = [# 直接点名股市 / 公司
    "A股", "沪深", "沪深两市", "中国股市",
    "上市公司", "IPO", "首发上市", "再融资",
    "分红", "派息", "高股息", "回购", "减持", "增持",
    "业绩预告", "业绩快报", "年报", "中报", "三季报",
    "重组", "并购", "资产重组", "股权转让", "控股权",
    "退市", "摘牌",

    # 政策 / 市场环境（最近新闻里很热）
    "新国九条", "市值管理",
    "中证", "沪深300",
    "中特估", "中字头",
    "注册制", "北向资金",

    # 热门赛道 & 行业（新闻里和上市公司经常一起出现）
    "新质生产力",
    "新能源", "光伏", "风电", "锂电",
    "新能源汽车", "智能汽车",
    "半导体", "芯片",
    "AI", "人工智能", "大模型", "算力",
    "高端制造", "机器人",
    "医药", "创新药",
    "消费电子",]

# GitHub Actions 运行时是 UTC，这里设定北京时间（UTC+8）
BEIJING_TZ = timezone(timedelta(hours=8))


def matches_keywords(entry):
    """判断一条新闻是否包含指定关键词（目前只看标题）"""
    title = (entry.get("title") or "").strip()
    if not title:
        return False
    return any(k in title for k in KEYWORDS)


def fetch_news():
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

    # 去重 + 关键词过滤
    seen_links = set()
    result_entries = []
    for _, e in filtered:
        # 关键词过滤：只要标题里含有 KEYWORDS 任意一个
        if KEYWORDS and not matches_keywords(e):
            continue

        link = (e.get("link") or "").strip()
        if link:
            if link in seen_links:
                continue
            seen_links.add(link)

        result_entries.append(e)
        if len(result_entries) >= MAX_ITEMS:
            break

    return result_entries


def format_text(entries):
    bj_now = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")

    if not entries:
        return (
            f"{bj_now} 上市公司 / 财经新闻精选（最近{RECENT_DAYS}天）：\n\n"
            f"当前未找到符合关键词 {KEYWORDS} 的新闻。\n"
            f"（说明：已启用关键词过滤，只推送标题中包含这些关键词的新闻）"
        )

    lines = [
        f"{bj_now} 上市公司 / 财经新闻精选（最近{RECENT_DAYS}天）：\n",
        f"信息源：FortuneChina、央视财经等；已启用关键词过滤，只保留标题中包含 {KEYWORDS} 的新闻。\n",
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
