import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
multimedia_dir = os.path.abspath(os.path.join(current_dir, '..', 'Multimedia'))

if multimedia_dir not in sys.path:
    sys.path.insert(0, multimedia_dir)

import json
import struct
import socket
import numpy as np
import cv2
import base64
from datetime import datetime
from integration import MessageSearchEngine, Message
from PySide6.QtWidgets import QApplication, QWidget, QMessageBox, QTextBrowser, QVBoxLayout, QLabel, QStyledItemDelegate, QListWidget, QListWidgetItem
from PySide6.QtUiTools import QUiLoader
from PySide6.QtGui import QImage, QPixmap, QPainter, QColor, QFont, QFontMetrics
from PySide6.QtCore import QFile, QTimer, QThread, Signal, Qt, QRectF, QSize

class SocketWorker(QThread):
    status_update = Signal(str)
    login_success = Signal(object, str)
    login_error = Signal(str)

    def __init__(self, host='127.0.0.1', port=9999, user_data=None):
        super().__init__()
        self.host = host
        self.port = port
        self.user_data = user_data or {"type": "login", "nickname": "Frontend_Dev"}

    def run(self):
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
    message_received = Signal(str, str, str) # Tín hiệu phát ra: (người_gửi, nội_dung, target_room)
    message_received_ex = Signal(str, str, str, object)  # kèm reply_to
    image_received = Signal(object)

    system_info_received = Signal(str)
    incoming_request = Signal(str, str, str) # req_type, sender, target (group_id/user)
    request_result = Signal(str, str, str)
    group_event = Signal(str, str, list)  # event_type (group_created/added_to_group), group_id, members

    def __init__(self, sock):
        super().__init__()
        self.sock = sock
        self._is_running = True

    def run(self):
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
                        members = data.get("members", [])
                        self.group_event.emit("group_created", group_id, members)
                    elif msg_type == "added_to_group":
                        group_id = data.get("group_id", "")
                        members = data.get("members", [])
                        self.group_event.emit("added_to_group", group_id, members)
                    elif msg_type == "system_info":
                        self.system_info_received.emit(data["msg"])
                    elif msg_type == "incoming_request":
                        self.incoming_request.emit(data["req_type"], data["sender"], data["target"])
                    elif msg_type == "request_result":
                        self.request_result.emit(data["target"], data["msg"], data["status"])

                except UnicodeDecodeError:
                    # Sử dụng logic giải mã từ OpenCV
                    buffer = np.frombuffer(payload, dtype=np.uint8)
                    frame = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
                    
                    if frame is not None:
                        self.image_received.emit(frame) # Phát tín hiệu ảnh ra ngoài
                    pass
            except Exception as e:
                print("[ReceiveThread] Lỗi nhận dữ liệu:", e)
                break

# LUỒNG CHỤP ẢNH TỪ WEBCAM (TRÁNH ĐƠ GIAO DIỆN)
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

