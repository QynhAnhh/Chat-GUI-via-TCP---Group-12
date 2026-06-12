import socket
import threading
import json
import struct

HOST = '127.0.0.1'
PORT = 9999
clients = {}

def recv_exact(conn, size):
    # Ham ho tro nhan du so byte, tranh loi dinh goi TCP
    data = b""
    while len(data) < size:
        packet = conn.recv(size - len(data))
        if not packet:
            return None
        data += packet
    return data

def recv_packet(conn):
    header = recv_exact(conn, 4)
    if header is None:
        return None
    (size,) = struct.unpack("!I", header)
    return recv_exact(conn, size)
    
def handle_client(conn, addr):
    print("Co ket noi tu:", addr)
    
    while True:
        try:
            # 1. Nhan 4 byte header de lay size
            header = recv_exact(conn, 4)
            if not header:
                break
                
            size = struct.unpack("!I", header)[0]
            
            # 2. Nhan du lieu dua tren size
            payload = recv_exact(conn, size)
            if not payload:
                break
                
            # 3. Kiem tra xem la Text(JSON) hay la Anh(Binary)
            try:
                # Thu dich sang string
                text = payload.decode('utf-8')
                data_json = json.loads(text)
                
                # Xu ly cac lenh JSON
                if data_json.get("type") == "login":
                    name = data_json.get("nickname")
                    print(f"[{addr}] dang nhap: {name}")
                    
                    # Gui phan hoi kem header
                    reply = json.dumps({"type": "info", "msg": "OK"}).encode('utf-8')
                    reply_header = struct.pack("!I", len(reply))
                    conn.sendall(reply_header + reply)
                    
                elif data_json.get("type") == "chat_all":
                    print(f"[{data_json.get('sender')}] chat: {data_json.get('content')}")
                    # TODO: Tuan sau viet vong lap gui tin nhan cho moi nguoi
                    
            except UnicodeDecodeError:
                # Dich loi -> Do la file anh cua Tien gui
                print(f"Nhan duoc file ANH tu {addr}, dung luong: {size} bytes")
                # TODO: Tuan sau viet code forward anh di
                
        except Exception as e:
            print("Loi ngat ket noi:", e)
            break
            
    if addr in clients:
        del clients[addr]
    conn.close()
    print("Da dong ket noi:", addr)

def main():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind((HOST, PORT))
    s.listen(5) 
    print(f"Server dang chay: {HOST}:{PORT}...")
    
    while True:
        conn, addr = s.accept()
        clients[addr] = conn
        print("So nguoi online:", len(clients))
        
        t = threading.Thread(target=handle_client, args=(conn, addr))
        t.start()

if __name__ == "__main__":
    main()
