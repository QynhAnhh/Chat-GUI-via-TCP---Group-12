import json
import struct
from typing import Optional


EMOJI_MAP = {
    ":like:":       "👍",  ":love:":    "❤️",
    ":haha:":       "😂",  ":wow:":     "😮",
    ":sad:":        "😢",  ":angry:":   "😡",
    ":clap:":       "👏",  ":fire:":    "🔥",
    ":check:":      "✅",  ":x:":       "❌",
    ":smile:":      "😊",  ":cry:":     "😭",
    ":think:":      "🤔",  ":wink:":    "😉",
    ":party:":      "🎉",  ":star:":    "⭐",
    ":camera:":     "📷",  ":phone:":   "📱",
    ":hello:":      "👋",  ":100:":     "💯",
}


def resolve_emoji(text: str) -> str:
    for shortcode, emoji in EMOJI_MAP.items():
        text = text.replace(shortcode, emoji)
    return text


def list_emoji() -> list:
    return [{"shortcode": k, "emoji": v} for k, v in EMOJI_MAP.items()]


def build_emoji_packet(sender: str, emoji: str, timestamp: str) -> bytes:
    payload = json.dumps({
        "type":      "emoji",
        "sender":    sender,
        "emoji":     emoji,
        "timestamp": timestamp,
    }, ensure_ascii=False).encode("utf-8")
    return struct.pack("!I", len(payload)) + payload


def parse_emoji_packet(data: bytes) -> Optional[dict]:
    try:
        return json.loads(data.decode("utf-8"))
    except Exception:
        return None


if __name__ == "__main__":
    from realtime_timestamp import get_timestamp

    print("[EMOJI] Danh sách shortcode:")
    for item in list_emoji():
        print(f"  {item['shortcode']:12} → {item['emoji']}")

    text = "Xong rồi :check: cảm ơn :like: :fire:"
    print(f"\n[EMOJI] Trước : {text}")
    print(f"[EMOJI] Sau   : {resolve_emoji(text)}")

    pkt = build_emoji_packet("Tiến", "👍", get_timestamp())
    parsed = parse_emoji_packet(pkt[4:])
    print(f"\n[EMOJI] Packet: {parsed}")
