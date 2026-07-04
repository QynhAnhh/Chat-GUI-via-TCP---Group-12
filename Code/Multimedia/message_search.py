from PySide6.QtWidgets import QListWidgetItem, QLabel, QAbstractItemView
from PySide6.QtCore import Qt, QSize

class SearchHandler:
    def __init__(self, main_window):
        self.main = main_window

    def show_search_panel(self):
        """Mở panel tìm kiếm ở cột 4."""
        if getattr(self.main, '_info_panel_visible', False) and self.main.ui.stacked_col4.currentIndex() == 1:
            self.main.ui.col4_info.hide()
            self.main._info_panel_visible = False
        else:
            self.main.ui.stacked_col4.setCurrentIndex(1) # Chuyển sang trang Search
            self.main._reposition_col4_overlay()
            self.main.ui.col4_info.show()
            self.main.ui.col4_info.raise_()
            self.main._info_panel_visible = True
            self.main.txt_local_search.setFocus()
            self.main.txt_local_search.selectAll()

    def perform_local_search_ui(self):
        keyword = self.main.txt_local_search.text().strip().lower()
        self.main.list_local_search.clear()
        
        if not keyword:
            return
            
        target = self.main.current_chat_target
        if target not in self.main.chat_history_db:
            return
            
        history = self.main.chat_history_db[target]
        for sender, content in history:
            # Bỏ qua tin nhắn hệ thống, ảnh và sticker
            if sender == "Hệ thống" or content.startswith("[IMAGE_BASE64]") or content.startswith("[STICKER_BASE64]"):
                continue
                
            idx = content.lower().find(keyword)
            if idx != -1:
                # Tạo snippet
                start = max(0, idx - 30)
                end = min(len(content), idx + len(keyword) + 30)
                
                snippet = content[start:end]
                if start > 0: snippet = "..." + snippet
                if end < len(content): snippet = snippet + "..."
                
                # Format highlight (đảm bảo giữ nguyên chữ gốc dù từ khóa search là chữ thường)
                original_kw = content[idx:idx+len(keyword)]
                highlighted_snippet = snippet.replace(original_kw, f"<b style='color:#f1c40f'>{original_kw}</b>")
                
                html_text = f"""
                <div style='color: white;'>
                    <div style='font-weight: bold; color: #3498db; margin-bottom: 3px;'>{sender}</div>
                    <div style='color: #B0B8C1; font-size: 13px;'>{highlighted_snippet}</div>
                </div>
                """
                
                item = QListWidgetItem(self.main.list_local_search)
                item.setData(Qt.UserRole, {"sender": sender, "content": content})
                item.setSizeHint(QSize(300, 70))
                
                lbl = QLabel(html_text)
                lbl.setWordWrap(True)
                self.main.list_local_search.setItemWidget(item, lbl)

    def navigate_to_message(self, item):
        data = item.data(Qt.UserRole)
        if not data: return
        
        target_sender = data.get("sender")
        target_content = data.get("content")
        
        # Tìm tin nhắn trong self.main.chat_list
        for i in range(self.main.chat_list.count()):
            chat_item = self.main.chat_list.item(i)
            chat_data = chat_item.data(Qt.UserRole)
            if not chat_data or not isinstance(chat_data, dict):
                continue
            
            # Match sender and content
            s = chat_data.get("sender", "")
            match_sender = (
                s == target_sender
                or (s == "Tôi" and target_sender == self.main.nickname)
                or (s == self.main.nickname and target_sender == "Tôi")
            )
            if match_sender and chat_data.get("content") == target_content:
                self.main.chat_list.scrollToItem(chat_item, QAbstractItemView.PositionAtCenter)
                self.main.chat_list.setCurrentItem(chat_item)
                
                # Có thể thêm hiệu ứng nháy nhẹ ở đây nếu muốn
                # Đóng panel
                self.main.ui.col4_info.hide()
                self.main._info_panel_visible = False
                break
