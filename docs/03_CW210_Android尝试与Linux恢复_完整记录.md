# CW210 (S5PV210) Android 尝试与 Linux 系统恢复 —— 完整记录

> 记录时间：2026-11-26
> 板卡：达内 CW210 / ME210-BOX 底板，S5PV210，1GB DDR2，NAND K9K8G08U0B（1GB）
> 目标：在板上安装 Android 2.3，让 800×480 LCD 显示桌面
> 最终结果：**Android 未成功**；已完整恢复原 Linux (cramfs) 系统，板子可正常使用

---

## 一、结论摘要

| 项目 | 结果 |
|---|---|
| Android 根文件系统修复与烧写 | ✅ 已完成，788 个 yaffs2 对象全量校验通过 |
| Android 内核启动 | ❌ 失败。`Starting kernel ...` 后零输出 |
| 内核是否执行到镜像第一条指令 | ✅ 已证实执行（UART 探针打印出标记字符） |
| Linux cramfs 系统恢复 | ✅ 完成，可进 shell、可 telnet/ftp |
| 内核源码与工具链 | ✅ 已找到并确认可用（见第六节） |

**Android 失败的定性结论**：CPU 会跳入内核镜像并执行第一条指令，但死在解压器的 MMU/cache 初始化阶段之前。与 rootfs、机器 ID、分区表、串口配置均无关。要继续推进必须从源码重编内核（环境已具备，但存在若干编译障碍，见第七节）。

---

## 二、NAND 分区与 u-boot 环境（当前生效配置）

```
mtd0: 0x000000  2 MB     bootloader（JFJKJ BIOS，未改动）
mtd1: 0x200000  5 MB     kernel
mtd2: 0x700000  ~1017 MB rootfs
```

u-boot（U-Boot 1.3.4 for CW210，提示符 `tarena #`，横幅 `##### JFJKJ BIOS for JFJ210 #####`）：

```
arch_number = 0x00000998          <- 关键，见 4.1
boot_params = 0x20000100
DRAM bank 0 = 0x20000000, 512MB
DRAM bank 1 = 0x40000000, 512MB

bootcmd   = nand read 0x20008000 0x200000 0x500000; bootm 0x20008000
bootargs  = root=/dev/mtdblock2 rootfstype=cramfs init=/linuxrc \
            console=ttySAC0,115200 \
            mtdparts=s5pv210-nand:2m(bootloader),5m(kernel),-(rootfs)
machid    = 0x998
```

拨码开关（NAND 启动）：**1=ON，2/3/4=OFF**；USB 下载档：1=ON，4=ON。

网络：PC `192.168.1.13`，板子 `192.168.1.6`（MAC `10:23:45:67:89:ab`，假 MAC）。

---

## 三、Android 侧已完成的工作

### 3.1 原始 rootfs 镜像的格式缺陷（已定位并修复）

原始 `rootfs_android.bin`（117,061,824 字节 / 55,427 页，页大小 2112 = 2048 数据 + 64 OOB）的 yaffs2 ObjectHeader 与标准布局不兼容：

| 偏移 | 原始镜像 | 标准 yaffs2 |
|---|---|---|
| 0x00 | type (u32 LE) | 相同 |
| 0x04 | parentObjectId (u32 LE) | 相同 |
| 0x08 | **`FF FF` 多余填充** | name 起始 |
| 0x0A | name（256 字节） | — |
| 0x10A | **`FF FF` 多余填充** | — |
| 0x10C | mode | mode @0x108 |
| 0x124 | fileSize | fileSize @0x120 |

即：**name 前后各多 2 字节填充，导致尾部所有字段整体后移 4 字节**。内核按标准布局解析时，`/system` 的 name 会变成 `\xff\xffsystem`，整棵子树变孤儿。

**修复方法**（对每个 chunk==0 且 seq==0x1000 的 ObjectHeader 页）：

