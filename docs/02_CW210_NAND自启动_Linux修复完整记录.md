# CW210 (S5PV210) NAND 自启动 Linux 修复完整记录

> 板卡：达内 CW210 / TPAD（康芯威核心板 + ME210-BOX 底板，S5PV210）
> 目标：**断电重启后从 NAND 自主启动，进入可用的 Linux**
> 最终状态：达成。串口出现 `~ #`，`uname -a` 正常返回 `Linux 2.6.35.7-Concenwit armv7l`
> **前置阅读**：`CW210_前期调试全记录_上篇.md` —— 记录本文之前的两天（11-23 ～ 11-25）：
> 驱动怎么绕过、串口怎么替代网口、内核"静默"怎么观测，以及 8 条被推翻的错误结论。
> 本文是"下篇"：换了术式（官方镜像 + NAND 三分区 + `bootm`），一次成功。

---

## 一、起始状态与最初方向错误

接手时的状态：一直用 **USB 下载 u-boot → bootm 启动自己解压出来的 vmlinux**，内核在
`Starting kernel ...` 之后完全静默。

当时在做的尝试（都属于无效方向）：

- 给内核打"预留内存表清零"补丁，绕开 bootmem OOM
- 自写 ATAGS 桩跳内核（bootfs.S）
- 把 vmlinux 手工封装成 uImage 头走 bootm
- 反复怀疑 `mem=128M` / 机器码 / ATAGS

**问题本质**：一直在优化"USB 加载内核"这条临时链路，而用户真正要的是
**NAND 自启动**。方向一开始就偏了。

---

## 二、标记探针法：把静默变成可观测

内核在 `console_init` 之前是没有任何输出的，静默 ≠ 没跑。为了定位挂死点，
建立了一套"在关键位置插字符标记"的方法：

### 1. 先验证最小链路
用 20 字节裸程序做成 uImage，bootm 后直接打印 `J`。
结果 `J` 出现 → **bootm 跳转与 UART 写入都正常**，可以放心用它做探针。

### 2. trampoline 方案
bootm 只加载一个很小的 trampoline 到 `0x22000000`，由它：

- 打印标记
- 给内核打补丁（把目标指令改成 `b` 跳到 stub）
- 跳进内核

**只改 DRAM，不写 NAND，零烧录风险。**

### 3. 最终标记链路

| 标记 | 位置 | 含义 |
|---|---|---|
| `S <r1> <r2>` | trampoline | bootm 已交接；打印 machine id 与 ATAGS 指针 |
| `P` | 0x20 | 处理器/机器查找通过 |
| `Q` | 0x28 | `__create_page_tables` 页表建立完成 |
| `A` | 0x4FC0 | `__v7_setup` 入口 |
| `C` | 0x4FC8 | L1 D-cache 全清完成 |
| `D` | 0x4FD0 | 即将读 MIDR |
| `F` | 0x5024 | errata 段结束 |
| `G` | 0x505C | 即将读 SCTLR |
| `M` | 0x44 | **MMU 即将开启** |
| `H` | 0xC0890000 | **MMU 已开启且 UART 可用** |

实测输出 `S 00000998 20000100 P Q A C D F G M H` —— 全过。
**结论：MMU 与页表完全正常，挂死在 `start_kernel` 内部（console 尚未初始化，所以无声）。**

### 4. 探针开发中踩到的三个坑

| 坑 | 现象 | 修复 |
|---|---|---|
| UART 丢字 | 连写 19 个字符只收到最后 1 个 | 每次 `putc` 前轮询 USR 的 TX FIFO 空位 |
| 破坏页表基址 | Q stub 用了 `r4`，而 0x40 要拿 r4 写 TTBR0 | stub 只用 `r3/r6` |
| MMU 后无法打印 | 页表没有 UART 映射，写 0xE2900020 直接 abort | 在 Q stub 里补写页表项 `[0xE29] = 0xE2900C12`（strongly-ordered） |
| stub 落点覆盖内核 | 0x2000D100 处是正常内核代码 | 改放到 PA `0x20890000`（镜像末尾之后），并用 `movw/movt` 免常量池 |

---

## 三、方向纠正：读资料，认清硬件真相

用户指出："128MB 昨天已经确认过了，别再重复。"并要求先读
`G:\lcd\S5PV210_X210_CW210_完整资料汇总.md`。

读完后的关键纠正：

