# -*- coding: utf-8 -*-
"""round_fs：用打过补丁的内核（多媒体预留清零）启动，并设法把启动日志取回来。

流程：
  1) 若不在 u-boot 命令行，走 DNW 载入 BL1+BL2
  2) YMODEM 把 zImage_patched.bin（4.25MB）传到 0x20008000
  3) YMODEM 把 bootfs.bin（736B，含 mtdparts 的完整 cmdline）传到 0x2F000000
  4) go 0x2F000000 —— 桩子建 ATAGS、武装看门狗(约32s)、跳内核
  5) 抓串口 CAPTURE 秒
  6) 看门狗复位后板子回到 USB 下载态，重新载入 u-boot，md.b 读 __log_buf
"""
import os
import re
import sys
import threading
import time

import serial

import dnw
from ymodem import send_file

COM, BAUD = "COM3", 115200
BASE = r"C:\Users\20808\WorkBuddy\automation-2026-11-23-13-48-36\dnw-python"
BL1 = os.path.join(BASE, r"x210_image\image\android_system\x210_usb.bin")
BL2 = os.path.join(BASE, r"x210_image\image\normal_system\u-boot_nomenu.bin")
KERNEL = os.path.join(BASE, "vmlinux_patched.bin")
STUB = os.path.join(BASE, "probe", "bootfs.bin")
OUT = os.path.join(BASE, "round_img_log.txt")

CR = b"\x0d"
CAPTURE = int(os.environ.get("CAPTURE", "120"))
LOGBUF = int(os.environ.get("LOGBUF", "0x20892695"), 0)
LOGLEN = int(os.environ.get("LOGLEN", "0x8000"), 0)
# 未压缩内核太大，放不进 5MB 的 kernel 分区；缓存到 NAND 16MB 处，
# 后续每轮测试直接 nand read，省掉 14 分钟 YMODEM。
NAND_OFF = 0x01000000
NAND_SIZE = 0x00900000      # 9MB，128KB 对齐


def note(s=""):
    print(s, flush=True)
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(str(s) + "\n")


def drain(ser, seconds):
    buf = bytearray()
    end = time.time() + seconds
    while time.time() < end:
        d = ser.read(4096)
        if d:
            buf.extend(d)
    return bytes(buf)


def sync_prompt(ser, seconds=15):
    end = time.time() + seconds
    while time.time() < end:
        ser.reset_input_buffer()
        ser.write(b"\x03\r")
        time.sleep(0.25)
        d = ser.read(65536)
        if b"#" in d[-400:]:
            return True
    return False


def send(ser, cmd, wait=30.0, idle_limit=30):
    sync_prompt(ser, 12)
    ser.reset_input_buffer()
    ser.write(cmd.encode() + CR)
    buf = bytearray()
    end = time.time() + wait
    idle = 0
    while time.time() < end:
        d = ser.read(4096)
        if d:
            buf.extend(d)
            idle = 0
            # 必须匹配完整提示符：tftp 的进度条本身全是 '#'，只判断末字符会误判
            if buf.rstrip().endswith(b"tarena #"):
                break
        else:
            idle += 1
            # 长命令（tftp/nand）在等对端响应时会短暂静默，阈值需放宽
            if idle > idle_limit:
                break
    note("\n$ " + cmd)
    note(buf.decode("latin1", "replace").replace("\r", "").strip())
    return bytes(buf)


def alive(ser):
    ser.reset_input_buffer()
    ser.write(b"echo FS_OK" + CR)
    return "FS_OK" in drain(ser, 1.5).decode("latin1")


def download_any(path, addr):
    for dev in dnw.find_devices():
        try:
            rc = dnw.download(dev, addr, path)
        finally:
            try:
                dnw.usb.util.dispose_resources(dev)
            except Exception:
                pass
        if rc == 0:
            return True
    return False


