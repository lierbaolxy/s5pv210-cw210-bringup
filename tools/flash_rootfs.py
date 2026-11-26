# -*- coding: utf-8 -*-
"""MEZIO_BOX (S5PV210) 串口 + TFTP 自动烧录 rootfs（含开机画面）"""
import os, re, socket, sys, threading, time, zlib
import serial

BOARD_IP = "192.168.1.6"
SERVER_IP = "192.168.1.13"
NETMASK = "255.255.255.0"
FILE = "rootfs_splash.cramfs"
ROOT = r"g:\lcd\bootimg"
IMG = os.path.join(ROOT, FILE)
SIZE = os.path.getsize(IMG)
SIZE_HEX = "0x%X" % SIZE
CRC_EXPECT = zlib.crc32(open(IMG, "rb").read()) & 0xFFFFFFFF
LOG = open(os.path.join(ROOT, "flash_log.txt"), "w", encoding="utf-8", buffering=1)
SERIAL_LOG = bytearray()

def log(*a):
    s = " ".join(str(x) for x in a)
    print(s)
    LOG.write(s + "\n")

# ---------------- TFTP server ----------------
stop_flag = threading.Event()
tftp_state = {"done": False, "bytes": 0, "error": None}

def tftp_server():
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("", 69))
    srv.settimeout(1.0)
    log("[tftp] listening on :69, file=%s size=%d crc=%08X" % (FILE, SIZE, CRC_EXPECT))
    while not stop_flag.is_set():
        try:
            data, addr = srv.recvfrom(2048)
        except socket.timeout:
            continue
        except Exception as e:
            log("[tftp] recv err", e); continue
        if len(data) < 4 or data[:2] != b"\x00\x01":
            continue
        parts = data[2:].split(b"\x00")
        fn = parts[0].decode("latin1")
        log("[tftp] RRQ %r from %s" % (fn, addr))
        if fn != FILE:
            srv.sendto(b"\x00\x05\x00\x01Not found\x00", addr)
            continue
        payload = open(IMG, "rb").read()
        ds = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        ds.bind(("", 0)); ds.settimeout(0.8)
        blk, off = 1, 0
        ok = False
        while True:
            chunk = payload[off:off + 512]
            pkt = b"\x00\x03" + blk.to_bytes(2, "big") + chunk
            for _ in range(8):
                ds.sendto(pkt, addr)
                try:
                    ack, _ = ds.recvfrom(2048)
                    if ack[:4] == b"\x00\x04" + blk.to_bytes(2, "big"):
                        break
                except socket.timeout:
                    continue
            else:
                tftp_state["error"] = "ACK timeout at block %d" % blk
                log("[tftp] " + tftp_state["error"])
                ds.close(); break
            off += len(chunk)
            if len(chunk) < 512:
                ok = True
                break
            blk = (blk + 1) & 0xFFFF
            if off % (512 * 200) == 0:
                log("[tftp] %d/%d bytes" % (off, len(payload)))
        ds.close()
        if ok:
            tftp_state["done"] = True
            tftp_state["bytes"] = off
            log("[tftp] transfer complete: %d bytes" % off)
    srv.close()

# ---------------- serial helpers ----------------
class Uart:
    def __init__(self):
        self.ser = serial.Serial("COM3", 115200, timeout=0.1)
        self.buf = b""
    def write(self, s):
        self.ser.write(s.encode("latin1")); self.ser.flush()
    def read_some(self):
        try:
            d = self.ser.read(4096)
        except Exception:
            return b""
        if d:
            self.buf += d
            SERIAL_LOG.extend(d)
            try:
                txt = d.decode("utf-8", "replace")
            except Exception:
                txt = str(d)
            sys.stdout.write(txt); sys.stdout.flush()
            LOG.write(txt)
        return d
    def wait(self, needles, timeout, key_tick=None, quiet=False):
        if isinstance(needles, (bytes, str)):
            needles = [needles]
        needles = [n.encode() if isinstance(n, str) else n for n in needles]
        end = time.time() + timeout
        last_tick = 0
        while time.time() < end:
            self.read_some()
            for n in needles:
                if n in self.buf:
                    self.buf = b""
                    return n
            if key_tick and time.time() - last_tick > key_tick:
                self.ser.write(b"\r")
                last_tick = time.time()
        return None
    def cmd(self, c, timeout=20):
        self.buf = b""
        self.write(c + "\r")
        r = self.wait(["tarena #"], timeout)
        if r is None:
            log("[!] command timeout: %s" % c)
        return r is not None

