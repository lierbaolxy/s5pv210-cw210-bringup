# -*- coding: utf-8 -*-
"""最小化 TFTP 服务器，专为 u-boot 1.3.4 的 tftp 客户端优化。

不用 tftpy：它的 listen() 处理一个请求后就 return，实测 u-boot 只收到几个块就断。

协议要点（RFC 1350）：
  RRQ  : opcode=1, filename\\0, mode\\0
  DATA : opcode=3, block#(16bit), data(<=512B)
  ACK  : opcode=4, block#(16bit)
  ERROR: opcode=5, errcode(16bit), msg\\0

111MB / 512B = 228,636 块，block# 会多次回绕（按 16 位取模），
u-boot 与标准实现都支持回绕。
"""
import os
import socket
import struct
import sys
import time

ROOT = r"G:\lcd\android_split"
PORT = 69
BLOCK = 512
RETRIES = 8


def log(msg):
    print(msg, flush=True)


def serve_one(fname, addr, master):
    path = os.path.join(ROOT, fname)
    if not os.path.isfile(path):
        log("[!] 文件不存在: %s" % path)
        err = struct.pack(">HH", 5, 1) + b"File not found\x00"
        master.sendto(err, addr)
        return

    size = os.path.getsize(path)
    log("[RRQ] %s  %d 字节  <- %s" % (fname, size, addr))

    # TFTP 规定：数据从新的随机端口发出，后续所有包都用这个端口
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 0))
    sock.settimeout(1.0)

    f = open(path, "rb")
    blk = 1
    sent_bytes = 0
    t0 = time.time()
    last_report = 0
    ok = True

    while True:
        chunk = f.read(BLOCK)
        pkt = struct.pack(">HH", 3, blk & 0xFFFF) + chunk

        acked = False
        for attempt in range(RETRIES):
            try:
                sock.sendto(pkt, addr)
                ack, _ = sock.recvfrom(1024)
                aop, ablk = struct.unpack(">HH", ack[:4])
                if aop == 4 and ablk == (blk & 0xFFFF):
                    acked = True
                    break
                # 收到重复 ACK（对方没收到上一块），重发当前块
            except socket.timeout:
                continue

        if not acked:
            log("[!] block %d 重试 %d 次仍无 ACK，终止" % (blk, RETRIES))
            ok = False
            break

        sent_bytes += len(chunk)

        if sent_bytes - last_report >= 8 * 1048576:
            last_report = sent_bytes
            el = time.time() - t0
            log("   %.1f / %.1f MB  %.2f MB/s  (block %d)" %
                (sent_bytes / 1048576.0, size / 1048576.0,
                 sent_bytes / 1048576.0 / el if el > 0 else 0, blk))

        # 最后一块（含长度为 0 的结束块）发完即止
        if len(chunk) < BLOCK:
            break
        blk += 1

    f.close()
    sock.close()

    el = time.time() - t0
    if ok:
        log("[OK ] %s 发送完成 %d 字节，%.1f 秒，%.2f MB/s" %
            (fname, sent_bytes, el, sent_bytes / 1048576.0 / el if el > 0 else 0))
    else:
        log("[ERR] %s 中断于 %d 字节" % (fname, sent_bytes))


def main():
    if not os.path.isdir(ROOT):
        log("[!] 目录不存在: %s" % ROOT)
        return 1

    log("[TFTP] 根目录: %s" % ROOT)
    for f in sorted(os.listdir(ROOT)):
        p = os.path.join(ROOT, f)
        if os.path.isfile(p):
            log("   %-24s %10d" % (f, os.path.getsize(p)))

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("0.0.0.0", PORT))
    log("[TFTP] 监听 0.0.0.0:%d 等待 u-boot ..." % PORT)

    while True:
        try:
            data, addr = sock.recvfrom(2048)
        except KeyboardInterrupt:
            break
        if len(data) < 4:
            continue
        opcode = struct.unpack(">H", data[:2])[0]
        if opcode != 1:
            continue
        parts = data[2:].split(b"\x00")
        fname = parts[0].decode("latin1", "replace")
        serve_one(fname, addr, sock)

    sock.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
