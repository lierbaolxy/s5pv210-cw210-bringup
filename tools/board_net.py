# -*- coding: utf-8 -*-
"""启用板子 eth0（192.168.1.6）并验证"""
import os, sys, time
import serial
import round_img as R

R.OUT = os.path.join(R.BASE, "board_net_log.txt")


def main():
    R.note("\n\n===== %s board_net =====" % time.strftime("%Y-%m-%d %H:%M:%S"))
    ser = serial.Serial(R.COM, R.BAUD, timeout=0.05, write_timeout=5)
    try:
        ser.dtr = False
        ser.rts = False
    except Exception:
        pass
    if not R.sync_prompt(ser, 20):
        R.note("[!] 不在 shell")
        ser.close()
        return 1

    R.send(ser, "ifconfig eth0 192.168.1.6 netmask 255.255.255.0 up", wait=12, idle_limit=40)
    R.send(ser, "ifconfig eth0", wait=10, idle_limit=40)
    R.send(ser, "ping -c 2 192.168.1.13", wait=15, idle_limit=40)
    ser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
