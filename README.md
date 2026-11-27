# s5pv210-cw210-bringup

达内 **CW210**（S5PV210 / ME210-BOX 底板）板卡的系统 bring-up 记录与可复现资源。

本仓库包含**当前实际运行在板子上的完整系统镜像**（u-boot / kernel / rootfs）、内核与 u-boot 源码、全部操作脚本，以及从零到可用的完整排障文档。

---

## 一、硬件与环境

| 项目 | 参数 |
|---|---|
| SoC | Samsung S5PV210（ARM Cortex-A8，1GHz 单核） |
| 内存 | 1GB DDR2，两个 bank：`0x20000000` 512MB + `0x40000000` 512MB |
| NAND | Samsung K9K8G08U0B，1GB，2KB 页 + 64B OOB，128KB 块，4-bit ECC |
| LCD | 800×480 |
| 板卡标识 | 达内 CW210 / ME210-BOX（底板）；u-boot 横幅 `##### JFJKJ BIOS for JFJ210 #####` |
| 调试串口 | UART0（`ttySAC0`，`0xE2900000`），经 SP3232EEN 转 RS232 接到 **COM1（DB9）**，115200-8-N-1 |
| 网络 | DM9000（16 位模式）；PC `192.168.1.13`，板子 `192.168.1.6`（MAC `10:23:45:67:89:ab`） |

> 📌 **接线速查**（实测可用）：
> - 串口：板 **COM1** DB9 的 **2 / 3 / 5** ↔ PC **USB 转 DB9** 的 **2 / 3 / 5**（直连，RS232 电平）
> - 拨码：**SW3 = ON ON OFF OFF**，**SW4 = OFF OFF OFF OFF**
> - 完整说明（含原理图依据、其他串口、故障判读）见 [docs/04_接线与拨码配置.md](docs/04_接线与拨码配置.md)
> - **硬件原理图与手册**（底板 / 核心板 / SoC 手册）见 [docs/hardware/](docs/hardware/README.md)

**拨码开关**

| 用途 | 1 | 2 | 3 | 4 |
|---|---|---|---|---|
| NAND 启动 | **ON** | OFF | OFF | OFF |
| USB 下载 | ON | OFF | OFF | ON |

### USB 下载模式需要先装对驱动 ⚠️

在 **USB 下载档**（1=ON、4=ON）下，S5PV210 的 iROM 会枚举出一个非标准 USB 设备，Windows 默认驱动会让 `dnw` / `libusb` 类工具**无法打开设备**（表现为找不到设备、通信失败、反复插拔无效）。

解决办法：用 **Zadig** 把该设备的驱动替换为 **WinUSB**。

- 工具：`tools/windows/zadig-2.9.exe`（GPLv3，来自 <https://zadig.akeo.ie/>）
- 步骤：运行 Zadig → `Options → List All Devices` → 选中目标设备 → 右侧选 **WinUSB** → `Install Driver`
- 详细说明见 [tools/windows/README.md](tools/windows/README.md)

> 正常 NAND 启动（1=ON，其余 OFF）**不需要** Zadig，也不需要连 USB。只有 bootloader 损坏需要重新刷机、或要在 USB 下载档下临时获得 u-boot 命令行时才用到。

---

## 二、当前板子状态

板子运行的是 **Linux 2.6.35.7 + cramfs** 系统，已完整可用：

```
Linux version 2.6.35.7-Concenwit (linux@linux) (gcc 4.4.6) #5 PREEMPT
Machine: SMDKV210
Memory: 512MB 320MB = 832MB total
VFS: Mounted root (cramfs filesystem) readonly on device 31:2.
~ #
```

- 串口可进 `~ #` shell
- `eth0` 需手动启用（系统默认不开）：
  ```sh
  ifconfig eth0 192.168.1.6 netmask 255.255.255.0 up
  ```
- 启用后 telnet(23)、ftp(21) 均可从 PC 访问
- 832MB 是正常值：1GB 物理内存减去 154MB 多媒体硬件预留（mfc/fimc/jpeg 等）
- 当前 cramfs 系统不含图形程序，LCD 无画面属正常现象（写入 `/dev/fb0` 可验证屏与 framebuffer 正常）

---

## 三、目录结构