```python
new[0:8]       = d[0:8]        # type + parent 原样保留
new[8:264]     = d[10:266]     # name 前移 2 字节
new[264:2044]  = d[268:2048]   # mode..尾部再前移 2 字节
new[2044:2048] = b'\x00'*4     # 尾部补 0
```

数据页（chunk>0）与 OOB 全部不动。共处理 **788 个** ObjectHeader 页。

**校验结果**：788 对象、0 个无效 parent、0 个成环、mode/fileSize 全正常；`/init`、`/system/bin/servicemanager`、`/system/bin/app_process`、`/system/bin/sh`、`/system/bin`(139 项)、`/system/lib`、`/sbin/adbd`、54 个符号链接全部解析正确。

产物：`G:\lcd\android_conv\rootfs_fix.bin`（117,061,824 字节）

### 3.2 烧写结果

分 6 段（5×10000 页 + 5427 页）经 TFTP + `nand write.yaffs` 写入 mtd2，全部 `bytes written: OK`。

Android 内核 `zImage.bin`（3,941,800 字节）写入 mtd1 @0x200000，魔数 `0x016F2818` 校验通过。

### 3.3 Android 启动结果

```
NAND read: device 0 offset 0x200000, size 0x500000
 5242880 bytes read: OK
Boot with zImage
Using machid 0x3f80 from environment

Starting kernel ...

<此后完全没有输出>
```

屏幕：白屏。

---

## 四、关键发现

### 4.1 `machid` 必须用 0x998，不能用 0x3F80  ⚠️ 最重要

**这是本次排查中代价最大的一个坑。**

- u-boot 的 `bdinfo` 显示 `arch_number = 0x00000998`
- 内核镜像里确实能找到 `nr=0x3F80 / name="SMDKV210"` 的字符串组合，容易误判为「内核要求 0x3F80」
- **实测**：把 `machid` 设成 `0x3F80` 时，连原本能正常启动的 Linux 内核都会静默挂死（现象：打印完 `Uncompressing Linux... done, booting the kernel.` 后再无任何输出）
- **实测**：`machid` 用 `0x998` 时，Linux 内核完整启动

**结论：不要手动设置 `machid`，或明确设置为 `0x998`。** 机器 ID 不匹配时内核走的是 `Machine configuration botched ... while(1);` 路径，printk 缓冲尚未 flush，所以表现为**完全静默的死循环**，极难定位。

> 注意：Android 内核在 0x998 和 0x3F80 下都试过，均静默，所以 Android 的问题不止于此。但这个坑会让所有后续测试失真，必须先排除。

### 4.2 `cramfs_backup_4MB.bin` 是含 OOB 的原始 NAND dump，不能直接 `nand write`

- 文件大小 4,325,376 字节 = 2048 页 × **2112** 字节
- 说明每页含 2048 数据 + **64 字节 OOB**
- 用 `nand write`（只写主区）写入时，OOB 被打进数据区，整体错位，表现为：
  ```
  cramfs: bad compressed blocksize 2099683276
  Failed to execute /linuxrc.  Attempting defaults...
  Kernel panic - not syncing: No init found.
  ```

**正确做法**：使用厂商原版 `rootfs.cramfs`（3,301,376 字节 = 1612 页 × 2048，无 OOB），或先把 dump 里的 OOB 剥掉。

### 4.3 Android 内核确实被执行了（UART 探针证据）

在内核镜像起始的 8 条 NOP（偏移 0x00–0x1F）里插入直接写 UART0 的 ARM 指令：

```asm
movw r1, #0x0020      @ 20 10 00 e3
movt r1, #0xE290      @ 90 12 4e e3   -> r1 = 0xE2900020 (UART0 UTXH)
mov  r0, #0x41        @ 41 00 a0 e3   -> 'A'
str  r0, [r1]         @ 00 00 81 e5
str  r0, [r1]
str  r0, [r1]
nop
nop
```

启动后串口打印出 `A`（只出现一个是因为 UART 未开 FIFO 模式，后两次写入被丢弃），**证明 CPU 确实跳入并执行了内核镜像**。

