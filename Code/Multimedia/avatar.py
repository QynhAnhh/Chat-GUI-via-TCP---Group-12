import os
import json
import struct
import random
from PySide6.QtGui import QPixmap, QPainter, QPainterPath, QColor, QIcon
from PySide6.QtCore import Qt, QSize
from PySide6.QtWidgets import QDialog, QGridLayout, QPushButton

class AvatarHandler:
    def __init__(self, main_window):
        self.main = main_window

    def create_circular_icon(self, image_path, size=60):
        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            return QIcon()
            
        pixmap = pixmap.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        target = QPixmap(size, size)
        target.fill(Qt.transparent)
        
        painter = QPainter(target)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        
        path = QPainterPath()
        path.addEllipse(0, 0, size, size)
        painter.setClipPath(path)
        
        x_offset = (size - pixmap.width()) // 2
        y_offset = (size - pixmap.height()) // 2
        painter.drawPixmap(x_offset, y_offset, pixmap)
        
        painter.setClipping(False)
        painter.setPen(QColor("#3498db"))
        painter.drawEllipse(1, 1, size - 2, size - 2)
        
        painter.end()
        return QIcon(target)

    def set_user_avatar(self, avatar_path):
        icon = self.create_circular_icon(avatar_path, size=46)
        self.main.ui.btn_avatar.setIcon(icon)
        self.main.ui.btn_avatar.setIconSize(QSize(46, 46))
        self.main.ui.btn_avatar.setStyleSheet("""
            #btn_avatar {
                background-color: transparent;
                border: none;
                padding: 0px;
            }
            #btn_avatar:hover {
                background-color: rgba(255,255,255,0.1);
                border-radius: 25px;
            }
        """)

    def show_avatar_selection_dialog(self):
        dlg = QDialog(self.main)
        dlg.setWindowTitle("Chọn ảnh đại diện")
        dlg.setFixedSize(400, 300)
        dlg.setStyleSheet("QDialog { background-color: #1E2227; }")
        
        layout = QGridLayout(dlg)
        row = col = 0
        
        for avatar_path in self.main.available_avatars:
            btn = QPushButton()
            btn.setFixedSize(60, 60)
            btn.setCursor(Qt.PointingHandCursor)
            
            icon = self.create_circular_icon(avatar_path, size=58)
            btn.setIcon(icon)
            btn.setIconSize(QSize(58, 58))
            
            btn.setStyleSheet("""
                QPushButton { background-color: transparent; border: none; padding: 0px; }
                QPushButton:hover { background-color: rgba(255,255,255,0.1); border-radius: 30px; }
            """)
            
            btn.clicked.connect(lambda checked=False, p=avatar_path: self.on_avatar_selected(p, dlg))
            layout.addWidget(btn, row, col)
            
            col += 1
            if col > 4:
                col = 0
                row += 1
                
        dlg.exec()

    def on_avatar_selected(self, avatar_path, dlg):
        self.set_user_avatar(avatar_path)
        dlg.accept()
        # Gửi avatar mới lên server để broadcast
        self.broadcast_my_avatar(avatar_path)

    def broadcast_my_avatar(self, avatar_path):
        """Gửi tên file avatar lên server để broadcast (không cần encode nhị phân)."""
        try:
            avatar_name = os.path.basename(avatar_path)
            msg = json.dumps({"type": "update_avatar", "sender": self.main.nickname, "avatar_name": avatar_name}).encode('utf-8')
            self.main.sock.sendall(struct.pack("!I", len(msg)) + msg)
            print(f"[Avatar] Broadcast avatar_name: {avatar_name}")
        except Exception as e:
            print("[Avatar] Lỗi gửi avatar:", e)

    def request_all_avatars(self):
        """Yêu cầu server gửi tên avatar của tất cả user đang online."""
        try:
            msg = json.dumps({"type": "get_avatars", "sender": self.main.nickname}).encode('utf-8')
            self.main.sock.sendall(struct.pack("!I", len(msg)) + msg)
        except Exception as e:
            print("[Avatar] Lỗi request avatars:", e)

    def get_sender_avatar_pixmap(self, sender):
        if sender == "Tôi" or sender == "Hệ thống":
            return None
        if not hasattr(self.main, "sender_avatar_pixmaps"):
            self.main.sender_avatar_pixmaps = {}
        if sender not in self.main.sender_avatar_pixmaps:
            if hasattr(self.main, "available_avatars") and self.main.available_avatars:
                path = random.choice(self.main.available_avatars)
                icon = self.create_circular_icon(path, size=36)
                self.main.sender_avatar_pixmaps[sender] = icon.pixmap(36, 36)
            else:
                self.main.sender_avatar_pixmaps[sender] = None
        return self.main.sender_avatar_pixmaps[sender]

    def handle_avatar_updated(self, sender, avatar_name):
        """Nhận tên file avatar từ mạng và tải file cục bộ tương ứng."""
        if not avatar_name:
            return
        try:
            # We assume avatar_dir is Code/frontend/images because main.py was there.
            # So from Multimedia/avatar.py, the images dir is ../frontend/images
            # Actually, `__file__` inside avatar.py points to Code/Multimedia/avatar.py
            # But the original code relied on `__file__` of main.py, which was Code/frontend/main.py.
            # So we should resolve to Code/frontend/images.
            frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
            avatar_dir = os.path.join(frontend_dir, "images")
            full_path = os.path.join(avatar_dir, avatar_name)
            
            if not os.path.exists(full_path):
                print(f"[Avatar] File không tồn tại: {full_path}")
                return
            icon = self.create_circular_icon(full_path, size=36)
            new_pm = icon.pixmap(36, 36)
            if not hasattr(self.main, "sender_avatar_pixmaps"):
                self.main.sender_avatar_pixmaps = {}
            self.main.sender_avatar_pixmaps[sender] = new_pm
            print(f"[Avatar] Cập nhật avatar {sender} → {avatar_name}")

            # Cập nhật tất cả item đang hiển thị trong chat_list
            for i in range(self.main.chat_list.count()):
                item = self.main.chat_list.item(i)
                data = item.data(Qt.UserRole)
                if data and data.get("sender") == sender and "avatar_pixmap" in data:
                    data["avatar_pixmap"] = new_pm
                    item.setData(Qt.UserRole, data)

            self.main.chat_list.viewport().update()

            # Cập nhật avatar lớn ở cột bên phải nếu đang xem thông tin người này
            if getattr(self.main, "current_chat_type", "") == "chat_private" and getattr(self.main, "current_chat_target", "") == sender:
                if hasattr(self.main.ui, "lbl_info_avatar"):
                    big_icon = self.create_circular_icon(full_path, size=100)
                    self.main.ui.lbl_info_avatar.setPixmap(big_icon.pixmap(100, 100))
        except Exception as e:
            print("[Avatar] Lỗi cập nhật avatar:", e)

    def handle_all_avatars(self, avatars_dict):
        """Nhận toàn bộ tên avatar từ server khi mới đăng nhập."""
        for sender, avatar_name in avatars_dict.items():
            if sender != self.main.nickname:
                self.handle_avatar_updated(sender, avatar_name)