class ChatDelegate(QStyledItemDelegate):
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
        data = index.data(Qt.UserRole)
        if not data: return QSize(0, 0)
        
        list_widget = option.widget
        w = list_widget.viewport().width() if list_widget else option.rect.width()
        
        max_bubble_w = min(500, w - 100) 
        
        h = 0
        if data.get("show_time_tag"): h += 40
        if data.get("show_name"): h += 25
            
        # Chiều cao khối quote (nếu có reply_to)
        if data.get("reply_to"):
            h += 38  # quote_name(16) + quote_text(16) + padding(6)
            
        if data.get("type") == "text":
            # --- DÙNG QTextDocument ĐỂ ÉP BẺ DÒNG MỌI CHUỖI DÀI ---
            from PySide6.QtGui import QTextDocument, QTextOption
            doc = QTextDocument()
            doc.setDefaultFont(self.font_text)
            opt = QTextOption()
            opt.setWrapMode(QTextOption.WrapAtWordBoundaryOrAnywhere) # Bẻ gãy cả code và URL
            doc.setDefaultTextOption(opt)
            doc.setPlainText(data["content"])
            doc.setTextWidth(max_bubble_w - 24)
            h += doc.size().height() + 20
        elif data.get("type") == "image":
            h += data["img_h"] + 20

        if data.get("show_time"): h += 18
        h += 6 
        return QSize(w, h)

    def paint(self, painter, option, index):
        data = index.data(Qt.UserRole)
        if not data: return

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing) 
        
        list_widget = option.widget
        w = list_widget.viewport().width() if list_widget else option.rect.width()
        y = option.rect.y()
        effective_w = w - 25
        
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
        if data.get("show_name"):
            painter.setPen(QColor("#8A8D91"))
            painter.setFont(self.font_name)
            name_rect = QRectF(25, y, effective_w - 50, 20)
            painter.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter, data["sender"])
            y += 25
            
        # 3. Đo đạc bong bóng
        max_bubble_w = min(500, w - 100)
        is_me = data["sender"] == "Tôi"
        
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
            doc.setPlainText(data["content"])
            doc.setTextWidth(max_bubble_w - 24)

            # Ép màu chữ thành màu trắng
            cursor = QTextCursor(doc)
            cursor.select(QTextCursor.Document)
            fmt = QTextCharFormat()
            fmt.setForeground(Qt.white)
            cursor.mergeCharFormat(fmt)

            # Lấy kích thước cực chuẩn
            bubble_w = doc.idealWidth() + 24
            bubble_h = doc.size().height() + 20 + quote_h
        else:
            bubble_w = data["img_w"] + 20
            bubble_h = data["img_h"] + 20 + quote_h
            
        if data.get("show_time"): bubble_h += 18
            
        bubble_x = w - bubble_w - 20 if is_me else 20
            
        # 4. Vẽ Background bong bóng bo góc
        bubble_rect = QRectF(bubble_x, y, bubble_w, bubble_h)
        painter.setBrush(QColor("#1E6C93") if is_me else QColor("#2C323A"))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(bubble_rect, 15, 15)

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
            painter.drawPixmap(int(bubble_x + 10), int(y_content + 10), data["pixmap"])
            
        # 6. Vẽ Giờ
        if data.get("show_time"):
            painter.setPen(QColor("#D0D0D0") if is_me else QColor("#8A8D91"))
            painter.setFont(self.font_time)
            time_align = Qt.AlignRight if is_me else Qt.AlignLeft
            time_rect = QRectF(bubble_x + 12, y + bubble_h - 22, bubble_w - 24, 15)
            painter.drawText(time_rect, time_align, data["time"])
        
        painter.restore()