```
s5pv210-cw210-bringup/
├── README.md                          本文件
├── docs/                              排障与实现文档
│   ├── 01_CW210_前期调试全记录_上篇.md
│   ├── 02_CW210_NAND自启动_Linux修复完整记录.md
│   ├── 03_CW210_Android尝试与Linux恢复_完整记录.md
│   ├── 04_接线与拨码配置.md             串口/网口/USB 连线与 SW3/SW4 拨码（实测可用）
│   └── hardware/                      硬件原理图与手册
│       ├── README.md
│       ├── schematic/                 底板 + 核心板原理图（3 份 PDF）
│       └── manual/                    S5PV210 SoC 手册 / iROM 笔记 / NAND 数据手册
├── bin/                               当前板上运行的二进制镜像
│   ├── README.md                      每个镜像的烧录位置与命令
│   ├── bootloader/
│   │   ├── u-boot_nomenu.bin          NAND 0x000000，393,216 字节
│   │   └── x210_usb.bin               BL1，USB 下载用，11,168 字节
│   ├── kernel/
│   │   └── zImage                      Linux 内核，4,261,256 字节
│   ├── rootfs/
│   │   └── rootfs.cramfs               cramfs 根文件系统，3,301,376 字节
│   └── android/
│       ├── README.md                   Android 根文件系统（117MB，超 GitHub 单文件上限，见说明）
│       └── zImage_android_fix.bin      Android 内核（补丁版，未成功启动）
├── src/                               源码
│   ├── kernel/
│   │   ├── README.md
│   │   └── kernel_2.6.35.7_CW210.tar.bz2    完整内核源码（69.4MB）
│   └── uboot/
│       └── u-boot_CW210_1.3.4.tar.gz        u-boot 源码（3.9MB）
└── tools/                             操作脚本
    ├── README.md
    ├── tftp_srv.py                    自研 TFTP 服务器（u-boot 1.3.4 专用）
    ├── round_img.py                   串口核心库
    ├── restore_linux.py               一键恢复 Linux 系统
    ├── fix_cramfs.py                  单独重写 cramfs 并验证
    ├── boot_fix.py                    修正 machid 后重启验证
    ├── resume_flash.py                分段烧写 rootfs
    ├── board_net.py                   启用板子 eth0
    ├── board_check.py                 查看板子网络与进程
    ├── rootfs_yaffs2_fix.py           Android rootfs 布局转换（可复现 117MB 镜像）
    └── windows/
        ├── README.md                  USB 下载模式驱动安装说明
        └── zadig-2.9.exe              把 USB 驱动替换为 WinUSB（USB 下载模式必需）
```

---

## 四、NAND 布局与烧录参数

```
mtd0: 0x000000   2 MB      bootloader
mtd1: 0x200000   5 MB      kernel
mtd2: 0x700000   ~1017 MB  rootfs
```

**当前生效的 u-boot 环境变量**

```
arch_number = 0x00000998
boot_params = 0x20000100

bootcmd   = nand read 0x20008000 0x200000 0x500000; bootm 0x20008000
bootargs  = root=/dev/mtdblock2 rootfstype=cramfs init=/linuxrc \
            console=ttySAC0,115200 \
            mtdparts=s5pv210-nand:2m(bootloader),5m(kernel),-(rootfs)
machid    = 0x998

ipaddr    = 192.168.1.100      (u-boot 阶段)
serverip  = 192.168.1.13
netmask   = 255.255.255.0
ethaddr   = 10:23:45:67:89:ab
```

**烧录注意：`nand write` 与 `nand write.yaffs` 不能混用**

| 镜像类型 | 页结构 | 写入命令 |
|---|---|---|
| kernel (zImage) | 2048 字节主区 | `nand write` |
| rootfs (cramfs) | 2048 字节主区 | `nand write` |
| rootfs (yaffs2) | 2112 字节（2048 数据 + 64 OOB） | `nand write.yaffs` |

内核与 cramfs 在写入前建议用 `0xFF` 补齐到 128KB 整数倍（本仓库 `bin/` 中的文件为原始大小，补齐步骤见 `bin/README.md`）。

---

## 五、快速恢复系统

前提：板子能进 u-boot（提示符 `tarena #`），PC 已起 TFTP 服务器（根目录指向镜像所在目录）。

