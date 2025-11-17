import os
import time
import requests
import feedparser
from datetime import datetime, timedelta, timezone

# ======= 你自己填的 RSS 源 =======
# 下面这些只是示例，请换成你自己在新浪财经等网站上复制的 RSS 链接
RSS_URLS = [
    # 示例：把这些替换成具体的 RSS 地址，例如新浪财经股票频道的 rss 链接等
    https://link.juejin.cn/?target=https%3A%2F%2Fplink.anyfeeder.com%2Ffortunechina%2Fshangye
]

# 最近几天内的新闻才推送（含当天），你可以改成 1 或 3 等
RECENT_DAYS = 3

# 每天推送的最大条数
MAX_ITEMS = 20

# GitHub Actions 运行时是 UTC，这里设定北京时间（UTC+8）
BEIJING_TZ = timezone(timedelta(hours=8))


def fetch_news():
    items = []
    for url in RSS_URLS:
        if not url.strip():
            continue
        try:
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
            # 没时间就先保留
            filtered.append((None, e))
            continue

        ts = datetime.fromtimestamp(time.mktime(t_struct), tz=timezone.utc)
        if ts >= cutoff:
            filtered.append((ts, e))

    if not filtered:
        return []

    # 按时间排序（新的在前），None 的排在后面
    filtered.sort(key=lambda x: x[0] or datetime.fromtimestamp(0, tz=timezone.utc), reverse=True)

    # 去重（按 link）
    seen_links = set()
    result_entries = []
    for _, e in filtered:
        link = (e.get("link") or "").strip()
        if link and link in seen_links:
            continue
        seen_links.add(link)
        result_entries.append(e)
        if len(result_entries) >= MAX_ITEMS:
            break

    return result_entries


def format_text(entries):
    if not entries:
        # 没抓到有效的，就发个提示，避免 workflow 看起来像挂了
        bj_now = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")
        return f"{bj_now} 早报：目前未抓到符合条件的财经 / 上市公司新闻（可能是 RSS 源本身没有更新或时间字段缺失）。"

    bj_now = datetime.now(BEIJING_TZ).strftime("%Y-%m-%d")
    lines = [f"{bj_now} 上市公司 / 财经新闻精选（最近{RECENT_DAYS}天）：\n"]

    for i, e in enumerate(entries, 1):
        title = (e.get("title") or "").strip()
        link = (e.get("link") or "").strip()

        # 尝试拿北京时间的发布时间（如果有的话）
        t_struct = e.get("published_parsed") or e.get("updated_parsed")
        if t_struct:
            dt = datetime.fromtimestamp(time.mktime(t_struct), tz=timezone.utc).astimezone(BEIJING_TZ)
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
