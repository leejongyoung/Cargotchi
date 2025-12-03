import time
import network
import socket
import ujson
import gc
import ubinascii
from machine import Pin
from lib.epd2in13_V4 import EPD_2in13_V4_Landscape

# --- Configuration ---
CONFIG_FILE = 'config.json'
# Waveshare Pico-ePaper-2.13 V4 Landscape resolution
EPD_WIDTH = 250
EPD_HEIGHT = 122  # display height (visible area)
CANVAS_HEIGHT = 128      # JS 캔버스 내부 높이 (상단 122라인만 실제로 보임)
BYTES_PER_ROW = (EPD_WIDTH + 7) // 8  # 250px -> 32 bytes

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
    success_msg = "alert('전송 완료! 화면이 곧 갱신되고, 디스플레이에 적용됩니다.');" if saved else ""

    # PC의 index.html 과 유사한 UI를 임베디드로 서빙
    html = f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Cargochi e-Paper 설정</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; padding: 20px; background: #f5f5f5; max-width: 600px; margin: 0 auto; }}
            .container {{ background: white; padding: 20px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
            .canvas-container {{
                width: 250px;
                height: 122px;         /* 실제 보이는 높이 */
                overflow: hidden;      /* 128px 중 넘치는 부분 숨김 */
                border: 2px solid #333;
                margin: 20px auto;
                background: white;
            }}
            canvas {{
                display: block;
                background: white;
            }}
            .input-group {{ margin-bottom: 15px; }}
            label {{ display: block; margin-bottom: 5px; font-weight: bold; }}
            input[type="text"], textarea {{ width: 100%; padding: 8px; border: 1px solid #ddd; border-radius: 4px; box-sizing: border-box; }}
            button {{ width: 100%; padding: 12px; background: #007aff; color: white; border: none; border-radius: 4px; font-size: 16px; cursor: pointer; }}
            .info {{ font-size: 12px; color: #666; margin-top: 5px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h2>Cargochi e-Paper 설정 (250x128 내부 / 250x122 표시)</h2>
            <p class="info">Wi-Fi에 접속한 뒤, 아래에서 내용을 수정하고 버튼을 누르면 e-Paper가 바로 갱신됩니다.</p>

            <div class="canvas-container">
                <canvas id="preview" width="250" height="128"></canvas>
            </div>

            <div class="input-group">
                <label>전화번호</label>
                <input type="text" id="phone" value="010-1234-5678" oninput="drawCanvas()">
            </div>

            <div class="input-group">
                <label>메시지</label>
                <textarea id="message" rows="3" oninput="drawCanvas()">잠시 외출 중입니다.&#13;&#10;택배는 문 앞에 부탁해요!&#13;&#10;(한글 테스트)</textarea>
            </div>

            <form id="imgForm" method="post" action="/">
                <input type="hidden" name="image_data" id="image_data">
                <button type="button" onclick="generateAndSend()">Hex 데이터 생성 및 전송</button>
            </form>
        </div>

        <script>
            const canvas = document.getElementById('preview');
            const ctx = canvas.getContext('2d');

            const width = 250;
            const height = 128;  // 내부 버퍼 기준

            function drawCanvas() {{
                const phone = document.getElementById('phone').value;
                const message = document.getElementById('message').value;

                // 배경 초기화 (흰색)
                ctx.fillStyle = 'white';
                ctx.fillRect(0, 0, width, height);

                // 텍스트 설정 (검정)
                ctx.fillStyle = 'black';
                ctx.textBaseline = 'top';

                // 타이틀
                ctx.font = 'bold 20px "Malgun Gothic", sans-serif';
                ctx.fillText('Cargochi', 10, 10);

                // 구분선
                ctx.fillRect(10, 38, width - 20, 2);

                // 전화번호
                ctx.font = 'bold 26px sans-serif';
                ctx.fillText(phone, 10, 48);

                // 메시지
                ctx.font = '16px "Malgun Gothic", sans-serif';
                const lines = message.split('\\n');
                let y = 85;
                lines.forEach(line => {{
                    ctx.fillText(line, 10, y);
                    y += 22;
                }});
            }}

            function getHexData() {{
                const imgData = ctx.getImageData(0, 0, width, height);
                const data = imgData.data;
                let hexStr = "";

                // Waveshare 1-bit 포맷: 가로 방향, 8픽셀 = 1바이트 (MSB First)
                // 0 = Black, 1 = White
                for (let y = 0; y < height; y++) {{
                    for (let x = 0; x < width; x += 8) {{
                        let byte = 0x00;
                        for (let bit = 0; bit < 8; bit++) {{
                            const currentX = x + bit;
                            if (currentX < width) {{
                                const i = (y * width + currentX) * 4;
                                const avg = (data[i] + data[i+1] + data[i+2]) / 3;
                                if (avg > 128) {{
                                    byte |= (0x80 >> bit);  // 흰색(1)
                                }}
                            }} else {{
                                byte |= (0x80 >> bit);      // 오른쪽 패딩은 흰색
                            }}
                        }}
                        hexStr += byte.toString(16).padStart(2, '0');
                    }}
                }}
                return hexStr;
            }}

            function generateAndSend() {{
                drawCanvas();
                const hex = getHexData();
                document.getElementById('image_data').value = hex;
                document.getElementById('imgForm').submit();
            }}

            // 초기 실행
            drawCanvas();
            {success_msg}
        </script>
    </body>
    </html>
    """
    return html

# --- Server Logic ---
def start_server():
    # Start Access Point
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

    # 부팅 시 e-Paper에 접속 정보를 한 번 표시
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
            cl.send('HTTP/1.0 200 OK\r\nContent-type: text/html\r\n\r\n')
            cl.send(response_html)
            
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