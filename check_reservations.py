import json
import os
import sys
import asyncio
import re
from curl_cffi.requests import AsyncSession

SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL", "")
RESTAURANT_URLS = os.environ.get("RESTAURANT_URLS", "[]")

AVAILABLE_TEXT = "このお店を予約する"
UNAVAILABLE_TEXT = "ログインして空き枠を確認"


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
        response = await session.get(url, timeout=30)
        content = response.text

        has_available_text = AVAILABLE_TEXT in content
        has_unavailable_text = UNAVAILABLE_TEXT in content
        available = has_available_text and not has_unavailable_text

        print(f"  → 「{AVAILABLE_TEXT}」: {'あり ✅' if has_available_text else 'なし ❌'}")
        print(f"  → 「{UNAVAILABLE_TEXT}」: {'あり ✅' if has_unavailable_text else 'なし ❌'}")

        # 各テキストが実際にどこにあるか前後100文字を表示
        for label, text in [("予約可能テキスト", AVAILABLE_TEXT), ("満席テキスト", UNAVAILABLE_TEXT)]:
            idx = content.find(text)
            if idx != -1:
                start = max(0, idx - 100)
                end = min(len(content), idx + len(text) + 100)
                print(f"  → [{label}] の前後:\n{content[start:end]}\n")

        if available:
            print(f"  → 判定: ✅ 予約可能 ({name})")
        elif has_unavailable_text:
            print(f"  → 判定: ❌ 満席 ({name})")
        else:
            print(f"  → 判定: ⚠️ 判定不明 ({name})")

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

    # curl_cffiでChrome指紋を偽装してCloudflareを回避
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