| 误判 | 真相 |
|---|---|
| DRAM 只有 128MB | **1GB DDR2**（8 × K4T1G084QQ），u-boot 自己会打印 `This Board: SDRAM is 1024MB` |
| 需要 `mem=128M` | **不要加**，让 u-boot 通过 ATAGS 传真实内存 |
| 自己拼内核 | 官方三件套就在 `porting\image\image\normal_system\` |

官方镜像（MD5 已在资料中核对）：

```
u-boot_nomenu.bin   393,216   U-Boot 1.3.4 (Aug 8 2012) for CW210
zImage            4,261,256   Linux 2.6.35.7-Concenwit
rootfs.cramfs     3,301,376   BusyBox cramfs
```

**正确路线：把官方 zImage + rootfs 烧进 NAND，用 NAND 里的 bootloader 自启动。**

---

## 四、NAND 启动失败的三层排查

烧好 kernel 后，拨码全 OFF 上电，串口 200 秒完全静默。

### 第 1 层：是不是 NAND 里的 u-boot 坏了？

读出 NAND 0x0 前 16 字节：

```
00 20 00 00 | 00 00 00 00 | a7 e8 0e 00 | 00 00 00 00
size=0x2000  reserved      checksum
```

对比 PC 端镜像：`size` 相同，但 **checksum = 0**（0 只适合 USB/SD 加载，iROM 从 NAND 启动时会校验）。

**推导出 iROM 的 BL1 校验算法**：

```python
checksum = sum(data[0x10:0x2000]) & 0xFFFFFFFF
# u-boot_nomenu.bin 算出来 = 0x000EE8A7
# NAND 里读出来也 = 0x000EE8A7  → 完全一致，证明是同一份 BL1
```

再用 u-boot 自带 `crc32` 校验 NAND 上完整的 384KB：

```
NAND CRC32 = 0x92348E53
PC   CRC32 = 0xDC445999    ← 不一致，BL2 确实损坏
```

→ 生成 `u-boot_nand.bin`（把正确 checksum 写回头部），重烧 → CRC 一致。

### 第 2 层：为什么全 OFF 还是启动不了？

读 `nand info`：`sector size 128 KiB`，2KB 页。
读 NAND ID：`0xEC 0xD3 0x51 0x95 0x58` → **Samsung K9K8G08U0B，8Gbit=1GB，2KB 页，128KB 块**。

全 OFF 上电后串口仍静默，但用 Python 查 USB 发现设备被枚举（VID 04E8 / PID 1234）：

**说明 iROM 从 NAND 启动失败后 fallback 到了 USB 下载态。**
（这也是之前所有"200 秒静默"的真相——不是板子没跑，是跑到 iROM 的 USB 等待里去了。）

继续查 `nand bad` → 只有 0x0DD80000 一个远处坏块，**block 0 是好的**。
查 OOB → 前 40 字节是 ECC 校验码，说明写入用的是 4-bit 及以上 ECC。

**结论：数据完好、块完好，问题在启动档位。**

### 第 3 层：找到正确的 NAND 启动拨码

文档写"NAND 启动 = 全 OFF"，实测不成立。改为试 **1=ON，2/3/4=OFF**：

- 串口立刻收到 17,504 字节
- USB 不再枚举
- 屏幕出现企鹅 LOGO，反复闪

**NAND 自启动打通了**，剩下的是内核 panic 重启循环。

---

## 五、真正的根因：内核分区表与 cmdline 不一致

日志关键片段：

```
This Board: SDRAM is 1024MB
Linux version 2.6.35.7-Concenwit
Memory: 675152k/675152k available
VFS: Cannot open root device "mtdblock4" or unknown-block(2,0)
Please append a correct "root=" boot option; here are the available partitions:
1f00      2048  mtdblock0      ← 2MB   u-boot
1f01      5120  mtdblock1      ← 5MB   kernel (0x200000 - 0x700000)
1f02   1041408  mtdblock2      ← 1017MB rootfs (0x700000 - )
Kernel panic - not syncing: VFS: Unable to mount root fs
```

**内核完全忽略 cmdline 里的 `mtdparts=`，用的是自己编译进去的 3 分区表。**

由此发现三处错位：

| 项目 | 之前 | 必须改成 |
|---|---|---|
| `root=` | `/dev/mtdblock4`（不存在） | **`/dev/mtdblock2`** |
| kernel 位置 | 0x500000（会压住 rootfs 区） | **0x200000** |
| rootfs 位置 | 未烧 | **0x700000** |

> 用户看到的"企鹅闪一下又消失、反复进行"，就是内核已经正常跑起来、
> 因为找不到根文件系统而 panic 重启，并非内核没启动。

---

## 六、传输稳定性：必须接 5V 独立供电

修复过程中 YMODEM 反复中断，规律很明确：

| 文件 | 包大小 | 结果 |
|---|---|---|
| zImage 4.26MB | 1024 | 成功（当时供电好） |
| u-boot 384KB | 1024 | 第 55 块（56KB）断 |
| rootfs 3.1MB | 1024 | 第 47 块（47KB）断 |
| rootfs 3.1MB | 128 | 187KB 处断 |
| **rootfs 3.1MB** | **1024 + DC 5V 供电** | **一次成功** |

**根因：USB 线同时供电+传数据，大文件传输时电流波动导致板子复位。**
接上 CW210 的 DC 5V 输入（5V/2A）后，USB 只走数据，3.15MB 稳定传完。

---

## 七、最终可用方案（可直接复现）

### 7.1 NAND 布局（以内核分区表为准）

| 分区 | 偏移 | 大小 | 内容 |
|---|---|---|---|
| mtdblock0 | `0x000000` | 2MB | bootloader（原厂 JFJKJ BIOS） |
| mtdblock1 | `0x200000` | 5MB | zImage |
| mtdblock2 | `0x700000` | 剩余 | rootfs.cramfs |

### 7.2 启动参数（已 saveenv 到 params 分区）

```
bootargs=root=/dev/mtdblock2 rootfstype=cramfs init=/linuxrc console=ttySAC0,115200
bootcmd=nand read 0x20008000 0x200000 0x500000; bootm 0x20008000
```

### 7.3 烧录步骤

**准备**：板子接 DC 5V 电源；拨码 `1=ON 2/3/4=OFF` 之外的那一档（USB 下载）为 `ON/OFF/OFF/ON`。

```text
# 1) 进入 u-boot（USB 下载态）
python dnw.py -a 0xd0020010 -f x210_image/image/android_system/x210_usb.bin
python dnw.py -a 0x23e00000 -f x210_image/image/normal_system/u-boot_nomenu.bin

