import socket
import serial
import serial.tools.list_ports
import time
import logging

LOG_FILE = "bridge_debug.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, mode="w", encoding="utf-8"),
        logging.StreamHandler()
    ]
)

UDP_PORT = 6454
NUM_STRIPS = 16                            # 16 Univerzum / csík
NUM_LEDS = 58
STRIP_SIZE = NUM_LEDS * 3                  # 174 bájt
FULL_FRAME_SIZE = STRIP_SIZE * NUM_STRIPS  # 2784 bájt (16 * 174)
HEADER = b"\xFF\xBB"

logging.info("=== MAGICQ USB BRIDGE (LOGGER + PICO TELEMETRIA MÓD - 16 UNIVERZUM) ===")

# Automatikus COM-port keresés (Pico, CDC vagy Serial nevű eszközökre)
pico_port = None
for port in serial.tools.list_ports.comports():
    desc = port.description.lower()
    if "board" in desc or "pico" in desc or "serial" in desc or "cdc" in desc:
        pico_port = port.device
        break

if not pico_port:
    pico_port = input("COM port automatikus keresése nem sikerült. Írd be kézzel (pl. COM5): ").strip()

try:
    ser = serial.Serial(pico_port, 115200, timeout=0.005)
    time.sleep(1)
    ser.reset_input_buffer()
    ser.reset_output_buffer()
    logging.info(f"USB Port Nyitva: {pico_port}")
except Exception as e:
    logging.error(f"Sikertelen port nyitás: {e}")
    exit(1)

# SOCKET BEÁLLÍTÁSOK (PORT FOGLALTSÁGI HIBA ELLENI VÉDELEMMEL)
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # Kényszerített port-újrafelhasználás
sock.bind(("127.0.0.1", UDP_PORT))
sock.setblocking(False)

full_frame_buffer = bytearray(FULL_FRAME_SIZE)
FPS_LIMIT = 25
FRAME_INTERVAL = 1.0 / FPS_LIMIT
last_send_time = time.time()

while True:
    # 1. Beolvassuk és logoljuk a Pico felől érkező üzeneteket/statisztikákat
    try:
        if ser.in_waiting > 0:
            pico_msg = ser.readline().decode('utf-8', errors='ignore').strip()
            if pico_msg:
                logging.info(f"[PICO] {pico_msg}")
    except Exception:
        pass

    # 2. Art-Net adatok fogadása MagicQ-ból (mind a 16 univerzumból)
    while True:
        try:
            data, addr = sock.recvfrom(1024)
            if len(data) >= 18 and data[0:8] == b"Art-Net\x00" and data[8] == 0x00 and data[9] == 0x50:
                universe = data[14] | (data[15] << 8)
                if 0 <= universe < NUM_STRIPS:
                    dmx_payload = data[18:]
                    if len(dmx_payload) < STRIP_SIZE:
                        dmx_payload = dmx_payload + b"\x00" * (STRIP_SIZE - len(dmx_payload))
                    else:
                        dmx_payload = dmx_payload[:STRIP_SIZE]

                    start_idx = universe * STRIP_SIZE
                    full_frame_buffer[start_idx : start_idx + STRIP_SIZE] = dmx_payload
        except OSError:
            break

    # 3. Teljes 16 univerzumos USB keret kiküldése 25 FPS-sel
    now = time.time()
    if now - last_send_time >= FRAME_INTERVAL:
        try:
            ser.write(HEADER + full_frame_buffer)
            last_send_time = now
        except Exception as e:
            logging.error(f"USB Írási Hiba: {e}")

    time.sleep(0.001)