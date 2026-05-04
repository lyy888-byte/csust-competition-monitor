#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
长沙理工大学教务处 - 学科竞赛监控脚本 (GitHub Actions版)
每天10:00(北京时间)运行，检查新发布的竞赛通知。
"""

import requests
from bs4 import BeautifulSoup
import re
import json
import os
import smtplib
import ssl
from email.mime.text import MIMEText
from email.header import Header
from datetime import datetime
import time

LIST_URL = "https://www.csust.edu.cn/jwc/cxjy_/xkjs.htm"
BASE_URL = "https://www.csust.edu.cn/jwc"
DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")

SMTP_SERVER = "smtp.qq.com"
SMTP_PORT = 465
SENDER_EMAIL = "1485409289@qq.com"
SENDER_AUTH_CODE = os.environ.get("SMTP_AUTH_CODE", "")
RECEIVER_EMAIL = "1485409289@qq.com"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
}


def fetch_page(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.encoding = "utf-8"
        if resp.status_code != 200:
            print(f"[ERROR] HTTP {resp.status_code} for {url}")
            return None
        return resp.text
    except Exception as e:
        print(f"[ERROR] Request failed: {e}")
        return None


def parse_list_page(html):
    soup = BeautifulSoup(html, "html.parser")
    items = []

    for li in soup.select("ul li[id^='line_u7_']"):
        title_elem = li.select_one(".listitem-title a")
        date_elem = li.select_one(".listitem-date")

        if not title_elem or not date_elem:
            continue

        title = title_elem.get("title", "").strip()
        href = title_elem.get("href", "").strip()
        date_text = date_elem.get_text(strip=True)

        match = re.search(r"/(\d+)\.htm", href)
        article_id = match.group(1) if match else None

        if href.startswith("../"):
            detail_url = BASE_URL + href[2:]
        elif href.startswith("/"):
            detail_url = "https://www.csust.edu.cn" + href
        else:
            detail_url = href

        items.append({
            "id": article_id,
            "title": title,
            "date": date_text,
            "url": detail_url,
        })

    return items


def extract_qq_group(html):
    if not html:
        return []

    qq_groups = []
    patterns = [
        r"QQ群[（(]?\s*群号[：:]\s*(\d{5,12})\s*[）)]?",
        r"群号[：:]\s*(\d{5,12})",
        r"QQ群[：:]\s*(\d{5,12})",
        r"加入.*?QQ.*?(\d{5,12})",
        r"QQ.*?群.*?(\d{5,12})",
    ]

    text = BeautifulSoup(html, "html.parser").get_text()
    for pattern in patterns:
        matches = re.findall(pattern, text)
        for m in matches:
            if m not in qq_groups:
                qq_groups.append(m)

    return qq_groups


def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def send_email(subject, body):
    auth_len = len(SENDER_AUTH_CODE) if SENDER_AUTH_CODE else 0
    print(f"[DEBUG] SMTP_AUTH_CODE present: {bool(SENDER_AUTH_CODE)}, length={auth_len}")

    if not SENDER_AUTH_CODE:
        print("[WARN] SMTP_AUTH_CODE not set, skipping email")
        return False

    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECEIVER_EMAIL
    msg["Subject"] = Header(subject, "utf-8")

    methods = [
        ("SMTP_SSL:465", lambda: smtplib.SMTP_SSL(SMTP_SERVER, 465, timeout=30)),
        ("SMTP+STARTTLS:587", lambda: _smtp_starttls()),
    ]

    for label, factory in methods:
        try:
            print(f"[DEBUG] Trying {label} ...")
            server = factory()
            server.login(SENDER_EMAIL, SENDER_AUTH_CODE)
            server.sendmail(SENDER_EMAIL, [RECEIVER_EMAIL], msg.as_string())
            server.quit()
            print(f"[OK] Email sent via {label}")
            return True
        except Exception as e:
            print(f"[WARN] {label} failed: {e}")

    print("[ERROR] All SMTP methods failed")
    return False


def _smtp_starttls():
    server = smtplib.SMTP(SMTP_SERVER, 587, timeout=30)
    context = ssl.create_default_context()
    server.starttls(context=context)
    return server


def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Checking for updates...")

    html = fetch_page(LIST_URL)
    if not html:
        print("[ERROR] Cannot fetch list page")
        return

    items = parse_list_page(html)
    print(f"[INFO] Found {len(items)} entries on page 1")

    stored_data = load_data()
    stored_ids = set(stored_data.keys())

    new_items = []
    for item in items:
        if item["id"] and item["id"] not in stored_ids:
            new_items.append(item)

    today = datetime.now().strftime("%Y-%m-%d")

    if not new_items:
        print("[INFO] No new entries")
        send_email(
            f"学科竞赛监控 - {today}",
            f"【{today}】长沙理工大学教务处学科竞赛页面没有新发布的竞赛通知。\n\n监测地址：{LIST_URL}"
        )
        for item in items:
            if item["id"] and item["id"] not in stored_data:
                stored_data[item["id"]] = {
                    "title": item["title"],
                    "date": item["date"],
                    "url": item["url"],
                    "qq_groups": [],
                }
        save_data(stored_data)
        return

    print(f"[INFO] {len(new_items)} new entries found")

    for item in new_items:
        print(f"[INFO] Fetching detail: {item['title'][:40]}...")
        detail_html = fetch_page(item["url"])
        qq_groups = extract_qq_group(detail_html) if detail_html else []
        item["qq_groups"] = qq_groups
        if qq_groups:
            print(f"  QQ群: {', '.join(qq_groups)}")
        else:
            print(f"  QQ群: not found")
        time.sleep(1)

    lines = [f"【{today}】长沙理工大学教务处学科竞赛有新通知，共 {len(new_items)} 条：\n"]
    for i, item in enumerate(new_items, 1):
        lines.append(f"{i}. {item['title']}")
        lines.append(f"   日期: {item['date']}")
        if item["qq_groups"]:
            lines.append(f"   QQ群号: {', '.join(item['qq_groups'])}")
        else:
            lines.append(f"   QQ群号: 未找到")
        lines.append(f"   链接: {item['url']}")
        lines.append("")
    lines.append(f"监测地址：{LIST_URL}")

    body = "\n".join(lines)
    subject = f"学科竞赛新通知 - {today} ({len(new_items)}条)"

    send_email(subject, body)

    for item in new_items:
        stored_data[item["id"]] = {
            "title": item["title"],
            "date": item["date"],
            "url": item["url"],
            "qq_groups": item.get("qq_groups", []),
        }
    save_data(stored_data)

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Done")


if __name__ == "__main__":
    main()