# 2) 烧 kernel 到 0x200000（YMODEM）
loady 0x20008000
# 用 ymodem.py 传 zImage
nand erase 0x200000 0x500000
nand write 0x20008000 0x200000 0x500000

# 3) 烧 rootfs 到 0x700000
loady 0x20008000
# 用 ymodem.py 传 rootfs.cramfs
nand erase 0x700000 0x340000
nand write 0x20008000 0x700000 0x340000

# 4) 写启动参数
setenv bootargs 'root=/dev/mtdblock2 rootfstype=cramfs init=/linuxrc console=ttySAC0,115200'
setenv bootcmd 'nand read 0x20008000 0x200000 0x500000; bootm 0x20008000'
saveenv
```

**校验点（缺一不可）**

| 对象 | 校验方法 | 期望值 |
|---|---|---|
| kernel | `md.l 0x20008024 1` | `016f2818` |
| rootfs | `md.l 0x700000 2` | `28cd3d45 00326000` |
| bootloader | `crc32 0x21000000 0x60000` | `dc445999` |

### 7.4 日常使用

**开机进系统**：断电 → 拨码 `1=ON 2/3/4=OFF` → 上电 → **10 秒内不要碰键盘和串口窗口** → 自动进 `~ #`

**想停 autoboot 进命令行**：上电后 10 秒内按任意键，然后 `run bootcmd`

---

## 八、避坑清单

| # | 坑 | 正确做法 |
|---|---|---|
| 1 | 以为内存 128MB | 实际 1GB，**不要传 `mem=`** |
| 2 | 以为 NAND 启动=全 OFF | **1=ON 2/3/4=OFF** 才是；全 OFF 会 fallback 到 USB |
| 3 | 照文档用 `root=/dev/mtdblock4` | 内核只有 3 个分区，**rootfs 是 mtdblock2** |
| 4 | kernel 放 0x500000 | **放 0x200000**，否则压住 rootfs 区 |
| 5 | 相信 cmdline 的 `mtdparts=` | 内核会用自带分区表，**以 `/proc/mtd` 为准** |
| 6 | PC 端 u-boot 直接烧 NAND | 头部 checksum 是 0，会启动失败；需改成 `sum(data[0x10:0x2000])` |
| 7 | USB 单线供电传大文件 | **必须接 DC 5V**，否则 50~190KB 处必断 |
| 8 | 误判"内核挂了" | MMU 开启后页表没 UART 映射时写串口会 abort；"静默"要先排除这项 |
| 9 | 按键打断 autoboot | 上电后 10 秒内不要碰键盘 |
| 10 | 全 OFF 时以为板子没电 | iROM 会枚举 USB（04E8:1234），说明它在等下载，不是坏 |

---

## 九、遗留问题（不影响使用）

| 现象 | 说明 |
|---|---|
| `SD Read NG` / `Fat32 ... failed` | 没插 SD 卡，bootloader 尝试读升级文件失败，正常 |
| `Goodix-TS ... I2C TEST FAILED` | 触摸屏 I2C 通信异常，shell 不受影响 |
| `gx801 ... I2C connection might be something wrong` | 重力传感器通信告警 |
| `eth0` 无 `UP`、无 IP | **网口没坏**，只是没启用：`ifconfig eth0 192.168.1.6 netmask 255.255.255.0 up` |
| MAC `10:23:45:67:89:ab` | u-boot 环境变量里的假 MAC，建议 `setenv ethaddr` 改掉 |

---

## 十、工具脚本索引

目录：`C:\Users\20808\WorkBuddy\automation-2026-11-23-13-48-36\dnw-python\`

| 脚本 | 用途 |
|---|---|
| `flash_kernel.py` | 烧 zImage 到 NAND |
| `flash_rootfs2.py` | 烧 rootfs + 设置启动参数（最终使用） |
| `flash_uboot.py` | 烧 bootloader（含 NAND 版 checksum 修正） |
| `watch_nand.py` | 被动抓取 NAND 自启动全过程 |
| `read_nandid.py` | 读 NAND ID 确认真实型号 |
| `crc_check.py` | CRC32 校验 NAND 内容 |
| `nand_oob.py` | 查坏块 / dump OOB / 读 NFCONF |
| `tramp_probe.S` | 标记探针 trampoline 源码 |
| `u-boot_nand.bin` | 修正了 BL1 checksum 的 NAND 可启动 u-boot |
