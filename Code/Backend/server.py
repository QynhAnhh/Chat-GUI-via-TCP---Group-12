import socket
import threading
import json
import struct

HOST = '127.0.0.1'
PORT = 9999

# Đổi cấu trúc lưu trữ từ địa chỉ IP sang nickname (Client ID)
clients = {} # Định dạng: {"nickname": conn}
groups = {}  # Định dạng: {"group_id": {"admin": "nickname", "members": ["nick1", "nick2"]}}
friends = {} # Định dạng: {"nickname": ["friend1", "friend2"]}
avatars = {} # Định dạng: {"nickname": "base64_avatar_string"}
def recv_exact(conn, size):
    # Ham ho tro nhan du so byte, tranh loi dinh goi TCP
    data = b""
    while len(data) < size:
        packet = conn.recv(size - len(data))
        if not packet:
            return None
        data += packet
    return data

def handle_client(conn, addr):
    print("Co ket noi tu:", addr)
    current_nickname = None
    
    while True:
        try:
            header = recv_exact(conn, 4)
            if not header:
                break
                
            size = struct.unpack("!I", header)[0]

            # Đọc payload ĐÚNG MỘT LẦN duy nhất
            payload = recv_exact(conn, size)
            if not payload: break

            try:
                text = payload.decode('utf-8')
                print(f"[SERVER DEBUG] Nhận được payload: {text}")
                data_json = json.loads(text)
                msg_type = data_json.get("type")
                
                # LOGIN & QUẢN LÝ CLIENT ID
                if msg_type == "login":
                    nickname = data_json.get("nickname")
                    if nickname in clients or nickname in groups:
                        reply = json.dumps({"type": "error", "msg": "Ten da ton tai!"}).encode('utf-8')
                        conn.sendall(struct.pack("!I", len(reply)) + reply)
                    else:
                        current_nickname = nickname
                        clients[nickname] = conn
                        if nickname not in friends: 
                            friends[nickname] = [] # Khởi tạo danh bạ rỗng
                        print(f"[*] {nickname} da dang nhap thanh cong.")
                        reply = json.dumps({"type": "info", "msg": "OK"}).encode('utf-8')
                        conn.sendall(struct.pack("!I", len(reply)) + reply)

                # YÊU CẦU NHẮN TIN CÁ NHÂN HOẶC VÀO NHÓM (TRONG SERVER.PY)
                elif msg_type == "request_private":
                    sender = data_json.get("sender")
                    target = data_json.get("target")
                    
                    # LOG KIỂM TRA TRÊN SERVER
                    print(f"\n[DEBUG] '{sender}' dang gui yeu cau ket noi toi '{target}'") 
                    print(f"[DEBUG] Danh sach dang online: {list(clients.keys())}")
                    
                    if target in clients:
                        if target in friends.get(sender, []):
                            print(f"[DEBUG] -> That bai: {sender} va {target} da la ban!")
                            reply = json.dumps({"type": "system_info", "msg": f"Bạn và {target} đã có thể nhắn tin."}).encode('utf-8')
                            conn.sendall(struct.pack("!I", len(reply)) + reply)
                        else:
                            forward_msg = json.dumps({"type": "incoming_request", "req_type": "private", "sender": sender, "target": target}).encode('utf-8')
                            # Gửi cho Client B
                            clients[target].sendall(struct.pack("!I", len(forward_msg)) + forward_msg)
                            print(f"[DEBUG] -> Thanh cong: Da forward yeu cau sang cho '{target}'")
                    elif target in groups:
                        admin = groups[target]["admin"]
                        if sender in groups[target]["members"]:
                            print(f"[DEBUG] -> That bai: {sender} da o trong nhom {target}!")
                            reply = json.dumps({"type": "system_info", "msg": f"Bạn đã ở trong nhóm {target} rồi!"}).encode('utf-8')
                            conn.sendall(struct.pack("!I", len(reply)) + reply)
                        else:
                            # Đưa vào danh sách duyệt
                            if "join_requests" not in groups[target]:
                                groups[target]["join_requests"] = []
                            if sender not in groups[target]["join_requests"]:
                                groups[target]["join_requests"].append(sender)
                                
                            if admin in clients:
                                notify_admin = json.dumps({"type": "new_join_request", "group_id": target}).encode('utf-8')
                                try: clients[admin].sendall(struct.pack("!I", len(notify_admin)) + notify_admin)
                                except: pass
                                print(f"[DEBUG] -> Thanh cong: Da them {sender} vao join_requests cua nhom {target} va thong bao admin")
                            else:
                                print(f"[DEBUG] -> Thanh cong: Da them {sender} vao join_requests cua nhom {target} (Admin offline)")
                                
                            reply = json.dumps({"type": "system_info", "msg": f"Đã gửi yêu cầu tham gia nhóm {target}. Chờ admin duyệt."}).encode('utf-8')
                            conn.sendall(struct.pack("!I", len(reply)) + reply)
                    else:
                        print(f"[DEBUG] -> That bai: Khong tim thay '{target}' (co the go sai ten hoac chu hoa/thuong)")
                        reply = json.dumps({"type": "system_info", "msg": "Người dùng hoặc nhóm không tồn tại!"}).encode('utf-8')
                        conn.sendall(struct.pack("!I", len(reply)) + reply)

                # PHẢN HỒI YÊU CẦU NHẮN TIN CÁ NHÂN
                elif msg_type == "respond_private":
                    sender = data_json.get("sender") # Người vừa bấm Chấp nhận/Từ chối
                    requester = data_json.get("requester") # Người đã gửi yêu cầu
                    status = data_json.get("status") # "accept" hoặc "decline"
                    
                    if status == "accept":
                        friends[sender].append(requester)
                        friends[requester].append(sender)
                        msg = "Đã chấp nhận yêu cầu nhắn tin."
                        req_msg = f"{sender} đã chấp nhận yêu cầu của bạn!"
                    else:
                        msg = "Đã từ chối yêu cầu nhắn tin."
                        req_msg = f"{sender} đã từ chối yêu cầu của bạn."
                    
                    if requester in clients:
                        forward_msg = json.dumps({"type": "request_result", "target": sender, "msg": req_msg, "status": status}).encode('utf-8')
                        clients[requester].sendall(struct.pack("!I", len(forward_msg)) + forward_msg)

                # NHẮN TIN RIÊNG 1-1 (UNICAST) - Bổ sung chặn nếu chưa kết bạn
                elif msg_type == "chat_private":
                    sender = data_json.get("sender")
                    receiver = data_json.get("receiver")
                    content = data_json.get("content")
                    
                    if receiver not in friends.get(sender, []):
                        reply = json.dumps({"type": "system_info", "msg": f"Bạn chưa thể nhắn tin với {receiver}. Hãy gửi yêu cầu trước."}).encode('utf-8')
                        conn.sendall(struct.pack("!I", len(reply)) + reply)
                        continue

                    if receiver in clients:
                        reply_to = data_json.get("reply_to", None)  # Pass-through
                        fwd = {"type": "private_message", "sender": sender, "content": content}
                        if reply_to:
                            fwd["reply_to"] = reply_to
                        forward_msg = json.dumps(fwd).encode('utf-8')
                        try:
                            clients[receiver].sendall(struct.pack("!I", len(forward_msg)) + forward_msg)
                        except: pass

                elif msg_type == "unfriend":
                    sender = data_json.get("sender")
                    target = data_json.get("target")
                    if sender in friends and target in friends[sender]:
                        friends[sender].remove(target)
                    if target in friends and sender in friends[target]:
                        friends[target].remove(sender)
                    if target in clients:
                        notify = json.dumps({"type": "unfriended", "target": sender}).encode('utf-8')
                        try:
                            clients[target].sendall(struct.pack("!I", len(notify)) + notify)
                        except: pass

                elif msg_type == "leave_group":
                    sender = data_json.get("sender")
                    group_id = data_json.get("group_id")
                    if group_id in groups and sender in groups[group_id]["members"]:
                        groups[group_id]["members"].remove(sender)
                        new_admin = None
                        if groups[group_id]["admin"] == sender and groups[group_id]["members"]:
                            import random
                            groups[group_id]["admin"] = random.choice(groups[group_id]["members"])
                            new_admin = groups[group_id]["admin"]
                        notify = json.dumps({"type": "member_left", "group_id": group_id, "member": sender, "new_admin": new_admin}).encode('utf-8')
                        for mem in groups[group_id]["members"]:
                            if mem in clients:
                                try: clients[mem].sendall(struct.pack("!I", len(notify)) + notify)
                                except: pass
                        if not groups[group_id]["members"]:
                            del groups[group_id]

                elif msg_type == "kick_member":
                    admin = data_json.get("admin")
                    group_id = data_json.get("group_id")
                    member = data_json.get("member")
                    if group_id in groups and groups[group_id]["admin"] == admin:
                        if member in groups[group_id]["members"]:
                            groups[group_id]["members"].remove(member)
                            notify = json.dumps({"type": "kicked_from_group", "group_id": group_id}).encode('utf-8')
                            if member in clients:
                                try: clients[member].sendall(struct.pack("!I", len(notify)) + notify)
                                except: pass
                            notify_others = json.dumps({"type": "member_kicked", "group_id": group_id, "member": member}).encode('utf-8')
                            for mem in groups[group_id]["members"]:
                                if mem in clients:
                                    try: clients[mem].sendall(struct.pack("!I", len(notify_others)) + notify_others)
                                    except: pass

                elif msg_type == "add_member":
                    sender = data_json.get("sender")
                    group_id = data_json.get("group_id")
                    member = data_json.get("member")
                    if group_id in groups:
                        if groups[group_id]["admin"] == sender:
                            # Add directly
                            if member not in groups[group_id]["members"]:
                                groups[group_id]["members"].append(member)
                                notify_new = json.dumps({"type": "added_to_group", "group_id": group_id, "admin": sender, "members": groups[group_id]["members"]}).encode('utf-8')
                                if member in clients:
                                    try: clients[member].sendall(struct.pack("!I", len(notify_new)) + notify_new)
                                    except: pass
                                notify_others = json.dumps({"type": "member_added", "group_id": group_id, "member": member}).encode('utf-8')
                                for mem in groups[group_id]["members"]:
                                    if mem != member and mem in clients:
                                        try: clients[mem].sendall(struct.pack("!I", len(notify_others)) + notify_others)
                                        except: pass
                        else:
                            # Put in join requests
                            if "join_requests" not in groups[group_id]:
                                groups[group_id]["join_requests"] = []
                            if member not in groups[group_id]["join_requests"]:
                                groups[group_id]["join_requests"].append(member)
                            admin = groups[group_id]["admin"]
                            if admin in clients:
                                notify_admin = json.dumps({"type": "new_join_request", "group_id": group_id}).encode('utf-8')
                                try: clients[admin].sendall(struct.pack("!I", len(notify_admin)) + notify_admin)
                                except: pass

                elif msg_type == "get_join_requests":
                    sender = data_json.get("sender")
                    group_id = data_json.get("group_id")
                    if group_id in groups and groups[group_id]["admin"] == sender:
                        requests = groups[group_id].get("join_requests", [])
                        reply = json.dumps({"type": "join_requests_list", "group_id": group_id, "requests": requests}).encode('utf-8')
                        conn.sendall(struct.pack("!I", len(reply)) + reply)
                        
                elif msg_type == "approve_join_request":
                    sender = data_json.get("sender")
                    group_id = data_json.get("group_id")
                    member = data_json.get("member")
                    if group_id in groups and groups[group_id]["admin"] == sender:
                        if "join_requests" in groups[group_id] and member in groups[group_id]["join_requests"]:
                            groups[group_id]["join_requests"].remove(member)
                            if member not in groups[group_id]["members"]:
                                groups[group_id]["members"].append(member)
                                notify_new = json.dumps({"type": "added_to_group", "group_id": group_id, "admin": sender, "members": groups[group_id]["members"]}).encode('utf-8')
                                if member in clients:
                                    try: clients[member].sendall(struct.pack("!I", len(notify_new)) + notify_new)
                                    except: pass
                                notify_others = json.dumps({"type": "member_added", "group_id": group_id, "member": member}).encode('utf-8')
                                for mem in groups[group_id]["members"]:
                                    if mem != member and mem in clients:
                                        try: clients[mem].sendall(struct.pack("!I", len(notify_others)) + notify_others)
                                        except: pass
                            reply = json.dumps({"type": "join_request_approved", "group_id": group_id, "member": member}).encode('utf-8')
                            conn.sendall(struct.pack("!I", len(reply)) + reply)

                # TẠO NHÓM MỚI - Validate số lượng và bạn bè
                elif msg_type == "create_group":
                    group_id = data_json.get("group_id")
                    members_to_invite = data_json.get("members", []) # Gửi kèm danh sách mời
                    
                    # Kiểm tra logic: Phải có ít nhất 2 người (bao gồm admin)
                    if len(members_to_invite) < 1:
                        reply = json.dumps({"type": "system_info", "msg": "Nhóm phải có ít nhất 2 người (bạn và 1 người khác)."}).encode('utf-8')
                        conn.sendall(struct.pack("!I", len(reply)) + reply)
                        continue
                        
                    # Kiểm tra đã là bạn bè chưa
                    valid_members = [current_nickname]
                    for mem in members_to_invite:
                        if mem in friends.get(current_nickname, []):
                            valid_members.append(mem)
                            
                    if len(valid_members) < 2:
                        reply = json.dumps({"type": "system_info", "msg": "Bạn chỉ có thể thêm những người đã chấp nhận nhắn tin với bạn."}).encode('utf-8')
                        conn.sendall(struct.pack("!I", len(reply)) + reply)
                        continue

                    if group_id in groups or group_id in clients:
                        reply = json.dumps({"type": "system_info", "msg": f"Tên '{group_id}' đã tồn tại (có thể là tên người dùng hoặc nhóm). Vui lòng chọn tên khác."}).encode('utf-8')
                        conn.sendall(struct.pack("!I", len(reply)) + reply)
                        continue

                    if group_id not in groups:
                        groups[group_id] = {"admin": current_nickname, "members": valid_members}
                        print(f"[*] {current_nickname} da tao nhom: {group_id}")
                        # Thông báo thành công cho admin
                        reply = json.dumps({"type": "group_created", "group_id": group_id, "admin": current_nickname, "members": valid_members}).encode('utf-8')
                        conn.sendall(struct.pack("!I", len(reply)) + reply)
                        # Thông báo cho tất cả members khác
                        for mem in valid_members:
                            if mem != current_nickname and mem in clients:
                                try:
                                    notify = json.dumps({"type": "added_to_group", "group_id": group_id, "admin": current_nickname, "members": valid_members}).encode('utf-8')
                                    clients[mem].sendall(struct.pack("!I", len(notify)) + notify)
                                except: pass
                    else:
                        reply = json.dumps({"type": "system_info", "msg": "Tên nhóm đã tồn tại."}).encode('utf-8')
                        conn.sendall(struct.pack("!I", len(reply)) + reply)

                # YÊU CẦU VÀO NHÓM
                elif msg_type == "request_group":
                    sender = data_json.get("sender")
                    group_id = data_json.get("group_id")
                    if group_id in groups:
                        admin = groups[group_id]["admin"]
                        if admin in clients:
                            forward_msg = json.dumps({"type": "incoming_request", "req_type": "group", "sender": sender, "target": group_id}).encode('utf-8')
                            clients[admin].sendall(struct.pack("!I", len(forward_msg)) + forward_msg)
                    else:
                        reply = json.dumps({"type": "system_info", "msg": "Nhóm không tồn tại!"}).encode('utf-8')
                        conn.sendall(struct.pack("!I", len(reply)) + reply)

                # PHẢN HỒI YÊU CẦU VÀO NHÓM (Từ Admin)
                elif msg_type == "respond_group":
                    admin = data_json.get("sender")
                    requester = data_json.get("requester")
                    group_id = data_json.get("group_id")
                    status = data_json.get("status")
                    
                    if group_id in groups and groups[group_id]["admin"] == admin:
                        if status == "accept":
                            if requester not in groups[group_id]["members"]:
                                groups[group_id]["members"].append(requester)
                                notify_new = json.dumps({"type": "added_to_group", "group_id": group_id, "admin": admin, "members": groups[group_id]["members"]}).encode('utf-8')
                                if requester in clients:
                                    try: clients[requester].sendall(struct.pack("!I", len(notify_new)) + notify_new)
                                    except: pass
                                notify_others = json.dumps({"type": "member_added", "group_id": group_id, "member": requester}).encode('utf-8')
                                for mem in groups[group_id]["members"]:
                                    if mem != requester and mem in clients:
                                        try: clients[mem].sendall(struct.pack("!I", len(notify_others)) + notify_others)
                                        except: pass
                            msg = f"Đã duyệt {requester} vào nhóm {group_id}."
                            req_msg = f"Yêu cầu vào nhóm {group_id} của bạn đã được chấp nhận!"
                        else:
                            msg = f"Đã từ chối {requester} vào nhóm."
                            req_msg = f"Yêu cầu vào nhóm {group_id} của bạn bị từ chối."
                            
                        if requester in clients:
                            forward_msg = json.dumps({"type": "request_result", "target": group_id, "msg": req_msg, "status": status}).encode('utf-8')
                            clients[requester].sendall(struct.pack("!I", len(forward_msg)) + forward_msg)
                        
                elif msg_type == "chat_group":
                    group_id = data_json.get("group_id")
                    sender = data_json.get("sender")
                    content = data_json.get("content")
                    if group_id in groups and sender in groups[group_id]["members"]:
                        reply_to = data_json.get("reply_to", None)  # Pass-through
                        fwd = {"type": "group_message", "group_id": group_id, "sender": sender, "content": content}
                        if reply_to:
                            fwd["reply_to"] = reply_to
                        forward_msg = json.dumps(fwd).encode('utf-8')
                        forward_header = struct.pack("!I", len(forward_msg))
                        for mem in groups[group_id]["members"]:
                            if mem != sender and mem in clients:
                                try: clients[mem].sendall(forward_header + forward_msg)
                                except: pass

                # CẬP NHẬT ẢNH ĐẠI DIỆN - Broadcast tên file đến tất cả client khác
                elif msg_type == "update_avatar":
                    sender = data_json.get("sender")
                    avatar_name = data_json.get("avatar_name", "")
                    # Lưu tên file lại trên server
                    avatars[sender] = avatar_name
                    broadcast = json.dumps({"type": "avatar_updated", "sender": sender, "avatar_name": avatar_name}).encode('utf-8')
                    header_bc = struct.pack("!I", len(broadcast))
                    for nick, c_conn in list(clients.items()):
                        if nick != sender:
                            try: c_conn.sendall(header_bc + broadcast)
                            except: pass
                    print(f"[*] {sender} đã cập nhật avatar: {avatar_name}")

                # CLIENT YÊU CẦU TOÀN BỘ AVATAR HIỆN TẠI
                elif msg_type == "get_avatars":
                    if avatars:
                        reply = json.dumps({"type": "all_avatars", "avatars": avatars}).encode('utf-8')
                        conn.sendall(struct.pack("!I", len(reply)) + reply)

            except UnicodeDecodeError:
                # --- Xu ly chuyen tiep Anh ---
                print(f"Nhan duoc file ANH tu {addr}, dung luong: {size} bytes")
                
                img_header = struct.pack("!I", len(payload))
                for nick, c_conn in list(clients.items()):
                    if nick != current_nickname:
                        try: c_conn.sendall(img_header + payload)
                        except: pass

            except Exception as logic_err:
                print(f"[SERVER LỖI LOGIC] Client {current_nickname} gặp lỗi: {logic_err}")

        # --- SỬA LẠI KHỐI EXCEPT NGOÀI CÙNG ---
        except Exception as e:
            print(f"[SERVER LỖI MẠNG] Mất kết nối. Chi tiết lỗi: {e}")
            break

    # Dọn dẹp RAM & Danh sách khi Client thoát
    if current_nickname and current_nickname in clients:
        del clients[current_nickname]
        print(f"[-] {current_nickname} da ngat ket noi.")

    # Xóa toàn bộ quan hệ bạn bè khi người dùng ngắt kết nối
    # (buộc phải gửi yêu cầu mới khi đăng nhập lại)
    if current_nickname and current_nickname in friends:
        for friend_nick in friends[current_nickname]:
            if friend_nick in friends and current_nickname in friends[friend_nick]:
                friends[friend_nick].remove(current_nickname)
                print(f"[*] Da xoa lien he giua '{current_nickname}' va '{friend_nick}'.")
        del friends[current_nickname]

    # Tự động xóa người dùng khỏi các nhóm
    for g_id, g_data in list(groups.items()):
        if current_nickname in g_data["members"]:
            g_data["members"].remove(current_nickname)
            if not g_data["members"]:
                del groups[g_id]
                print(f"[*] Nhom '{g_id}' da bi xoa vi khong con thanh vien nao.")

    conn.close()
    print("Da dong ket noi:", addr)

def main():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind((HOST, PORT))
    s.listen(5) 
    print(f"Server dang chay tai {HOST}:{PORT}...")
    
    while True:
        conn, addr = s.accept()
        clients[addr] = conn
        print("So nguoi online:", len(clients))
        
        t = threading.Thread(target=handle_client, args=(conn, addr))
        t.start()

if __name__ == "__main__":
    main()
