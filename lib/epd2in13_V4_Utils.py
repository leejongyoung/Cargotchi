import ubinascii

def display_js_hex_image(epd, hex_data):
    """
    웹(Canvas)에서 생성된 Hex String을 E-Paper 객체에 그리는 함수
    
    Args:
        epd: 초기화된 EPD_2in13_V4_Landscape 객체
        hex_data (str): 가로 250px, 세로 128px 기준의 1bpp Hex 문자열
    """
    
    # 브라우저 Canvas 스펙 정의
    CANVAS_WIDTH = 250
    VISIBLE_HEIGHT = 122
    BYTES_PER_ROW = (CANVAS_WIDTH + 7) // 8  # 32 bytes

    print("[Utils] Processing Hex Image...")

    try:
        # 1. Hex String -> Bytes 변환
        src = ubinascii.unhexlify(hex_data)
        
        # 2. 화면 버퍼 초기화 (흰색)
        # epd 객체의 메소드를 사용합니다.
        epd.fill(1)

        # 3. 픽셀 매핑 (Row-major -> FrameBuffer VLSB)
        for y in range(VISIBLE_HEIGHT):
            for x in range(CANVAS_WIDTH):
                byte_index = y * BYTES_PER_ROW + (x // 8)
                
                if byte_index >= len(src):
                    break
                    
                bit = x % 8
                mask = 0x80 >> bit
                
                # 1=White, 0=Black
                is_white = 1 if (src[byte_index] & mask) else 0
                
                # epd 객체에 점을 찍습니다.
                epd.pixel(x, y, is_white)

        # 4. 화면 갱신
        print("[Utils] Sending buffer to display...")
        epd.display(epd.buffer)
        
    except Exception as e:
        print("[Utils] Error:", e)