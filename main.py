import time
import network
import socket
import gc
from lib.epd2in13_V4 import EPD_2in13_V4_Landscape
import lib.epd2in13_V4_Utils as epd_utils

# --- Configuration ---
CONFIG_FILE = 'config.json'
HTML_FILE = 'index.html'  # 분리된 HTML 파일명

# --- E-Paper Display Function ---
def update_display_from_buffer(hex_data):
    # (이전과 동일)
    print("Processing image request...")
    try:
        epd = EPD_2in13_V4_Landscape()
        epd.init()
        epd_utils.display_js_hex_image(epd, hex_data)
        print("Putting display to sleep")
        epd.sleep()
        del epd
        gc.collect()
    except Exception as e:
        print("Display Update Error:", e)

# --- Web Server Helpers ---
def unquote_plus(s):
    # (이전과 동일)
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

def get_web_page(saved=False):
    """
    index.html 파일을 읽어서, 저장 성공 시 알림 메시지를 주입하여 반환
    """
    success_script = "alert('전송 완료! 화면이 곧 갱신되고, 디스플레이에 적용됩니다.');" if saved else ""
    
    html_content = ""
    try:
        with open(HTML_FILE, 'r') as f:
            html_content = f.read()
            
        # HTML 파일 내의 {{SUCCESS_MSG}} 치환자를 실제 스크립트로 교체
        html_content = html_content.replace('{{SUCCESS_MSG}}', success_script)
        
    except OSError:
        html_content = "<h1>Error: index.html not found</h1>"
        
    return html_content

# --- Server Logic ---
def start_server():
    ap = network.WLAN(network.AP_IF)
    ssid = 'Cargochi'
    password = 'Cargochi1234'
    ap.config(essid=ssid, password=password)
    ap.active(True)

    while not ap.active():
        print("Starting AP...")
        time.sleep(0.5)

    print('AP Active.')
    ip = ap.ifconfig()[0]
    print(f'Connect to WiFi "{ssid}" and visit: http://{ip}')

    # (부팅 시 화면 표시 로직은 동일)
    try:
        epd = EPD_2in13_V4_Landscape()
        epd.init()
        epd.fill(1)
        epd.text("Cargochi AP", 10, 10, 0)
        epd.text("SSID: " + ssid, 10, 30, 0)
        epd.text("PASS: " + password, 10, 45, 0)
        epd.text("URL:", 10, 65, 0)
        epd.text(ip, 10, 80, 0)
        epd.display(epd.buffer)
        epd.sleep()
        del epd
        gc.collect()
    except Exception as e:
        print("AP info display error:", e)

    addr = socket.getaddrinfo('0.0.0.0', 80)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(1)

    while True:
        cl = None
        try:
            cl, addr = s.accept()
            print('Client connected from', addr)
            
            cl.settimeout(2.0)
            request_file = cl.makefile('rwb', 0)
            
            header_lines = []
            while True:
                line = request_file.readline()
                if not line or line == b'\r\n':
                    break
                header_lines.append(line)
            
            content_length = 0
            is_post = False
            
            if len(header_lines) > 0:
                request_line = header_lines[0].decode('utf-8')
                if 'POST' in request_line:
                    is_post = True
                    for line in header_lines:
                        line_str = line.decode('utf-8')
                        if 'Content-Length:' in line_str:
                            try:
                                content_length = int(line_str.split(':')[1].strip())
                            except:
                                pass

            post_data = b""
            if is_post and content_length > 0:
                print(f"Reading body of size: {content_length}")
                post_data = request_file.read(content_length)

            saved_status = False
            if is_post and post_data:
                try:
                    body_str = post_data.decode('utf-8')
                    if 'image_data=' in body_str:
                        parts = body_str.split('image_data=')
                        if len(parts) > 1:
                            hex_data = parts[1].split('&')[0]
                            hex_data = unquote_plus(hex_data)
                            update_display_from_buffer(hex_data)
                            saved_status = True
                except Exception as e:
                    print(f"Parsing Error: {e}")

            # --- Send Response ---
            # 변경된 부분: 파일 읽기 함수 호출
            response_html = get_web_page(saved_status)
            
            cl.send('HTTP/1.0 200 OK\r\nContent-type: text/html\r\n\r\n')
            cl.send(response_html)
            
        except OSError as e:
            pass
        except Exception as e:
            print(f"Server Error: {e}")
        finally:
            if cl:
                cl.close()
            gc.collect()

if __name__ == "__main__":
    start_server()