def stage(ser, wait):
    """等 USB 下载态并载入 BL1/BL2，拿到 u-boot 命令行。"""
    # 板子可能已经从 NAND 启动了 u-boot，先看有没有现成提示符
    if sync_prompt(ser, 4):
        note("  [prompt] 已在命令行")
        return True

    end = time.time() + wait
    while time.time() < end:
        if download_any(BL1, 0xD0020010):
            note("  [BL1] OK")
            break
        time.sleep(1.0)
    else:
        return False

    stop = threading.Event()
    sink = bytearray()

    def spam():
        while not stop.is_set():
            try:
                ser.write(CR)
            except Exception:
                return
            time.sleep(0.03)
            try:
                d = ser.read(8192)
            except Exception:
                return
            if d:
                sink.extend(d)

    th = threading.Thread(target=spam, daemon=True)
    th.start()

    time.sleep(1.0)
    end = time.time() + 40
    ok2 = False
    while time.time() < end:
        if download_any(BL2, 0x23E00000):
            note("  [BL2] OK")
            ok2 = True
            break
        time.sleep(0.8)
    if not ok2:
        stop.set()
        th.join(timeout=1)
        return False

    t0 = time.time()
    while time.time() - t0 < 20:
        if b"tarena #" in sink or b"tarena#" in sink:
            stop.set()
            th.join(timeout=1)
            note("  [prompt] 抓住命令行")
            return True
        time.sleep(0.2)
    stop.set()
    th.join(timeout=1)
    note("  [dump] " + sink.decode("latin1", "replace").replace("\r", "")[-400:])
    return b"tarena" in sink


def wait_token(ser, token, seconds):
    buf = bytearray()
    end = time.time() + seconds
    while time.time() < end:
        d = ser.read(4096)
        if d:
            buf.extend(d)
            if token in buf:
                return True
    return False


def ymodem(ser, path, addr):
    sync_prompt(ser, 10)
    ser.reset_input_buffer()
    ser.write(("loady 0x%08x" % addr).encode() + CR)
    if not wait_token(ser, b"Ready", 12):
        note("  [!] loady 未就绪")
        return False
    t0 = time.time()
    ok = send_file(ser, path, addr)
    note("  [%s] YMODEM %s -> 0x%08X  用时 %.0fs" %
         ("OK" if ok else "!", os.path.basename(path), addr, time.time() - t0))
    drain(ser, 0.5)
    return ok


def read_logbuf(ser):
    """md.b 读 __log_buf 并还原成文本。"""
    sync_prompt(ser, 12)
    ser.reset_input_buffer()
    ser.write(("md.b 0x%08X 0x%X" % (LOGBUF, LOGLEN)).encode() + CR)
    buf = bytearray()
    end = time.time() + 120
    while time.time() < end:
        d = ser.read(4096)
        if d:
            buf.extend(d)
            # 必须匹配完整提示符：tftp 的进度条本身全是 '#'，只判断末字符会误判
            if buf.rstrip().endswith(b"tarena #"):
                break
    raw = os.path.join(BASE, "logbuf_fs_raw.txt")
    with open(raw, "wb") as f:
        f.write(buf)

    # 解析 "20892695: 4c 69 6e 75 78 ..." 每行最多 16 字节
    out = bytearray()
    for line in buf.decode("latin1").splitlines():
        m = re.match(r"^[0-9a-fA-F]{8}:(.*)$", line.strip())
        if not m:
            continue
        hexs = re.findall(r"\b[0-9a-fA-F]{2}\b", m.group(1))
        for h in hexs[:16]:
            out.append(int(h, 16))
    txt = out.decode("latin1", "replace")
    with open(os.path.join(BASE, "logbuf_fs.txt"), "w", encoding="utf-8", errors="replace") as f:
        f.write(txt)
    note("[logbuf] 还原 %d 字节" % len(out))
    return txt


