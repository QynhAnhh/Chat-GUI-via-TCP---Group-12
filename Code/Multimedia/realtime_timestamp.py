import time
from datetime import datetime


def get_timestamp() -> str:
    return datetime.now().strftime("%H:%M:%S")


def get_full_timestamp() -> str:
    return datetime.now().strftime("%d/%m/%Y %H:%M:%S")


def format_display_time(timestamp: str) -> str:
    try:
        dt = datetime.strptime(timestamp, "%d/%m/%Y %H:%M:%S")
        now = datetime.now()
        delta = now - dt

        if delta.seconds < 60:
            return "Vừa xong"
        elif delta.seconds < 3600:
            return f"{delta.seconds // 60} phút trước"
        elif delta.days == 0:
            return dt.strftime("%H:%M")
        elif delta.days == 1:
            return f"Hôm qua {dt.strftime('%H:%M')}"
        else:
            return dt.strftime("%d/%m %H:%M")
    except Exception:
        return timestamp


if __name__ == "__main__":
    ts = get_full_timestamp()
    print(f"Timestamp gửi   : {ts}")
    print(f"Timestamp ngắn  : {get_timestamp()}")

    import time
    time.sleep(2)
    print(f"Hiển thị sau 2s : {format_display_time(ts)}")
