import json
import os
import sys
import asyncio
from playwright.async_api import async_playwright

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
RESTAURANTS_FILE = "restaurants.json"
STATUS_FILE = "status.json"

AVAILABLE_TEXT = "このお店を予約する"
UNAVAILABLE_TEXT = "ご予約可能な枠がありません"


def load_restaurants():
    with open(RESTAURANTS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_status():
    if os.path.exists(STATUS_FILE):
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_status(status):
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, ensure_ascii=False, indent=2)


def make_reservation_url(url):
    """URLの末尾に /reservations/new を付ける"""
    return url.rstrip("/") + "/reservations/new"


async def get_restaurant_name(page):
    """ページからレストラン名を取得"""
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

        # ページからレストラン名を取得（取れなければJSONの名前を使う）
        page_name = await get_restaurant_name(page)
        name = page_name if page_name else name_fallback

        available = AVAILABLE_TEXT in content
        unavailable = UNAVAILABLE_TEXT in content

        if available:
            print(f"  → ✅ 予約可能 ({name})")
        elif unavailable:
            print(f"  → ❌ 満席 ({name})")
        else:
            print(f"  → ⚠️ 判定不明 ({name})")

        return {"name": name, "url": url, "available": available}

    except Exception as e:
        print(f"  → ⚠️ エラー: {e}")
        return {"name": name_fallback, "url": url, "available": None, "error": str(e)}


async def send_slack(name, url):
    import urllib.request

    reservation_url = make_reservation_url(url)

    message = {
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"🍽️ *予約可能になりました！*\n\n*レストラン:* {name}\n*URL:* {url}"
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
    prev_status = load_status()
    new_status = {}
    notify_list = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            locale="ja-JP",
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        for restaurant in restaurants:
            result = await check_restaurant(page, restaurant)
            url = result["url"]
            new_status[url] = result.get("available")

            # 「False/None → True」に変わったときだけ通知
            if result.get("available") and not prev_status.get(url):
                notify_list.append(result)

        await browser.close()

    save_status(new_status)

    if notify_list:
        if not SLACK_WEBHOOK_URL:
            print("⚠️ SLACK_WEBHOOK_URL が設定されていません")
            sys.exit(1)
        for r in notify_list:
            await send_slack(r["name"], r["url"])
    else:
        print("新しく予約可能になったレストランはありません")


if __name__ == "__main__":
    asyncio.run(main())