同时把解压器里 4 个 `*_mmu_cache_on` 入口（偏移 0x268 / 0x298 / 0x2E8 / 0x318，均为 `mov r12,lr` 开头）改成 `mov pc,lr` 直接返回，跳过 MMU/cache 开启 → **仍然零输出**。

结论：死点在 `Starting kernel ...` 之后、解压器 C 代码第一句 `putstr("Uncompressing Linux...")` 之前。

### 4.4 已逐项排除的可能性

| 怀疑点 | 排除依据 |
|---|---|
| 根文件系统格式 | 已按标准 yaffs2 重新生成，788 对象全量校验通过 |
| 加载地址 / zreladdr | zImage 头部挖出 zreladdr = **0x20008000**，与 `bootm 0x20008000` 完全一致 |
| 机器 ID | 0x998 与 0x3F80 都试过 |
| 缺 `mtdparts` | 加了 `mtdparts=s5pv210-nand:2m(bootloader),5m(kernel),-(rootfs)` 仍静默 |
| `mem=` 参数 | 加了 `mem=512M`（厂商默认值）仍静默 |
| `noinitrd` / `ignore_loglevel` | 都加过，无效 |
| 多媒体预留表占用内存 | 已清零 mfc×2/fimc0/fimc1/fimc2/jpeg 共 137.7MB，无效 |
| 内建 cmdline 控制台错误 | 内建 cmdline 是 `console=ttySAC2,115200`，已单字节改为 `ttySAC0`，无效 |
| 调试串口不是 UART0 | 解压器 putc 的常量是 0xE2900000（UART0），DEBUG 字符串（`Uncompressing Linux` / `done, booting the kernel`）也确实存在于镜像中 |
| 镜像损坏 | gzip 流可完整解压出 8,273,472 字节，含合法内核版本串 |
| 内核入口代码异常 | 解压后入口前 64 字节与**能正常启动的 Linux 内核完全一致** |
| L2 cache 控制器地址 | 两侧均无 0xF8F02000 / 0xF8F00000 常量 |
| Android u-boot 内的 0xC0008000 | 该默认环境是别的板子模板，DRAM 实际只有 0x20000000/0x40000000 两个 bank |

### 4.5 Android 内核与 Linux 内核的差分结论

- 版本：Android `2.6.35.7-Concenwit ... #1 PREEMPT Mon Jul 16 16:40:27 CST 2012 (root@hui-desktop)`；Linux `#5 PREEMPT Wed Oct 21 19:03:37 CST 2015 (linux@linux)`
- 源码路径串：`/opt/kernel_2.6.35.7_CW210_android/`（说明 Android 内核确实基于 CW210 源码）
- zImage 前缀（16,601 字节）差异仅 **136 字节 / 44 段**，且全部是**镜像尺寸相关的字面量重定位值**（如 `0x3C25A8` = Android 文件大小、`0x410588` = Linux 文件大小），**解压器代码本身一致**
- 因此「同样代码、同样加载地址，一个能跑一个不跑」只能用镜像 payload 内部差异解释，需源码级调试

---

## 五、Linux 系统恢复过程（已验证可复用）

### 5.1 使用的文件

| 用途 | 文件 | 大小 | 说明 |
|---|---|---|---|
| 内核 | `dnw-python\x210_image\image\normal_system\zImage` | 4,261,256 | 补 0xFF 到 `0x420000`（33×128KB） |
| 根文件系统 | `dnw-python\x210_image\image\normal_system\rootfs.cramfs` | 3,301,376 | 补 0xFF 到 `0x340000`（26×128KB） |

### 5.2 操作步骤