```
setenv ipaddr 192.168.1.100
setenv serverip 192.168.1.13
setenv netmask 255.255.255.0
setenv ethaddr 10:23:45:67:89:ab

# 内核 -> 0x200000（先补 0xFF 到 0x420000 = 4,325,376）
tftp 0x30000000 zImage
nand erase 0x200000 0x00500000
nand write 0x30000000 0x200000 0x420000

# 根文件系统 -> 0x700000（先补 0xFF 到 0x340000 = 3,407,872）
tftp 0x30000000 rootfs.cramfs
nand erase 0x700000 0x00500000
nand write 0x30000000 0x700000 0x340000

# 启动参数（machid 必须是 0x998）
setenv machid 0x998
setenv bootargs 'root=/dev/mtdblock2 rootfstype=cramfs init=/linuxrc console=ttySAC0,115200 mtdparts=s5pv210-nand:2m(bootloader),5m(kernel),-(rootfs)'
setenv bootcmd 'nand read 0x20008000 0x200000 0x500000; bootm 0x20008000'
saveenv
reset
```

成功判据：串口出现 `VFS: Mounted root (cramfs filesystem)` 与 `~ #`。

也可以用 `tools/restore_linux.py` 全自动完成（脚本内置串口抓取与校验）。

---

## 六、关键结论与重要注意事项

### 6.1 `machid` 必须是 `0x998` ⚠️

u-boot 的 `bdinfo` 显示 `arch_number = 0x00000998`。**不要把它改成 `0x3F80`**：内核会在机器 ID 校验处进入 `while(1)` 静默死循环，现象是打印完 `Uncompressing Linux... done, booting the kernel.` 之后**再无任何输出**，极难定位。

> 内核镜像里确实能找到 `nr=0x3F80 / "SMDKV210"` 的字符串组合，那是误导——实测只有 `0x998` 能让内核正常启动。

### 6.2 带 OOB 的 NAND dump 不能直接 `nand write`

若某个备份文件大小是 **2112 的整数倍**（如 4,325,376 = 2048 × 2112），说明它是**含 64 字节 OOB 的原始 dump**。用 `nand write` 会把 OOB 打进数据区导致整体错位，表现为：

```
cramfs: bad compressed blocksize xxxxx
Failed to execute /linuxrc.  Attempting defaults...
Kernel panic - not syncing: No init found.
```

必须改用干净的 cramfs（大小是 2048 的整数倍），或先剥离 OOB。

### 6.3 `nand read` 读 yaffs2 区域必然报 `-74`

yaffs2 镜像的 OOB 里存的是 tag 而不是硬件 ECC，因此用带 ECC 校验的 `nand read` 读取必然返回 `Read failed ..., -74`。**这是正常现象，不代表数据损坏。**

### 6.4 TFTP 传输单个文件不要超过约 60MB

u-boot 1.3.4 的 DM9000 16 位轮询驱动在长时间高负载下会挂死。111MB 的 Android rootfs 必须切成 6 段（每段 ≤20MB）逐段传输并写入。

### 6.5 Android 未能启动的结论

Android 根文件系统已修正为标准 yaffs2 并通过 788 个对象全量校验，Android 内核也确认被 CPU 执行（UART 探针打印出标记字符），但**死在解压器的 MMU/cache 初始化之前**，`Starting kernel ...` 之后零输出。

已逐项排除：rootfs 格式、zreladdr、加载地址、机器 ID、`mtdparts`、`mem=`、`noinitrd`、多媒体预留表、内建 cmdline 串口、镜像完整性、L2 cache 地址。详见 [docs/03_CW210_Android尝试与Linux恢复_完整记录.md](docs/03_CW210_Android尝试与Linux恢复_完整记录.md)。

后续若要继续，需从源码重编内核（源码与配套 GCC 4.4.1 工具链均已确认存在，见文档第六、七节）。

---

## 七、文档索引

