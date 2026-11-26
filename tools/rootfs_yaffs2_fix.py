#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Android rootfs yaffs2 布局修复工具
==================================

背景
----
板卡配套的 Android 2.3 根文件系统镜像 rootfs_android.bin 的 yaffs2
ObjectHeader 与标准布局不兼容：name 前后各多 2 字节 0xFF 填充，
导致 name 及之后所有字段整体后移（name@10、mode@268、fileSize@292），
而内核按标准布局解析（name@8、mode@264、fileSize@288）。

结果：/system 的 name 被解析成 "\\xff\\xffsystem"，整棵子树变成孤儿，
表现为 init: cannot find '/system/bin/servicemanager'、zygote 被禁用。

修复
----
对每个 ObjectHeader 页（chunk==0 且 seq==0x1000 且 0<obj<0x40000）：

    new[0:8]       = d[0:8]        # type + parent 原样保留
    new[8:264]     = d[10:266]     # name 前移 2 字节
    new[264:2044]  = d[268:2048]   # mode..尾部再前移 2 字节
    new[2044:2048] = b'\\x00' * 4   # 尾部补 0

数据页（chunk>0）与 OOB 全部不动。

用法
----
    python rootfs_yaffs2_fix.py <原始 rootfs_android.bin> [输出目录]

输出
----
    <输出目录>/rootfs_fix.bin          修复后的完整镜像（与输入等长）
    <输出目录>/rootfs_p01..p06.bin     分片，可直接 nand write.yaffs

分片规则（适配 u-boot 1.3.4 单次 TFTP 不超过约 20MB）：
    5 段 × 10000 页 + 1 段 × 剩余页数，每页 2112 字节
"""
import os
import struct
import sys

PAGE = 2112          # 2048 数据 + 64 OOB
DATA = 2048
MAX_OBJ = 0x40000
SEQ_OH = 0x1000      # ObjectHeader 页的序列号

CHUNK_PAGES = [10000, 10000, 10000, 10000, 10000]   # 最后一段为剩余页数


def hexdump_head(d, n=32):
    return " ".join("%02x" % b for b in d[:n])


def fix(src_path, out_dir):
    size = os.path.getsize(src_path)
    total = size // PAGE
    print("[输入] %s" % src_path)
    print("        %d 字节  %d 页  （页大小 %d）" % (size, total, PAGE))

    if size % PAGE:
        print("[!] 警告：文件大小不是 %d 的整数倍，尾部 %d 字节被忽略"
              % (PAGE, size % PAGE))

    oh_count = 0
    gap1 = 0
    gap2 = 0
    buf = bytearray()

    with open(src_path, "rb") as f:
        for i in range(total):
            raw = f.read(PAGE)
            seq, obj, chunk, _bcnt = struct.unpack("<IIII", raw[DATA:DATA + 16])
            if chunk == 0 and 0 < obj < MAX_OBJ and seq == SEQ_OH:
                oh_count += 1
                d = raw[:DATA]
                if d[8] == 0xFF and d[9] == 0xFF:
                    gap1 += 1
                if d[266] == 0xFF and d[267] == 0xFF:
                    gap2 += 1
                new = bytearray(DATA)
                new[0:8] = d[0:8]
                new[8:264] = d[10:266]
                new[264:2044] = d[268:2048]
                new[2044:2048] = b"\x00\x00\x00\x00"
                buf += new + raw[DATA:PAGE]
            else:
                buf += raw

    print("[统计] ObjectHeader 页: %d" % oh_count)
    print("       offset 8-9     为 FF FF: %d" % gap1)
    print("       offset 266-267 为 FF FF: %d" % gap2)
    if oh_count == 0:
        print("[!] 未找到任何 ObjectHeader 页，输入可能不是该格式的镜像")

    os.makedirs(out_dir, exist_ok=True)
    fix_path = os.path.join(out_dir, "rootfs_fix.bin")
    with open(fix_path, "wb") as f:
        f.write(buf)
    print("[输出] %s  %d 字节" % (fix_path, len(buf)))

    # 抽样检查
    print("\n[抽样] 修复后前几个 ObjectHeader 的 name 字段：")
    with open(fix_path, "rb") as f:
        shown = 0
        for i in range(min(total, 4000)):
            f.seek(i * PAGE)
            raw = f.read(PAGE)
            seq, obj, chunk, _ = struct.unpack("<IIII", raw[DATA:DATA + 16])
            if chunk == 0 and 0 < obj < MAX_OBJ and seq == SEQ_OH:
                d = raw[:DATA]
                nul = d[8:264].find(0)
                name = d[8:8 + nul].decode("ascii", "replace") if nul >= 0 else ""
                parent = struct.unpack("<I", d[4:8])[0]
                print("       page %-5d obj=%-5d parent=%-5d name=%r"
                      % (i, obj, parent, name))
                shown += 1
                if shown >= 8:
                    break

    # 分片
    print("\n[分片]")
    pages_left = total
    idx = 1
    off = 0
    chunks = list(CHUNK_PAGES)
    with open(fix_path, "rb") as f:
        for n in chunks:
            if pages_left <= 0:
                break
            take = min(n, pages_left)
            part = f.read(take * PAGE)
            p = os.path.join(out_dir, "rootfs_p%02d.bin" % idx)
            with open(p, "wb") as g:
                g.write(part)
            print("       %s  %d 页  %d 字节" % (os.path.basename(p), take, len(part)))
            pages_left -= take
            idx += 1
            off += take
        if pages_left > 0:
            part = f.read(pages_left * PAGE)
            p = os.path.join(out_dir, "rootfs_p%02d.bin" % idx)
            with open(p, "wb") as g:
                g.write(part)
            print("       %s  %d 页  %d 字节" % (os.path.basename(p), pages_left, len(part)))

    print("\n[完成] 烧写方式（必须是 nand write.yaffs，页大小 2112）：")
    print("       tftp 0x30000000 rootfs_p01.bin")
    print("       nand write.yaffs 0x30000000 0x00700000 0x01424400")
    print("       后续段 NAND 偏移按页累加：每 10000 页 = 20,480,000 字节")
    return 0


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    src = sys.argv[1]
    out_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.dirname(os.path.abspath(src)) or "."
    if not os.path.isfile(src):
        print("[!] 文件不存在: %s" % src)
        return 1
    return fix(src, out_dir)


if __name__ == "__main__":
    sys.exit(main())