def main():
    u = Uart()
    u.buf = b""
    log("=== 1. 重启进 u-boot ===")
    # 先 Ctrl+C 退出可能正在运行的 top 等前台程序，回到 shell
    for _ in range(3):
        u.write("\x03"); time.sleep(0.3)
    u.write("\r"); time.sleep(0.5)
    u.read_some()
    u.buf = b""
    u.write("reboot\r")
    log("reboot sent, waiting for u-boot prompt...")
    if u.wait(["tarena #"], 70, key_tick=0.25) is None:
        log("[!] 未能进入 u-boot"); return 2
    log("=== 2. 已进入 u-boot ===")

    cmds = [
        ("setenv ipaddr %s" % BOARD_IP, 10),
        ("setenv serverip %s" % SERVER_IP, 10),
        ("setenv netmask %s" % NETMASK, 10),
        ("setenv ethaddr 10:23:45:67:89:ab", 10),
        ("tftp 0x30000000 %s" % FILE, 150),
    ]
    for c, t in cmds:
        log(">>> " + c)
        if not u.cmd(c, t):
            return 3
        if c.startswith("tftp") and not tftp_state["done"]:
            log("[!] TFTP 未完成"); return 3

    # 校验下载内容
    SERIAL_LOG.clear()
    u.buf = b""
    u.write("crc32 0x30000000 %s\r" % SIZE_HEX)
    time.sleep(3)
    u.read_some()
    text = SERIAL_LOG.decode("latin1", "ignore")
    m = re.findall(r"CRC32 for [0-9a-fA-Fx]+ \.\.\. [0-9a-fA-F]+ ==> ([0-9a-fA-F]{8})", text)
    got = int(m[-1], 16) if m else None
    log("CRC expect=%08X got=%s" % (CRC_EXPECT, ("%08X" % got) if got is not None else "?"))
    if got is not None and got != CRC_EXPECT:
        log("[!] CRC 不一致，终止"); return 4
    u.wait(["tarena #"], 10)

    log("=== 3. 擦除并写入 rootfs ===")
    if not u.cmd("nand erase 0x700000 0x400000", 60):
        return 5
    if not u.cmd("nand write 0x30000000 0x700000 %s" % SIZE_HEX, 120):
        return 5

    log("=== 4. 更新 bootargs（加 logo.nologo）===")
    bootargs = ("root=/dev/mtdblock2 rootfstype=cramfs init=/linuxrc console=ttySAC0,115200 "
                "logo.nologo mtdparts=s5pv210-nand:2m(bootloader),5m(kernel),-(rootfs)")
    if not u.cmd("setenv bootargs '%s'" % bootargs, 10):
        return 6
    if not u.cmd("printenv bootargs", 10):
        return 6
    if not u.cmd("saveenv", 30):
        return 6

    log("=== 5. 启动系统 ===")
    u.buf = b""
    u.write("boot\r")
    if u.wait(["~ #", "login:"], 120) is None:
        log("[!] 未等到系统 shell")
        return 7
    log("=== 烧录完成，系统已启动 ===")
    time.sleep(1)
    u.write("cat /usr/share/splash/lesening.fb > /dev/fb0\r")
    time.sleep(2)
    log("已触发显示冷酸灵图片")
    return 0

if __name__ == "__main__":
    th = threading.Thread(target=tftp_server, daemon=True); th.start()
    time.sleep(0.5)
    rc = -1
    try:
        rc = main()
    finally:
        stop_flag.set()
        log("exit code:", rc)
