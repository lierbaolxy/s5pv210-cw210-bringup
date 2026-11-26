# -*- coding: utf-8 -*-
"""恢复原 Linux (cramfs) 系统：
   mtd1 @0x200000 <- linux_zimage.bin
   mtd2 @0x700000 <- cramfs.bin
   并写回原启动参数
"""
import os, sys, time, traceback
import serial
import round_img as R

R.OUT = os.path.join(R.BASE, "restore_log.txt")

LOAD = 0x30000000
KSIZE = 0x420000          # 4,325,376
K_OFF = 0x200000
R_OFF = 0x700000
BOOTARGS = ("root=/dev/mtdblock2 rootfstype=cramfs init=/linuxrc "
            "console=ttySAC0,115200 "
            "mtdparts=s5pv210-nand:2m(bootloader),5m(kernel),-(rootfs)")
BOOTCMD = "nand read 0x20008000 0x200000 0x500000; bootm 0x20008000"


def safe(ser, cmd, wait=15, idle=60):
    for _ in range(3):
        try:
            return R.send(ser, cmd, wait=wait, idle_limit=idle)
        except Exception as e:
            R.note("  [重试 %s: %s]" % (cmd.split()[0], type(e).__name__))
            time.sleep(1)
    return b""


def main():
    R.note("\n\n===== %s RESTORE linux =====" % time.strftime("%Y-%m-%d %H:%M:%S"))

    ser = None
    t_end = time.time() + 200
    while time.time() < t_end:
        try:
            ser = serial.Serial(R.COM, R.BAUD, timeout=0.05, write_timeout=5)
            break
        except Exception:
            time.sleep(3)
    if ser is None:
        R.note("[!] 无法打开 %s" % R.COM)
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
    R.note("[OK] u-boot 命令行就绪")

    try:
        safe(ser, "setenv ipaddr 192.168.1.100", 5)
        safe(ser, "setenv serverip 192.168.1.13", 5)
        safe(ser, "setenv netmask 255.255.255.0", 5)
        safe(ser, "setenv ethaddr 10:23:45:67:89:ab", 5)

        for tag, fname, off in (("内核", "linux_zimage.bin", K_OFF),
                                ("根文件系统", "cramfs.bin", R_OFF)):
            R.note("\n===== 写入%s -> NAND 0x%08X =====" % (tag, off))
            r = safe(ser, "tftp 0x%08X %s" % (LOAD, fname), wait=120, idle=300)
            if b"Bytes transferred" not in r:
                R.note("[!] tftp 失败，终止")
                R.note(r.decode("latin1", "replace").replace("\r", "")[-400:])
                ser.close()
                return 2
            safe(ser, "nand erase 0x%08X 0x00500000" % off, wait=180, idle=300)
            r = safe(ser, "nand write 0x%08X 0x%08X 0x%08X" % (LOAD, off, KSIZE),
                     wait=300, idle=300)
            t = r.decode("latin1", "replace")
            R.note("  " + ("写入 OK" if "OK" in t else "写入结果需确认"))

        R.note("\n===== 写回启动参数 =====")
        safe(ser, "setenv bootargs '%s'" % BOOTARGS, 8)
        safe(ser, "setenv bootcmd '%s'" % BOOTCMD, 8)
        safe(ser, "setenv machid 0x3F80", 6)
        safe(ser, "printenv bootargs", 8)
        safe(ser, "saveenv", 30, 100)

        R.note("\n===== reset 并抓 150 秒 =====")
        ser.reset_input_buffer()
        ser.write(b"reset\x0d")
        buf = bytearray()
        end = time.time() + 150
        while time.time() < end:
            try:
                d = ser.read(4096)
            except Exception:
                continue
            if d:
                buf.extend(d)
        txt = bytes(buf).decode("latin1", "replace").replace("\r", "")
        open(os.path.join(R.BASE, "restore_dump.bin"), "wb").write(bytes(buf))
        R.note("[串口收到 %d 字节]" % len(buf))
        R.note(txt)
        R.note("\n===== 判定 =====")
        R.note("  内核日志    : %s" % ("是" if "Linux version" in txt else "否"))
        R.note("  cramfs 挂载 : %s" % ("是" if "Mounted root (cramfs" in txt else "否"))
        R.note("  进入 shell  : %s" % ("是" if "~ #" in txt else "否"))
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