def main():
    note("\n\n===== %s round_img =====" % time.strftime("%Y-%m-%d %H:%M:%S"))
    if not os.path.exists(KERNEL):
        note("[!] 缺 %s，先跑 patch_kernel.py" % KERNEL)
        return 1
    note("内核镜像 %s  %d 字节" % (os.path.basename(KERNEL), os.path.getsize(KERNEL)))

    ser = serial.Serial(COM, BAUD, timeout=0.05, write_timeout=30)
    try:
        ser.dtr = False
        ser.rts = False
    except Exception:
        pass

    if not alive(ser):
        note("----- 等 USB 下载态（请按一次 RESET，拨码 ON OFF OFF ON，最多 300 秒）-----")
        if not stage(ser, 300):
            note("[!] 拿不到命令行")
            ser.close()
            return 1
    note("[OK] 命令行就绪")

    # 1) 优先从 NAND 16MB 处的缓存加载未压缩内核；没有才 YMODEM 并写入
    note("----- 尝试从 NAND 0x%08X 加载未压缩内核缓存 -----" % NAND_OFF)
    send(ser, "nand read 0x20008000 0x%08X 0x%08X" % (NAND_OFF, NAND_SIZE), wait=120)
    r = send(ser, "md.l 0x20008000 1", wait=12)
    if b"e321f0d3" not in r:
        note("  [NAND] 缓存无效，改走 YMODEM（约 14 分钟）")
        if not ymodem(ser, KERNEL, 0x20008000):
            ser.close()
            return 1
        r = send(ser, "md.l 0x20008000 1", wait=12)
        if b"e321f0d3" not in r:
            note("  [!] 0x20008000 首字不是 e321f0d3，镜像可能没传对")
        else:
            note("----- 把未压缩内核写入 NAND 0x%08X 缓存 -----" % NAND_OFF)
            send(ser, "nand erase 0x%08X 0x%08X" % (NAND_OFF, NAND_SIZE), wait=180)
            send(ser, "nand write 0x20008000 0x%08X 0x%08X" % (NAND_OFF, NAND_SIZE), wait=180)
            send(ser, "nand read 0x24000000 0x%08X 0x%08X" % (NAND_OFF, NAND_SIZE), wait=120)
            r2 = send(ser, "md.l 0x24000000 1", wait=12)
            note("  [NAND] 回读首字: " + ("OK" if b"e321f0d3" in r2 else "FAIL"))
    else:
        note("  [OK] NAND 缓存内核有效，跳过 YMODEM")

    # 2) 启动桩
    if not ymodem(ser, STUB, 0x2F000000):
        ser.close()
        return 1
    send(ser, "md.l 0x2F000000 1", wait=12)

    # 3) 跳
    note("\n===== go 0x2F000000，抓 %d 秒 =====" % CAPTURE)
    sync_prompt(ser, 10)
    ser.reset_input_buffer()
    ser.write(b"go 0x2F000000" + CR)
    buf = bytearray()
    t_end = time.time() + CAPTURE
    resent = False
    while time.time() < t_end:
        dd = ser.read(4096)
        if dd:
            buf.extend(dd)
        elif not resent and len(buf) == 0 and time.time() > t_end - CAPTURE + 4:
            note("  [!] go 后 4 秒无输出，重发一次")
            ser.write(b"go 0x2F000000" + CR)
            resent = True
    buf = bytes(buf)
    with open(os.path.join(BASE, "round_img_dump.bin"), "wb") as f:
        f.write(buf)
    note("[串口收到 %d 字节]" % len(buf))
    note(buf.decode("latin1", "replace").replace("\r", ""))

    # 4) 看门狗复位后重新进 u-boot，读日志
    note("\n----- 等板子复位后重新进 u-boot（最多 180 秒）-----")
    time.sleep(5)
    if stage(ser, 180):
        txt = read_logbuf(ser)
        note("\n===== __log_buf 前 6000 字 =====")
        note(txt[:6000])
    else:
        note("[!] 没能重新进入 u-boot，读不到日志")

    ser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
