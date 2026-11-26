# -*- coding: utf-8 -*-
"""把 machid 改回 0x998（原厂默认）并重启，验证 Linux 系统"""
import os, sys, time, traceback
import serial
import round_img as R

R.OUT = os.path.join(R.BASE, "boot_fix_log.txt")
BOOTARGS = ("root=/dev/mtdblock2 rootfstype=cramfs init=/linuxrc "
            "console=ttySAC0,115200 "
            "mtdparts=s5pv210-nand:2m(bootloader),5m(kernel),-(rootfs)")
CAPTURE = int(os.environ.get("CAPTURE", "150"))


def safe(ser, cmd, wait=12, idle=60):
    for _ in range(3):
        try:
            return R.send(ser, cmd, wait=wait, idle_limit=idle)
        except Exception:
            time.sleep(1)
    return b""


def main():
    R.note("\n\n===== %s boot_fix (machid 0x998) =====" % time.strftime("%Y-%m-%d %H:%M:%S"))

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
        safe(ser, "setenv machid 0x998", 6)
        safe(ser, "setenv bootargs '%s'" % BOOTARGS, 8)
        safe(ser, "printenv machid", 6)
        safe(ser, "printenv bootargs", 8)
        safe(ser, "saveenv", 30, 100)

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
        open(os.path.join(R.BASE, "boot_fix_dump.bin"), "wb").write(bytes(buf))
        R.note("[串口收到 %d 字节]" % len(buf))
        R.note(txt)
        R.note("\n===== 判定 =====")
        R.note("  内核日志    : %s" % ("是" if "Linux version" in txt else "否"))
        R.note("  cramfs 挂载 : %s" % ("是" if "Mounted root (cramfs" in txt else "否"))
        R.note("  shell 提示符: %s" % ("是" if "~ #" in txt else "否"))
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
