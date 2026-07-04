from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QMenu, QAbstractItemView, QListWidget, QDialog, QVBoxLayout, QMessageBox
from PySide6.QtCore import Qt
import json
import struct
import time

class ReplyHandler:
    def __init__(self, main_window):
        self.main = main_window
        self._setup_reply_bar()
        self.original_mouse_press = self.main.chat_list.mousePressEvent
        self.main.chat_list.mousePressEvent = self._chat_list_mouse_press

    def _setup_reply_bar(self):
        """Tạo thanh preview reply phía trên ô nhập tin nhắn (ẩn mặc định)."""
        self.reply_bar = QFrame()
        self.reply_bar.setFixedHeight(44)
        self.reply_bar.setStyleSheet("""
            QFrame {
                background-color: #1E242C;
                border-top: 2px solid #3498db;
            }
        """)

        bar_layout = QHBoxLayout(self.reply_bar)
        bar_layout.setContentsMargins(10, 4, 6, 4)
        bar_layout.setSpacing(6)

        icon_lbl = QLabel("↩")
        icon_lbl.setStyleSheet("color: #3498db; font-size: 16px; background: transparent;")
        icon_lbl.setFixedWidth(20)

        self.reply_preview_lbl = QLabel("Đang trả lời...")
        self.reply_preview_lbl.setStyleSheet(
            "color: #B0B8C1; font-size: 12px; background: transparent;"
        )

        cancel_btn = QPushButton("✕")
        cancel_btn.setFixedSize(24, 24)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background: transparent; color: #8A8D91;
                font-size: 14px; border: none; border-radius: 12px;
            }
            QPushButton:hover { color: #fff; background: rgba(255,255,255,0.1); }
        """)
        cancel_btn.clicked.connect(self._cancel_reply)

        bar_layout.addWidget(icon_lbl)
        bar_layout.addWidget(self.reply_preview_lbl, 1)
        bar_layout.addWidget(cancel_btn)

        # Chèn vào layout của col3, phía trên widget cuối (input area)
        col3_layout = self.main.ui.col3_mainchat.layout()
        col3_layout.insertWidget(col3_layout.count() - 1, self.reply_bar)
        self.reply_bar.hide()

    def _show_chat_context_menu(self, pos):
        """Hiển thị menu chuột phải trên danh sách tin nhắn."""
        item = self.main.chat_list.itemAt(pos)
        if not item:
            return
        data = item.data(Qt.UserRole)
        if not data or data.get("type") not in ("text", "image"):
            return
        menu = QMenu(self.main)
        menu.setStyleSheet("""
            QMenu { background:#2C323A; color:white; border:1px solid #444;
                    border-radius:6px; padding:4px; }
            QMenu::item { padding:6px 20px; border-radius:4px; }
            QMenu::item:selected { background:#3498db; }
        """)
        reply_action = menu.addAction("↩  Trả lời tin nhắn này")
        forward_action = menu.addAction("➡  Chuyển tiếp tin nhắn này")
        action = menu.exec(self.main.chat_list.viewport().mapToGlobal(pos))
        
        if action == reply_action:
            self._start_reply(data)
        elif action == forward_action:
            self._start_forward(data)

    def _start_forward(self, msg_data):
        """Khởi chạy cửa sổ chuyển tiếp tin nhắn."""
        dialog = ForwardDialog(self.main, msg_data)
        dialog.exec()

    def _start_reply(self, msg_data):
        """Lưu tin nhắn cần reply và hiện thanh preview."""
        self.main.reply_to_data = {
            "sender": msg_data["sender"],
            "content": msg_data.get("content", "[Ảnh]")
        }
        preview = self.main.reply_to_data["content"]
        if len(preview) > 55:
            preview = preview[:52] + "..."
        self.reply_preview_lbl.setText(
            f"<b style='color:#3498db'>{self.main.reply_to_data['sender']}</b>: {preview}"
        )
        self.reply_bar.show()
        self.main.ui.txt_input_message.setFocus()

    def _cancel_reply(self):
        """Hủy trả lời — ẩn thanh preview và xóa state."""
        self.main.reply_to_data = None
        self.reply_bar.hide()

    def _chat_list_mouse_press(self, event):
        """Xử lý click vào tin nhắn — nếu click trúng quote reply thì nhảy về tin gốc."""
        # Gọi xử lý mặc định trước
        self.original_mouse_press(event)

        item = self.main.chat_list.itemAt(event.position().toPoint())
        if not item:
            return

        data = item.data(Qt.UserRole)
        if not data or not isinstance(data, dict) or not data.get("reply_to"):
            return

        # Tính vùng quote block trong item
        y_offset = 0
        if data.get("show_time_tag"):
            y_offset += 40
        if data.get("show_name"):
            y_offset += 25

        item_rect = self.main.chat_list.visualItemRect(item)
        click_y = event.position().y() - item_rect.y()

        # Quote block cao 38px, bắt đầu tại y_offset+6
        if y_offset + 6 <= click_y <= y_offset + 44:
            reply_to = data["reply_to"]
            target_sender = reply_to.get("sender", "")
            target_content = reply_to.get("content", "")

            # Tìm tin gốc từ dưới lên
            for i in range(self.main.chat_list.count() - 1, -1, -1):
                other = self.main.chat_list.item(i)
                od = other.data(Qt.UserRole)
                if not od or not isinstance(od, dict) or od.get("type") != "text":
                    continue
                s = od.get("sender", "")
                # So sánh sender ("Tôi" ⟷ nickname)
                match_sender = (
                    s == target_sender
                    or (s == "Tôi" and target_sender == self.main.nickname)
                    or (s == self.main.nickname and target_sender == "Tôi")
                )
                if match_sender and od.get("content") == target_content:
                    self.main.chat_list.scrollToItem(other, QAbstractItemView.PositionAtCenter)
                    self.main.chat_list.setCurrentItem(other)
                    break

class ForwardDialog(QDialog):
    def __init__(self, main_window, msg_data):
        super().__init__(main_window)
        self.main = main_window
        self.msg_data = msg_data
        self.setWindowTitle("Chuyển tiếp tin nhắn")
        self.setFixedSize(300, 400)
        self.setStyleSheet("""
            QDialog { background-color: #2C323A; color: white; }
            QListWidget { background-color: #1E242C; border: 1px solid #444; border-radius: 4px; padding: 5px; color: white; }
            QListWidget::item { padding: 10px; border-bottom: 1px solid #333; }
            QListWidget::item:selected { background-color: #3498db; border-radius: 4px; }
            QPushButton { background-color: #3498db; color: white; border: none; padding: 10px; border-radius: 4px; font-weight: bold; }
            QPushButton:hover { background-color: #2980b9; }
        """)

        layout = QVBoxLayout(self)
        
        title = QLabel("Chọn cuộc trò chuyện để chuyển tiếp:")
        title.setStyleSheet("color: white; font-size: 13px; font-weight: bold;")
        layout.addWidget(title)

        self.list_widget = QListWidget()
        layout.addWidget(self.list_widget)

        # Lấy danh sách từ Cột 2
        for i in range(self.main.ui.list_chats.count()):
            item = self.main.ui.list_chats.item(i)
            target = item.text()
            if target and item.data(Qt.UserRole) != "self_greeting" and "Xin chào" not in target:
                self.list_widget.addItem(target)

        self.btn_send = QPushButton("Gửi Chuyển Tiếp")
        self.btn_send.clicked.connect(self._do_forward)
        layout.addWidget(self.btn_send)

    def _do_forward(self):
        selected = self.list_widget.currentItem()
        if not selected:
            QMessageBox.warning(self, "Lỗi", "Vui lòng chọn một cuộc trò chuyện!")
            return

        target = selected.text()
        original_sender = self.msg_data["sender"]
        original_content = self.msg_data.get("content", "[Ảnh/Sticker]")
        
        if self.msg_data.get("type") in ("image", "sticker"):
            original_content = f"[{'Ảnh' if self.msg_data.get('type') == 'image' else 'Sticker'}]"

        forwarded_content = f"[Tin nhắn chuyển tiếp]:\n{original_content}"

        msg_dict = None
        if target == "Phòng Chat Chung":
            msg_dict = {"type": "chat_all", "sender": self.main.nickname, "content": forwarded_content}
        elif target.startswith("Nhóm: "):
            group_id = target.replace("Nhóm: ", "").strip()
            msg_dict = {"type": "chat_group", "group_id": group_id, "sender": self.main.nickname, "content": forwarded_content}
        else:
            msg_dict = {"type": "chat_private", "sender": self.main.nickname, "receiver": target, "content": forwarded_content}

        try:
            payload = json.dumps(msg_dict).encode('utf-8')
            header = struct.pack("!I", len(payload))
            self.main.sock.sendall(header + payload)

            # Cập nhật hiển thị cục bộ
            current_time = time.strftime("%H:%M")
            if target not in self.main.chat_history_db:
                self.main.chat_history_db[target] = []
            self.main.chat_history_db[target].append(("Tôi", forwarded_content))
            self.main.last_message_times[target] = time.time()
            self.main.sort_chat_list()

            # Nếu phòng đích đang mở thì vẽ luôn
            if self.main.current_chat_target == target:
                self.main.display_message("Tôi", forwarded_content)
                
            QMessageBox.information(self, "Thành công", f"Đã chuyển tiếp tin nhắn đến {target}!")

            self.accept()
        except Exception as e:
            QMessageBox.critical(self, "Lỗi", f"Không thể gửi: {str(e)}")
