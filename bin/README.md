# bin —— 当前板上运行的二进制镜像

本目录是**当前实际写入 NAND、可正常启动**的镜像。文件均为原始大小（未补齐），写入 NAND 前需按说明用 `0xFF` 补齐。

---

## 一、bootloader/

| 文件 | 大小 | NAND 位置 | 说明 |
|---|---|---|---|
| `u-boot_nomenu.bin` | 393,216 | `0x000000`（mtd0） | 当前 NAND 中的 bootloader。横幅 `##### JFJKJ BIOS for JFJ210 #####`，`version` 显示 `U-Boot 1.3.4 (Aug 8 2012) for CW210` |
| `x210_usb.bin` | 11,168 | 载入 `0xD0020010` | BL1。USB 下载用（DNW），配合 `u-boot_nomenu.bin` 载入 `0x23E00000` 可在 USB 下载档下临时获得 u-boot 命令行，不写 NAND |

**写入 bootloader（有风险，操作前先确认能通过 USB 下载模式恢复）**

```
nand erase 0x0 0x100000
nand write 0x23E00000 0x0 0x60000        # 393,216 = 0x60000
```

> 说明：u-boot 大小为 393,216 字节（0x60000），是 128KB 块的整数倍（3 块），无需补齐。
> 当前 NAND 中该镜像为 `load_official_uboot.py` 写入并做过 `cmp.b` 首 4KB 校验；此后未再改动 mtd0。

---

## 二、kernel/

| 文件 | 大小 | NAND 位置 | 说明 |
|---|---|---|---|
| `zImage` | 4,261,256 | `0x200000`（mtd1） | Linux 2.6.35.7-Concenwit #5 PREEMPT Wed Oct 21 19:03:37 CST 2015 |

**写入步骤**

1. 用 `0xFF` 补齐到 **128KB 整数倍**：4,261,256 → **4,325,376**（0x420000，33 块）
2. 写入：

```
tftp 0x30000000 zImage
nand erase 0x200000 0x00500000
nand write 0x30000000 0x200000 0x420000
```

PowerShell 补齐示例：

```powershell
$b = [System.IO.File]::ReadAllBytes("zImage")
$pad = 4325376
$buf = New-Object byte[] $pad
[Array]::Copy($b, $buf, $b.Length)
for ($i = $b.Length; $i -lt $pad; $i++) { $buf[$i] = 0xFF }
[System.IO.File]::WriteAllBytes("zImage_padded.bin", $buf)
```

---

## 三、rootfs/

| 文件 | 大小 | NAND 位置 | 说明 |
|---|---|---|---|
| `rootfs.cramfs` | 3,301,376 | `0x700000`（mtd2） | cramfs 根文件系统，只读 |

**写入步骤**

1. 补齐到 128KB 整数倍：3,301,376 → **3,407,872**（0x340000，26 块）
2. 写入：

```
tftp 0x30000000 rootfs.cramfs
nand erase 0x700000 0x00500000
nand write 0x30000000 0x700000 0x340000
```

> ⚠️ 本文件是纯 cramfs（大小是 **2048** 的整数倍），用 `nand write`。
> 如果手上的备份文件是 **2112** 的整数倍（如 4,325,376 = 2048×2112），那是**含 OOB 的原始 dump，不能直接 `nand write`**，否则会 `cramfs: bad compressed blocksize` 并 panic。

---

## 四、android/

Android 尝试验证过的产物，**当前未在板上运行**（内核无法启动，详见 [../docs/03_CW210_Android尝试与Linux恢复_完整记录.md](../docs/03_CW210_Android尝试与Linux恢复_完整记录.md)）。

| 文件 | 大小 | 说明 |
|---|---|---|
| `zImage_android_fix.bin` | 3,935,540 | Android 内核，已打补丁：清零 s5p 多媒体预留表 137.7MB、内建 cmdline `console=ttySAC2` → `ttySAC0`、修正 zImage 头 `end` 字段 |
| 根文件系统 | **未入库** | 117,061,824 字节，超过 GitHub 单文件 100MB 上限。用 [../tools/rootfs_yaffs2_fix.py](../tools/rootfs_yaffs2_fix.py) 可从配套资源 `image/android_system/rootfs_android.bin` 重新生成 |

Android 根文件系统的烧写方式（2112 字节/页，必须用 `nand write.yaffs`）：

```
# 切成 6 段：5 段 × 10000 页 + 1 段 × 5427 页，每段 2112 字节/页
tftp 0x30000000 rootfs_p01.bin
nand write.yaffs 0x30000000 0x00700000 0x01424400      # 21120000 = 0x1424400
# 后续段 NAND 偏移按页累加：每 10000 页 = 20,480,000 字节
```

---

## 五、校验信息

| 文件 | 大小（字节） | 首 4 字节 |
|---|---|---|
| `bootloader/u-boot_nomenu.bin` | 393,216 | — |
| `bootloader/x210_usb.bin` | 11,168 | — |
| `kernel/zImage` | 4,261,256 | `00 00 a0 e1`（ARM NOP，zImage 起始） |
| `rootfs/rootfs.cramfs` | 3,301,376 | `45 3d cd 28`（cramfs magic `0x28CD3D45`） |
| `android/zImage_android_fix.bin` | 3,935,540 | `00 00 a0 e1` |

内核 zImage 的魔数位置在偏移 **0x24**，应为 `18 28 6f 01`（`0x016F2818`）。可用 u-boot 验证：

```
md.l 0x20008024 1
20008024: 016f2818
```