| 文档 | 内容 |
|---|---|
| [01_CW210_前期调试全记录_上篇.md](docs/01_CW210_前期调试全记录_上篇.md) | 最早期的串口、DNW、BL1/BL2、内存与启动失败的排查 |
| [02_CW210_NAND自启动_Linux修复完整记录.md](docs/02_CW210_NAND自启动_Linux修复完整记录.md) | 从 USB 下载态到 NAND 自启动 Linux 的完整修复过程 |
| [03_CW210_Android尝试与Linux恢复_完整记录.md](docs/03_CW210_Android尝试与Linux恢复_完整记录.md) | Android 2.3 的尝试全过程、根因分析、以及 Linux 系统的恢复方法 |
| [04_接线与拨码配置.md](docs/04_接线与拨码配置.md) | **串口/网口/USB 连线、SW3/SW4 拨码、启动方式、接线速查表与日志判读** |
| [05_USB摄像头实时显示与开机自启动.md](docs/05_USB摄像头实时显示与开机自启动.md) | **给内核补 UVC 驱动、cramfs 加自启动、实测 28~29fps 的完整过程与坑** |
| [06_DS18B20温度水印_完整记录.md](docs/06_DS18B20温度水印_完整记录.md) | **DS18B20 驱动编译、温度水印叠加、三个“水印看不见”的坑、cramfs 烧录** |
| [hardware/](docs/hardware/README.md) | **硬件原理图与手册**：底板图、核心板图（TARENA / LHGZ 两版）、S5PV210 SoC 用户手册、iROM 应用笔记、NAND 数据手册 |

---

## 八、镜像与源码来源

| 内容 | 来源 |
|---|---|
| `bin/bootloader/u-boot_nomenu.bin` | 板卡配套资源 `image/normal_system/u-boot_nomenu.bin`，已写入 NAND 0x0 |
| `bin/bootloader/x210_usb.bin` | 配套资源 `image/android_system/x210_usb.bin`（BL1，USB 下载用） |
| `bin/kernel/zImage` | 配套资源 `image/normal_system/zImage`（Linux 2.6.35.7-Concenwit #5） |
| `bin/rootfs/rootfs.cramfs` | 配套资源 `image/normal_system/rootfs.cramfs` |
| `bin/rootfs/rootfs_wm.cramfs` | **当前板内运行**：摄像头 + DS18B20 温度水印 + 两个驱动 + rcS 自启动（3,944,448 字节） |
| `bin/rootfs/rootfs_uvc.cramfs` | 只有摄像头、无水印（3,940,352 字节） |
| `bin/rootfs/rootfs_splash.cramfs` | 加摄像头功能之前的镜像（3,555,328 字节），回滚用 |
| `bin/uvc/uvcvideo.ko` | 自行编译的 UVC 驱动模块，vermagic `2.6.35.7-Concenwit preempt mod_unload ARMv7` |
| `bin/uvc/ds18b20_drv.ko` | DS18B20 温度驱动模块（已改 `msleep` + 静音 printk），vermagic 同上 |
| `bin/uvc/uvc2fb` | 摄像头→帧缓冲显示程序（ARM 静态，含温度水印） |
| `bin/android/zImage_android_fix.bin` | 由配套资源 `image/android_system/zImage.bin` 打补丁生成（清零多媒体预留表 + 内建 console 改 `ttySAC0`） |
| `src/kernel/kernel_2.6.35.7_CW210.tar.bz2` | 培训资料 `porting/kernel.tar.bz2` |
| `src/uboot/u-boot_CW210_1.3.4.tar.gz` | 培训资料 `porting/env/u-boot_CW210_1.3.4.tar.gz` |

以上原始资源版权归原始厂商/培训机构所有，本仓库仅用于该板卡的学习与维护归档。

---

## 九、配套交叉工具链（未入库，体积超限）

- 名称：**Sourcery G++ Lite 2009q3-67**（GCC 4.4.1），`arm-none-linux-gnueabi-`
- 原始包：培训资料 `env/交叉编译器包/arm-2009q3.tar.bz2`（261.9MB）
- **注意：该压缩包存在 CRC 损坏**，直接用 `tar -xjf` 会报 `bzip2: Data integrity error`。需用 WinRAR / Bandizip 之类容错工具解压
- 该工具链是 **32 位 x86 程序**，在现代 64 位 Linux（如 Ubuntu 24.04）上需先安装 32 位运行库：
  ```bash
  sudo dpkg --add-architecture i386
  sudo apt-get update
  sudo apt-get install -y libc6:i386 libstdc++6:i386
  ```
- 用现代环境编译 Linux 2.6.35 还需额外处理，详见 [docs/03_CW210_Android尝试与Linux恢复_完整记录.md](docs/03_CW210_Android尝试与Linux恢复_完整记录.md) 第七节

---

## 十、USB 摄像头实时显示（2026-11 新增）

板子系统现在可以做到：**插上 UVC 摄像头，开机自动在 LCD 上显示实时画面，无需任何手工操作。**

