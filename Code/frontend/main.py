import sys
import os

# Thêm thư mục gốc vào sys.path để có thể import Multimedia
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import struct
import socket
import numpy as np
import cv2
import base64
from datetime import datetime
from PySide6.QtWidgets import QApplication, QWidget, QMessageBox, QVBoxLayout, QLabel, QStyledItemDelegate, QListWidget, QListWidgetItem, QLineEdit
from PySide6.QtUiTools import QUiLoader
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QFont, QFontMetrics
from PySide6.QtCore import QFile, QTimer, QThread, Signal, Qt, QRectF, QSize

class SocketWorker(QThread):
    """
    Luồng xử lý việc kết nối ban đầu đến Server (Đăng nhập).
    Chạy nền để không làm đơ giao diện UI khi chờ Server phản hồi.
    """
    login_success = Signal(object, str)
    login_error = Signal(str)

    def __init__(self, host='127.0.0.1', port=9999, user_data=None):
        super().__init__()
        self.host = host
        self.port = port
        self.user_data = user_data or {"type": "login", "nickname": "Frontend_Dev"}

    def run(self):
        """
        Thực hiện bắt tay (handshake) với Server. Đóng gói dữ liệu login,
        nhận 4-byte header để tính toán độ lớn gói tin phản hồi,
        giúp tránh lỗi dính gói (TCP Fragmentation).
        """
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(5.0)  
            sock.connect((self.host, self.port))

            # Gói dữ liệu login
            json_str = json.dumps(self.user_data)
            payload = json_str.encode('utf-8')
            header = struct.pack("!I", len(payload))
            sock.sendall(header + payload)

            # Chờ phản hồi từ server (đọc đủ 4 byte header)
            reply_header = b""
            while len(reply_header) < 4:
                chunk = sock.recv(4 - len(reply_header))
                if not chunk:
                    self.login_error.emit("Server đóng kết nối đột ngột.")
                    sock.close()
                    return
                reply_header += chunk

            reply_size = struct.unpack("!I", reply_header)[0]

            # Đọc đủ payload phản hồi
            reply_payload = b""
            while len(reply_payload) < reply_size:
                chunk = sock.recv(reply_size - len(reply_payload))
                if not chunk:
                    self.login_error.emit("Server đóng kết nối đột ngột.")
                    sock.close()
                    return
                reply_payload += chunk

            reply_json = json.loads(reply_payload.decode('utf-8'))

            if reply_json.get("type") == "info" and reply_json.get("msg") == "OK":
                # THÀNH CÔNG: Gỡ bỏ timeout để socket rảnh rỗi chờ chat
                sock.settimeout(None)
                # Phát tín hiệu mang theo đối tượng socket ra ngoài (KHÔNG GỌI sock.close())
                self.login_success.emit(sock, "Đăng nhập thành công!")
                return
            else:
                self.login_error.emit(f"Đăng nhập thất bại: {reply_json.get('msg', 'Lỗi không xác định')}")
                sock.close()

        except ConnectionRefusedError:
            self.login_error.emit("Không thể kết nối. Server chưa bật!")
        except Exception as e:
            self.login_error.emit(f"Lỗi mạng: {str(e)}")

class ReceiveThread(QThread):
    """
    Luồng lắng nghe liên tục dữ liệu từ Server trong suốt quá trình chat.
    Sử dụng hệ thống Signal để giao tiếp an toàn với luồng chính (Main Thread UI).
    """
    message_received = Signal(str, str, str) # Tín hiệu phát ra: (người_gửi, nội_dung, target_room)
    message_received_ex = Signal(str, str, str, object)  # kèm reply_to


    system_info_received = Signal(str)
    incoming_request = Signal(str, str, str) # req_type, sender, target (group_id/user)
    request_result = Signal(str, str, str)
    group_event = Signal(str, str, str, list)  # event_type, group_id, admin, members
    avatar_updated = Signal(str, str)  # sender, avatar_b64
    all_avatars_received = Signal(object)  # dict {nickname: avatar_b64}
    unfriended_event = Signal(str)
    group_member_event = Signal(str, str, str, object) # event_type, group_id, member, new_admin
    group_kicked_event = Signal(str) # group_id
    new_join_request_event = Signal(str)
    join_requests_list_event = Signal(str, list)
    join_request_approved_event = Signal(str, str)


    def __init__(self, sock):
        super().__init__()
        self.sock = sock
        self._is_running = True

    def run(self):
        """
        Vòng lặp vô hạn nhận gói tin. Đầu tiên đọc 4-byte header để lấy size,
        sau đó đọc đủ payload theo size. Phân loại gói JSON và phát Signal tương ứng.
        """
        while self._is_running:
            try:
                # 1. Nhận 4-byte header để biết kích thước gói tin
                header = b""
                while len(header) < 4:
                    chunk = self.sock.recv(4 - len(header))
                    if not chunk:
                        return
                    header += chunk
                
                size = struct.unpack("!I", header)[0]
                
                # 2. Nhận đủ dữ liệu (payload)
                payload = b""
                while len(payload) < size:
                    chunk = self.sock.recv(size - len(payload))
                    if not chunk:
                        return
                    payload += chunk
                    
                # 3. Phân loại dữ liệu
                try:
                    text = payload.decode('utf-8')
                    data = json.loads(text)
                    msg_type = data.get("type")
                    
                    # Phân loại tin nhắn từ Server và phát tín hiệu ra UI
                    if msg_type == "new_message":
                        self.message_received.emit(data["sender"], data["content"], "all")
                    elif msg_type == "private_message":
                        # Tin nhắn riêng thì target_room chính là tên người gửi
                        reply_to = data.get("reply_to", None)
                        self.message_received_ex.emit(data["sender"], data["content"], data["sender"], reply_to)
                    elif msg_type == "group_message":
                        # Tin nhắn nhóm thì target_room là group_id
                        reply_to = data.get("reply_to", None)
                        self.message_received_ex.emit(data["sender"], data["content"], data["group_id"], reply_to)

                    elif msg_type == "group_created":
                        group_id = data.get("group_id", "")
                        admin = data.get("admin", "")
                        members = data.get("members", [])
                        self.group_event.emit("group_created", group_id, admin, members)
                    elif msg_type == "added_to_group":
                        group_id = data.get("group_id", "")
                        admin = data.get("admin", "")
                        members = data.get("members", [])
                        self.group_event.emit("added_to_group", group_id, admin, members)
                    elif msg_type == "system_info":
                        self.system_info_received.emit(data["msg"])
                    elif msg_type == "incoming_request":
                        self.incoming_request.emit(data["req_type"], data["sender"], data["target"])
                    elif msg_type == "request_result":
                        self.request_result.emit(data["target"], data["msg"], data["status"])
                    elif msg_type == "avatar_updated":
                        self.avatar_updated.emit(data["sender"], data.get("avatar_name", ""))
                    elif msg_type == "all_avatars":
                        self.all_avatars_received.emit(data.get("avatars", {}))
                    elif msg_type == "unfriended":
                        self.unfriended_event.emit(data.get("target", ""))
                    elif msg_type == "member_left":
                        self.group_member_event.emit("left", data.get("group_id", ""), data.get("member", ""), data.get("new_admin", None))
                    elif msg_type == "kicked_from_group":
                        self.group_kicked_event.emit(data.get("group_id", ""))
                    elif msg_type == "member_kicked":
                        self.group_member_event.emit("kicked", data.get("group_id", ""), data.get("member", ""), None)
                    elif msg_type == "member_added":
                        self.group_member_event.emit("added", data.get("group_id", ""), data.get("member", ""), None)
                    elif msg_type == "new_join_request":
                        self.new_join_request_event.emit(data.get("group_id", ""))
                    elif msg_type == "join_requests_list":
                        self.join_requests_list_event.emit(data.get("group_id", ""), data.get("requests", []))
                    elif msg_type == "join_request_approved":
                        self.join_request_approved_event.emit(data.get("group_id", ""), data.get("member", ""))


                except json.JSONDecodeError:
                    print("[ReceiveThread] Nhận được chuỗi không phải JSON hợp lệ.")
            except Exception as e:
                print("[ReceiveThread] Lỗi nhận dữ liệu:", e)
                break

