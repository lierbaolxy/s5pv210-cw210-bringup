# -*- coding: utf-8 -*-
"""只重写干净版 cramfs 到 0x700000，然后重启验证"""
import os, sys, time, traceback
import serial
import round_img as R

R.OUT = os.path.join(R.BASE, "fix_cramfs_log.txt")
LOAD = 0x30000000
SIZE = 0x340000
OFF = 0x700000
CAPTURE = int(os.environ.get("CAPTURE", "150"))


def safe(ser, cmd, wait=12, idle=60):
    for _ in range(3):
        try:
            return R.send(ser, cmd, wait=wait, idle_limit=idle)
        except Exception:
            time.sleep(1)
    return b""


def main():
    R.note("\n\n===== %s fix_cramfs =====" % time.strftime("%Y-%m-%d %H:%M:%S"))

    ser = None
    t_end = time.time() + 200
    while time.time() < t_end:
        try:
            ser = serial.Serial(R.COM, R.BAUD, timeout=0.05, write_timeout=5)
            break
        except Exception:
            time.sleep(3)
    if ser is None:
        R.note("[!] 无法打开串口")
        return 1
    try:
        ser.dtr = False
        ser.rts = False
    except Exception:
        pass
    R.note("[OK] 串口已打开")

    ok = False
    t_end = time.time() + 300
    while time.time() < t_end:
        try:
            if R.sync_prompt(ser, 20):
                ok = True
                break
        except Exception:
            time.sleep(1)
    if not ok:
        R.note("[!] 抢不到 u-boot 命令行")
        ser.close()
        return 1
    R.note("[OK] u-boot 就绪")

    try:
        safe(ser, "setenv ipaddr 192.168.1.100", 5)
        safe(ser, "setenv serverip 192.168.1.13", 5)
        safe(ser, "setenv ethaddr 10:23:45:67:89:ab", 5)

        R.note("\n===== 写干净版 cramfs -> 0x%08X =====" % OFF)
        r = safe(ser, "tftp 0x%08X cramfs2.bin" % LOAD, wait=120, idle=300)
        if b"Bytes transferred" not in r:
            R.note("[!] tftp 失败")
            R.note(r.decode("latin1", "replace").replace("\r", "")[-400:])
            ser.close()
            return 2
        safe(ser, "nand erase 0x%08X 0x00500000" % OFF, wait=180, idle=300)
        r = safe(ser, "nand write 0x%08X 0x%08X 0x%08X" % (LOAD, OFF, SIZE),
                 wait=300, idle=300)
        R.note("  " + ("写入 OK" if "OK" in r.decode("latin1", "replace") else "见下"))
        R.note(r.decode("latin1", "replace").replace("\r", "")[-300:])

        R.note("\n===== reset 抓 %d 秒 =====" % CAPTURE)
        ser.reset_input_buffer()
        ser.write(b"reset\x0d")
        buf = bytearray()
        end = time.time() + CAPTURE
        while time.time() < end:
            try:
                d = ser.read(4096)
            except Exception:
                continue
            if d:
                buf.extend(d)
        txt = bytes(buf).decode("latin1", "replace").replace("\r", "")
        open(os.path.join(R.BASE, "fix_cramfs_dump.bin"), "wb").write(bytes(buf))
        R.note("[串口收到 %d 字节]" % len(buf))
        R.note(txt)
        R.note("\n===== 判定 =====")
        R.note("  cramfs 挂载 : %s" % ("是" if "Mounted root (cramfs" in txt else "否"))
        R.note("  bad blocksize: %s" % ("有" if "bad compressed blocksize" in txt else "无"))
        R.note("  linuxrc 执行 : %s" % ("成功" if "Failed to execute /linuxrc" not in txt else "失败"))
        R.note("  shell 提示符 : %s" % ("是" if "~ #" in txt else "否"))
    except Exception:
        R.note("[异常]\n" + traceback.format_exc())
    finally:
        try:
            ser.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
