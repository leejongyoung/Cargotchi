import time
import network
import socket
import ujson
import gc
from machine import Pin
from lib.epd2in13_V4 import EPD_2in13_V4_Landscape

# --- Configuration ---
CONFIG_FILE = 'config.json'
DEFAULT_PHONE = '010-0000-0000'
# 주의: 기본 프레임버퍼 폰트는 한글을 지원하지 않습니다. 
# 한글 출력을 위해서는 별도의 폰트 라이브러리(예: micropython-font-to-py)가 필요합니다.
DEFAULT_MESSAGE = 'Out of Office' 

# --- E-Paper Display Function ---
def update_display(phone, message):
    """Updates the e-paper display with the given phone number and message."""
    print(f"Updating display: Phone='{phone}', Message='{message}'")
    try:
        epd = EPD_2in13_V4_Landscape()
        epd.init()
        epd.Clear()
        
        epd.fill(0xff)  # White background
        
        # Draw content (Black text)
        epd.text("Cargotchi", 10, 10, 0x00)
        epd.hline(10, 25, 230, 0x00)
        
        # 폰트 크기가 작으므로 임시 방편으로 두 번 겹쳐 그려서 진하게 만듦
        epd.text(phone, 20, 40, 0x00)
        epd.text(phone, 21, 40, 0x00) 
        
        epd.text(message, 20, 60, 0x00)
        
        # Push to display
        epd.display(epd.buffer)
        
        print("Putting display to sleep")
        epd.sleep()
        
        # EPD 객체 해제 및 메모리 정리
        del epd
        gc.collect()
        
    except Exception as e:
        print(f"Display Error: {e}")

# --- Configuration Management ---
def save_config(phone, message):
    try:
        with open(CONFIG_FILE, 'w') as f:
            ujson.dump({'phone': phone, 'message': message}, f)
        print("Config saved.")
    except Exception as e:
        print(f"Error saving config: {e}")

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = ujson.load(f)
            return config.get('phone', DEFAULT_PHONE), config.get('message', DEFAULT_MESSAGE)
    except (OSError, ValueError):
        print("Creating default config.")
        save_config(DEFAULT_PHONE, DEFAULT_MESSAGE)
        return DEFAULT_PHONE, DEFAULT_MESSAGE

# --- Web Server Helpers ---
def unquote_plus(s):
    """Decodes URL-encoded characters (UTF-8 support)."""
    s = s.replace('+', ' ')
    parts = s.split('%')
    if len(parts) == 1:
        return s
    res = bytearray()
    res.extend(parts[0].encode('utf-8'))
    for item in parts[1:]:
        try:
            code = int(item[:2], 16)
            res.append(code)
            res.extend(item[2:].encode('utf-8'))
        except ValueError:
            res.extend(b'%')
            res.extend(item.encode('utf-8'))
    return res.decode('utf-8')

def create_web_page(phone, message, saved=False):
    success_msg = '<p class="success">저장되었습니다! (화면이 갱신됩니다)</p>' if saved else ''
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Cargotchi Setup</title>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{ font-family: sans-serif; padding: 20px; background-color: #f4f4f8; }}
            .container {{ max-width: 400px; margin: auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }}
            label {{ display: block; margin-top: 15px; font-weight: bold; }}
            input[type="text"] {{ width: 100%; padding: 10px; margin-top: 5px; border: 1px solid #ddd; border-radius: 4px; box-sizing: border-box; }}
            input[type="submit"] {{ width: 100%; background-color: #007aff; color: white; padding: 12px; margin-top: 20px; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; }}
            .success {{ color: #28a745; margin-top: 15px; text-align: center; font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Cargotchi 설정</h1>
            <form action="/" method="post">
                <label for="phone">전화번호</label>
                <input type="text" id="phone" name="phone" value="{phone}">
                <label for="message">메시지 (영문 권장)</label>
                <input type="text" id="message" name="message" value="{message}">
                <input type="submit" value="디스플레이 업데이트">
            </form>
            {success_msg}
        </div>
    </body>
    </html>
    """
    return html

# --- Server Logic ---
def start_server():
    # Start Access Point
    ap = network.WLAN(network.AP_IF)
    ap.config(essid='Cargotchi-Setup', password='cargotchi1234') 
    ap.active(True)

    while not ap.active():
        print("Starting AP...")
        time.sleep(0.5)

    print('AP Active.')
    print(f'Connect to WiFi "Cargotchi-Setup" and visit: http://{ap.ifconfig()[0]}')

    # Socket Setup
    addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(1)

    while True:
        cl = None
        try:
            cl, addr = s.accept()
            cl.settimeout(3.0) 
            print('Client connected from', addr)
            
            # 1. 헤더 읽기 (빈 줄이 나올 때까지)
            request_bytes = b""
            while b"\r\n\r\n" not in request_bytes:
                chunk = cl.recv(1024)
                if not chunk:
                    break
                request_bytes += chunk
            
            request_str = request_bytes.decode('utf-8')
            
            # 2. Content-Length 찾기 (POST 요청인 경우 본문 길이를 알아야 함)
            content_length = 0
            if 'POST' in request_str:
                for line in request_str.split('\r\n'):
                    if 'Content-Length:' in line:
                        try:
                            content_length = int(line.split(':')[1].strip())
                        except ValueError:
                            pass
            
            # 3. 본문(Body) 데이터 읽기
            # 헤더와 본문이 분리되어 있는 경우(\r\n\r\n 뒤에 데이터가 모자란 경우) 추가로 읽음
            header_end_idx = request_bytes.find(b"\r\n\r\n") + 4
            body_received_len = len(request_bytes) - header_end_idx
            
            if content_length > 0:
                while body_received_len < content_length:
                    chunk = cl.recv(1024)
                    if not chunk:
                        break
                    request_bytes += chunk
                    body_received_len += len(chunk)

            # 전체 요청 문자열 완성
            full_request = request_bytes.decode('utf-8')
            print(f"[Debug] Full Request Length: {len(full_request)}") # 디버깅용

            phone_val, msg_val = load_config()
            saved_status = False

            # POST 처리
            if 'POST /' in full_request:
                parts = full_request.split('\r\n\r\n')
                if len(parts) > 1:
                    form_data = parts[1]
                    print(f"[Debug] Form Data: {form_data}") # 데이터가 잘 들어왔는지 확인

                    params = {}
                    for pair in form_data.split('&'):
                        if '=' in pair:
                            key, value = pair.split('=', 1)
                            params[key] = unquote_plus(value)

                    new_phone = params.get('phone', phone_val)
                    new_msg = params.get('message', msg_val)
                    
                    print(f"[Debug] New: {new_phone}, {new_msg}")
                    
                    # 값이 변경되었거나 강제 업데이트를 위해 조건문 완화
                    # (기존 값이 같아도 '저장' 버튼을 누르면 화면을 갱신하고 싶다면 조건을 지우세요)
                    save_config(new_phone, new_msg)
                    update_display(new_phone, new_msg)
                    phone_val, msg_val = new_phone, new_msg
                    saved_status = True

            # Response 생성
            response_html = create_web_page(phone_val, msg_val, saved_status)
            cl.send('HTTP/1.0 200 OK\r\nContent-type: text/html\r\n\r\n')
            cl.send(response_html)
            
        except OSError as e:
            pass # 타임아웃은 자연스러운 현상이므로 무시
        except Exception as e:
            print(f"Server Error: {e}")
        finally:
            if cl:
                cl.close()
            gc.collect()

# --- Main ---
if __name__ == "__main__":
    phone, message = load_config()
    update_display(phone, message)
    start_server()