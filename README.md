# PROJECT: UDM_08 Lập trình ứng dụng Chat (GUI) via TCP

## 1. Thành viên nhóm
| STT | Họ và tên | MSSV | Tài khoản GitHub |
|---|---|---|---|
| 1 | Đỗ Nguyễn Quỳnh Anh | 086306005322 | [QynhAnhh](https://github.com/QynhAnhh) |
| 2 | Trần Minh Quân | 352774521 | [quantran9739-png](https://github.com/quantran9739-png) |
| 3 | Lê Hữu Tiến | 072206006554 | [LeHuuTien1006](https://github.com/LeHuuTien1006) |

## 2. Công nghệ sử dụng
* **Ngôn ngữ:** Python.
* **Giao thức mạng:** TCP/IP (thư viện socket, struct).
* **Giao diện (GUI):** PySide6.
* **Đa luồng:** QThread và hệ thống Signal/Slot của PySide6 để giao tiếp bất đồng bộ.
* **Xử lý Đa phương tiện:** Thư viện opencv-python (cv2), numpy, và mã hóa base64.
* **Đóng gói dữ liệu:** Định dạng JSON kết hợp Header nhị phân.

## 3. Các tính năng chính
* **Kết nối đa luồng:** Server quản lý đồng thời nhiều Client; Client sử dụng QThread nhận dữ liệu mạng để tránh treo giao diện.
* **Hệ thống chat cốt lõi:** Hỗ trợ chat phòng chung (Broadcast) và nhắn tin riêng tư 1-1 (Unicast) với tốc độ phản hồi tức thì. Tích hợp bộ đếm hiển thị thông báo tin nhắn chưa đọc.
* **Quản lý danh bạ & Trải nghiệm UI:** Hỗ trợ kết bạn, hủy kết bạn. Tự động sắp xếp ưu tiên danh sách hội thoại theo thời gian thực (tin nhắn mới nổi lên đầu). Thuật toán bẻ dòng (word-wrap) thông minh trong bong bóng chat.
* **Quản lý nhóm chat:** Hỗ trợ tạo nhóm chat mới (Multicast) và tự động cấp quyền Admin cho người khởi tạo.
* **Quyền hạn Admin:** Hỗ trợ menu ngữ cảnh kích thành viên ra khỏi nhóm; Server tự động điều hướng gói tin hệ thống ép Client bị kích phải thoát phòng.
* **Rời nhóm & Chuyển giao quyền:** Thành viên tự do rời nhóm; nếu Admin rời đi, Server tự động kích hoạt thuật toán chọn ngẫu nhiên một thành viên còn lại lên làm Admin mới để duy trì nhóm.
* **Cá nhân hóa & Tiện ích:** Thay đổi biệt danh hiển thị, tùy biến màu nền chat, công cụ tìm kiếm tin nhắn cũ tốc độ cao (loại trừ các thông báo hệ thống), tự động cắt bớt (`...`) nếu tên nhóm quá dài để giữ giao diện gọn gàng.
* **Đa phương tiện:** Gửi Sticker sinh động qua mã định danh. Hỗ trợ truyền tải ảnh chất lượng gốc qua luồng byte TCP, tích hợp cửa sổ xem ảnh nâng cao (ImageViewer) hỗ trợ phóng to/thu nhỏ bằng chuột và kéo thả ảnh.
## 4. Kết quả đạt được (Final Output)
* **ChatServer:** Backend xử lý ổn định, điều hướng hàng nghìn tin nhắn đa kênh bằng JSON, quản lý trạng thái Admin tự động và có khả năng giải phóng bộ nhớ RAM khi Client mất kết nối đột ngột.
* **ChatClient:** Giao diện đồ họa Desktop (PySide6) hỗ trợ người dùng giao tiếp mượt mà, quản lý nhóm thông minh và tương tác đa phương tiện một cách tinh tế.