# LUỒNG CHỤP ẢNH TỪ WEBCAM (TRÁNH ĐƠ GIAO DIỆN)


class ChatDelegate(QStyledItemDelegate):
    """
    Họa sĩ (Custom Delegate) vẽ từng bong bóng chat trong danh sách.
    Sử dụng QTextDocument để bẻ dòng (word-wrap) tự động.
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        self.font_text = QFont()
        self.font_text.setPointSize(13) # Cỡ chữ tin nhắn
        self.font_name = QFont()
        self.font_name.setPointSize(11)
        self.font_name.setBold(True)
        self.font_time = QFont()
        self.font_time.setPointSize(10)
        self.font_tag = QFont()
        self.font_tag.setPointSize(10)
        self.font_quote = QFont()
        self.font_quote.setPointSize(10)
        self.font_quote.setItalic(True)
        self.font_quote_name = QFont()
        self.font_quote_name.setPointSize(10)
        self.font_quote_name.setBold(True)

    def sizeHint(self, option, index):
        """
        Tính toán chiều cao cần thiết cho bong bóng chat.
        Bao gồm chiều cao text nội dung, avatar, quote (nếu có), và đệm.
        """
        data = index.data(Qt.UserRole)
        if not data: return QSize(0, 0)
        
        list_widget = option.widget
        w = list_widget.viewport().width() if list_widget else option.rect.width()
        
        is_me = data.get("sender") == "Tôi"
        max_bubble_w = min(500, w - 100) if is_me else min(500, w - 146)
        
        h = 0
        if data.get("show_time_tag"): h += 40
        if data.get("show_name") and data.get("chat_type") != "chat_private": h += 25
            
        # Chiều cao khối quote (nếu có reply_to)
        if data.get("reply_to"):
            h += 38  # quote_name(16) + quote_text(16) + padding(6)
            
        if data.get("type") == "system":
            return QSize(w, 40)
            
        if data.get("type") == "text":
            # --- DÙNG QTextDocument ĐỂ ÉP BẺ DÒNG MỌI CHUỖI DÀI ---
            from PySide6.QtGui import QTextDocument, QTextOption
            doc = QTextDocument()
            doc.setDefaultFont(self.font_text)
            opt = QTextOption()
            opt.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere) # Bẻ gãy cả code và URL
            doc.setDefaultTextOption(opt)
            
            # --- TÍNH NĂNG CHUYỂN TIẾP: Format chữ nhỏ & nhạt màu ---
            if data["content"].startswith("[Tin nhắn chuyển tiếp]:\n"):
                import html
                real_text = data["content"].replace("[Tin nhắn chuyển tiếp]:\n", "", 1)
                escaped = html.escape(real_text).replace('\n', '<br>')
                html_text = f"<span style='color: #8A8D91; font-size: 11px; font-style: italic;'>[Tin nhắn chuyển tiếp]</span><br><span style='color: white;'>{escaped}</span>"
                doc.setHtml(html_text)
            else:
                doc.setPlainText(data["content"])
                
            doc.setTextWidth(max_bubble_w - 24)
            h += doc.size().height() + 20
        elif data.get("type") == "image":
            offset = 0
            h += data["img_h"] + offset

        if data.get("show_time"): h += 18
        h += 6 
        return QSize(w, h)

    def paint(self, painter, option, index):
        """
        Vẽ giao diện tin nhắn:
        - Phân biệt người gửi (is_me) để vẽ bên trái hoặc bên phải.
        - Vẽ Background bo góc (QPainterPath).
        - Vẽ khối trích dẫn (Quote) nếu là tin nhắn phản hồi.
        - Vẽ Text hoặc Ảnh nhúng.
        """
        data = index.data(Qt.UserRole)
        if not data: return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing) 
        
        list_widget = option.widget
        w = list_widget.viewport().width() if list_widget else option.rect.width()
        y = option.rect.y()
        effective_w = w - 25

        if data.get("type") == "system":
            fm_tag = QFontMetrics(self.font_tag)
            tag_text = data.get("tag_text", "")
            tag_w = fm_tag.horizontalAdvance(tag_text) + 24
            tag_rect = QRectF((w - tag_w) / 2, y + 10, tag_w, 22)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 255, 255, 20))
            painter.drawRoundedRect(tag_rect, 11, 11)
            painter.setPen(QColor("#8A8D91"))
            painter.setFont(self.font_tag)
            painter.drawText(tag_rect, Qt.AlignCenter, tag_text)
            painter.restore()
            return
            
        # 1. Vẽ Tag 20 phút
        if data.get("show_time_tag"):
            fm_tag = QFontMetrics(self.font_tag)
            tag_w = fm_tag.horizontalAdvance(data["tag_text"]) + 24
            tag_rect = QRectF((w - tag_w) / 2, y + 10, tag_w, 22)
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 255, 255, 20))
            painter.drawRoundedRect(tag_rect, 11, 11)
            painter.setPen(QColor("#8A8D91"))
            painter.setFont(self.font_tag)
            painter.drawText(tag_rect, Qt.AlignCenter, data["tag_text"])
            y += 40
            
        # 2. Vẽ Tên người gửi
        if data.get("show_name") and data.get("chat_type") != "chat_private":
            painter.setPen(QColor("#8A8D91"))
            painter.setFont(self.font_name)
            name_rect = QRectF(66, y, effective_w - 90, 20)
            painter.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter, data["sender"])
            y += 25
            
        # 3. Đo đạc bong bóng
        is_me = data["sender"] == "Tôi"
        max_bubble_w = min(500, w - 100) if is_me else min(500, w - 146)
        
        bubble_w, bubble_h = 0, 0
        doc = None

        # Thêm chiều cao quote vào bộ tính toán bong bóng
        quote_h = 38 if data.get("reply_to") else 0
        
        if data.get("type") == "text":
            # --- VẼ CHỮ BẰNG QTextDocument CHỐNG TRÀN LỀ ---
            from PySide6.QtGui import QTextDocument, QTextOption, QTextCursor, QTextCharFormat
            doc = QTextDocument()
            doc.setDefaultFont(self.font_text)
            opt = QTextOption()
            opt.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere)
            doc.setDefaultTextOption(opt)
            
            # --- TÍNH NĂNG CHUYỂN TIẾP: Format chữ nhỏ & nhạt màu ---
            if data["content"].startswith("[Tin nhắn chuyển tiếp]:\n"):
                import html
                real_text = data["content"].replace("[Tin nhắn chuyển tiếp]:\n", "", 1)
                escaped = html.escape(real_text).replace('\n', '<br>')
                html_text = f"<span style='color: #8A8D91; font-size: 11px; font-style: italic;'>[Tin nhắn chuyển tiếp]</span><br><span style='color: white;'>{escaped}</span>"
                doc.setHtml(html_text)
            else:
                doc.setPlainText(data["content"])
                # Ép màu chữ thành màu trắng
                cursor = QTextCursor(doc)
                cursor.select(QTextCursor.Document)
                fmt = QTextCharFormat()
                fmt.setForeground(Qt.white)
                cursor.mergeCharFormat(fmt)
                
            doc.setTextWidth(max_bubble_w - 24)

            # Lấy kích thước cực chuẩn
            bubble_w = max(58.0, doc.idealWidth() + 24)
            bubble_h = doc.size().height() + 20 + quote_h
        else:
            offset = 0
            bubble_w = data["img_w"] + offset
            bubble_h = data["img_h"] + offset + quote_h
            
        if data.get("show_time"): bubble_h += 18
            
        bubble_x = w - bubble_w - 20 if is_me else 66
            
        # 4. Vẽ Background bong bóng bo góc
        if data.get("type") != "image":
            bubble_rect = QRectF(bubble_x, y, bubble_w, bubble_h)
            painter.setBrush(QColor("#1E6C93") if is_me else QColor("#2C323A"))
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(bubble_rect, 15, 15)

        # 4a. Vẽ Avatar đối phương
        if not is_me and data.get("show_name"):
            avatar_pm = data.get("avatar_pixmap")
            if avatar_pm and not avatar_pm.isNull():
                painter.drawPixmap(20, int(y), avatar_pm)

        # 4b. Vẽ khối QUOTE nếu có reply_to
        if data.get("reply_to"):
            reply_to = data["reply_to"]
            quote_bg = QColor("#155070") if is_me else QColor("#1E242C")
            quote_rect = QRectF(bubble_x + 8, y + 6, bubble_w - 16, quote_h - 4)
            painter.setBrush(quote_bg)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(quote_rect, 8, 8)

            # Đường kẻ dọc bên trái
            accent_color = QColor("#5BC8F5") if is_me else QColor("#3498db")
            painter.setBrush(accent_color)
            painter.drawRoundedRect(QRectF(bubble_x + 8, y + 6, 3, quote_h - 4), 1, 1)

            # Tên người được reply
            painter.setPen(accent_color)
            painter.setFont(self.font_quote_name)
            qname_rect = QRectF(bubble_x + 16, y + 8, bubble_w - 28, 16)
            painter.drawText(qname_rect, Qt.AlignLeft | Qt.AlignVCenter,
                             reply_to.get("sender", ""))

            # Nội dung trích dẫn (cắt ngắn nếu quá dài)
            quoted_text = reply_to.get("content", "")
            if len(quoted_text) > 60:
                quoted_text = quoted_text[:57] + "..."
            painter.setPen(QColor("#B0B8C1"))
            painter.setFont(self.font_quote)
            qtext_rect = QRectF(bubble_x + 16, y + 22, bubble_w - 28, 16)
            painter.drawText(qtext_rect, Qt.AlignLeft | Qt.AlignVCenter, quoted_text)

            y_content = y + quote_h  # Nội dung chính bắt đầu sau khối quote
        else:
            y_content = y
        
        # 5. Vẽ Nội dung (Chữ/Ảnh)
        if data.get("type") == "text" and doc:
            painter.save()
            painter.translate(bubble_x + 12, y_content + 10)
            doc.drawContents(painter) # Họa sĩ vẽ lại bản text đã được bẻ gãy mượt mà
            painter.restore()
        elif data.get("type") == "image":
            offset = 0
            painter.drawPixmap(int(bubble_x + offset), int(y_content + offset), data["pixmap"])
            
        # 6. Vẽ Giờ
        if data.get("show_time"):
            painter.setPen(QColor("#D0D0D0") if is_me else QColor("#8A8D91"))
            painter.setFont(self.font_time)
            time_align = Qt.AlignRight if is_me else Qt.AlignLeft
            time_rect = QRectF(bubble_x + 12, y + bubble_h - 22, bubble_w - 24, 15)
            painter.drawText(time_rect, time_align, data["time"])
        
        painter.restore()

# 2. CỬA SỔ PHÒNG CHAT (CHÍNH)
class MainChatWindow(QWidget):
    """
    Cửa sổ trung tâm quản lý giao diện chính sau khi đăng nhập thành công.
    Quản lý luồng tương tác: Nhắn tin, chuyển phòng, thông báo, và giao diện danh sách.
    """
    def __init__(self, sock, nickname):
        super().__init__()
        self.sock = sock 
        self.nickname = nickname
        
        # 1. SỬA ĐƯỜNG DẪN TUYỆT ĐỐI CHO FILE UI PHÒNG CHAT
        import os
        from PySide6.QtUiTools import QUiLoader
        from PySide6.QtCore import QFile
        
        current_dir = os.path.dirname(os.path.abspath(__file__))
        ui_path = os.path.join(current_dir, "mainchatUI.ui")
        
        loader = QUiLoader()
        ui_file = QFile(ui_path) 
        if not ui_file.open(QFile.ReadOnly):
            print(f"Không thể mở file UI phòng chat: {ui_file.errorString()}")
            sys.exit(-1)
            
        self.ui = loader.load(ui_file)
        ui_file.close()

        from PySide6.QtWidgets import QVBoxLayout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(self.ui)

        # 2. KHỞI TẠO BẢNG VẼ QLISTWIDGET (CHUẨN ZALO)
        from PySide6.QtWidgets import QVBoxLayout

        self.ui.scroll_chat_history.setWidgetResizable(True)
        # Cấm tuyệt đối khung cuộn bên ngoài bật thanh cuộn ngang
        self.ui.scroll_chat_history.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        self.chat_layout = QVBoxLayout(self.ui.scrollAreaWidgetContents_2)
        self.chat_layout.setContentsMargins(0, 0, 0, 0)
        
        self.chat_list = QListWidget()
        self.chat_list.setStyleSheet("background-color: transparent; border: none;")
        self.chat_list.setSelectionMode(QListWidget.NoSelection) # Tắt hiệu ứng bôi xanh khi click
        self.chat_list.setVerticalScrollMode(QListWidget.ScrollPerPixel) # Cuộn mượt

        self.chat_list.setWordWrap(True)
        
        class ChatListDelegate(QStyledItemDelegate):
            def __init__(self, main_window, parent=None):
                super().__init__(parent)
                self.main = main_window
                self.font_name = QFont()
                self.font_name.setPointSize(12)
                self.font_name.setBold(True)
                self.font_badge = QFont()
                self.font_badge.setPointSize(10)
                self.font_badge.setItalic(True)

            def sizeHint(self, option, index):
                from PySide6.QtCore import QSize, Qt
                if index.data(Qt.UserRole) == "self_greeting":
                    return super().sizeHint(option, index)
                    
                target = index.data(Qt.DisplayRole)
                unread = getattr(self.main, "unread_counts", {}).get(target, 0)
                h = 50
                if unread > 0:
                    from PySide6.QtGui import QFontMetrics
                    fm = QFontMetrics(self.font_name)
                    name_w = fm.horizontalAdvance(target)
                    w = option.widget.viewport().width() if option.widget else option.rect.width()
                    if name_w > w - 120:
                        h += 20
                return QSize(option.rect.width(), h)

            def paint(self, painter, option, index):
                from PySide6.QtCore import Qt, QRectF
                from PySide6.QtGui import QColor, QFontMetrics, QPainter
                from PySide6.QtWidgets import QStyle
                
                painter.save()
                painter.setRenderHint(QPainter.Antialiasing)
                
                if option.state & QStyle.State_Selected:
                    painter.fillRect(option.rect, QColor("#1E6C93"))
                    
                if index.data(Qt.UserRole) == "self_greeting":
                    super().paint(painter, option, index)
                    painter.restore()
                    return
                    
                target = index.data(Qt.DisplayRole)
                unread = getattr(self.main, "unread_counts", {}).get(target, 0)
                
                rect = option.rect
                x = rect.x() + 10
                y = rect.y()
                w = rect.width() - 20
                h = rect.height()
                
                painter.setFont(self.font_name)
                if target in getattr(self.main, "my_groups", {}):
                    painter.setPen(QColor("#27ae60"))
                else:
                    painter.setPen(QColor("white"))
                
                if unread > 0:
                    badge_text = f"+{unread} tin nhắn mới"
                    fm_name = QFontMetrics(self.font_name)
                    name_w = fm_name.horizontalAdvance(target)
                    
                    fm_badge = QFontMetrics(self.font_badge)
                    badge_w = fm_badge.horizontalAdvance(badge_text)
                    
                    if name_w <= w - badge_w - 10:
                        painter.drawText(QRectF(x, y, w, h), Qt.AlignLeft | Qt.AlignVCenter, target)
                        painter.setFont(self.font_badge)
                        painter.setPen(QColor("#e74c3c"))
                        painter.drawText(QRectF(x, y, w, h), Qt.AlignRight | Qt.AlignVCenter, badge_text)
                    else:
                        elided_target = fm_name.elidedText(target, Qt.ElideRight, w)
                        painter.drawText(QRectF(x, y + 5, w, 20), Qt.AlignLeft, elided_target)
                        painter.setFont(self.font_badge)
                        painter.setPen(QColor("#e74c3c"))
                        painter.drawText(QRectF(x, y + 25, w, 20), Qt.AlignLeft, badge_text)
                else:
                    fm_name = QFontMetrics(self.font_name)
                    elided_target = fm_name.elidedText(target, Qt.ElideRight, w)
                    painter.drawText(QRectF(x, y, w, h), Qt.AlignLeft | Qt.AlignVCenter, elided_target)
                    
                painter.setPen(QColor("#3A4047"))
                painter.drawLine(rect.x() + 10, rect.bottom(), rect.right() - 10, rect.bottom())
                painter.restore()

        self.ui.list_chats.setItemDelegate(ChatListDelegate(self, self.ui.list_chats))

        self.chat_list.verticalScrollBar().setSingleStep(15)
        self.chat_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        self.chat_list.setResizeMode(QListWidget.Adjust)
        self.setMinimumWidth(500)
        
        # Giao phó việc vẽ cho Họa sĩ
        self.chat_delegate = ChatDelegate(self.chat_list)
        self.chat_list.setItemDelegate(self.chat_delegate)
        
        self.chat_layout.addWidget(self.chat_list)
        self.chat_list.itemClicked.connect(self._handle_chat_item_clicked)

        self.ui.btn_send.clicked.connect(self.send_message)
        self.ui.txt_input_message.returnPressed.connect(self.send_message)
        from Multimedia.tcp_image_transfer import ImageHandler
        self.image_handler = ImageHandler(self)
        self.ui.btn_camera.clicked.connect(self.image_handler.capture_and_send_image)
        if hasattr(self.ui, 'btn_image'):
            self.ui.btn_image.clicked.connect(self.image_handler.select_and_send_image)

        # --- TÍNH NĂNG: ẢNH ĐẠI DIỆN ---
        if hasattr(self.ui, 'btn_avatar'):
            import os
            import random
            from Multimedia.avatar import AvatarHandler
            self.avatar_handler = AvatarHandler(self)
            self.ui.btn_avatar.clicked.connect(self.avatar_handler.show_avatar_selection_dialog)
            
            avatar_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "images")
            self.available_avatars = []
            self.available_stickers = []
            if os.path.exists(avatar_dir):
                for f in os.listdir(avatar_dir):
                    if not f.endswith(".png"): continue
                    if f in ["logochat-removebg-preview.png", "ipchat-removebg-preview.png", "emo_9436509.png", "avtchat-removebg-preview.png"]:
                        continue
                    is_avatar = any(f.startswith(prefix) for prefix in ["avatar_", "napoleon_", "nun_", "rapper_", "superhero_", "vampire_", "woman_", "wrestler_"])
                    if is_avatar:
                        self.available_avatars.append(os.path.join(avatar_dir, f))
                    else:
                        self.available_stickers.append(os.path.join(avatar_dir, f))
            
            if self.available_avatars:
                chosen = random.choice(self.available_avatars)
                self.avatar_handler.set_user_avatar(chosen)
                self._pending_avatar_broadcast = chosen  # Broadcast sau khi receiver start
                
        if hasattr(self.ui, 'btn_sticker'):
            from Multimedia.emoji import StickerHandler
            self.sticker_handler = StickerHandler(self)
            self.ui.btn_sticker.clicked.connect(self.sticker_handler.show_sticker_dialog)
        # -------------------------------



        self.current_chat_type = "chat_all" # Mặc định là chat tổng
        self.current_chat_target = "all"
        self.chat_history_db = {"all": []}
        self.unread_counts = {}
        self.last_message_times = {}
        self.ui.list_chats.itemClicked.connect(self.switch_chat_room)

        # --- TÍNH NĂNG: GHIM HIGHLIGHT NICKNAME CỦA BẢN THÂN LÊN ĐẦU ---
        greeting_item = QListWidgetItem(f"🌟 Xin chào, {self.nickname}!")
        greeting_item.setBackground(QColor("#2C323A")) # Nền xám đen
        greeting_item.setForeground(QColor("#3498db")) # Chữ xanh dương nổi bật
        font = QFont()
        font.setBold(True)
        font.setPointSize(12)
        greeting_item.setFont(font)
        greeting_item.setData(Qt.UserRole, "self_greeting") # Đánh dấu cờ để không bị click nhầm
        greeting_item.setFlags(greeting_item.flags() & ~Qt.ItemIsSelectable) # Không cho phép focus/chọn
        self.ui.list_chats.addItem(greeting_item)
        # ---------------------------------------------------------------

        from Features.group_handler import GroupHandler
        self.group_handler = GroupHandler(self)

        from Features.group_handler import GroupHandler
        self.group_handler = GroupHandler(self)

        # Khởi chạy luồng nhận dữ liệu
        self.receiver = ReceiveThread(self.sock)
        self.receiver.message_received.connect(self.handle_incoming_message, Qt.QueuedConnection)
        self.receiver.message_received_ex.connect(self.handle_incoming_message, Qt.QueuedConnection)
        # ĐÃ XÓA DÒNG LỖI CỦA DISPLAY_MESSAGE Ở ĐÂY

        self.receiver.system_info_received.connect(self.show_system_msg, Qt.QueuedConnection)
        self.receiver.incoming_request.connect(self.handle_incoming_request, Qt.QueuedConnection)
        self.receiver.request_result.connect(self.handle_request_result, Qt.QueuedConnection)
        self.receiver.group_event.connect(self.group_handler.handle_group_event, Qt.QueuedConnection)
        self.receiver.avatar_updated.connect(self.avatar_handler.handle_avatar_updated, Qt.QueuedConnection)
        self.receiver.all_avatars_received.connect(self.avatar_handler.handle_all_avatars, Qt.QueuedConnection)
        self.receiver.unfriended_event.connect(self.handle_unfriended, Qt.QueuedConnection)
        self.receiver.group_member_event.connect(self.group_handler.handle_group_member_event, Qt.QueuedConnection)
        self.receiver.group_kicked_event.connect(self.group_handler.handle_group_kicked, Qt.QueuedConnection)
        self.receiver.new_join_request_event.connect(self.group_handler.handle_new_join_request, Qt.QueuedConnection)
        self.receiver.join_requests_list_event.connect(self.group_handler.handle_join_requests_list, Qt.QueuedConnection)
        self.receiver.join_request_approved_event.connect(self.group_handler.handle_join_request_approved, Qt.QueuedConnection)

        self.receiver.start()

        # Sau khi ReceiveThread start: gửi avatar của mình và xin avatar của người khác
        from PySide6.QtCore import QTimer
        if getattr(self, '_pending_avatar_broadcast', None):
            QTimer.singleShot(300, lambda: self.avatar_handler.broadcast_my_avatar(self._pending_avatar_broadcast))
        QTimer.singleShot(600, self.avatar_handler.request_all_avatars)

        
        self.ui.lbl_chat_title.setText(f"Chào mừng, {self.nickname}!")
        self.ui.txt_search.returnPressed.connect(self.send_connection_request)
        # --- KẾT NỐI NÚT TÌM KIẾM TIN NHẮN ---
        from Multimedia.message_search import SearchHandler
        self.search_handler = SearchHandler(self)
        if hasattr(self.ui, 'btn_search_chat'):
            self.ui.btn_search_chat.clicked.connect(self.search_handler.show_search_panel)
        self.ui.txt_search.setMaxLength(40)
        # ----------------------------
        
        # --- UI TÌM KIẾM TRONG TRÒ CHUYỆN (COL4) ---
        
        self.search_layout = QVBoxLayout(self.ui.page_2)
        self.search_layout.setContentsMargins(10, 20, 10, 10)
        
        self.lbl_search_title = QLabel("Tìm kiếm trong trò chuyện")
        self.lbl_search_title.setStyleSheet("color: white; font-size: 16px; font-weight: bold;")
        self.search_layout.addWidget(self.lbl_search_title)
        
        self.txt_local_search = QLineEdit()
        self.txt_local_search.setPlaceholderText("Nhập từ khóa...")
        self.txt_local_search.setStyleSheet("background:#2C323A; color:white; border-radius:8px; padding:8px;")
        self.search_layout.addWidget(self.txt_local_search)
        
        self.list_local_search = QListWidget()
        self.list_local_search.setStyleSheet("background:#2C323A; color:white; border:none; outline: 0;")
        self.search_layout.addWidget(self.list_local_search)
        
        # Gắn event search cục bộ
        self.txt_local_search.returnPressed.connect(self.search_handler.perform_local_search_ui)
        self.list_local_search.itemClicked.connect(self.search_handler.navigate_to_message) 
        if hasattr(self.ui, 'btn_create_group'):
            self.ui.btn_create_group.clicked.connect(self.group_handler.open_create_group_dialog)

        # Danh sách nhóm mà user đã tham gia (local)
        self.my_groups = {}  # {group_id: [members]}
        self.group_admins = {} # {group_id: admin}

        # --- TÍNH NĂNG: KHÓA CỨNG KÍCH THƯỚC BAN ĐẦU CHỈ HIỆN CỘT 1 & 2 ---
        self.ui.col3_mainchat.hide()
        self.ui.col4_info.hide()
        self.setFixedSize(425, 700) # Khóa chết kích thước (Vừa khít chiều ngang Cột 1 + Cột 2)
        # ------------------------------------------------------------------
        
        # CẬP NHẬT LẠI TRÍ NHỚ ĐỂ TƯƠNG THÍCH LIST WIDGET
        self.last_sender = None
        self.last_msg_time = None
        self.last_item = None
        self._window_unlocked = False  # Cờ để tránh gọi setWindowFlags nhiều lần

        # --- TÍNH NĂNG REPLY ---
        self.reply_to_data = None  # None = không đang reply
        from Multimedia.reply_forward import ReplyHandler
        self.reply_handler = ReplyHandler(self)
        
        # Right-click trên chat_list để chọn Reply
        self.chat_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.chat_list.customContextMenuRequested.connect(self.reply_handler._show_chat_context_menu)
        # -----------------------


        # --- KẾT NỐI NÚT SIDEBAR (btn_toggle_info) ---
        if hasattr(self.ui, 'btn_toggle_info'):
            self.ui.btn_toggle_info.clicked.connect(self._toggle_info_panel)
        # Ẩn col4 lúc khởi động (sẽ dùng overlay, không phải trong layout)
        if hasattr(self.ui, 'horizontalLayout'):
            self.ui.horizontalLayout.removeWidget(self.ui.col4_info)
        self.ui.col4_info.setParent(self.ui)
        self.ui.col4_info.hide()
        self._info_panel_visible = False

        if hasattr(self.ui, 'btn_info_block'):
            self.ui.btn_info_block.clicked.connect(self.handle_info_block_action)
        if hasattr(self.ui, 'btn_info_action'):
            self.ui.btn_info_action.clicked.connect(self.group_handler.open_create_group_from_private)
        if hasattr(self.ui, 'btn_info_members'):
            self.ui.btn_info_members.clicked.connect(self.group_handler.show_members_dialog)
        if hasattr(self.ui, 'btn_info_add_member'):
            self.ui.btn_info_add_member.clicked.connect(self.group_handler.show_add_member_dialog)
        if hasattr(self.ui, 'btn_info_requests'):
            self.ui.btn_info_requests.clicked.connect(self.group_handler.request_join_requests_list)

        # Căn giữa màn hình
        screen_geometry = QApplication.primaryScreen().geometry()
        x = (screen_geometry.width() - self.width()) // 2
        y = (screen_geometry.height() - self.height()) // 2
        self.move(x, y)

        # Cài đặt event filter để ẩn panel thông tin khi click ra ngoài
        QApplication.instance().installEventFilter(self)




    # ===================== REPLY FEATURE =====================


    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent, QRect
        from PySide6.QtGui import QMouseEvent
        if event.type() == QEvent.MouseButtonPress and getattr(self, '_info_panel_visible', False):
            if isinstance(event, QMouseEvent):
                pos = event.globalPosition().toPoint()
                
                col4 = self.ui.col4_info
                col4_global_pos = col4.mapToGlobal(col4.rect().topLeft())
                col4_rect = QRect(col4_global_pos, col4.rect().size())
                
                toggle_btn = getattr(self.ui, 'btn_toggle_info', None)
                if toggle_btn:
                    toggle_global_pos = toggle_btn.mapToGlobal(toggle_btn.rect().topLeft())
                    toggle_rect = QRect(toggle_global_pos, toggle_btn.rect().size())
                else:
                    toggle_rect = QRect(-1, -1, 0, 0)
                
                if not col4_rect.contains(pos) and not toggle_rect.contains(pos):
                    # Hide the panel
                    self.ui.col4_info.hide()
                    self._info_panel_visible = False
                    
        return super().eventFilter(obj, event)

    def _toggle_info_panel(self):
        """Hiện/ẩn cột 4 dưới dạng overlay đè lên cột 3."""
        if self._info_panel_visible and self.ui.stacked_col4.currentIndex() == 0:
            self.ui.col4_info.hide()
            self._info_panel_visible = False
        else:
            self.ui.stacked_col4.setCurrentIndex(0) # Đưa về trang Info
            self._reposition_col4_overlay()
            self.ui.col4_info.show()
            self.ui.col4_info.raise_()
            self._info_panel_visible = True

    def _reposition_col4_overlay(self):
        """Đặt col4 nằm đè lên góc phải của col3, kích thước bằng chiều cao cửa sổ."""
        col3 = self.ui.col3_mainchat
        col4 = self.ui.col4_info
        # Tính tọa độ trong không gian của QWidget cha (self.ui = Form widget)
        col3_pos = col3.mapTo(self.ui, col3.rect().topLeft())
        col4_w = 350
        col4_x = col3_pos.x() + col3.width() - col4_w
        col4.setParent(self.ui)
        col4.setGeometry(col4_x, col3_pos.y(), col4_w, col3.height())

    def _unlock_window(self):
        """
        Mở khóa cửa sổ — bỏ FixedSize (chỉ khóa lúc đăng nhập hoặc chưa chọn phòng).
        Ép HĐH khôi phục nút Maximize và cho phép kéo giãn toàn màn hình.
        """
        # Phải nới lỏng MaxSize TRƯỚC KHI setWindowFlags để HĐH nhận diện cửa sổ có thể resize
        self.setMinimumSize(870, 700)
        self.setMaximumSize(16777215, 16777215)
        self.ui.setMinimumSize(0, 0)
        self.ui.setMaximumSize(16777215, 16777215)
        
        # Chỉ set WindowFlags 1 lần duy nhất để tránh UI rebuild nhiều lần
        if not self._window_unlocked:
            from PySide6.QtCore import Qt as _Qt
            flags = (
                _Qt.Window
                | _Qt.WindowTitleHint
                | _Qt.WindowSystemMenuHint
                | _Qt.WindowMinimizeButtonHint
                | _Qt.WindowMaximizeButtonHint
                | _Qt.WindowCloseButtonHint
            )
            self.setWindowFlags(flags)
            self.showNormal()  # Cần showNormal để HĐH cập nhật lại title bar có nút Maximize
            self._window_unlocked = True
        if self.width() <= 425:
            self.resize(1000, 700)
            screen = QApplication.primaryScreen().geometry()
            self.move((screen.width() - self.width()) // 2,
                      (screen.height() - self.height()) // 2)
        self.ui.col3_mainchat.show()


    def send_message(self):
        content = self.ui.txt_input_message.text().strip()
        if not content: return

        # Linh hoạt tạo payload dựa trên loại chat đang chọn
        if self.current_chat_type == "chat_all":
            msg_dict = {"type": "chat_all", "sender": self.nickname, "content": content}

        elif self.current_chat_type == "chat_private":
            msg_dict = {"type": "chat_private", "sender": self.nickname,
                        "receiver": self.current_chat_target, "content": content}

        elif self.current_chat_type == "chat_group":
            msg_dict = {"type": "chat_group", "group_id": self.current_chat_target,
                        "sender": self.nickname, "content": content}

        # Đính kèm reply_to nếu đang trả lời ai đó
        if self.reply_to_data:
            msg_dict["reply_to"] = self.reply_to_data

        payload = json.dumps(msg_dict).encode('utf-8')
        header = struct.pack("!I", len(payload))

        try:
            self.sock.sendall(header + payload)
            # Tự in ra màn hình của mình (kèm reply_to nếu có)
            self.display_message("Tôi", content, reply_to=self.reply_to_data)

            # Lưu vào bộ nhớ tạm thời của phòng đó
            if self.current_chat_target not in self.chat_history_db:
                self.chat_history_db[self.current_chat_target] = []
            self.chat_history_db[self.current_chat_target].append(("Tôi", content))
            
            import time
            self.last_message_times[self.current_chat_target] = time.time()
            self.sort_chat_list()

            self.ui.txt_input_message.clear()
            if hasattr(self, "reply_handler"):
                self.reply_handler._cancel_reply()  # Ẩn thanh reply sau khi gửi
        except Exception as e:
            print("Lỗi gửi tin nhắn:", e)

    def _add_contact_to_list(self, name):
        """Thêm liên hệ vào danh sách chỉ khi chưa tồn tại — tránh hiển thị trùng."""
        for i in range(self.ui.list_chats.count()):
            if self.ui.list_chats.item(i).text() == name:
                return  # Đã có rồi, không thêm nữa
        self.ui.list_chats.addItem(name)

    def handle_incoming_message(self, sender, content, target_room, reply_to=None):
        """
        Nhận tin nhắn đến từ ReceiveThread. Lưu vào bộ nhớ cục bộ `chat_history_db`.
        Nếu người dùng đang mở đúng phòng này, vẽ lên màn hình.
        Nếu không, tăng số lượng tin nhắn chưa đọc (unread_counts).
        Cập nhật thời gian gửi và gọi `sort_chat_list()`.
        """
        import time
        # 1. Lưu tin nhắn vào bộ nhớ đệm của đúng phòng
        if target_room not in self.chat_history_db:
            self.chat_history_db[target_room] = []
            # Nếu có người mới nhắn tới, tự động thêm vào danh sách liên hệ bên trái
            self._add_contact_to_list(target_room)

        self.chat_history_db[target_room].append((sender, content))
        self.last_message_times[target_room] = time.time()

        # 2. Nếu người dùng đang mở đúng phòng đó, hiển thị luôn lên màn hình
        if self.current_chat_target == target_room:
            self.display_message(sender, content, reply_to=reply_to)
        else:
            self.unread_counts[target_room] = self.unread_counts.get(target_room, 0) + 1
            
        self.sort_chat_list()

    def sort_chat_list(self):
        """
        Sắp xếp lại danh sách trò chuyện (Cột 2) dựa trên `last_message_times`.
        Luôn giữ nguyên focus của item hiện tại sau khi sắp xếp.
        """
        current_item = self.ui.list_chats.currentItem()
        current_target = current_item.text() if current_item else None
        
        items = []
        for i in range(self.ui.list_chats.count() - 1, 0, -1):
            items.append(self.ui.list_chats.takeItem(i))
            
        items.sort(key=lambda it: self.last_message_times.get(it.text(), 0), reverse=True)
        
        target_item = None
        for item in items:
            self.ui.list_chats.addItem(item)
            if current_target and item.text() == current_target:
                target_item = item
                
        if target_item:
            self.ui.list_chats.setCurrentItem(target_item)

    def send_connection_request(self):
        target = self.ui.txt_search.text().strip()
        print(f"[CLIENT LOG] Bắt đầu gửi yêu cầu đến: {target}") # Theo dõi log
        
        if not target: return
        
        if target == self.nickname:
            QMessageBox.information(self, "Thông báo", "Đây là nickname của bạn!")
            self.ui.txt_search.clear()
            return
        
        reply = QMessageBox.question(self, "Xác nhận gửi yêu cầu", 
                                     f"Bạn muốn gửi yêu cầu kết nối tới '{target}'?",
                                     QMessageBox.Yes | QMessageBox.Cancel)
                                     
        # SỬA LỖI PYSIDE6 ENUM: Không import cục bộ nữa, so sánh thẳng bằng các Enum hợp lệ
        if reply != QMessageBox.Yes and reply != QMessageBox.StandardButton.Yes:
            print("[CLIENT LOG] Đã hủy gửi yêu cầu.")
            return
        
        msg_dict = {"type": "request_private", "sender": self.nickname, "target": target}
        payload = json.dumps(msg_dict).encode('utf-8')
        
        try:
            self.sock.sendall(struct.pack("!I", len(payload)) + payload)
            self.ui.txt_search.clear()
            print("[CLIENT LOG] Đã đẩy gói tin vào Socket thành công!")
            # Không hiện popup ở đây — server sẽ tự gửi phản hồi:
            # - Nếu đã là bạn: system_info "Bạn và X đã có thể nhắn tin."
            # - Nếu chưa: forward yêu cầu đến người kia, kết quả sẽ về qua request_result
        except Exception as e:
            print(f"[CLIENT LỖI] Không thể gửi qua Socket: {e}")

    def handle_incoming_request(self, _req_type, sender, target):
        # In ra terminal của Frontend để chắc chắn luồng này đã chạy
        print(f"[FRONTEND DEBUG] Nhận được yêu cầu {_req_type} từ: {sender}")

        if _req_type == "group":
            content = f"Người dùng '{sender}' muốn tham gia nhóm '{target}'. Chấp nhận?"
        else:
            content = f"Người dùng '{sender}' muốn kết nối nhắn tin với bạn. Chấp nhận?"

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Yêu cầu mới")
        msg_box.setText(content)
        msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg_box.setDefaultButton(QMessageBox.No)
        reply = msg_box.exec()

        status = "accept" if reply == QMessageBox.Yes or reply == QMessageBox.StandardButton.Yes else "decline"

        if _req_type == "group":
            msg_dict = {"type": "respond_group", "sender": self.nickname, "requester": sender, "group_id": target, "status": status}
        else:
            msg_dict = {"type": "respond_private", "sender": self.nickname, "requester": sender, "status": status}
            
        payload = json.dumps(msg_dict).encode('utf-8')

        try:
            self.sock.sendall(struct.pack("!I", len(payload)) + payload)
            if status == "accept" and _req_type != "group":
                # Khởi tạo chat_history_db trước để handle_incoming_message không thêm trùng
                if sender not in self.chat_history_db:
                    self.chat_history_db[sender] = []
                self._add_contact_to_list(sender)  # Thêm có kiểm tra trùng
                self._unlock_window()              # Mở khóa cửa sổ ngay sau khi kết nối
                
                # --- Tự động chuyển sang phòng chat ---
                from PySide6.QtCore import QTimer
                for i in range(self.ui.list_chats.count()):
                    if self.ui.list_chats.item(i).text() == sender:
                        target_item = self.ui.list_chats.item(i)
                        QTimer.singleShot(150, lambda: self.switch_chat_room(target_item))
                        break
        except Exception as e:
            print("Lỗi phản hồi yêu cầu:", e)

    def handle_request_result(self, target, msg, status):
        QMessageBox.information(self, "Phản hồi", msg)
        if status == "accept":
            # Khởi tạo chat_history_db trước để handle_incoming_message không thêm trùng
            if target not in self.chat_history_db:
                self.chat_history_db[target] = []
            self._add_contact_to_list(target)
            self._unlock_window()  # Mở khóa cửa sổ ngay khi kết nối thành công
            
            # --- Tự động chuyển sang phòng chat ---
            from PySide6.QtCore import QTimer
            for i in range(self.ui.list_chats.count()):
                if self.ui.list_chats.item(i).text() == target:
                    target_item = self.ui.list_chats.item(i)
                    QTimer.singleShot(150, lambda: self.switch_chat_room(target_item))
                    break

    def show_system_msg(self, msg):
        QMessageBox.warning(self, "Thông báo hệ thống", msg)

    def _update_col4_for_chat(self, chat_type, target):
        """Cập nhật tiêu đề, tên và các nút ở cột 4 theo loại chat."""
        ui = self.ui
        is_group = (chat_type == "chat_group")
        is_private = (chat_type == "chat_private")

        # Cập nhật tiêu đề cột 4
        if hasattr(ui, 'lbl_col4_title'):
            ui.lbl_col4_title.setText("Thông tin nhóm" if is_group else "Thông tin hội thoại")

        # Cập nhật tên đối tượng
        if hasattr(ui, 'lbl_info_name'):
            ui.lbl_info_name.setText(target)

        # Hiện avatar nếu là chat 1-1
        if hasattr(ui, 'lbl_info_avatar'):
            if is_private:
                avatar_pm = self.avatar_handler.get_sender_avatar_pixmap(target)
                if avatar_pm and not avatar_pm.isNull():
                    from PySide6.QtCore import Qt
                    avatar_pm = avatar_pm.scaled(100, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                ui.lbl_info_avatar.setPixmap(avatar_pm)
                ui.lbl_info_avatar.show()
            else:
                ui.lbl_info_avatar.hide()

        # Hiện/ẩn các nút theo loại chat:
        if hasattr(ui, 'btn_info_block'):
            ui.btn_info_block.setVisible(is_private or is_group)
            if hasattr(ui, 'lbl_btn_block'):
                ui.lbl_btn_block.setVisible(is_private or is_group)
                ui.lbl_btn_block.setText(
                    "<html><head/><body><p align=\"center\">Rời<br/>nhóm</p></body></html>" if is_group
                    else "<html><head/><body><p align=\"center\">Hủy kết<br/>bạn</p></body></html>"
                )
            
            if hasattr(ui, 'btn_info_action'):
                ui.btn_info_action.setVisible(is_private)
                if hasattr(ui, 'lbl_btn_action'):
                    ui.lbl_btn_action.setVisible(is_private)
                    
            if hasattr(ui, 'btn_info_members'):
                ui.btn_info_members.setVisible(is_group)
                if hasattr(ui, 'lbl_btn_members'):
                    ui.lbl_btn_members.setVisible(is_group)
                    
            if hasattr(ui, 'btn_info_add_member'):
                ui.btn_info_add_member.setVisible(is_group)
                if hasattr(ui, 'label_4'):
                    ui.label_4.setVisible(is_group)
                    
            is_admin = (is_group and self.group_admins.get(target) == self.nickname)
            if hasattr(ui, 'btn_info_requests'):
                ui.btn_info_requests.setVisible(is_admin)
                if hasattr(ui, 'lbl_btn_requests'):
                    ui.lbl_btn_requests.setVisible(is_admin)

            # Sắp xếp lại layout để căn giữa hoàn hảo
            try:
                parent_layout = ui.btn_info_block.parentWidget().layout()
                if parent_layout:
                    if not hasattr(self, '_original_col4_items'):
                        self._original_col4_items = []
                        while parent_layout.count():
                            self._original_col4_items.append(parent_layout.takeAt(0))
                    
                    while parent_layout.count():
                        parent_layout.takeAt(0)
                        
                    items = self._original_col4_items
                    if len(items) >= 7:
                        parent_layout.addItem(items[0])
                        
                        if is_private or is_group:
                            parent_layout.addItem(items[1])
                        if is_private:
                            parent_layout.addItem(items[2])
                        if is_group:
                            parent_layout.addItem(items[3])
                            parent_layout.addItem(items[4])
                        if is_admin:
                            parent_layout.addItem(items[5])
                            
                        parent_layout.addItem(items[6])
                        parent_layout.setSpacing(35)
            except Exception as e:
                print("Error updating col4 layout:", e)
                


    def _handle_chat_item_clicked(self, item):
        from PySide6.QtCore import Qt
        data = item.data(Qt.UserRole)
        if not data: return
        
        if data.get("type") == "image" and not data.get("is_sticker"):
            original_pixmap = data.get("original_pixmap")
            if original_pixmap and not original_pixmap.isNull():
                from Multimedia.image_viewer import ImageViewerDialog
                viewer = ImageViewerDialog(original_pixmap, self)
                viewer.exec()

    def switch_chat_room(self, item):
        """
        Người dùng bấm chọn phòng trò chuyện.
        - Xóa thông báo tin nhắn mới.
        - Dọn dẹp khung chat hiện tại.
        - Lấy lịch sử từ `chat_history_db` và vẽ lại ngay lập tức (không cần truy vấn server).
        """
        # --- TÍNH NĂNG: NGĂN CLICK VÀO LỜI CHÀO ---
        if item.data(Qt.UserRole) == "self_greeting":
            return # Bấm vào lời chào thì không làm gì cả
        
        self._unlock_window()
        
        target = item.text()
        self.unread_counts[target] = 0
        self.ui.list_chats.viewport().update() # Force redraw to hide badge

        self.ui.list_chats.setCurrentItem(item)

        target = item.text()
        self.current_chat_target = target

        if target == "all":
            self.current_chat_type = "chat_all"
            self.ui.lbl_chat_title.setText("Chat toàn Server")
        elif target in self.my_groups:
            self.current_chat_type = "chat_group"
            self.ui.lbl_chat_title.setText(f"👥 {target}  |  {len(self.my_groups.get(target, []))} thành viên")
        else:
            self.current_chat_type = "chat_private"
            self.ui.lbl_chat_title.setText(f"Đang chat với: {target}")

        # Cập nhật cột 4 theo loại chat
        self._update_col4_for_chat(self.current_chat_type, target)
        # Tái định vị nếu đang hiển thị
        if self._info_panel_visible:
            self._reposition_col4_overlay()

        self.chat_list.clear()
        self.last_sender = None
        self.last_msg_time = None

        if target in self.chat_history_db:
            for past_sender, past_content in self.chat_history_db[target]:
                self.display_message(past_sender, past_content)

    def display_system_message(self, content):
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtWidgets import QListWidgetItem
        data = {
            "type": "system",
            "tag_text": content
        }
        item = QListWidgetItem(self.chat_list)
        item.setData(Qt.UserRole, data)
        self.chat_list.addItem(item)
        QTimer.singleShot(50, self.chat_list.scrollToBottom)

    def display_message(self, sender, content, reply_to=None):
        if sender == "Hệ thống":
            self.display_system_message(content)
            return

        if content.startswith("[IMAGE_BASE64]"):
            import base64
            import numpy as np
            import cv2
            try:
                b64_str = content[14:]
                img_bytes = base64.b64decode(b64_str)
                buffer = np.frombuffer(img_bytes, dtype=np.uint8)
                frame = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
                if frame is not None:
                    self.image_handler.display_image(frame, is_sender=(sender == self.nickname or sender == "Tôi"), sender=sender)
                return
            except Exception as e:
                content = "[Ảnh bị lỗi hoặc không thể hiển thị]"

        if content.startswith("[STICKER_BASE64]"):
            import base64
            import numpy as np
            import cv2
            try:
                b64_str = content[16:]
                img_bytes = base64.b64decode(b64_str)
                buffer = np.frombuffer(img_bytes, dtype=np.uint8)
                frame = cv2.imdecode(buffer, cv2.IMREAD_UNCHANGED)
                if frame is not None:
                    self.image_handler.display_image(frame, is_sender=(sender == self.nickname or sender == "Tôi"), sender=sender, is_sticker=True)
                return
            except Exception as e:
                content = "[Sticker bị lỗi]"
        from datetime import datetime
        from PySide6.QtCore import Qt, QTimer

        current_time = datetime.now()
        display_time = current_time.strftime("%H:%M")
        
        # Tính toán Gom cụm
        show_time_tag = False
        if self.last_msg_time is None or (current_time - self.last_msg_time).total_seconds() > 1200:
            show_time_tag = True
            self.last_sender = None

        show_name = (sender != "Tôi" and sender != self.last_sender)

        # Giấu thời gian của tin nhắn trước nếu nhắn liên tục
        if sender == self.last_sender and not show_time_tag:
            if self.last_item is not None:
                prev_data = self.last_item.data(Qt.UserRole)
                prev_data["show_time"] = False
                self.last_item.setData(Qt.UserRole, prev_data)
        
        # Đóng gói dữ liệu gửi cho Họa sĩ
        data = {
            "type": "text",
            "sender": sender,
            "content": content,
            "time": display_time,
            "show_time": True,
            "show_time_tag": show_time_tag,
            "tag_text": current_time.strftime("%H:%M %d/%m/%Y"),
            "show_name": show_name,
            "chat_type": getattr(self, 'current_chat_type', 'chat_all'),
            "reply_to": reply_to,  # None nếu không phải reply
            "avatar_pixmap": self.avatar_handler.get_sender_avatar_pixmap(sender)
        }

        # Ném vào danh sách
        item = QListWidgetItem(self.chat_list)
        item.setData(Qt.UserRole, data)
        self.chat_list.addItem(item)
        
        # Cập nhật trí nhớ và cuộn
        self.last_sender = sender
        self.last_msg_time = current_time
        self.last_item = item
        QTimer.singleShot(50, self.chat_list.scrollToBottom)


    def resizeEvent(self, event):
        super().resizeEvent(event)
        current_width = self.width()

        # 1. Nếu đang ở trạng thái KHÓA (chưa chat với ai) -> Chỉ ép cứng Cột 1 và 2
        if current_width <= 450:
            self.ui.col3_mainchat.hide()
            self.ui.col2_chatlist.show()
            return

        # Khôi phục hiển thị cột 3 nếu màn hình lớn hơn 450
        # self.ui.col3_mainchat.show()

        # 2. Nếu đã mở khóa, xử lý cột 2 theo độ rộng (col4 luôn ở dạng overlay)
        if current_width >= 870:
            self.ui.col2_chatlist.show()
        else:
            self.ui.col2_chatlist.hide()

        # Cập nhật vị trí overlay col4 nếu đang hiển thị
        if getattr(self, '_info_panel_visible', False):
            self._reposition_col4_overlay()

        self.chat_list.doItemsLayout()


    def handle_unfriended(self, target):
        if target in self.chat_history_db:
            del self.chat_history_db[target]
        for i in range(self.ui.list_chats.count()):
            if self.ui.list_chats.item(i).text() == target:
                self.ui.list_chats.takeItem(i)
                break
        if self.current_chat_target == target:
            self.switch_chat_room(self.ui.list_chats.item(0))
            if getattr(self, '_info_panel_visible', False) and hasattr(self.ui, 'stacked_col4') and self.ui.stacked_col4.currentIndex() == 0:
                self.ui.col4_info.hide()
                self._info_panel_visible = False
        self.display_message("Hệ thống", f"Bạn và {target} đã hủy kết bạn.")

    def handle_info_block_action(self):
        if self.current_chat_type == "chat_private":
            from PySide6.QtWidgets import QMessageBox
            import json, struct
            target = self.current_chat_target
            reply = QMessageBox.question(self, "Xác nhận", f"Bạn có chắc chắn muốn hủy kết bạn với {target} không?")
            if reply == QMessageBox.Yes:
                msg = json.dumps({"type": "unfriend", "sender": self.nickname, "target": target}).encode('utf-8')
                self.sock.sendall(struct.pack("!I", len(msg)) + msg)
                self.handle_unfriended(target)
        elif self.current_chat_type == "chat_group":
            self.group_handler.leave_group()


class LoginWindow(QWidget): 
    """
    Cửa sổ Đăng Nhập đầu tiên. Quản lý việc kết nối Socket ban đầu.
    Giới hạn các input để tránh spam.
    """
    def __init__(self):
        super().__init__()
        
        import os
        from PySide6.QtUiTools import QUiLoader
        from PySide6.QtCore import QFile
        
        current_dir = os.path.dirname(os.path.abspath(__file__))
        ui_path = os.path.join(current_dir, "loginUI.ui")
        
        loader = QUiLoader()
        ui_file = QFile(ui_path) 
        
        if not ui_file.open(QFile.ReadOnly):
            print(f"Không thể mở file UI: {ui_file.errorString()}")
            sys.exit(-1)
            
        self.ui = loader.load(ui_file, self)
        ui_file.close()
        

        self.setFixedSize(831, 486)

        self.ui.label_readytochat.setText("")
        if hasattr(self.ui, 'lineEdit_inputnickname'):
            self.ui.lineEdit_inputnickname.setMaxLength(40)
        
        self.timer = QTimer(self)
        self.dot_count = 0
        self.timer.timeout.connect(self.update_dots)

        self.ui.pushButton_enter.clicked.connect(self.start_connecting)

    def start_connecting(self):
        self.dot_count = 0
        self.ui.label_readytochat.setText("Ready to connect")
        if hasattr(self.ui, "lbl_error_msg"):
            self.ui.lbl_error_msg.setText("")
        self.timer.start(500) 

        # Lấy thông tin từ giao diện để cấu hình kết nối
        ip = self.ui.lineEdit_ipnum.text()
        port = int(self.ui.lineEdit_portnum.text())
        nickname = self.ui.lineEdit_inputnickname.text().strip()

        if not nickname:
            self.ui.label_readytochat.setText("Vui lòng nhập biệt danh!")
            self.timer.stop()
            return
            
        user_data = {"type": "login", "nickname": nickname}
        
        # Khởi tạo và chạy luồng mạng
        self.worker = SocketWorker(host=ip, port=port, user_data=user_data)
        self.worker.login_success.connect(self.handle_login_success)
        self.worker.login_error.connect(self.handle_login_error)
        self.worker.start()

    def handle_login_success(self, sock, msg):
        self.timer.stop()
        self.ui.label_readytochat.setText(msg)
        
        # Lấy nickname để truyền sang phòng chat
        nickname = self.ui.lineEdit_inputnickname.text().strip()
        # Đóng cửa sổ login
        self.close()
        # Mở cửa sổ chat chính
        self.chat_window = MainChatWindow(sock, nickname) # Khởi tạo kèm tên người dùng
        self.chat_window.show()              # Hiển thị cửa sổ chat

    def handle_login_error(self, msg):
        self.timer.stop()
        if "Ten da ton tai" in msg or "Tên đã tồn tại" in msg:
            if hasattr(self.ui, "lbl_error_msg"):
                self.ui.lbl_error_msg.setText("Tên đã tồn tại, vui lòng nhập tên khác!")
                self.ui.label_readytochat.setText("")
            else:
                self.ui.label_readytochat.setText("Tên đã tồn tại, vui lòng nhập tên khác!")
        else:
            self.ui.label_readytochat.setText(msg)

    def update_dots(self):
        self.dot_count += 1
        if self.dot_count > 3:
            self.dot_count = 0
        
        dots = "." * self.dot_count
        self.ui.label_readytochat.setText(f"Ready to connect{dots}")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = LoginWindow()
    window.show()
    sys.exit(app.exec())