```
# 1) 网络
setenv ipaddr 192.168.1.100
setenv serverip 192.168.1.13
setenv netmask 255.255.255.0
setenv ethaddr 10:23:45:67:89:ab

# 2) 内核 -> 0x200000
tftp 0x30000000 linux_zimage.bin
nand erase 0x200000 0x00500000
nand write 0x30000000 0x200000 0x420000

# 3) 根文件系统 -> 0x700000
tftp 0x30000000 cramfs2.bin
nand erase 0x700000 0x00500000
nand write 0x30000000 0x700000 0x340000

# 4) 启动参数（务必用 0x998）
setenv machid 0x998
setenv bootargs 'root=/dev/mtdblock2 rootfstype=cramfs init=/linuxrc console=ttySAC0,115200 mtdparts=s5pv210-nand:2m(bootloader),5m(kernel),-(rootfs)'
setenv bootcmd 'nand read 0x20008000 0x200000 0x500000; bootm 0x20008000'
saveenv
reset
```

### 5.3 成功判据（串口日志）

```
Using machid 0x998 from environment
Starting kernel ...
Uncompressing Linux... done, booting the kernel.
Linux version 2.6.35.7-Concenwit (linux@linux) ... for CW210 Concenwit Tech
Machine: SMDKV210
Memory: 512MB 320MB = 832MB total
...
VFS: Mounted root (cramfs filesystem) readonly on device 31:2.
Freeing init memory: 188K
~ #
```

`Memory: 832MB total` 是这块板子的正常值（1GB 物理内存减去 154MB 多媒体预留）。

### 5.4 启用网络（系统默认不启用 eth0）

```sh
ifconfig eth0 192.168.1.6 netmask 255.255.255.0 up
```

成功后会打印 `eth0: link up, 100Mbps, full-duplex`，此时 PC 可 ping 通、可 telnet(23)、可 ftp(21)。`telnetd` 与 `inetd` 由 init 自动启动。

---

## 六、内核源码与交叉工具链（已确认可用）

| 内容 | 路径 | 大小 |
|---|---|---|
| 内核源码包 | `G:\三星\test\U盘20161119\U盘20161119\达内\1605所有资源\porting\kernel.tar.bz2` | 72,758,378 |
| 内核源码（已解压） | `...\porting\kernel\kernel` | 34,085 文件 |
| 工具链包 | `G:\三星\test\U盘20161119\U盘20161119\env\交叉编译器包\arm-2009q3.tar.bz2` | 274,653,785（**CRC 损坏**） |
| 工具链（已解压） | `...\env\交叉编译器包\arm-2009q3\arm-2009q3` | GCC 4.4.1（Sourcery G++ Lite 2009q3-67） |

源码确认内容：
- `arch/arm/mach-s5pv210/mach-cw210.c` —— CW210 板级定义
- `arch/arm/configs/cw210_defconfig` —— 完整 Linux 配置（67,959 字节，与 `config_CW210_linux_V1.0` 同）
- `arch/arm/configs/smdkv210_android_defconfig` —— Android 最小 defconfig（7,783 字节），其中 `CONFIG_CMDLINE="console=ttySAC2,115200"` 与 Android 内核内建 cmdline 逐字一致
- `drivers/video/samsung/cw210_800*480.c`、`cw210_640*480.c` 等 —— 屏幕配置
- `drivers/char/cw210_beep.c`、`cw210_leds.c`、`drivers/input/touchscreen/cw210_ts.c`
- Android 驱动齐全：binder / logger / lowmemorykiller / ram_console

关键源码事实：
- `arch/arm/mach-s5pv210/include/mach/memory.h`：`PHYS_OFFSET = 0x20000000`
- `arch/arm/mach-s5pv210/include/mach/debug-macro.S`：
  ```asm
  ldreq rx, = S3C_PA_UART            @ 0xE2900000
  ldrne rx, = S3C_VA_UART
  add   rx, rx, #(0x400 * CONFIG_DEBUG_S3C_UART)
  ```
- `arch/arm/plat-samsung/include/plat/uncompress.h`：
  `#define uart_base S3C_PA_UART + (S3C_UART_OFFSET * CONFIG_S3C_LOWLEVEL_UART_PORT)`
- `kernel/printk.c`：`#ifdef CONFIG_DEBUG_LL → printascii(printk_buf);`（**每条 printk 直通 DEBUG_LL 串口**）

### 6.1 编译环境（已搭好）

