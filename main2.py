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
EPD_HEIGHT = 122

# --- E-Paper Display Function ---
def update_display_from_buffer(hex_data):
    """
    브라우저에서 받은 Hex String을 Bytearray로 변환하여 디스플레이에 표시
    """
    print("Processing image data...")
    try:
        # Hex String을 binary data로 변환
        buffer = ubinascii.unhexlify(hex_data)
        
        epd = EPD_2in13_V4_Landscape()
        epd.init()
        epd.Clear() # 전체 덮어쓰기이므로 Clear 생략 가능 (속도 향상)
        
        print(f"Displaying buffer of length: {len(buffer)}")
        epd.display(buffer)
        
        print("Putting display to sleep")
        epd.sleep()
        
        # 메모리 정리
        del epd
        del buffer
        gc.collect()
        
    except Exception as e:
        print(f"Display Error: {e}")

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
    success_msg = "alert('전송 완료! 화면이 곧 갱신됩니다.');" if saved else ""
    
    # HTML/JS 포함 (브라우저에서 렌더링 담당)
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>Cargotchi Canvas Editor</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; padding: 20px; background: #f0f2f5; display: flex; flex-direction: column; align-items: center; }}
            h1 {{ color: #333; }}
            .container {{ background: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); max-width: 400px; width: 100%; }}
            canvas {{ border: 2px solid #333; margin: 10px auto; display: block; background: white; }}
            input, textarea {{ width: 100%; padding: 10px; margin: 5px 0; border: 1px solid #ddd; border-radius: 6px; box-sizing: border-box; font-size: 16px; }}
            button {{ width: 100%; background: #007aff; color: white; padding: 12px; border: none; border-radius: 6px; font-size: 16px; font-weight: bold; cursor: pointer; margin-top: 10px; }}
            button:active {{ background: #0056b3; }}
            .controls {{ margin-top: 15px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Cargotchi 설정</h1>
            <canvas id="preview" width="{EPD_WIDTH}" height="{EPD_HEIGHT}"></canvas>
            
            <div class="controls">
                <label>전화번호</label>
                <input type="text" id="phone" value="010-1234-5678" oninput="drawCanvas()">
                
                <label>메시지</label>
                <textarea id="message" rows="3" oninput="drawCanvas()">잠시 외출 중입니다.&#13;&#10;택배는 문 앞에 부탁해요!</textarea>
                
                <form id="imgForm" method="post" action="/">
                    <input type="hidden" name="image_data" id="image_data">
                    <button type="button" onclick="submitData()">디스플레이 업데이트</button>
                </form>
            </div>
        </div>

        <script>
            const canvas = document.getElementById('preview');
            const ctx = canvas.getContext('2d');
            const width = {EPD_WIDTH};
            const height = {EPD_HEIGHT};

            // 1. 캔버스에 텍스트 그리기
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
                ctx.font = 'bold 20px sans-serif';
                ctx.fillText('Cargotchi', 10, 10);
                
                // 구분선
                ctx.fillRect(10, 35, width - 20, 2);

                // 전화번호 (큰 글씨)
                ctx.font = 'bold 24px sans-serif';
                ctx.fillText(phone, 10, 45);

                // 메시지 (줄바꿈 처리 필요하면 로직 추가, 여기선 간단히)
                ctx.font = '16px sans-serif';
                const lines = message.split('\\n');
                let y = 80;
                lines.forEach(line => {{
                    ctx.fillText(line, 10, y);
                    y += 20;
                }});
            }}

            // 2. 픽셀 데이터를 E-Paper용 Hex String으로 변환
            function getHexData() {{
                const imgData = ctx.getImageData(0, 0, width, height);
                const data = imgData.data;
                let hexStr = "";
                
                // Waveshare 1-bit 포맷: 가로로 8픽셀씩 1바이트 (MSB First)
                // 0 = Black, 1 = White
                
                for (let y = 0; y < height; y++) {{
                    for (let x = 0; x < width; x += 8) {{
                        let byte = 0x00;
                        for (let bit = 0; bit < 8; bit++) {{
                            if (x + bit < width) {{
                                const i = (y * width + (x + bit)) * 4;
                                // R,G,B 평균이 128보다 크면 흰색(1), 아니면 검정(0)
                                const avg = (data[i] + data[i+1] + data[i+2]) / 3;
                                if (avg > 128) {{
                                    byte |= (0x80 >> bit); // bit set to 1
                                }}
                            }}
                        }}
                        // 1바이트를 2자리 Hex로 변환
                        hexStr += byte.toString(16).padStart(2, '0');
                    }}
                }}
                return hexStr;
            }}

            function submitData() {{
                const hex = getHexData();
                document.getElementById('image_data').value = hex;
                document.getElementById('imgForm').submit();
            }}

            // 초기 로딩 시 그리기
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
    ap.config(essid='Cargotchi', password='cargotchi1234') 
    ap.active(True)

    while not ap.active():
        print("Starting AP...")
        time.sleep(0.5)

    print('AP Active.')
    print(f'Connect to WiFi "Cargotchi" and visit: http://{ap.ifconfig()[0]}')

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