# 2. CỬA SỔ PHÒNG CHAT (CHÍNH)
class ChatWindow(QWidget):
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

        self.chat_list.verticalScrollBar().setSingleStep(15)
        self.chat_list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        
        self.chat_list.setResizeMode(QListWidget.Adjust)
        # self.chat_list.setMinimumWidth(440)
        self.setMinimumWidth(500)
        
        # Giao phó việc vẽ cho Họa sĩ
        self.chat_delegate = ChatDelegate(self.chat_list)
        self.chat_list.setItemDelegate(self.chat_delegate)
        
        self.chat_layout.addWidget(self.chat_list)

        self.ui.btn_send.clicked.connect(self.send_message)
        self.ui.txt_input_message.returnPressed.connect(self.send_message)
        self.ui.btn_camera.clicked.connect(self.capture_and_send_image)
        if hasattr(self.ui, 'btn_image'):
            self.ui.btn_image.clicked.connect(self.select_and_send_image)


        self.current_chat_type = "chat_all" # Mặc định là chat tổng
        self.current_chat_target = "all"
        self.chat_history_db = {"all": []}
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
        self.ui.list_chats.addItem(greeting_item)
        # ---------------------------------------------------------------

        # Khởi chạy luồng nhận dữ liệu
        self.receiver = ReceiveThread(self.sock)
        self.receiver.message_received.connect(self.handle_incoming_message, Qt.QueuedConnection)
        self.receiver.message_received_ex.connect(self.handle_incoming_message, Qt.QueuedConnection)
        # ĐÃ XÓA DÒNG LỖI CỦA DISPLAY_MESSAGE Ở ĐÂY
        self.receiver.image_received.connect(self.display_image, Qt.QueuedConnection)
        self.receiver.system_info_received.connect(self.show_system_msg, Qt.QueuedConnection)
        self.receiver.incoming_request.connect(self.handle_incoming_request, Qt.QueuedConnection)
        self.receiver.request_result.connect(self.handle_request_result, Qt.QueuedConnection)
        self.receiver.group_event.connect(self.handle_group_event, Qt.QueuedConnection)
        self.receiver.start()

        
        self.ui.lbl_chat_title.setText(f"Chào mừng, {self.nickname}!")
        self.engine = MessageSearchEngine()
        self.msg_counter = 0 
        self.ui.txt_search.textChanged.connect(self.perform_global_search)
        self.ui.txt_search.returnPressed.connect(self.send_connection_request) 
        self.ui.btn_search_chat.clicked.connect(self.show_local_search_input) 
        if hasattr(self.ui, 'btn_create_group'):
            self.ui.btn_create_group.clicked.connect(self.open_create_group_dialog)

        # Danh sách nhóm mà user đã tham gia (local)
        self.my_groups = {}  # {group_id: [members]}

        # --- TÍNH NĂNG: KHÓA CỨNG KÍCH THƯỚC BAN ĐẦU CHỈ HIỆN CỘT 1 & 2 ---
        self.ui.col3_mainchat.hide()
        self.ui.col4_info.hide()
        self.setFixedSize(425, 700) # Khóa chết kích thước (Vừa khít chiều ngang Cột 1 + Cột 2)
        # (Em NHỚ XÓA dòng self.resize(1000, 700) cũ ở tít phía dưới __init__ đi nhé)
        # ------------------------------------------------------------------
        
        # CẬP NHẬT LẠI TRÍ NHỚ ĐỂ TƯƠNG THÍCH LIST WIDGET
        self.last_sender = None
        self.last_msg_time = None
        self.last_item = None
        self._window_unlocked = False  # Cờ để tránh gọi setWindowFlags nhiều lần

        # --- TÍNH NĂNG REPLY ---
        self.reply_to_data = None  # None = không đang reply
        self._setup_reply_bar()
        # -----------------------

        # Right-click trên chat_list để chọn Reply
        self.chat_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.chat_list.customContextMenuRequested.connect(self._show_chat_context_menu)

        # Left-click để nhảy về tin gốc khi đang xem reply
        self.chat_list.mousePressEvent = self._chat_list_mouse_press

        self.setup_dynamic_tabs()
        
        # Căn giữa màn hình
        screen_geometry = QApplication.primaryScreen().geometry()
        x = (screen_geometry.width() - self.width()) // 2
        y = (screen_geometry.height() - self.height()) // 2
        self.move(x, y)



    def setup_dynamic_tabs(self):
        from PySide6.QtWidgets import QTabWidget, QListWidget

        # Khởi tạo QTabWidget mới hoàn toàn bằng mã Python
        self.tab_widget = QTabWidget()
        self.tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: none;
                background-color: #22262B;
            }
            QTabBar::tab {
                background-color: #1E1F20;
                color: #8A8D91;
                padding: 8px 16px;
                border: none;
                font-size: 13px;
                font-weight: 500;
            }
            QTabBar::tab:selected {
                background-color: #22262B;
                color: #ffffff;
                border-bottom: 2px solid #3498db;
            }
            QTabBar::tab:hover {
                color: #ffffff;
                background-color: rgba(255, 255, 255, 0.05);
            }
        """)

        # Tạo các QListWidget độc lập cho dữ liệu TÌM KIẾM
        self.list_all = QListWidget()                
        self.list_contacts = QListWidget()           
        self.list_messages = QListWidget()           

        list_style = "background-color: transparent; color: white; border: none; font-size: 13px;"
        self.list_all.setStyleSheet(list_style) 
        self.list_contacts.setStyleSheet(list_style)
        self.list_messages.setStyleSheet(list_style)

        # Thêm các List tương ứng vào từng trang Tab
        self.tab_widget.addTab(self.list_all, "Tất cả")
        self.tab_widget.addTab(self.list_contacts, "Liên hệ")
        self.tab_widget.addTab(self.list_messages, "Tin nhắn")

        # Đưa QTabWidget vào layout đứng của Cột 2
        self.ui.verticalLayout_2.addWidget(self.tab_widget)

        # MẶC ĐỊNH ẨN THANH TAB KHI MỚI KHỞI ĐỘNG
        self.tab_widget.hide()
        # ĐÃ XÓA TOÀN BỘ PHẦN CODE TRÙNG LẶP GÂY XUNG ĐỘT LUỒNG TẠI ĐÂY


    # ===================== REPLY FEATURE =====================
    def _setup_reply_bar(self):
        """Tạo thanh preview reply phía trên ô nhập tin nhắn (ẩn mặc định)."""
        from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton

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
        col3_layout = self.ui.col3_mainchat.layout()
        col3_layout.insertWidget(col3_layout.count() - 1, self.reply_bar)
        self.reply_bar.hide()

    def _show_chat_context_menu(self, pos):
        """Hiển thị menu chuột phải trên danh sách tin nhắn."""
        from PySide6.QtWidgets import QMenu
        item = self.chat_list.itemAt(pos)
        if not item:
            return
        data = item.data(Qt.UserRole)
        if not data or data.get("type") not in ("text", "image"):
            return
        menu = QMenu(self)
        menu.setStyleSheet("""
            QMenu { background:#2C323A; color:white; border:1px solid #444;
                    border-radius:6px; padding:4px; }
            QMenu::item { padding:6px 20px; border-radius:4px; }
            QMenu::item:selected { background:#3498db; }
        """)
        reply_action = menu.addAction("↩  Trả lời tin nhắn này")
        action = menu.exec(self.chat_list.viewport().mapToGlobal(pos))
        if action == reply_action:
            self._start_reply(data)

    def _start_reply(self, msg_data):
        """Lưu tin nhắn cần reply và hiện thanh preview."""
        self.reply_to_data = {
            "sender": msg_data["sender"],
            "content": msg_data.get("content", "[Ảnh]")
        }
        preview = self.reply_to_data["content"]
        if len(preview) > 55:
            preview = preview[:52] + "..."
        self.reply_preview_lbl.setText(
            f"<b style='color:#3498db'>{self.reply_to_data['sender']}</b>: {preview}"
        )
        self.reply_bar.show()
        self.ui.txt_input_message.setFocus()

    def _cancel_reply(self):
        """Hủy trả lời — ẩn thanh preview và xóa state."""
        self.reply_to_data = None
        self.reply_bar.hide()

    def _chat_list_mouse_press(self, event):
        """Xử lý click vào tin nhắn — nếu click trúng quote reply thì nhảy về tin gốc."""
        from PySide6.QtWidgets import QAbstractItemView, QListWidget as _QLW

        # Gọi xử lý mặc định trước
        super(_QLW, self.chat_list).mousePressEvent(event)

        item = self.chat_list.itemAt(event.position().toPoint())
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

        item_rect = self.chat_list.visualItemRect(item)
        click_y = event.position().y() - item_rect.y()

        # Quote block cao 38px, bắt đầu tại y_offset+6
        if y_offset + 6 <= click_y <= y_offset + 44:
            reply_to = data["reply_to"]
            target_sender = reply_to.get("sender", "")
            target_content = reply_to.get("content", "")

            # Tìm tin gốc từ dưới lên
            for i in range(self.chat_list.count() - 1, -1, -1):
                other = self.chat_list.item(i)
                od = other.data(Qt.UserRole)
                if not od or not isinstance(od, dict) or od.get("type") != "text":
                    continue
                s = od.get("sender", "")
                # So sánh sender ("Tôi" ⟷ nickname)
                match_sender = (
                    s == target_sender
                    or (s == "Tôi" and target_sender == self.nickname)
                    or (s == self.nickname and target_sender == "Tôi")
                )
                if match_sender and od.get("content") == target_content:
                    self.chat_list.scrollToItem(other, QAbstractItemView.PositionAtCenter)
                    self.chat_list.setCurrentItem(other)
                    break

    def _unlock_window(self):
        """Mở khóa cửa sổ — bỏ FixedSize, hiện nút toàn màn hình, giãn kích thước."""
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
            self.show()  # setWindowFlags ẩn cửa sổ, cần show() lại
            self._window_unlocked = True

        self.setMinimumSize(870, 700)
        self.setMaximumSize(16777215, 16777215)
        if self.width() <= 425:
            self.resize(1000, 700)
            # Căn giữa màn hình sau khi giãn
            screen = QApplication.primaryScreen().geometry()
            self.move((screen.width() - self.width()) // 2,
                      (screen.height() - self.height()) // 2)
        self.ui.col3_mainchat.show()

    # --- THÊM 2 HÀM TÌM KIẾM CỤC BỘ CHO CỘT 3 VÀO ĐÂY ---

    def show_local_search_input(self):
        from PySide6.QtWidgets import QInputDialog
        keyword, ok = QInputDialog.getText(self, "Tìm kiếm cục bộ", "Nhập từ khóa cần tìm trong đoạn chat này:")
        if ok and keyword.strip():
            self.perform_local_search(keyword.strip())

    def perform_local_search(self, keyword):
        from integration import highlight_for_qt
        current_room = self.ui.lbl_chat_title.text()
        
        all_results = self.engine.search(keyword)
        # Nếu chưa chia phòng, có thể bỏ qua lọc theo current_room tạm thời
        # local_results = [r for r in all_results if r.message.room == current_room]
        local_results = all_results 
        
        self.chat_browser.append("<hr>")
        self.chat_browser.append(f"<div style='color: #f1c40f;'><b>🔍 KẾT QUẢ TÌM KIẾM TRONG ĐOẠN CHAT: '{keyword}'</b></div>")
        
        for r in local_results:
            html_content = highlight_for_qt(r.message.content, r.match_positions)
            self.chat_browser.append(f"<b>{r.message.sender}:</b> {html_content}")
        
        self.chat_browser.append("<hr>")


    def perform_global_search(self, text):
        keyword = text.strip()
        
        # Xóa sạch kết quả tìm kiếm cũ ở các tab trước khi nạp data mới
        self.list_all.clear()
        self.list_contacts.clear()
        self.list_messages.clear()

        # TRƯỜNG HỢP Ô TÌM KIẾM TRỐNG: Ẩn thanh Tab tìm kiếm, hiện lại danh sách chat gốc ban đầu
        if not keyword:
            self.tab_widget.hide()
            self.ui.list_chats.show()
            return

        # TRƯỜNG HỢP CÓ TỪ KHÓA: Ẩn danh sách chat gốc, bật thanh Tab kết quả tìm kiếm lên
        self.ui.list_chats.hide()
        self.tab_widget.show()

        # --- LUỒNG 1: TÌM KIẾM LIÊN HỆ ---
        sample_contacts = ["Lê Trần Hiền", "Bùi Minh Hiếu", "Trung Hiếu", "Vũ Thị Thu Hiền", "Tấn Hiệp", "Công Hiếu"]
        
        for contact in sample_contacts:
            if keyword.lower() in contact.lower():
                self.list_contacts.addItem(contact)
                self.list_all.addItem(f"[Liên hệ] {contact}")

        # --- LUỒNG 2: TÌM KIẾM TIN NHẮN (Gọi Engine) ---
        message_results = self.engine.search(keyword)
        
        for r in message_results:
            msg_display = f"{r.message.sender}: {r.message.content}"
            self.list_messages.addItem(msg_display)
            self.list_all.addItem(f"[Tin nhắn] {msg_display}")

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

            self.ui.txt_input_message.clear()
            self._cancel_reply()  # Ẩn thanh reply sau khi gửi
        except Exception as e:
            print("Lỗi gửi tin nhắn:", e)

    def _add_contact_to_list(self, name):
        """Thêm liên hệ vào danh sách chỉ khi chưa tồn tại — tránh hiển thị trùng."""
        for i in range(self.ui.list_chats.count()):
            if self.ui.list_chats.item(i).text() == name:
                return  # Đã có rồi, không thêm nữa
        self.ui.list_chats.addItem(name)

    def handle_incoming_message(self, sender, content, target_room, reply_to=None):
        # 1. Lưu tin nhắn vào bộ nhớ đệm của đúng phòng
        if target_room not in self.chat_history_db:
            self.chat_history_db[target_room] = []
            # Nếu có người mới nhắn tới, tự động thêm vào danh sách liên hệ bên trái
            self._add_contact_to_list(target_room)

        self.chat_history_db[target_room].append((sender, content))

        # 2. Nếu người dùng đang mở đúng phòng đó, hiển thị luôn lên màn hình
        if self.current_chat_target == target_room:
            self.display_message(sender, content, reply_to=reply_to)

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

    def open_create_group_dialog(self):
        from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                                       QLabel, QLineEdit, QListWidget,
                                       QPushButton, QListWidgetItem, QAbstractItemView)

        # Lấy danh sách bạn bè hiện có trong list_chats (bỏ "all" và các nhóm)
        friends = []
        for i in range(self.ui.list_chats.count()):
            it = self.ui.list_chats.item(i)
            text = it.text()
            if text and text != "all" and text not in self.my_groups and it.data(Qt.UserRole) != "self_greeting":
                friends.append(text)

        if len(friends) == 0:
            QMessageBox.information(self, "Thông báo", "Bạn cần có ít nhất 1 liên hệ để tạo nhóm!")
            return

        dlg = QDialog(self)
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
        name_edit.setPlaceholderText("Nhập tên nhóm...")
        layout.addWidget(name_edit)

        layout.addWidget(QLabel("Chọn thành viên (giữ Ctrl để chọn nhiều):"))
        member_list = QListWidget()
        member_list.setSelectionMode(QAbstractItemView.MultiSelection)
        for f in friends:
            member_list.addItem(QListWidgetItem(f))
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
                self.sock.sendall(struct.pack("!I", len(payload)) + payload)
                dlg.accept()
            except Exception as e:
                QMessageBox.critical(dlg, "Lỗi", f"Không thể gửi: {e}")

        btn_cancel.clicked.connect(dlg.reject)
        btn_create.clicked.connect(do_create)
        dlg.exec()

    def handle_group_event(self, event_type, group_id, members):
        """Xử lý khi tạo nhóm xong hoặc được thêm vào nhóm."""
        # Lưu nhóm vào bộ nhớ
        self.my_groups[group_id] = members
        if group_id not in self.chat_history_db:
            self.chat_history_db[group_id] = []

        # Thêm vào danh sách chat với biểu tượng nhóm
        target_item = None
        for i in range(self.ui.list_chats.count()):
            if self.ui.list_chats.item(i).text() == group_id:
                target_item = self.ui.list_chats.item(i)
                break
        if target_item is None:
            target_item = QListWidgetItem(f"{group_id}")
            target_item.setForeground(QColor("#2ecc71"))
            target_item.setData(Qt.UserRole, "group")
            self.ui.list_chats.addItem(target_item)

        self._unlock_window()

        # Dùng QTimer để đợi UI ổn định rồi mới mở phòng chat nhóm
        from PySide6.QtCore import QTimer
        if target_item:
            QTimer.singleShot(150, lambda: self.switch_chat_room(target_item))


    def handle_incoming_request(self, req_type, sender, target):
        # In ra terminal của Frontend để chắc chắn luồng này đã chạy
        print(f"[FRONTEND DEBUG] Nhận được yêu cầu kết bạn từ: {sender}")

        content = f"Người dùng '{sender}' muốn kết nối nhắn tin với bạn. Chấp nhận?"

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("Yêu cầu mới")
        msg_box.setText(content)
        msg_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        msg_box.setDefaultButton(QMessageBox.No)
        reply = msg_box.exec()

        status = "accept" if reply == QMessageBox.Yes or reply == QMessageBox.StandardButton.Yes else "decline"

        msg_dict = {"type": "respond_private", "sender": self.nickname, "requester": sender, "status": status}
        payload = json.dumps(msg_dict).encode('utf-8')

        try:
            self.sock.sendall(struct.pack("!I", len(payload)) + payload)
            if status == "accept":
                # Khởi tạo chat_history_db trước để handle_incoming_message không thêm trùng
                if sender not in self.chat_history_db:
                    self.chat_history_db[sender] = []
                self._add_contact_to_list(sender)  # Thêm có kiểm tra trùng
                self._unlock_window()              # Mở khóa cửa sổ ngay sau khi kết nối
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

    def show_system_msg(self, msg):
        QMessageBox.warning(self, "Thông báo hệ thống", msg)

    def switch_chat_room(self, item):
        # --- TÍNH NĂNG: NGĂN CLICK VÀO LỜI CHÀO ---
        if item.data(Qt.UserRole) == "self_greeting":
            return

        self._unlock_window()

        target = item.text()
        self.current_chat_target = target

        if target == "all":
            self.current_chat_type = "chat_all"
            self.ui.lbl_chat_title.setText("Chat toàn Server")
        elif target in self.my_groups:
            self.current_chat_type = "chat_group"
            members_str = ", ".join(self.my_groups[target])
            self.ui.lbl_chat_title.setText(f"👥 {target}  |  {members_str}")
        else:
            self.current_chat_type = "chat_private"
            self.ui.lbl_chat_title.setText(f"Đang chat với: {target}")

        self.chat_list.clear()
        self.last_sender = None
        self.last_msg_time = None

        if target in self.chat_history_db:
            for past_sender, past_content in self.chat_history_db[target]:
                self.display_message(past_sender, past_content)

    def display_message(self, sender, content, reply_to=None):
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
                    self.display_image(frame, is_sender=(sender == self.nickname or sender == "Tôi"), sender=sender)
                return
            except Exception as e:
                content = "[Ảnh bị lỗi hoặc không thể hiển thị]"

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
            "reply_to": reply_to  # None nếu không phải reply
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

        # Lưu Database
        self.msg_counter += 1
        full_timestamp = current_time.strftime("%H:%M:%S")
        from integration import Message
        msg_obj = Message(msg_id=self.msg_counter, sender=sender, content=content, timestamp=full_timestamp)
        self.engine.add_message(msg_obj)


    def display_image(self, frame, is_sender=False, sender=None):
        import cv2
        from PySide6.QtGui import QImage, QPixmap
        from PySide6.QtCore import Qt, QTimer
        from datetime import datetime

        if sender is None:
            sender = "Tôi" if is_sender else "Người khác"
        elif is_sender:
            sender = "Tôi"

        current_time = datetime.now()
        display_time = current_time.strftime("%H:%M")

        # Tính toán Gom cụm
        show_time_tag = False
        if self.last_msg_time is None or (current_time - self.last_msg_time).total_seconds() > 1200:
            show_time_tag = True
            self.last_sender = None

        show_name = (sender != "Tôi" and sender != self.last_sender)

        if sender == self.last_sender and not show_time_tag:
            if self.last_item is not None:
                prev_data = self.last_item.data(Qt.UserRole)
                prev_data["show_time"] = False
                self.last_item.setData(Qt.UserRole, prev_data)

        # Xử lý ảnh
        rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb_image.shape
        qt_image = QImage(rgb_image.data, w, h, ch * w, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qt_image)
        
        if pixmap.width() > 250:
            pixmap = pixmap.scaledToWidth(250, Qt.SmoothTransformation)

        # Đóng gói dữ liệu ảnh
        data = {
            "type": "image",
            "sender": sender,
            "pixmap": pixmap,
            "img_w": pixmap.width(),
            "img_h": pixmap.height(),
            "time": display_time,
            "show_time": True,
            "show_time_tag": show_time_tag,
            "tag_text": current_time.strftime("%H:%M %d/%m/%Y"),
            "show_name": show_name
        }

        item = QListWidgetItem(self.chat_list)
        item.setData(Qt.UserRole, data)
        self.chat_list.addItem(item)
        
        # Cập nhật trí nhớ và cuộn
        self.last_sender = sender
        self.last_msg_time = current_time
        self.last_item = item
        QTimer.singleShot(50, self.chat_list.scrollToBottom)

    def perform_search(self):
        # 1. Lấy từ khóa người dùng nhập
        keyword = self.ui.txt_search.text().strip()
        
        if not keyword:
            self.display_message("Hệ thống", "Vui lòng nhập từ khóa vào ô tìm kiếm!")
            return

        # 2. Gọi hàm tìm kiếm của Tiến, trả về danh sách HTML đã bôi vàng
        results_html = self.engine.get_qt_html_results(keyword)
        
        # 3. Hiển thị kết quả ra màn hình (ngăn cách bằng đường kẻ <hr>)
        self.chat_browser.append("<hr>")
        self.chat_browser.append(f"<div style='color: #f1c40f;'><b>🔍 KẾT QUẢ TÌM KIẾM CHO: '{keyword}' ({len(results_html)} kết quả)</b></div>")
        
        if len(results_html) == 0:
            self.chat_browser.append("<i>Không tìm thấy tin nhắn nào khớp.</i>")
        else:
            for html_line in results_html:
                self.chat_browser.append(html_line)
                
        self.chat_browser.append("<hr>")

    def capture_and_send_image(self):
        # Vô hiệu hóa nút tạm thời để tránh click liên tục
        self.ui.btn_camera.setEnabled(False)
        self.display_message("Hệ thống", "Đang mở camera chụp ảnh...")
        
        # Khởi chạy luồng camera
        self.camera_thread = CameraThread()
        self.camera_thread.image_encoded.connect(self.send_image_bytes)
        self.camera_thread.error_occurred.connect(lambda err: self.display_message("Lỗi", err))
        self.camera_thread.finished.connect(lambda: self.ui.btn_camera.setEnabled(True))
        self.camera_thread.start()

    def send_image_bytes(self, img_bytes):
        import base64
        import json
        import struct

        try:
            # Mã hóa ảnh sang Base64
            b64_str = base64.b64encode(img_bytes).decode('utf-8')
            content = f"[IMAGE_BASE64]{b64_str}"

            # Đóng gói JSON tùy theo phòng chat
            if self.current_chat_type == "chat_all":
                msg_dict = {"type": "chat_all", "sender": self.nickname, "content": content}
            elif self.current_chat_type == "chat_private":
                msg_dict = {"type": "chat_private", "sender": self.nickname, "receiver": self.current_chat_target, "content": content}
            elif self.current_chat_type == "chat_group":
                msg_dict = {"type": "chat_group", "group_id": self.current_chat_target, "sender": self.nickname, "content": content}

            if getattr(self, 'reply_to_data', None):
                msg_dict["reply_to"] = self.reply_to_data

            payload = json.dumps(msg_dict).encode('utf-8')
            header = struct.pack("!I", len(payload))
            
            self.sock.sendall(header + payload)
            print(f"[LOG] Đã gửi ảnh thành công dưới dạng Base64 (Dung lượng payload: {len(payload)} bytes)")
            
            # Hiển thị ảnh cho chính mình
            import numpy as np
            import cv2
            buffer = np.frombuffer(img_bytes, dtype=np.uint8)
            frame = cv2.imdecode(buffer, cv2.IMREAD_COLOR)
            self.display_image(frame, is_sender=True, sender="Tôi") 
            
        except Exception as e:
            print("Lỗi gửi ảnh:", e)
            self.display_message("Lỗi", "Không thể gửi ảnh!")


    def select_and_send_image(self):
        from PySide6.QtWidgets import QFileDialog
        import cv2
        import numpy as np

        file_path, _ = QFileDialog.getOpenFileName(self, "Chọn ảnh", "", "Image Files (*.png *.jpg *.jpeg *.bmp)")
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
                self.display_message("Lỗi", "Định dạng ảnh không hợp lệ hoặc file bị hỏng.")
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
                self.display_message("Lỗi", "Không thể xử lý ảnh.")
                return

            img_bytes = buffer.tobytes()
            
            # Gửi thông qua hàm có sẵn
            self.send_image_bytes(img_bytes)

        except Exception as e:
            self.display_message("Lỗi", f"Không thể tải ảnh: {str(e)}")


    def resizeEvent(self, event):
        super().resizeEvent(event)
        current_width = self.width()

        # 1. Nếu đang ở trạng thái KHÓA (chưa chat với ai) -> Chỉ ép cứng Cột 1 và 2
        if current_width <= 450:
            self.ui.col3_mainchat.hide()
            self.ui.col4_info.hide()
            self.ui.col2_chatlist.show()
            return

        # 2. Nếu đã mở khóa, xử lý ẩn/hiện cột 4 và cột 2 theo độ rộng
        if current_width >= 1220:
            self.ui.col4_info.show()
            self.ui.col2_chatlist.show()
        elif current_width >= 870:
            self.ui.col4_info.hide()
            self.ui.col2_chatlist.show()
        else:
            self.ui.col4_info.hide()
            self.ui.col2_chatlist.hide() 
            
        self.chat_list.doItemsLayout()

class LoginWindow(QWidget): 
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
        
        self.hide()                          
        self.chat_window = ChatWindow(sock, nickname) # Khởi tạo kèm tên người dùng
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
