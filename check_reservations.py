import json
import os
import sys
import asyncio
from curl_cffi.requests import AsyncSession

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
RESTAURANT_URLS = os.environ.get("RESTAURANT_URLS", "[]")

AVAILABLE_BUTTON = 'ui button primary big fluid'
AVAILABLE_TEXT = "このお店を予約する"


def load_restaurants():
    return json.loads(RESTAURANT_URLS)


def make_reservation_url(url):
    url = url.replace("/ja/r/", "/r/")
    return url.rstrip("/") + "/reservations/new"


async def check_restaurant(session, restaurant):
    url = restaurant["url"]
    name = restaurant.get("name", url)
    print(f"チェック中: {name} ({url})")

    try:
        response = await session.get(url, timeout=30, headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "ja-JP,ja;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.google.com/",
            "Upgrade-Insecure-Requests": "1",
        })
        content = response.text

        print(f"  → HTML取得: {len(content)}文字 / ステータス: {response.status_code}")
        if len(content) < 5000:
            print(f"  → HTML全文:\n{content}\n")

        # 各テキストが実際にどこにあるか前後100文字を表示
        for label, text in [("予約可能テキスト", AVAILABLE_TEXT), ("予約ボタンクラス", AVAILABLE_BUTTON)]:
            idx = content.find(text)
            if idx != -1:
                start = max(0, idx - 100)
                end = min(len(content), idx + len(text) + 100)
                print(f"  → [{label}] の前後:\n{content[start:end]}\n")
            else:
                print(f"  → [{label}]: 見つかりませんでした")

        # aタグ(ui button primary big fluid) AND テキスト(このお店を予約する) の両方があれば予約可能
        has_button = AVAILABLE_BUTTON in content
        has_text = AVAILABLE_TEXT in content
        available = has_button and has_text

        if available:
            print(f"  → 判定: ✅ 予約可能 ({name})")
        else:
            print(f"  → 判定: ❌ 満席 ({name})")

        return {"name": name, "url": url, "available": available}

    except Exception as e:
        print(f"  → ⚠️ エラー: {e}")
        return {"name": name, "url": url, "available": False}


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
    if not restaurants:
        print("⚠️ RESTAURANT_URLS が設定されていません")
        sys.exit(1)

    notify_list = []

    async with AsyncSession(impersonate="chrome120") as session:
        for restaurant in restaurants:
            result = await check_restaurant(session, restaurant)
            if result["available"]:
                notify_list.append(result)

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
