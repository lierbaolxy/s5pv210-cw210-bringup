# -*- coding: utf-8 -*-
"""从当前 u-boot 状态续接分段烧写。

适用场景：某一段的 tftp 已经完成、数据仍在 DRAM 0x30000000，
但脚本因串口误判提前退出。此时不必重传该段，直接从写入开始。

用法：
    python resume_flash.py            # 从第 1 段写入开始，继续到第 6 段
    python resume_flash.py 3          # 从第 3 段的 tftp 开始（前两段已写）

NAND 偏移按页累加：每 10000 页镜像占 20,480,000 字节 NAND 空间。
"""
import os
import sys
import time

import serial

import round_img as R

R.OUT = os.path.join(R.BASE, "resume_flash_log.txt")

PC_IP = "192.168.1.13"
DEV_IP = "192.168.1.100"
LOAD = 0x30000000
NAND_BASE = 0x00700000
DATA = 2048
PAGE = 2112

CHUNKS = [
    ("rootfs_p01.bin", 10000),
    ("rootfs_p02.bin", 10000),
    ("rootfs_p03.bin", 10000),
    ("rootfs_p04.bin", 10000),
    ("rootfs_p05.bin", 10000),
    ("rootfs_p06.bin", 5427),
]

BOOTARGS_A = ("root=/dev/mtdblock2 rootfstype=yaffs2 init=/init "
              "console=ttySAC0,115200")
BOOTCMD_A = "nand read 0x20008000 0x200000 0x500000; bootm 0x20008000"


def main():
    start_from = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    # start_from = 1 表示第一段已在 DRAM，只需写入；>=2 表示需要 tftp
    # 带 full 参数时强制第 1 段也走 tftp（镜像已更新时必须用）
    reuse_first = (start_from == 1 and "full" not in sys.argv)

    R.note("\n\n===== %s resume_flash from p%02d =====" %
           (time.strftime("%Y-%m-%d %H:%M:%S"), start_from))

    ser = serial.Serial(R.COM, R.BAUD, timeout=0.05, write_timeout=30)
    try:
        ser.dtr = False
        ser.rts = False
    except Exception:
        pass

    # 60 秒内持续发 Ctrl-C/回车，可自动抓住 u-boot 自动启动倒计时
    if not R.sync_prompt(ser, 60):
        R.note("[!] 板子不在命令行，需重新进 u-boot")
        ser.close()
        return 1
    R.note("[OK] u-boot 命令行就绪")

    R.send(ser, "setenv ipaddr %s" % DEV_IP, wait=5)
    R.send(ser, "setenv serverip %s" % PC_IP, wait=5)
    R.send(ser, "setenv netmask 255.255.255.0", wait=5)
    R.send(ser, "setenv ethaddr 10:23:45:67:89:ab", wait=5)

    pages_done = (start_from - 1) * 10000

    for idx in range(start_from, len(CHUNKS) + 1):
        name, pages = CHUNKS[idx - 1]
        img_size = pages * PAGE
        nand_off = NAND_BASE + pages_done * DATA
        nand_len = pages * DATA

        R.note("\n===== [%d/6] %s  ->  NAND 0x%08X  (%d 字节镜像) =====" %
               (idx, name, nand_off, img_size))

        # 第一段若数据已在 DRAM 则跳过传输
        if idx == start_from and reuse_first:
            R.note("  [跳过 tftp] 数据已在 DRAM 0x%08X" % LOAD)
        else:
            t0 = time.time()
            r = R.send(ser, "tftp 0x%08X %s" % (LOAD, name), wait=300, idle_limit=600)
            R.note("  [tftp %.0f 秒]" % (time.time() - t0))
            if b"Bytes transferred" not in r:
                R.note("  [!] tftp 失败，终止")
                R.note(r.decode("latin1", "replace").replace("\r", "")[-400:])
                ser.close()
                return 2

        t0 = time.time()
        r = R.send(ser, "nand write.yaffs 0x%08X 0x%08X 0x%08X" %
                   (LOAD, nand_off, img_size), wait=600, idle_limit=600)
        R.note("  [写入 %.0f 秒]" % (time.time() - t0))
        if b"NAND write: OK" not in r and b"OK" not in r:
            R.note("  [!] 写入结果异常，输出尾部:")
            R.note(r.decode("latin1", "replace").replace("\r", "")[-400:])

        pages_done += pages

    R.note("\n===== 回读校验首 32 字节 =====")
    R.send(ser, "nand read 0x21000000 0x00700000 0x00100000", wait=180, idle_limit=300)
    r = R.send(ser, "md.b 0x21000000 0x20", wait=20, idle_limit=60)
    R.note(r.decode("latin1", "replace").replace("\r", "")[-400:])

    R.note("\n===== 写启动参数 =====")
    R.send(ser, "setenv bootargs '%s'" % BOOTARGS_A, wait=8)
    R.send(ser, "setenv bootcmd '%s'" % BOOTCMD_A, wait=8)
    R.send(ser, "printenv bootargs", wait=8)
    R.send(ser, "saveenv", wait=30, idle_limit=100)

    R.note("\n[完成] 断电重启验证 Android")
    ser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
