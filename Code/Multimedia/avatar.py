import struct
import socket
import os
import cv2
import numpy as np
from typing import Optional

AVATAR_DIR = "avatars"
AVATAR_SIZE = (64, 64)
JPEG_QUALITY = 85


def _ensure_dir():
    os.makedirs(AVATAR_DIR, exist_ok=True)


def load_avatar(nickname: str) -> Optional[np.ndarray]:
    path = os.path.join(AVATAR_DIR, f"{nickname}.jpg")
    if not os.path.exists(path):
        return None
    return cv2.imread(path)


def save_avatar(nickname: str, frame: np.ndarray) -> str:
    _ensure_dir()
    resized = cv2.resize(frame, AVATAR_SIZE)
    path = os.path.join(AVATAR_DIR, f"{nickname}.jpg")
    cv2.imwrite(path, resized, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    return path


def make_default_avatar(nickname: str) -> np.ndarray:
    img = np.zeros((64, 64, 3), dtype=np.uint8)
    colors = [(52, 152, 219), (46, 204, 113), (231, 76, 60), (155, 89, 182)]
    color = colors[sum(ord(c) for c in nickname) % len(colors)]
    img[:] = color
    letter = nickname[0].upper() if nickname else "?"
    cv2.putText(img, letter, (18, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (255, 255, 255), 2)
    return img


def encode_avatar(frame: np.ndarray) -> bytes:
    resized = cv2.resize(frame, AVATAR_SIZE)
    _, buf = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    return buf.tobytes()


def decode_avatar(img_bytes: bytes) -> Optional[np.ndarray]:
    arr = np.frombuffer(img_bytes, dtype=np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


def send_avatar(sock: socket.socket, nickname: str, img_bytes: bytes) -> bool:
    try:
        nick_enc = nickname.encode("utf-8")
        header = struct.pack("!I", len(nick_enc)) + nick_enc
        payload = header + struct.pack("!I", len(img_bytes)) + img_bytes
        sock.sendall(payload)
        return True
    except OSError:
        return False


def recv_avatar(sock: socket.socket) -> Optional[tuple]:
    try:
        def _read(n):
            buf = b""
            while len(buf) < n:
                chunk = sock.recv(n - len(buf))
                if not chunk:
                    return None
                buf += chunk
            return buf

        nick_len_raw = _read(4)
        if not nick_len_raw:
            return None
        (nick_len,) = struct.unpack("!I", nick_len_raw)
        nickname = _read(nick_len).decode("utf-8")

        img_len_raw = _read(4)
        (img_len,) = struct.unpack("!I", img_len_raw)
        img_bytes = _read(img_len)

        frame = decode_avatar(img_bytes)
        if frame is not None:
            save_avatar(nickname, frame)
        return nickname, frame
    except Exception:
        return None


if __name__ == "__main__":
    nick = "Tiến"
    avatar = make_default_avatar(nick)
    path = save_avatar(nick, avatar)
    print(f"[AVATAR] Tạo avatar mặc định cho '{nick}' → {path}")

    loaded = load_avatar(nick)
    print(f"[AVATAR] Load lại: shape={loaded.shape} ✓")

    img_bytes = encode_avatar(avatar)
    recovered = decode_avatar(img_bytes)
    print(f"[AVATAR] Encode/decode: {len(img_bytes)} byte → shape={recovered.shape} ✓")