- **WSL Ubuntu 24.04**（本机已安装），28 核，可用空间 890GB
- 工具链是 **32 位 x86 程序**，Ubuntu 24.04 需补装 32 位运行库：
  ```bash
  sudo dpkg --add-architecture i386
  sudo apt-get update
  sudo apt-get install -y libc6:i386 libstdc++6:i386
  ```
- 已解压到 `~/cw210/tc`（工具链）与 `~/cw210/linux`（源码）

### 6.2 编译配置修改清单（为让日志回到 UART0）

| 配置项 | Android defconfig 原值 | 应改为 | 作用 |
|---|---|---|---|
| `CONFIG_S3C_LOWLEVEL_UART_PORT` | 2 | **0** | 解压器 putc 输出到 UART0 |
| `CONFIG_DEBUG_S3C_UART` | 2 | **0** | `printascii` 直通输出到 UART0 |
| `CONFIG_CMDLINE` | `console=ttySAC2,115200` | `console=ttySAC0,115200` | 内建控制台回到 UART0 |

编译命令：
```bash
export PATH=~/cw210/tc/bin:$PATH
export ARCH=arm
export CROSS_COMPILE=arm-none-linux-gnueabi-
cd ~/cw210/linux
make mrproper
make smdkv210_android_defconfig
# 改上面三项后
make -j16 zImage
```

---

## 七、编译过程中遇到的障碍（已解决 3 项，剩 1 项）

| # | 现象 | 原因 | 处理 |
|---|---|---|---|
| 1 | `make: *** empty variable name. Stop.`（Makefile:389 scripts_basic） | 源码解压不完整，`scripts/Kbuild.include` 缺失（解压只有 151MB，完整应为 465MB / 34,098 文件） | 重新完整解压 |
| 2 | `kernel/timeconst.h] Error 255` | `kernel/timeconst.pl` 用了 `defined(@val)`，Perl 5.22+ 已列为**致命错误**（本机 Perl 5.38.2） | `sed -i 's/if (!defined(@val))/if (!@val)/' kernel/timeconst.pl` |
| 3 | `wext-priv.c / wext-spy.c: 'struct net_device' has no member named 'wireless_handlers' / 'wireless_data'` | 配置里 `WEXT_SPY`/`WEXT_PRIV` 被打开但 `WIRELESS_EXT` 未开，Kconfig 又不允许手动关闭（非提示符号） | 在 `net/wireless/Makefile` 里注释掉 `obj-$(CONFIG_WEXT_SPY)` 与 `obj-$(CONFIG_WEXT_PRIV)` 两行（板子用有线网，不需要） |
| 4 | **未解决**：`undefined reference to '__tracepoint_kmalloc'` / `'kmem_cache_alloc_notrace'` | 该 vendor 源码树中 `CONFIG_TRACING` 无法通过 Kconfig 打开（非提示符号，`make oldconfig` 会丢弃），但 `mm/slub.c` 内部仍引用 `trace_kmalloc()` | 已尝试：`CREATE_TRACE_POINTS` + `#include <trace/events/kmem.h>` 的自定义 stub 文件；未成功。下一步建议改 `arch/arm/Kconfig` 给 `CONFIG_ARCH_S5PV210` 加 `select TRACING`，让配置层正确打开 |

---

## 八、后续如果继续 Android 的可行路径

1. **先解决第 7 节的第 4 项编译障碍**（`select TRACING`），拿到可编译的 Android 内核
2. 用 `smdkv210_android_defconfig` + 上述三项 UART 修改编译，烧入 mtd1
3. 启动后应能看到完整内核日志，从而确定真正死点
4. 若仍静默，则考虑物理引出 **UART2**（`0xE2900800`）接管日志
5. rootfs 已就绪（`G:\lcd\android_conv\rootfs_fix.bin`），无需重做
6. **注意**：`machid` 保持默认 `0x998`；任何测试前先确认这一项，否则所有结果都不可信

