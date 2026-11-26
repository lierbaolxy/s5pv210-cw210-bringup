# -*- coding: utf-8 -*-
"""在板子 shell 上检查网络与已启动服务"""
import os, sys, time
import serial
import round_img as R

R.OUT = os.path.join(R.BASE, "board_check_log.txt")


def safe(ser, cmd, wait=10, idle=40):
    try:
        return R.send(ser, cmd, wait=wait, idle_limit=idle)
    except Exception as e:
        R.note("  [异常 %s]" % type(e).__name__)
        return b""


def main():
    R.note("\n\n===== %s board_check =====" % time.strftime("%Y-%m-%d %H:%M:%S"))
    ser = serial.Serial(R.COM, R.BAUD, timeout=0.05, write_timeout=5)
    try:
        ser.dtr = False
        ser.rts = False
    except Exception:
        pass

    if not R.sync_prompt(ser, 20):
        R.note("[!] 不在 shell 提示符")
        ser.close()
        return 1

    safe(ser, "ifconfig -a")
    safe(ser, "ps")
    safe(ser, "ls /usr/sbin /sbin 2>/dev/null | grep -iE 'telnet|ftp'")
    ser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
