import os
import json
import struct
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget,
                               QPushButton, QListWidgetItem, QAbstractItemView, QMessageBox, QWidget)
from PySide6.QtGui import QIcon, QColor
from PySide6.QtCore import Qt

class GroupHandler:
    """
    Class quản lý toàn bộ các tính năng liên quan đến Nhóm Chat (Group Chat).
    Bao gồm:
    - Tạo nhóm mới, thêm thành viên.
    - Xử lý các sự kiện nhóm (thành viên rời, bị kick, có người mới).
    - Quản lý quyền hạn (Admin) và duyệt yêu cầu vào nhóm.
    - Xây dựng các hộp thoại (Dialog) tương tác với người dùng.
    
    LƯU Ý ĐẶC BIỆT TRONG KIẾN TRÚC:
    - File này đóng vai trò cầu nối: Nhận tương tác UI -> Gửi gói tin JSON qua Socket lên Server -> 
      Server xử lý -> Server trả về gói tin -> `ReceiveThread` trong main.py bắt được -> Gọi ngược lại các hàm `handle_*` trong file này để cập nhật UI.
    """
    def __init__(self, main_window):
        self.main = main_window

    def open_create_group_dialog(self, preselect_user=None):
        """
        Mở hộp thoại tạo nhóm mới.
        - Quét danh sách các liên hệ hiện có trong cột bên trái (bỏ qua 'all' và các nhóm đã có).
        - Cho phép chọn nhiều người cùng lúc.
        - Đóng gói dữ liệu thành chuẩn JSON (type: 'create_group') và gửi đi.
        - preselect_user: Tính năng UX - Nếu đang chat riêng với A mà bấm tạo nhóm, A sẽ được tick chọn sẵn.
        """
        # Lấy danh sách bạn bè hiện có trong list_chats (bỏ "all" và các nhóm)
        friends = []
        for i in range(self.main.ui.list_chats.count()):
            it = self.main.ui.list_chats.item(i)
            text = it.text()
            if text and text != "all" and text not in self.main.my_groups and it.data(Qt.UserRole) != "self_greeting":
                friends.append(text)

        if len(friends) == 0:
            QMessageBox.information(self.main, "Thông báo", "Bạn cần có ít nhất 1 liên hệ để tạo nhóm!")
            return

        dlg = QDialog(self.main)
        dlg.setWindowTitle("👥 Tạo nhóm mới")
        dlg.setFixedWidth(360)
        dlg.setStyleSheet("""
            QDialog { background:#1E2227; color:white; }
            QLabel { color:#B0B8C1; font-size:13px; }
            QLabel#title { color:white; font-size:16px; font-weight:bold; }
            QLineEdit {
                background:#2C323A; color:white; border:1px solid #444;
                border-radius:8px; padding:8px 12px; font-size:13px;
            }
            QLineEdit:focus { border:1px solid #3498db; }
            QListWidget {
                background:#2C323A; color:white; border:1px solid #444;
                border-radius:8px; font-size:13px;
            }
            QListWidget::item { padding:6px 10px; }
            QListWidget::item:selected { background:#3498db; border-radius:4px; }
            QPushButton {
                background:#3498db; color:white; border:none;
                border-radius:8px; padding:10px; font-size:14px; font-weight:bold;
            }
            QPushButton:hover { background:#2980b9; }
            QPushButton#btn_cancel {
                background:#2C323A; color:#B0B8C1;
            }
            QPushButton#btn_cancel:hover { background:#3a4048; }
        """)

        layout = QVBoxLayout(dlg)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel("👥 Tạo nhóm mới")
        title.setObjectName("title")
        layout.addWidget(title)

        layout.addWidget(QLabel("Tên nhóm:"))
        name_edit = QLineEdit()
        name_edit.setMaxLength(40)
        name_edit.setPlaceholderText("Nhập tên nhóm...")
        layout.addWidget(name_edit)

        layout.addWidget(QLabel("Chọn thành viên (giữ Ctrl để chọn nhiều):"))
        member_list = QListWidget()
        member_list.setSelectionMode(QAbstractItemView.MultiSelection)
        for f in friends:
            item = QListWidgetItem(f)
            member_list.addItem(item)
            if preselect_user and f == preselect_user:
                item.setSelected(True)
        
        if preselect_user:
            def prevent_deselect():
                for i in range(member_list.count()):
                    item = member_list.item(i)
                    if item.text() == preselect_user and not item.isSelected():
                        item.setSelected(True)
            member_list.itemSelectionChanged.connect(prevent_deselect)

        member_list.setMinimumHeight(120)
        layout.addWidget(member_list)

        btn_row = QHBoxLayout()
        btn_cancel = QPushButton("Hủy")
        btn_cancel.setObjectName("btn_cancel")
        btn_create = QPushButton("✔  Tạo nhóm")
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_create)
        layout.addLayout(btn_row)

        def do_create():
            group_name = name_edit.text().strip()
            selected = [item.text() for item in member_list.selectedItems()]
            if not group_name:
                name_edit.setPlaceholderText("⚠ Vui lòng nhập tên nhóm!")
                return
            if not selected:
                QMessageBox.warning(dlg, "Thiếu thành viên", "Vui lòng chọn ít nhất 1 thành viên!")
                return
            msg_dict = {
                "type": "create_group",
                "group_id": group_name,
                "members": selected
            }
            payload = json.dumps(msg_dict).encode('utf-8')
            try:
                self.main.sock.sendall(struct.pack("!I", len(payload)) + payload)
                dlg.accept()
            except Exception as e:
                QMessageBox.critical(dlg, "Lỗi", f"Không thể gửi: {e}")

        btn_cancel.clicked.connect(dlg.reject)
        btn_create.clicked.connect(do_create)
        dlg.exec()

    def handle_group_event(self, event_type, group_id, admin, members):
        """
        Xử lý khi hệ thống báo có một nhóm mới được tạo thành công, hoặc bản thân vừa được ai đó thêm vào nhóm.
        - Cập nhật danh sách nhóm và admin trong bộ nhớ.
        - Khởi tạo lịch sử chat trống cho nhóm này nếu chưa có.
        - Tạo thẻ nhóm mới trong cột danh sách (màu xanh lá) và tự động switch sang nhóm đó.
        """
        self.main.my_groups[group_id] = members
        self.main.group_admins[group_id] = admin
        if group_id not in self.main.chat_history_db:
            self.main.chat_history_db[group_id] = []

        target_item = None
        for i in range(self.main.ui.list_chats.count()):
            if self.main.ui.list_chats.item(i).text() == group_id:
                target_item = self.main.ui.list_chats.item(i)
                break
        if target_item is None:
            target_item = QListWidgetItem(f"{group_id}")
            target_item.setForeground(QColor("#2ecc71"))
            target_item.setData(Qt.UserRole, "group")
            self.main.ui.list_chats.addItem(target_item)
            self.main.handle_incoming_message("Hệ thống", f"Bạn đã tham gia nhóm {group_id}. Admin: {admin}", group_id)
            
        self.main.ui.list_chats.setCurrentItem(target_item)
        self.main.switch_chat_room(target_item)

    def handle_group_member_event(self, event_type, group_id, member, new_admin=None):
        """
        Lắng nghe và cập nhật giao diện khi có thay đổi nhân sự trong một nhóm đang tham gia:
        - 'left': Có người rời nhóm. Nếu Admin rời đi, Server sẽ gửi kèm tên `new_admin` mới.
        - 'kicked': Có người bị đuổi khỏi nhóm.
        - 'added': Có người mới gia nhập nhóm.
        Ghi nhận thông báo hệ thống và tự động cập nhật số lượng thành viên trên thanh tiêu đề.
        """
        if group_id in self.main.my_groups:
            if event_type == "left":
                if member in self.main.my_groups[group_id]:
                    self.main.my_groups[group_id].remove(member)
                if new_admin and group_id in self.main.group_admins:
                    self.main.group_admins[group_id] = new_admin
                self.main.handle_incoming_message("Hệ thống", f"{member} đã rời nhóm.", group_id)
                if new_admin:
                    self.main.handle_incoming_message("Hệ thống", f"{new_admin} đã trở thành nhóm trưởng.", group_id)
            elif event_type == "kicked":
                if member in self.main.my_groups[group_id]:
                    self.main.my_groups[group_id].remove(member)
                self.main.handle_incoming_message("Hệ thống", f"{member} đã bị xóa khỏi nhóm.", group_id)
            elif event_type == "added":
                if member not in self.main.my_groups[group_id]:
                    self.main.my_groups[group_id].append(member)
                self.main.handle_incoming_message("Hệ thống", f"{member} đã gia nhập nhóm.", group_id)
            if self.main.current_chat_target == group_id:
                self.main.ui.lbl_chat_title.setText(f"👥 {group_id}  |  {len(self.main.my_groups[group_id])} thành viên")
                
    def handle_group_kicked(self, group_id):
        """
        Xử lý sự kiện CHÍNH BẢN THÂN bị Admin đá khỏi nhóm.
        - Xóa sạch dữ liệu của nhóm này trong bộ nhớ cục bộ (my_groups, chat_history_db).
        - Gỡ bỏ nhóm khỏi danh sách bên trái.
        - Nếu đang mở nhóm đó, tự động đá màn hình về phòng chat đầu tiên.
        """
        if group_id in self.main.my_groups:
            del self.main.my_groups[group_id]
        if group_id in self.main.chat_history_db:
            del self.main.chat_history_db[group_id]
        for i in range(self.main.ui.list_chats.count()):
            if self.main.ui.list_chats.item(i).text() == group_id:
                self.main.ui.list_chats.takeItem(i)
                break
        if self.main.current_chat_target == group_id:
            self.main.switch_chat_room(self.main.ui.list_chats.item(0))
        self.main.display_message("Hệ thống", f"Bạn đã bị xóa khỏi nhóm {group_id}.")
        
    def handle_new_join_request(self, group_id):
        """Hiện thông báo hệ thống cho Admin biết có người đang xin vào nhóm."""
        self.main.handle_incoming_message("Hệ thống", f"Có yêu cầu tham gia mới trong nhóm {group_id}.", group_id)
        
    def request_join_requests_list(self):
        """Hành động của Admin: Bấm nút lấy danh sách những người đang xin vào nhóm từ Server."""
        if self.main.current_chat_type != "chat_group": return
        group_id = self.main.current_chat_target
        if group_id not in self.main.my_groups: return
        msg = json.dumps({"type": "get_join_requests", "sender": self.main.nickname, "group_id": group_id}).encode('utf-8')
        self.main.sock.sendall(struct.pack("!I", len(msg)) + msg)

    def handle_join_requests_list(self, group_id, requests):
        """
        Vẽ hộp thoại hiển thị danh sách các yêu cầu xin vào nhóm.
        (Lưu ý: Chỉ Admin mới gọi và thấy được hàm này do Server quản lý quyền).
        Admin có thể click chọn và bấm "Duyệt".
        """
        if not requests:
            QMessageBox.information(self.main, "Yêu cầu", "Không có yêu cầu tham gia nào.")
            return
            
        dlg = QDialog(self.main)
        dlg.setWindowTitle("Yêu cầu vào nhóm")
        dlg.resize(300, 400)
        dlg.setStyleSheet("QDialog { background-color: #1E2227; color: white; } QLabel { color: white; } QListWidget { background: #2C323A; color: white; } QPushButton { background-color: #3498db; color: white; padding: 5px; border-radius: 3px; } QPushButton:hover { background-color: #2980b9; }")
        layout = QVBoxLayout(dlg)
        
        lbl = QLabel(f"Các yêu cầu tham gia nhóm {group_id}:")
        layout.addWidget(lbl)
        
        list_widget = QListWidget()
        layout.addWidget(list_widget)
        
        for req in requests:
            item = QListWidgetItem(req)
            list_widget.addItem(item)
            
        btn_layout = QHBoxLayout()
        btn_approve = QPushButton("Duyệt")
        btn_reject = QPushButton("Đóng") 
        btn_layout.addWidget(btn_approve)
        btn_layout.addWidget(btn_reject)
        layout.addLayout(btn_layout)
        
        def approve_selected():
            sel = list_widget.currentItem()
            if sel:
                msg = json.dumps({"type": "approve_join_request", "sender": self.main.nickname, "group_id": group_id, "member": sel.text()}).encode('utf-8')
                self.main.sock.sendall(struct.pack("!I", len(msg)) + msg)
                list_widget.takeItem(list_widget.row(sel))
                if list_widget.count() == 0:
                    dlg.accept()
                    
        btn_approve.clicked.connect(approve_selected)
        btn_reject.clicked.connect(dlg.reject)
        
        dlg.exec()
        
    def handle_join_request_approved(self, group_id, member):
        """Hiển thị thông báo khi yêu cầu gia nhập của một người đã được duyệt thành công."""
        QMessageBox.information(self.main, "Thành công", f"Đã thêm {member} vào nhóm {group_id}.")

    def leave_group(self):
        """
        Xử lý hành động người dùng chủ động bấm rời nhóm.
        - Gửi lệnh 'leave_group' lên server.
        - Xóa dữ liệu nhóm trong bộ nhớ, gỡ nhóm khỏi danh sách UI.
        - Ẩn luôn cột 4 (Thông tin nhóm) nếu nó đang mở.
        """
        if self.main.current_chat_type == "chat_group":
            target = self.main.current_chat_target
            reply = QMessageBox.question(self.main, "Xác nhận", f"Bạn có chắc chắn muốn rời nhóm {target} không?")
            if reply == QMessageBox.Yes:
                msg = json.dumps({"type": "leave_group", "sender": self.main.nickname, "group_id": target}).encode('utf-8')
                self.main.sock.sendall(struct.pack("!I", len(msg)) + msg)
                if target in self.main.my_groups:
                    del self.main.my_groups[target]
                if target in self.main.chat_history_db:
                    del self.main.chat_history_db[target]
                for i in range(self.main.ui.list_chats.count()):
                    if self.main.ui.list_chats.item(i).text() == target:
                        self.main.ui.list_chats.takeItem(i)
                        break
                self.main.switch_chat_room(self.main.ui.list_chats.item(0))
                self.main.display_message("Hệ thống", f"Bạn đã rời nhóm {target}.")
                if getattr(self.main, '_info_panel_visible', False) and hasattr(self.main.ui, 'stacked_col4') and self.main.ui.stacked_col4.currentIndex() == 0:
                    self.main.ui.col4_info.hide()
                    self.main._info_panel_visible = False

    def open_create_group_from_private(self):
        """Shortcut UX: Nhấn nút tạo nhóm khi đang ở phòng chat riêng với ai đó."""
        self.open_create_group_dialog(preselect_user=self.main.current_chat_target)

    def show_members_dialog(self):
        """
        Hiển thị hộp thoại danh sách toàn bộ các thành viên trong nhóm.
        ĐIỂM ĐẶC BIỆT UX/UI:
        - Admin luôn được đẩy lên đầu danh sách và gắn kèm icon Chìa khóa (Key).
        - Nếu người xem TỰ NHẬN THẤY MÌNH LÀ ADMIN, họ sẽ thấy nút "Kick" xuất hiện bên cạnh mỗi thành viên khác.
        - Bấm "Kick" sẽ gửi lệnh 'kick_member' lên server để xử lý.
        """
        if self.main.current_chat_type != "chat_group": return
        group_id = self.main.current_chat_target
        if group_id not in self.main.my_groups: return
        
        dlg = QDialog(self.main)
        dlg.setWindowTitle(f"Thành viên nhóm {group_id}")
        dlg.resize(300, 400)
        dlg.setStyleSheet("QDialog { background-color: #1E2227; color: white; } QLabel { color: white; font-weight: bold; } QListWidget { background: #2C323A; color: white; border: none; }")
        
        layout = QVBoxLayout(dlg)
        lbl = QLabel(f"Thành viên ({len(self.main.my_groups[group_id])}):")
        layout.addWidget(lbl)
        
        list_widget = QListWidget()
        layout.addWidget(list_widget)
        
        admin = self.main.group_admins.get(group_id)
        is_me_admin = (admin == self.main.nickname)
        
        # Sắp xếp admin lên đầu
        members = list(self.main.my_groups[group_id])
        if admin in members:
            members.remove(admin)
            members.insert(0, admin)
            
        key_icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "images", "key.svg")
        kick_icon_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "images", "kick.svg")
        
        for mem in members:
            item = QListWidgetItem()
            widget = QWidget()
            h_layout = QHBoxLayout(widget)
            h_layout.setContentsMargins(5, 5, 5, 5)
            
            name_lbl = QLabel(mem + (" (Bạn)" if mem == self.main.nickname else ""))
            h_layout.addWidget(name_lbl)
            
            if mem == admin:
                key_lbl = QLabel()
                if os.path.exists(key_icon_path):
                    key_lbl.setPixmap(QIcon(key_icon_path).pixmap(16, 16))
                else:
                    key_lbl.setText("[Admin]")
                h_layout.addWidget(key_lbl)
                
            h_layout.addStretch()
            
            if is_me_admin and mem != self.main.nickname:
                kick_btn = QPushButton()
                if os.path.exists(kick_icon_path):
                    kick_btn.setIcon(QIcon(kick_icon_path))
                else:
                    kick_btn.setText("Kick")
                kick_btn.setFixedSize(24, 24)
                kick_btn.setStyleSheet("QPushButton { background: transparent; } QPushButton:hover { background: rgba(255, 0, 0, 0.2); border-radius: 12px; }")
                def make_kick_handler(m):
                    def kick():
                        reply = QMessageBox.question(dlg, "Xác nhận", f"Xóa {m} khỏi nhóm?")
                        if reply == QMessageBox.Yes:
                            msg = json.dumps({"type": "kick_member", "admin": self.main.nickname, "group_id": group_id, "member": m}).encode('utf-8')
                            self.main.sock.sendall(struct.pack("!I", len(msg)) + msg)
                            dlg.accept()
                    return kick
                kick_btn.clicked.connect(make_kick_handler(mem))
                h_layout.addWidget(kick_btn)
                
            item.setSizeHint(widget.sizeHint())
            list_widget.addItem(item)
            list_widget.setItemWidget(item, widget)
            
        btn_close = QPushButton("Đóng")
        btn_close.setStyleSheet("background-color: #3498db; color: white; padding: 8px; border-radius: 4px;")
        btn_close.clicked.connect(dlg.reject)
        layout.addWidget(btn_close)
        
        dlg.exec()

    def show_add_member_dialog(self):
        """
        Hộp thoại chọn liên hệ để thêm (invite) vào nhóm hiện tại.
        Cơ chế quyền lực:
        - Lọc danh sách liên hệ để giấu đi những người ĐÃ CÓ MẶT trong nhóm.
        - NẾU bản thân là Admin: Lệnh gửi đi ('add_member') sẽ có tác dụng ép thành viên vào nhóm ngay lập tức.
        - NẾU bản thân là Member thường: Lệnh gửi đi vẫn là 'add_member' nhưng Server sẽ tự động hạ cấp lệnh này thành một 'yêu cầu' (join_request) gửi đến Admin phê duyệt.
        """
        if self.main.current_chat_type != "chat_group": return
        group_id = self.main.current_chat_target
        if group_id not in self.main.my_groups: return
        
        friends = []
        for i in range(self.main.ui.list_chats.count()):
            it = self.main.ui.list_chats.item(i)
            text = it.text()
            if text and text != "all" and text not in self.main.my_groups and it.data(Qt.UserRole) != "self_greeting":
                if text not in self.main.my_groups[group_id]:
                    friends.append(text)
                    
        if not friends:
            QMessageBox.information(self.main, "Thông báo", "Bạn không có liên hệ nào để thêm (hoặc tất cả đã ở trong nhóm).")
            return
            
        dlg = QDialog(self.main)
        dlg.setWindowTitle("Thêm thành viên")
        dlg.resize(300, 400)
        dlg.setStyleSheet("QDialog { background-color: #1E2227; color: white; } QLabel { color: white; } QListWidget { background: #2C323A; color: white; } QPushButton { background-color: #3498db; color: white; padding: 5px; border-radius: 3px; } QPushButton:hover { background-color: #2980b9; }")
        
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel("Chọn liên hệ để thêm:"))
        
        list_widget = QListWidget()
        for f in friends:
            list_widget.addItem(f)
        layout.addWidget(list_widget)
        
        btn_layout = QHBoxLayout()
        btn_add = QPushButton("Thêm")
        btn_cancel = QPushButton("Hủy")
        btn_layout.addWidget(btn_add)
        btn_layout.addWidget(btn_cancel)
        layout.addLayout(btn_layout)
        
        def do_add():
            sel = list_widget.currentItem()
            if sel:
                member = sel.text()
                msg = json.dumps({"type": "add_member", "sender": self.main.nickname, "group_id": group_id, "member": member}).encode('utf-8')
                self.main.sock.sendall(struct.pack("!I", len(msg)) + msg)
                if self.main.group_admins.get(group_id) == self.main.nickname:
                    QMessageBox.information(dlg, "Thành công", f"Đã thêm {member} vào nhóm.")
                else:
                    QMessageBox.information(dlg, "Thành công", f"Đã gửi yêu cầu thêm {member} cho trưởng nhóm.")
                dlg.accept()
                
        btn_add.clicked.connect(do_add)
        btn_cancel.clicked.connect(dlg.reject)
        
        dlg.exec()
