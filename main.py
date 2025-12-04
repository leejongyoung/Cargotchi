import time
import network
import socket
import ujson
import gc
import ubinascii
import urandom
from machine import Pin
from lib.epd2in13_V4 import EPD_2in13_V4_Landscape

# QR 코드는 uQR 의 QRCode / QRData 를 직접 사용
try:
    from uQR import QRCode, QRData, MODE_8BIT_BYTE
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False

HTML_FILE = 'index.html'
EPD_WIDTH = 250
EPD_HEIGHT = 122
CANVAS_HEIGHT = 128      # JS 캔버스 내부 높이 (상단 122라인만 실제로 보임)
BYTES_PER_ROW = (EPD_WIDTH + 7) // 8  # 250px -> 32 bytes


def draw_wifi_qr(epd, ssid, password, x=0, y=0, max_size=100):
    """
    Wi-Fi 설정 QR 코드(WIFI:T:WPA;S:..;P:..;;)를 생성해서
    e-Paper에 (x, y)를 좌상단 기준으로 그린다.
    """
    if not HAS_QRCODE:
        print("qrcode 모듈이 없어 QR 코드는 생략됩니다.")
        return

    try:
        wifi_text = "WIFI:T:WPA;S:{};P:{};;".format(ssid, password)
        qr = QRCode()
        qr_data = QRData(wifi_text, mode=MODE_8BIT_BYTE)
        qr.add_data(qr_data)
        matrix = qr.get_matrix()
        rows = len(matrix)
        cols = len(matrix[0])

        scale = max(1, min(max_size // rows, max_size // cols))

        for j in range(rows):
            for i in range(cols):
                if matrix[j][i]:
                    for dy in range(scale):
                        for dx in range(scale):
                            px = x + i * scale + dx
                            py = y + j * scale + dy
                            if 0 <= px < EPD_WIDTH and 0 <= py < EPD_HEIGHT:
                                epd.pixel(px, py, 0)
        print("Wi-Fi QR 코드 표시 완료.")
    except Exception as e:
        import sys
        sys.print_exception(e)
        raise


def update_display_from_buffer(hex_data):
    """
    브라우저에서 받은 Hex String을 FrameBuffer 기반 e-ink 버퍼로 렌더링.
    """
    print("Processing image data...")
    try:
        src = ubinascii.unhexlify(hex_data)
        src_len = len(src)
        print("Received data length:", src_len, "bytes")

        min_len = BYTES_PER_ROW * EPD_HEIGHT
        if src_len < min_len:
            print("Error: Buffer too short. Expected at least", min_len)
            return

        epd = EPD_2in13_V4_Landscape()
        epd.init()
        epd.fill(1)

        for y in range(EPD_HEIGHT):
            for x in range(EPD_WIDTH):
                byte_index = y * BYTES_PER_ROW + (x // 8)
                bit = x % 8
                mask = 0x80 >> bit
                is_white = 1 if (src[byte_index] & mask) else 0
                epd.pixel(x, y, is_white)

        print("Sending buffer to display...")
        epd.display(epd.buffer)
        print("Putting display to sleep")
        epd.sleep()
        del epd
        del src
        gc.collect()

    except Exception as e:
        print("Display Error:", e)


def send_all(sock, data):
    """
    socket.send()가 전체 데이터를 보내지 못할 경우를 대비한 유틸 함수.
    """
    if isinstance(data, str):
        data = data.encode("utf-8")
    total = 0
    length = len(data)
    while total < length:
        sent = sock.send(data[total:])
        if not sent:
            break
        total += sent

def unquote_plus(s):
    """URL decoding"""
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
    index.html 파일을 읽고, 저장 성공 시 알림 메시지를 주입하여 반환.
    """
    success_script = "alert('전송 완료! 화면이 곧 갱신되고, 디스플레이에 적용됩니다.');" if saved else ""
    
    html_content = ""
    try:
        with open(HTML_FILE, 'r') as f:
            html_content = f.read()
        html_content = html_content.replace('{{SUCCESS_MSG}}', success_script)
    except OSError:
        html_content = "<h1>Error: index.html not found</h1>"
    return html_content


def start_server():
    ap = network.WLAN(network.AP_IF)
    base_ssid = 'Cargochi_'
    suffix = "{:04X}".format(urandom.getrandbits(16))
    ssid = base_ssid + suffix
    password = 'Cargochi1234'
    ap.config(essid=ssid, password=password)
    ap.active(True)

    while not ap.active():
        print("Starting AP...")
        time.sleep(0.5)

    print('AP Active.')
    ip = ap.ifconfig()[0]
    print(f'Connect to WiFi "{ssid}" and visit: http://{ip}')

    try:
        epd = EPD_2in13_V4_Landscape()
        epd.init()
        epd.fill(1)

        draw_wifi_qr(epd, ssid, password, x=4, y=4, max_size=100)

        text_x = 100
        epd.text("Please connect WiFi", text_x, 8, 0)
        epd.text("and Visit URL", text_x, 20, 0)
        epd.text("SSID:", text_x, 38, 0)
        epd.text(ssid, text_x, 50, 0)
        epd.text("PASS:", text_x, 68, 0)
        epd.text(password, text_x, 80, 0)
        epd.text("URL:", text_x, 98, 0)
        epd.text(ip, text_x, 110, 0)

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

            response_html = get_web_page(saved_status)
            send_all(cl, 'HTTP/1.0 200 OK\r\nContent-type: text/html\r\n\r\n')
            send_all(cl, response_html)
            
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