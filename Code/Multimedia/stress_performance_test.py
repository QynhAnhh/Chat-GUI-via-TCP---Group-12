"""
Stress Test & Performance Test
Nhóm 12 - Lê Hữu Tiến
─────────
"""

import socket
import threading
import time
import struct
import json
import random
import numpy as np
import cv2
import os
from dataclasses import dataclass
from typing import List


@dataclass
class TestResult:
    test_name: str
    total_clients: int
    success_count: int
    fail_count: int
    duration_sec: float
    images_sent: int = 0
    messages_sent: int = 0
    avg_latency_ms: float = 0.0
    crashes_detected: int = 0
    notes: str = ""

    @property
    def success_rate(self) -> float:
        if self.total_clients == 0:
            return 0.0
        return self.success_count / self.total_clients * 100


def _send_framed(sock: socket.socket, payload: bytes):
    """Gửi 1 gói đúng khuôn giao thức của server.py: [4-byte len][payload]."""
    header = struct.pack("!I", len(payload))
    sock.sendall(header + payload)


def _recv_framed(sock: socket.socket, timeout=3.0):
    """Nhận 1 gói trả lời từ server (dùng để confirm login OK)."""
    sock.settimeout(timeout)
    hdr = b""
    while len(hdr) < 4:
        chunk = sock.recv(4 - len(hdr))
        if not chunk:
            return None
        hdr += chunk
    size = struct.unpack("!I", hdr)[0]
    data = b""
    while len(data) < size:
        chunk = sock.recv(min(4096, size - len(data)))
        if not chunk:
            return None
        data += chunk
    return data


def _make_fake_jpeg(text: str = "Test") -> bytes:
    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    frame[:] = (30, 60, 90)
    cv2.putText(frame, text, (10, 120), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return buf.tobytes()


# ─────────────────────────────────────────────────────────────
#  STRESS TEST CHÍNH — Đúng flow login -> chat -> ảnh
# ─────────────────────────────────────────────────────────────

def stress_test_real_server(
    server_host: str = "127.0.0.1",
    server_port: int = 9999,
    num_clients: int = 50,
    actions_per_client: int = 10,
    timeout_sec: float = 5.0,
) -> TestResult:
    print(f"\n{'='*60}")
    print(f" STRESS TEST (SERVER THẬT): {num_clients} client x {actions_per_client} hành động")
    print(f"{'='*60}")

    img_bytes = _make_fake_jpeg("STRESS")
    results = {"success": 0, "fail": 0, "images": 0, "messages": 0, "crash": 0}
    lock = threading.Lock()
    latencies = []

    def client_worker(client_id: int):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout_sec)
            sock.connect((server_host, server_port))

            # 1. Login đúng flow thật
            login_payload = json.dumps({
                "type": "login", "nickname": f"stress_client_{client_id}"
            }).encode("utf-8")
            _send_framed(sock, login_payload)
            reply = _recv_framed(sock, timeout=timeout_sec)
            if reply is None:
                raise ConnectionError("Server không trả lời login")

            # 2. Trộn lẫn chat text + gửi ảnh, giống hành vi user thật
            for i in range(actions_per_client):
                t0 = time.perf_counter()
                if random.random() < 0.5:
                    msg = json.dumps({
                        "type": "chat_all",
                        "sender": f"stress_client_{client_id}",
                        "content": f"msg #{i} from {client_id}",
                    }).encode("utf-8")
                    _send_framed(sock, msg)
                    with lock:
                        results["messages"] += 1
                else:
                    _send_framed(sock, img_bytes)
                    with lock:
                        results["images"] += 1
                dt = (time.perf_counter() - t0) * 1000
                with lock:
                    latencies.append(dt)

            sock.close()
            with lock:
                results["success"] += 1

        except (ConnectionResetError, BrokenPipeError) as e:
            # Đây chính là dấu hiệu server bị crash giữa chừng (vd. do
            # RuntimeError dict-changed-size làm broadcast loop chết,
            # socket bị đóng đột ngột)
            with lock:
                results["fail"] += 1
                results["crash"] += 1
        except Exception:
            with lock:
                results["fail"] += 1

    t_start = time.perf_counter()
    threads = [threading.Thread(target=client_worker, args=(i,), daemon=True)
               for i in range(num_clients)]
    for t in threads:
        t.start()
        time.sleep(0.01)  # stagger nhẹ để giống traffic thực, không đốt CPU local đo sai
    for t in threads:
        t.join(timeout=timeout_sec + 10)

    duration = time.perf_counter() - t_start
    avg_latency = sum(latencies) / len(latencies) if latencies else 0

    result = TestResult(
        test_name=f"Stress Test thật ({num_clients} client)",
        total_clients=num_clients,
        success_count=results["success"],
        fail_count=results["fail"],
        duration_sec=round(duration, 2),
        images_sent=results["images"],
        messages_sent=results["messages"],
        avg_latency_ms=round(avg_latency, 2),
        crashes_detected=results["crash"],
    )

    print(f"\n  Kết quả:")
    print(f"  +- Thanh cong   : {result.success_count}/{result.total_clients} ({result.success_rate:.1f}%)")
    print(f"  +- That bai     : {result.fail_count} (trong do nghi crash server: {result.crashes_detected})")
    print(f"  +- Anh gui      : {result.images_sent:,}")
    print(f"  +- Tin nhan gui : {result.messages_sent:,}")
    print(f"  +- Thoi gian    : {result.duration_sec:.2f}s")
    print(f"  +- Latency TB   : {result.avg_latency_ms:.2f}ms")
    return result


# ─────────────────────────────────────────────────────────────
#  CHURN TEST — Cố tình khai thác race condition trên `clients` dict
#  (kết nối + rớt mạng dồn dập trong khi vẫn có client khác đang chat)
# ─────────────────────────────────────────────────────────────