对比参考：用同一套源码 + `cw210_defconfig`（Linux 配置）编译的内核是能正常启动的，说明工具链与板级代码没有问题，差异只在配置选项。

---

## 九、可复用资产清单

```
G:\lcd\
├─ android_conv\rootfs_fix.bin          117,061,824  Android 根文件系统（已修正为标准 yaffs2）
├─ android_split\rootfs_p01..p06.bin    分片，已验证可直接 nand write.yaffs
├─ android_split\cramfs2.bin            3,407,872    Linux 根文件系统（干净，已补 0xFF 对齐）
├─ android_split\linux_zimage.bin       4,325,376    Linux 内核（已补 0xFF 对齐）
├─ android_split\zImage_android_fix.bin 3,935,540    Android 内核（预留表清零 + console=ttySAC0）
├─ android_split\zImage_probe.bin       3,935,540    带 UART 'A' 探针的 Android 内核
├─ android_split\zImage_nocache.bin     3,935,540    探针 + 4 个 cache_on 跳过
├─ cramfs_backup_4MB.bin                4,325,376    原始 dump（含 OOB，不能直接 nand write）
└─ CW210_Android尝试与Linux恢复_完整记录.md  本文档

C:\Users\20808\WorkBuddy\automation-2026-11-23-13-48-36\dnw-python\
├─ tftp_srv.py          自研 TFTP 服务器（ROOT=G:\lcd\android_split，端口 69）
├─ round_img.py         串口核心库（send/alive/stage/note）
├─ restore_linux.py     完整恢复 Linux 系统
├─ boot_fix.py          修正 machid 后重启验证
├─ fix_cramfs.py        单独重写 cramfs 并验证
├─ board_net.py         启用板子 eth0
├─ board_check.py       查看板子网络与进程
└─ resume_flash.py      分段烧写 rootfs 到 NAND

G:\三星\test\U盘20161119\U盘20161119\
├─ 达内\1605所有资源\porting\kernel.tar.bz2               内核源码（完好）
└─ env\交叉编译器包\arm-2009q3.tar.bz2                     工具链（CRC 损坏，需 WinRAR 容错解压）
```

---

## 十、踩坑清单（下次直接避开）

1. **`machid` 只能是 `0x998`**。设成 `0x3F80` 会让任何内核静默挂死，且极难识别。
2. **`cramfs_backup_4MB.bin` 含 64 字节 OOB**（2112 字节/页），不能直接 `nand write`。用 `rootfs.cramfs`。
3. **`nand read` 读 yaffs2 区域必然报 `-74` ECC 错误**，这是正常的（yaffs OOB 存的是 tag 不是硬件 ECC），不代表数据损坏。
4. **`nand write.yaffs` 用于 yaffs2 镜像（2112 字节/页）；`nand write` 用于 cramfs/内核（2048 字节主区）**，两者不能混用。
5. **TFTP 长传输会挂死**：单次超过约 60MB u-boot 会无响应，必须分段（每段 ≤20MB）。
6. **`round_img.send()` 判断提示符必须用 `buf.rstrip().endswith(b"tarena #")`**，只判断末字符 `#` 会被 tftp 进度条 `####` 误判；tftp 命令要传 `idle_limit=600`。
7. **板子供电**：大文件传输时若只靠 USB 供电，可能在传输中途掉电重启（表现为串口突然重新打印 BIOS 横幅）。
8. **`com3` 会被 SecureCRT 占用**（即使显示"未连接"也锁端口），脚本前必须先关闭。
9. **WSL 的 `/tmp` 在会话间会被清空**，编译日志要放 `~/` 下。
10. **`arm-2009q3` 是 32 位程序**，Ubuntu 24.04 默认无 `/lib/ld-linux.so.2`，需装 `libc6:i386`。
11. **Linux 2.6.35 与现代 Perl 不兼容**：`kernel/timeconst.pl` 的 `defined(@val)` 必须改。
12. **解压内核源码要校验完整性**：检查 `scripts/Kbuild.include` 是否存在、文件数是否约 34,000。
