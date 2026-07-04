import cv2
import base64
import json
import struct
import numpy as np
from datetime import datetime
from PySide6.QtWidgets import QFileDialog, QListWidgetItem
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtCore import Qt, QTimer, QThread, Signal

class CameraThread(QThread):
    image_encoded = Signal(bytes) # Tín hiệu mang mảng byte của ảnh
    error_occurred = Signal(str)

    def run(self):
        try:
            # 1. Mở camera mặc định (index = 0)
            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                self.error_occurred.emit("Không thể kết nối với Webcam!")
                return
            
            # 2. Chụp 1 khung hình rồi tắt camera ngay
            ret, frame = cap.read()
            cap.release()

            if not ret or frame is None:
                self.error_occurred.emit("Chụp ảnh thất bại!")
                return

            # 3. Nén ảnh thành chuẩn JPEG để giảm dung lượng mạng
            success, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if success:
                # Chuyển thành dạng byte và phát tín hiệu ra ngoài
                self.image_encoded.emit(buffer.tobytes())
            else:
                self.error_occurred.emit("Lỗi mã hóa ảnh!")
        except Exception as e:
            self.error_occurred.emit(f"Lỗi Camera: {str(e)}")

class ImageHandler:
    def __init__(self, main_window):
        self.main = main_window

    def capture_and_send_image(self):
        # Vô hiệu hóa nút tạm thời để tránh click liên tục
        self.main.ui.btn_camera.setEnabled(False)
        self.main.display_message("Hệ thống", "Đang mở camera chụp ảnh...")
        
        # Khởi chạy luồng camera
        self.camera_thread = CameraThread()
        self.camera_thread.image_encoded.connect(self.send_image_bytes)
        self.camera_thread.error_occurred.connect(lambda err: self.main.display_message("Lỗi", err))
        self.camera_thread.finished.connect(lambda: self.main.ui.btn_camera.setEnabled(True))
        self.camera_thread.start()

    def send_image_bytes(self, img_bytes):
        try:
            # Mã hóa ảnh sang Base64
            b64_str = base64.b64encode(img_bytes).decode('utf-8')
            content = f"[IMAGE_BASE64]{b64_str}"

            # Đóng gói JSON tùy theo phòng chat
            if self.main.current_chat_type == "chat_all":
                msg_dict = {"type": "chat_all", "sender": self.main.nickname, "content": content}
            elif self.main.current_chat_type == "chat_private":
                msg_dict = {"type": "chat_private", "sender": self.main.nickname, "receiver": self.main.current_chat_target, "content": content}
            elif self.main.current_chat_type == "chat_group":
                msg_dict = {"type": "chat_group", "group_id": self.main.current_chat_target, "sender": self.main.nickname, "content": content}

            if getattr(self.main, 'reply_to_data', None):
                msg_dict["reply_to"] = self.main.reply_to_data

            payload = json.dumps(msg_dict).encode('utf-8')
            header = struct.pack("!I", len(payload))
            
            self.main.sock.sendall(header + payload)
            print(f"[LOG] Đã gửi ảnh thành công dưới dạng Base64 (Dung lượng payload: {len(payload)} bytes)")
            
            # Hiển thị ảnh cho chính mình
            buffer = np.frombuffer(img_bytes, dtype=np.uint8)
            frame = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
            self.display_image(frame, is_sender=True, sender="Tôi") 
            
        except Exception as e:
            print("Lỗi gửi ảnh:", e)
            self.main.display_message("Lỗi", "Không thể gửi ảnh!")

    def select_and_send_image(self):
        file_path, _ = QFileDialog.getOpenFileName(self.main, "Chọn ảnh", "", "Image Files (*.png *.jpg *.jpeg *.bmp)")
        if not file_path:
            return

        try:
            # Đọc ảnh (hỗ trợ đường dẫn có dấu tiếng Việt)
            with open(file_path, "rb") as f:
                bytes_array = bytearray(f.read())
                
            # Decode bằng OpenCV
            numpyarray = np.asarray(bytes_array, dtype=np.uint8)
            frame = cv2.imdecode(numpyarray, cv2.IMREAD_COLOR)

            if frame is None:
                self.main.display_message("Lỗi", "Định dạng ảnh không hợp lệ hoặc file bị hỏng.")
                return

            # Nén và resize ảnh nếu quá lớn để đảm bảo truyền mạng tốt
            max_dim = 1280
            h, w = frame.shape[:2]
            if w > max_dim or h > max_dim:
                scale = max_dim / max(w, h)
                frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

            # Ép về JPEG
            success, buffer = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if not success:
                self.main.display_message("Lỗi", "Không thể xử lý ảnh.")
                return

            img_bytes = buffer.tobytes()
            
            # Gửi thông qua hàm có sẵn
            self.send_image_bytes(img_bytes)
        except Exception as e:
            print("Lỗi chọn ảnh:", e)
            self.main.display_message("Lỗi", "Có lỗi xảy ra khi đọc ảnh!")

    def display_image(self, frame, is_sender=False, sender=None, is_sticker=False):
        if is_sender:
            sender = "Tôi"

        current_time = datetime.now()
        display_time = current_time.strftime("%H:%M")

        # Tính toán Gom cụm
        show_time_tag = False
        if getattr(self.main, "last_msg_time", None) is None or (current_time - self.main.last_msg_time).total_seconds() > 1200:
            show_time_tag = True
            self.main.last_sender = None

        show_name = (sender != "Tôi" and sender != getattr(self.main, "last_sender", None))

        if sender == getattr(self.main, "last_sender", None) and not show_time_tag:
            last_item = getattr(self.main, "last_item", None)
            if last_item is not None:
                prev_data = last_item.data(Qt.UserRole)
                prev_data["show_time"] = False
                last_item.setData(Qt.UserRole, prev_data)

        # Xử lý ảnh
        if len(frame.shape) == 3 and frame.shape[2] == 4:
            rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGRA2RGBA)
            h, w, ch = rgb_image.shape
            qt_image = QImage(rgb_image.data, w, h, ch * w, QImage.Format_RGBA8888)
        else:
            rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_image.shape
            qt_image = QImage(rgb_image.data, w, h, ch * w, QImage.Format_RGB888)
            
        pixmap = QPixmap.fromImage(qt_image)
        
        original_pixmap = pixmap
        if is_sticker:
            if pixmap.width() > 120:
                pixmap = pixmap.scaledToWidth(120, Qt.SmoothTransformation)
        else:
            if pixmap.width() > 250:
                pixmap = pixmap.scaledToWidth(250, Qt.SmoothTransformation)

        # Đóng gói dữ liệu ảnh
        data = {
            "type": "image",
            "is_sticker": is_sticker,
            "sender": sender,
            "pixmap": pixmap,
            "original_pixmap": original_pixmap,
            "img_w": pixmap.width(),
            "img_h": pixmap.height(),
            "time": display_time,
            "show_time": True,
            "show_time_tag": show_time_tag,
            "tag_text": current_time.strftime("%H:%M %d/%m/%Y"),
            "show_name": show_name,
            "chat_type": getattr(self.main, 'current_chat_type', 'chat_all'),
            "avatar_pixmap": self.main.avatar_handler.get_sender_avatar_pixmap(sender)
        }

        item = QListWidgetItem(self.main.chat_list)
        item.setData(Qt.UserRole, data)
        self.main.chat_list.addItem(item)
        
        # Cập nhật trí nhớ và cuộn
        self.main.last_sender = sender
        self.main.last_msg_time = current_time
        self.main.last_item = item
        QTimer.singleShot(50, self.main.chat_list.scrollToBottom)