def churn_test(
    server_host: str = "127.0.0.1",
    server_port: int = 9999,
    background_clients: int = 15,
    churners: int = 20,
    duration_sec: int = 8,
) -> TestResult:
    """
    background_clients: client ổn định, liên tục chat -> để có gì đó cho
                         server broadcast (tức là server phải lặp clients.items()).
    churners: client connect rồi disconnect ngay lập tức, lặp lại liên
              tục trong duration_sec giây -> để liên tục có del clients[addr]
              xảy ra giữa lúc background_clients đang khiến server iterate
              dict đó để broadcast.
    Mục tiêu: lộ ra "RuntimeError: dictionary changed size during iteration"
    phía server (Quân sẽ thấy log lỗi này nếu chạy server ở terminal riêng).
    """
    print(f"\n{'='*60}")
    print(f" CHURN TEST (khai thac race condition clients dict)")
    print(f" {background_clients} client chat lien tuc + {churners} client connect/disconnect lien tuc")
    print(f"{'='*60}")

    stop_event = threading.Event()
    counters = {"bg_msgs": 0, "bg_fail": 0, "churn_ok": 0, "churn_fail": 0}
    lock = threading.Lock()

    def background_worker(cid: int):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(3.0)
            sock.connect((server_host, server_port))
            login = json.dumps({"type": "login", "nickname": f"bg_{cid}"}).encode()
            _send_framed(sock, login)
            _recv_framed(sock, timeout=3.0)
            while not stop_event.is_set():
                msg = json.dumps({
                    "type": "chat_all", "sender": f"bg_{cid}", "content": "ping"
                }).encode()
                _send_framed(sock, msg)
                with lock:
                    counters["bg_msgs"] += 1
                time.sleep(0.05)
            sock.close()
        except Exception:
            with lock:
                counters["bg_fail"] += 1

    def churn_worker():
        while not stop_event.is_set():
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2.0)
                sock.connect((server_host, server_port))
                login = json.dumps({"type": "login", "nickname": "churn"}).encode()
                _send_framed(sock, login)
                _recv_framed(sock, timeout=2.0)
                sock.close()  # disconnect ngay -> trigger del clients[addr] phía server
                with lock:
                    counters["churn_ok"] += 1
            except Exception:
                with lock:
                    counters["churn_fail"] += 1
            # FIX: giảm tốc độ churn (0.02s -> 0.25s). Tốc độ cũ tạo ra
            # ~970 connect/giây, làm bão hòa s.listen(5) của server LIÊN
            # TỤC suốt cả test -> khiến cả background_worker (vốn không
            # liên quan gì tới race condition) bị timeout ngay từ bước
            # connect(), làm nhiễu kết quả, không phân biệt được đâu là
            # do bug #2 (race condition dict) và đâu là do bug #4
            # (backlog quá nhỏ). Giảm tốc để background có thể connect
            # và chạy ổn định, chỉ còn biến churn làm yếu tố kích hoạt
            # race condition trên dict clients.
            time.sleep(0.25)

    t_start = time.perf_counter()
    threads = []
    threads += [threading.Thread(target=background_worker, args=(i,), daemon=True)
                for i in range(background_clients)]
    threads += [threading.Thread(target=churn_worker, daemon=True)
                for _ in range(churners)]
    for t in threads:
        t.start()
        time.sleep(0.03)  # FIX: stagger nhẹ để không bị nghẽn do
                           # listen(5) backlog quá nhỏ của server -
                           # tránh nhiễu kết quả với bug đang muốn test

    time.sleep(duration_sec)
    stop_event.set()
    for t in threads:
        t.join(timeout=3)
    duration = time.perf_counter() - t_start

    total = background_clients + churners
    fail = counters["bg_fail"] + counters["churn_fail"]

    result = TestResult(
        test_name=f"Churn Test ({background_clients} bg + {churners} churn)",
        total_clients=total,
        success_count=total - fail,
        fail_count=fail,
        duration_sec=round(duration, 2),
        messages_sent=counters["bg_msgs"],
        notes=(f"churn_ok={counters['churn_ok']}, churn_fail={counters['churn_fail']}. "
               f"NEU server.py crash/dung log trong luc nay (kiem tra terminal chay "
               f"server) -> da xac nhan bug race condition tren dict clients."),
    )

    print(f"\n  Ket qua:")
    print(f"  +- Background chat gui   : {counters['bg_msgs']:,} (fail: {counters['bg_fail']})")
    print(f"  +- Churn connect/disconnect: {counters['churn_ok']} ok / {counters['churn_fail']} fail")
    print(f"  +- LUU Y: kiem tra terminal dang chay server.py xem co log")
    print(f"            'RuntimeError: dictionary changed size during iteration' khong.")
    print(f"            Neu co -> bug #2 trong phan tich da duoc xac nhan thuc te.")
    return result


if __name__ == "__main__":
    HOST = os.environ.get("CHAT_SERVER_HOST", "127.0.0.1")
    PORT = int(os.environ.get("CHAT_SERVER_PORT", "9999"))

    print(f"\n>>> Dam bao server.py thuc cua Quan dang chay tai {HOST}:{PORT} truoc khi test <<<\n")

    all_results: List[TestResult] = []

    r1 = stress_test_real_server(HOST, PORT, num_clients=50, actions_per_client=10)
    all_results.append(r1)
    time.sleep(1)

    r2 = churn_test(HOST, PORT, background_clients=15, churners=20, duration_sec=15)
    all_results.append(r2)

    print(f"\n{'='*60}")
    print(" TONG KET")
    for r in all_results:
        print(f"  - {r.test_name}: {r.success_count}/{r.total_clients} OK, fail={r.fail_count}")
    print(f"{'='*60}")
