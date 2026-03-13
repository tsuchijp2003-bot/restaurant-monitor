import json
import os
import sys
import functools
print = functools.partial(print, flush=True)
import asyncio
from playwright.async_api import async_playwright

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
RESTAURANT_URLS = os.environ.get("RESTAURANT_URLS", "[]")

AVAILABLE_BUTTON = 'ui button primary big fluid'
AVAILABLE_TEXT = "このお店を予約する"

LOOP_COUNT = 30      # 12回チェック
LOOP_INTERVAL = 120  # 5分おき


def load_restaurants():
    return json.loads(RESTAURANT_URLS)


def make_reservation_url(url):
    url = url.replace("/ja/r/", "/r/")
    return url.rstrip("/") + "/reservations/new"


async def check_restaurant(page, restaurant):
    url = restaurant["url"]
    name = restaurant.get("name", url)
    print(f"チェック中: {name} ({url})")

    content = ""
    for attempt in range(3):
        try:
            await page.goto(url, timeout=30000, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
            content = await page.content()
            if len(content) > 10000:
                break
            print(f"  → HTML少なすぎ({len(content)}文字)、リトライ {attempt+1}/3...")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"  → ⚠️ エラー(試行{attempt+1}): {e}")
            await asyncio.sleep(5)

    print(f"  → HTML取得: {len(content)}文字")

    for label, text in [("予約可能テキスト", AVAILABLE_TEXT), ("予約ボタンクラス", AVAILABLE_BUTTON)]:
        idx = content.find(text)
        if idx != -1:
            start = max(0, idx - 100)
            end = min(len(content), idx + len(text) + 100)
            print(f"  → [{label}] の前後:\n{content[start:end]}\n")
        else:
            print(f"  → [{label}]: 見つかりませんでした")

    has_button = AVAILABLE_BUTTON in content
    has_text = AVAILABLE_TEXT in content
    available = has_button and has_text

    if available:
        print(f"  → 判定: ✅ 予約可能 ({name})")
    else:
        print(f"  → 判定: ❌ 満席 ({name})")

    return {"name": name, "url": url, "available": available}


async def send_slack(name, url):
    import urllib.request

    reservation_url = make_reservation_url(url)

    message = {
        "blocks": [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"🍽️ *予約可能です！*\n\n*レストラン:* {name}\n*URL:* {reservation_url}"
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


async def run_check(restaurants):
    """1回分のチェックを全店舗に対して実行"""
    notify_list = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"]
        )

        for restaurant in restaurants:
            context = await browser.new_context(
                locale="ja-JP",
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            await context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            page = await context.new_page()
            result = await check_restaurant(page, restaurant)
            await context.close()
            if result["available"]:
                notify_list.append(result)

        await browser.close()

    return notify_list


async def main():
    restaurants = load_restaurants()
    if not restaurants:
        print("⚠️ RESTAURANT_URLS が設定されていません")
        sys.exit(1)

    for i in range(LOOP_COUNT):
        now = i * LOOP_INTERVAL // 60
        print(f"\n{'='*50}")
        print(f"チェック {i+1}/{LOOP_COUNT} 回目（開始から約{now}分経過）")
        print(f"{'='*50}")

        notify_list = await run_check(restaurants)

        if notify_list:
            if not SLACK_WEBHOOK_URL:
                print("⚠️ SLACK_WEBHOOK_URL が設定されていません")
                sys.exit(1)
            for r in notify_list:
                await send_slack(r["name"], r["url"])
        else:
            print("予約可能なレストランはありません")

        # 最後のループは待機不要
        if i < LOOP_COUNT - 1:
            print(f"\n⏳ {LOOP_INTERVAL // 60}分待機中...")
            await asyncio.sleep(LOOP_INTERVAL)


if __name__ == "__main__":
    asyncio.run(main())
