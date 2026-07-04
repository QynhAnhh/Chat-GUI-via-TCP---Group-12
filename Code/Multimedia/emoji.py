import cv2
import base64
import json
import struct
from PySide6.QtWidgets import QDialog, QGridLayout, QPushButton
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtCore import Qt, QSize

class StickerHandler:
    def __init__(self, main_window):
        self.main = main_window

    def show_sticker_dialog(self):
        dlg = QDialog(self.main)
        dlg.setWindowTitle("Nhãn dán")
        dlg.setFixedSize(400, 300)
        dlg.setStyleSheet("QDialog { background-color: #1E2227; }")
        
        layout = QGridLayout(dlg)
        row = col = 0
        
        for sticker_path in getattr(self.main, "available_stickers", []):
            btn = QPushButton()
            btn.setFixedSize(70, 70)
            btn.setCursor(Qt.PointingHandCursor)
            
            pixmap = QPixmap(sticker_path)
            if not pixmap.isNull():
                btn.setIcon(QIcon(pixmap))
                btn.setIconSize(QSize(60, 60))
            
            btn.setStyleSheet("""
                QPushButton { background-color: transparent; border: none; padding: 0px; }
                QPushButton:hover { background-color: rgba(255,255,255,0.1); border-radius: 10px; }
            """)
            
            btn.clicked.connect(lambda checked=False, p=sticker_path: self.on_sticker_selected(p, dlg))
            layout.addWidget(btn, row, col)
            
            col += 1
            if col > 4:
                col = 0
                row += 1
                
        dlg.exec()

    def on_sticker_selected(self, sticker_path, dlg):
        self.send_sticker(sticker_path)
        dlg.accept()

    def send_sticker(self, sticker_path):
        try:
            frame = cv2.imread(sticker_path, cv2.IMREAD_UNCHANGED)
            if frame is None: return
            
            success, buffer = cv2.imencode(".png", frame)
            if not success: return
            
            b64_str = base64.b64encode(buffer.tobytes()).decode('utf-8')
            content = f"[STICKER_BASE64]{b64_str}"
            
            msg_dict = {"sender": self.main.nickname, "content": content}
            if self.main.current_chat_type == "chat_all":
                msg_dict["type"] = "chat_all"
            elif self.main.current_chat_type == "chat_private":
                msg_dict["type"] = "chat_private"
                msg_dict["receiver"] = self.main.current_chat_target
            elif self.main.current_chat_type == "chat_group":
                msg_dict["type"] = "chat_group"
                msg_dict["group_id"] = self.main.current_chat_target

            if getattr(self.main, 'reply_to_data', None):
                msg_dict["reply_to"] = self.main.reply_to_data

            payload = json.dumps(msg_dict).encode('utf-8')
            header = struct.pack("!I", len(payload))
            
            self.main.sock.sendall(header + payload)
            
            self.main.image_handler.display_image(frame, is_sender=True, sender="Tôi", is_sticker=True)
            if hasattr(self.main, "reply_handler"):
                self.main.reply_handler._cancel_reply()
        except Exception as e:
            print("Lỗi gửi sticker:", e)
