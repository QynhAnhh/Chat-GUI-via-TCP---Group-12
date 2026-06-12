import json
import struct
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Message:
    msg_id: str
    sender: str
    content: str
    timestamp: str
    reply_to_id: Optional[str] = None
    reply_to_sender: Optional[str] = None
    reply_to_content: Optional[str] = None
    forwarded_from: Optional[str] = None


def build_reply(msg_id: str, sender: str, content: str,
                timestamp: str, original: Message) -> Message:
    return Message(
        msg_id=msg_id,
        sender=sender,
        content=content,
        timestamp=timestamp,
        reply_to_id=original.msg_id,
        reply_to_sender=original.sender,
        reply_to_content=original.content,
    )


def build_forward(msg_id: str, sender: str,
                  timestamp: str, original: Message) -> Message:
    return Message(
        msg_id=msg_id,
        sender=sender,
        content=original.content,
        timestamp=timestamp,
        forwarded_from=original.sender,
    )


def pack_message(msg: Message) -> bytes:
    payload = json.dumps(asdict(msg), ensure_ascii=False).encode("utf-8")
    return struct.pack("!I", len(payload)) + payload


def unpack_message(data: bytes) -> Message:
    d = json.loads(data.decode("utf-8"))
    return Message(**d)


if __name__ == "__main__":
    from realtime_timestamp import get_full_timestamp

    original = Message("001", "Quân", "Server chạy ổn rồi!", get_full_timestamp())

    replied = build_reply("002", "Tiến", "Ok anh, em test ngay", get_full_timestamp(), original)
    print(f"[REPLY] {replied.sender} trả lời {replied.reply_to_sender}: '{replied.reply_to_content}'")
    print(f"        → '{replied.content}'")

    forwarded = build_forward("003", "Quỳnh Anh", get_full_timestamp(), original)
    print(f"\n[FWD]   {forwarded.sender} chuyển tiếp từ {forwarded.forwarded_from}:")
    print(f"        → '{forwarded.content}'")

    packed = pack_message(replied)
    recovered = unpack_message(packed[4:])
    print(f"\n[PACK]  Pack/unpack OK: {recovered.sender} → '{recovered.content}'")