| 项目 | 结果 |
|---|---|
| 摄像头 | `USB2.0 PC CAMERA`，`1908:2310`，UVC 1.00 |
| 原内核 | **没有** `CONFIG_USB_VIDEO_CLASS`，插上只有 USB 枚举，没有 `/dev/videoN` |
| 解决 | 自编 `uvcvideo.ko` + 重做 cramfs 加入 `insmod` 与启动脚本 |
| 采集/输出 | 640×480 YUYV → 800×480 XRGB8888（32bpp） |
| 实测帧率 | **28~29 fps**，连续 209 秒零 URB 报错 |
| 自启动 | 冷启动全自动；守护循环负责断流自愈 |

两个必须知道的坑：

1. **只改 `CONFIG_USB_VIDEO_CLASS=m` 会被 oldconfig 删掉** —— 必须先打开 `V4L_USB_DRIVERS` 这个总开关，UVC 的 Kconfig 才会被 source 进来。
2. **交叉工具链放在中文路径下会导致 `cc1` 找不到**（`execvp: No such file or directory`），需复制到纯 ASCII 路径。

重要限制：

> **不要用 `reboot` 或 u-boot 的 `boot` 热重启。** 摄像头供电不断时，驱动重新绑定后会报
> `Failed to resubmit video URB (-27)` / `Failed to set UVC probe control : -110`，画面不再输出。
> **拔掉 DC 电源等 10 秒再上电即可恢复。**

另外，当前 `bootargs` 已加入 **`consoleblank=0`**：否则内核会在 10 分钟后关闭 LCD
（程序用 mmap 写 `/dev/fb0` 不算控制台活动，不会重置息屏定时器）。
注意 u-boot 1.3.4 的**命令行缓冲区会把长 setenv 截断**，需用短变量分段拼接，
详见文档 7.4 节。

完整过程（含 cramfs 解包/打包、u-boot 烧录参数、回滚方法）见
[docs/05_USB摄像头实时显示与开机自启动.md](docs/05_USB摄像头实时显示与开机自启动.md)。

> 归档提交：`2d40538`（2026-11-27）`feat: USB 摄像头实时显示到 LCD 并开机自启`，共 7 个文件 / +637 行。

---

## 十一、DS18B20 温度水印（2026-11 新增）

在第十章的摄像头画面上，**左上角实时叠加板载 DS18B20 的实测温度**，同样开机全自动。

| 项目 | 结果 |
|---|---|
| 传感器 | 原理图 U20 DS18B20，DQ → **XEINT8 = GPH1_0**，R20 4.7K 上拉 3V3_IO |
| 驱动 | 自编 `ds18b20_drv.ko`（3,814 字节），misc 设备 `/dev/ds18b20` |
| 数据格式 | `read()` 返回 4 字节 int，单位 0.0001℃（`285625` = 28.5625℃） |
| 水印样式 | 白字黑底 `T=28.6C`，5×7 点阵 ×5 放大，矩形 247×47，位于 (8,8) |
| 实测 | 冷启动后识别为 **T=28.6C**，与 `dd if=/dev/ds18b20` 一致 |
| 自启动 | rcS 先 `insmod` 两个模块，再由守护循环拉起 `uvc2fb` |

驱动相对原版改了两处：

1. `ds18b20_reset()` 去掉成功时的 `printk` —— 每秒打印会让 fbcon 重绘并**盖掉水印**。
2. `mdelay(750)` → `msleep(750)` —— `read()` 在进程上下文，忙等会白烧 43% CPU。

水印能稳定显示的关键：**YUYV→RGB 转换时直接跳过水印矩形**。
如果只在帧末绘制，下一帧从 y=0 整屏重写，水印只可见约 1ms。

另外温度读取放在 `fork` 出的子进程里（`read()` 每次阻塞 750ms），
子进程必须把 `SIGTERM/SIGINT/SIGHUP` 恢复为 `SIG_DFL` 并关掉继承的 3~63 号 fd，
否则 `killall` 杀不掉、`rmmod` 报 device busy。

完整过程（引脚核对、两处修改、点阵字体、三个坑、cramfs 重打包与烧录、回滚）见
[docs/06_DS18B20温度水印_完整记录.md](docs/06_DS18B20温度水印_完整记录.md)。

> 效果截图：[docs/uvc_temp_watermark.png](docs/uvc_temp_watermark.png)（800×480 帧缓冲原始导出）
