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

# --- Configuration ---
CONFIG_FILE = 'config.json'
# Waveshare Pico-ePaper-2.13 V4 Landscape resolution
EPD_WIDTH = 250
EPD_HEIGHT = 122  # display height (visible area)
CANVAS_HEIGHT = 128      # JS 캔버스 내부 높이 (상단 122라인만 실제로 보임)
BYTES_PER_ROW = (EPD_WIDTH + 7) // 8  # 250px -> 32 bytes


# --- QR 코드 그리기 도우미 ---
def draw_wifi_qr(epd, ssid, password, x=0, y=0, max_size=100):
    """
    Wi-Fi 설정 QR 코드(WIFI:T:WPA;S:..;P:..;;)를 생성해서
    e-Paper에 (x, y)를 좌상단 기준으로 그린다.

    uQR 모듈이 없다면 조용히 스킵한다.
    """
    if not HAS_QRCODE:
        print("qrcode 모듈이 없어 QR 코드는 생략됩니다.")
        return

    try:
        # 표준 Wi-Fi QR 포맷
        wifi_text = "WIFI:T:WPA;S:{};P:{};;".format(ssid, password)

        # uQR 의 QRData 를 직접 사용해서 모드를 강제로 8비트로 고정
        qr = QRCode()
        qr_data = QRData(wifi_text, mode=MODE_8BIT_BYTE)
        qr.add_data(qr_data)
        matrix = qr.get_matrix()
        rows = len(matrix)
        cols = len(matrix[0])

        # 주어진 max_size 안에 들어가도록 스케일 결정 (정수 배율)
        scale = max(1, min(max_size // rows, max_size // cols))

        for j in range(rows):
            for i in range(cols):
                if matrix[j][i]:
                    # scale 배율로 각 모듈을 사각형으로 채우기
                    for dy in range(scale):
                        for dx in range(scale):
                            px = x + i * scale + dx
                            py = y + j * scale + dy
                            if 0 <= px < EPD_WIDTH and 0 <= py < EPD_HEIGHT:
                                epd.pixel(px, py, 0)  # 0 = 검정
        print("Wi-Fi QR 코드 표시 완료.")
    except Exception as e:
        import sys
        sys.print_exception(e)
        raise


# --- E-Paper Display Function ---
def update_display_from_buffer(hex_data):
    """
    브라우저에서 받은 Hex String(가로 250, 세로 128, 1bpp)을
    FrameBuffer 기반 e-ink 버퍼로 다시 렌더링해서 표시.

    JS 비트 의미: 1 = 흰색, 0 = 검정
    FrameBuffer(epd.pixel) 색상: 1 = 흰색, 0 = 검정
    """
    print("Processing image data...")
    try:
        src = ubinascii.unhexlify(hex_data)
        src_len = len(src)
        print("Received data length:", src_len, "bytes")

        # 상단 122라인(실제 표시 영역)에 필요한 최소 바이트 수
        min_len = BYTES_PER_ROW * EPD_HEIGHT
        if src_len < min_len:
            print("Error: Buffer too short (", src_len, "). Expected at least", min_len)
            return

        epd = EPD_2in13_V4_Landscape()
        epd.init()
        epd.fill(1)  # 전체를 흰색으로 초기화

        # JS 버퍼(250x128)의 상단 122라인만 사용
        # src 인덱싱:
        #  - 한 줄당 BYTES_PER_ROW 바이트
        #  - x 픽셀 비트 위치: 0x80 >> (x % 8)
        for y in range(EPD_HEIGHT):       # 0 ~ 121
            for x in range(EPD_WIDTH):    # 0 ~ 249
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

# --- Web Server Helpers ---
def send_all(sock, data):
    """
    socket.send() 가 전체 데이터를 한 번에 보내지 못할 수 있으므로
    끝까지 반복해서 보내는 유틸 함수.
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

def create_web_page(saved=False):
    """
    루트의 index.html 파일을 그대로 서빙한다.
    - index.html 이 Hex 생성 및 POST(image_data=...) 까지 담당
    - saved 파라미터는 현재 별도 표시 없이 무시
    """
    try:
        with open('index.html', 'r') as f:
            return f.read()
    except Exception as e:
        # index.html 이 없거나 읽기 실패 시 간단한 안내 페이지
        return """<!DOCTYPE html>
        <html><head><meta charset="utf-8"><title>Cargochi</title></head>
        <body><h3>index.html 을 찾을 수 없습니다.</h3>
        <p>루트에 index.html 파일이 있는지 확인해 주세요.</p></body></html>"""

# --- Server Logic ---
def start_server():
    # Start Access Point
    ap = network.WLAN(network.AP_IF)
    # SSID를 Cargochi_XXXX 형태로 생성 (XXXX = 랜덤 4자리 영문/숫자)
    base_ssid = 'Cargochi_'
    # 0-9A-F 16진수 4자리를 랜덤 생성 (영문+숫자)
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

    # 부팅 시 e-Paper에 접속 정보를 한 번 표시 (좌측에 Wi-Fi QR 코드)
    try:
        epd = EPD_2in13_V4_Landscape()
        epd.init()
        epd.fill(1)

        # 왼쪽에 Wi-Fi QR 코드 (대략 100x100 내)
        draw_wifi_qr(epd, ssid, password, x=4, y=4, max_size=100)

        # 오른쪽에 텍스트 정보
        text_x = 100  # QR 코드 오른쪽 여백 이후
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
            
            # --- Robust Request Reading ---
            # 1. Read headers
            cl.settimeout(2.0)
            request_file = cl.makefile('rwb', 0)
            
            # 헤더와 바디 분리 로직
            header_lines = []
            while True:
                line = request_file.readline()
                if not line or line == b'\r\n':
                    break
                header_lines.append(line)
            
            content_length = 0
            is_post = False
            
            # 헤더 분석
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

            # 2. Read Body (POST Data)
            # 대량의 데이터를 읽어야 하므로 버퍼 사이즈 주의
            post_data = b""
            if is_post and content_length > 0:
                print(f"Reading body of size: {content_length}")
                post_data = request_file.read(content_length)

            # --- Process Data ---
            saved_status = False
            if is_post and post_data:
                # 간단한 파싱 (메모리 절약을 위해 정규식 대신 split 사용)
                # 데이터 형태: image_data=FFFF00...
                try:
                    body_str = post_data.decode('utf-8')
                    if 'image_data=' in body_str:
                        # 'image_data=' 이후의 데이터만 추출
                        parts = body_str.split('image_data=')
                        if len(parts) > 1:
                            hex_data = parts[1].split('&')[0] # 뒤에 다른 파라미터가 있을 경우 제거
                            hex_data = unquote_plus(hex_data) # URL decode
                            
                            # 디스플레이 업데이트
                            update_display_from_buffer(hex_data)
                            saved_status = True
                except Exception as e:
                    print(f"Parsing Error: {e}")

            # --- Send Response ---
            response_html = create_web_page(saved_status)
            # socket.send() 가 일부만 보낼 수 있으므로 send_all() 로 반복 전송
            send_all(cl, 'HTTP/1.0 200 OK\r\nContent-type: text/html\r\n\r\n')
            send_all(cl, response_html)
            
        except OSError as e:
            pass
        except Exception as e:
            print(f"Server Error: {e}")
        finally:
            if cl:
                cl.close()
            gc.collect() # 중요: 메모리 해제

# --- Main ---
if __name__ == "__main__":
    start_server()