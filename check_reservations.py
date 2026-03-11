import json
import os
import sys
import asyncio
from playwright_stealth import stealth_async
from playwright.async_api import async_playwright

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
RESTAURANTS_FILE = "restaurants.json"

AVAILABLE_TEXT = "このお店を予約する"
UNAVAILABLE_TEXT = "ログインして空き枠を確認"


def load_restaurants():
    with open(RESTAURANTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def make_reservation_url(url):
    return url.rstrip("/") + "/reservations/new"


async def get_restaurant_name(page):
    try:
        el = await page.query_selector("h1")
        if el:
            name = await el.inner_text()
            name = name.strip()
            if name:
                return name
    except:
        pass
    return None


async def check_restaurant(page, restaurant):
    url = restaurant["url"]
    name_fallback = restaurant.get("name", url)
    print(f"チェック中: {name_fallback} ({url})")

    try:
        await page.goto(url, timeout=30000, wait_until="domcontentloaded")
        await page.wait_for_timeout(3000)

        content = await page.content()

        page_name = await get_restaurant_name(page)
        name = page_name if page_name else name_fallback

        available = AVAILABLE_TEXT in content

        if available:
            print(f"  → ✅ 予約可能 ({name})")
        elif UNAVAILABLE_TEXT in content:
            print(f"  → ❌ 満席 ({name})")
        else:
            print(f"  → ⚠️ 判定不明 ({name})")

        return {"name": name, "url": url, "available": available}

    except Exception as e:
        print(f"  → ⚠️ エラー: {e}")
        return {"name": name_fallback, "url": url, "available": False}


async def send_slack(name, url):
    import urllib.request

    reservation_url = make_reservation_url(url)

    message = {
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"🍽️ *予約可能です！*\n\n*レストラン:* {name}\n*URL:* {url}"
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "今すぐ予約する →"},
                        "url": reservation_url,
                        "style": "primary"
                    }
                ]
            }
        ]
    }

    data = json.dumps(message).encode("utf-8")
    req = urllib.request.Request(
        SLACK_WEBHOOK_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req) as res:
        print(f"Slack通知送信: {res.status} ({name})")


async def main():
    restaurants = load_restaurants()
    notify_list = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            locale="ja-JP",
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        await stealth_async(page)

        for restaurant in restaurants:
            result = await check_restaurant(page, restaurant)
            if result["available"]:
                notify_list.append(result)

        await browser.close()

    if notify_list:
        if not SLACK_WEBHOOK_URL:
            print("⚠️ SLACK_WEBHOOK_URL が設定されていません")
            sys.exit(1)
        for r in notify_list:
            await send_slack(r["name"], r["url"])
    else:
        print("予約可能なレストランはありません")


if __name__ == "__main__":
    asyncio.run(main())
