import json
import os
import sys
import asyncio
import functools
import time
from playwright.async_api import async_playwright

# 全printをリアルタイム出力に
print = functools.partial(print, flush=True)

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
RESTAURANT_URLS = os.environ.get("RESTAURANT_URLS", "[]")

AVAILABLE_BUTTON = 'ui button primary big fluid'
AVAILABLE_TEXT = "このお店を予約する"

MAX_SECONDS = 6 * 60 * 60  # 6時間


def load_restaurants():
    return json.loads(RESTAURANT_URLS)


def make_reservation_url(url):
    url = url.replace("/ja/r/", "/r/")
    return url.rstrip("/") + "/reservations/new"


def elapsed_str(start):
    elapsed = int(time.time() - start)
    h = elapsed // 3600
    m = (elapsed % 3600) // 60
    s = elapsed % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


async def check_restaurant(page, restaurant):
    url = restaurant["url"]
    name = restaurant.get("name", url)
    print(f"  チェック中: {name}")

    content = ""
    for attempt in range(3):
        try:
            print(f"    → ページ読み込み開始... (試行{attempt+1}/3)")
            await page.goto(url, timeout=30000, wait_until="domcontentloaded")
            await page.wait_for_timeout(3000)
            content = await page.content()
            print(f"    → HTML取得: {len(content)}文字")
            if len(content) > 10000:
                break
            print(f"    → HTML少なすぎ、リトライ...")
            await asyncio.sleep(5)
        except Exception as e:
            print(f"    → ⚠️ エラー(試行{attempt+1}): {e}")
            await asyncio.sleep(5)

    for label, text in [("予約可能テキスト", AVAILABLE_TEXT), ("予約ボタンクラス", AVAILABLE_BUTTON)]:
        idx = content.find(text)
        if idx != -1:
            start = max(0, idx - 100)
            end = min(len(content), idx + len(text) + 100)
            print(f"    → [{label}] の前後:\n{content[start:end]}\n")
        else:
            print(f"    → [{label}]: 見つかりませんでした")

    has_button = AVAILABLE_BUTTON in content
    has_text = AVAILABLE_TEXT in content
    available = has_button and has_text

    if available:
        print(f"    → 判定: ✅ 予約可能")
    else:
        print(f"    → 判定: ❌ 満席")

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
        print(f"  Slack通知送信: {res.status} ({name})")


async def run_check(restaurants):
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

    print(f"監視対象: {len(restaurants)}店舗")
    print(f"最大実行時間: {MAX_SECONDS // 3600}時間")

    start_time = time.time()
    loop_count = 0

    while time.time() - start_time < MAX_SECONDS:
        loop_count += 1
        print(f"\n{'='*50}")
        print(f"チェック {loop_count} 回目 [経過時間: {elapsed_str(start_time)}]")
        print(f"{'='*50}")

        notify_list = await run_check(restaurants)

        if notify_list:
            if not SLACK_WEBHOOK_URL:
                print("⚠️ SLACK_WEBHOOK_URL が設定されていません")
                sys.exit(1)
            for r in notify_list:
                await send_slack(r["name"], r["url"])
        else:
            print(f"→ 予約可能なレストランはありません [経過時間: {elapsed_str(start_time)}]")

    print(f"\n✅ 全チェック完了 [合計{loop_count}回 / 経過時間: {elapsed_str(start_time)}]")


if __name__ == "__main__":
    asyncio.run(main())
