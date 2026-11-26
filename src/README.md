# src —— 源码

| 目录 | 文件 | 大小 | 说明 |
|---|---|---|---|
| `kernel/` | `kernel_2.6.35.7_CW210.tar.bz2` | 69.4 MB | 完整内核源码，`VERSION=2 PATCHLEVEL=6 SUBLEVEL=35 EXTRAVERSION=.7` |
| `uboot/` | `u-boot_CW210_1.3.4.tar.gz` | 3.9 MB | u-boot 1.3.4 CW210 版源码 |

---

## 一、内核源码要点

解压后顶层目录为 `kernel/`，共约 **34,098 个文件 / 465MB**。

CW210 相关文件：

```
kernel/arch/arm/mach-s5pv210/mach-cw210.c                    CW210 板级定义
kernel/arch/arm/mach-s5pv210/cw210-rtc.c                     RTC
kernel/arch/arm/mach-s5pv210/include/mach/gpio-cw210.h       GPIO
kernel/arch/arm/configs/cw210_defconfig                      完整 Linux 配置（67,959 字节）
kernel/arch/arm/configs/smdkv210_android_defconfig           Android 最小 defconfig（7,783 字节）
kernel/config_CW210_linux_V1.0                               另一份完整 Linux 配置
kernel/drivers/video/samsung/cw210_800*480.c                 LCD 800×480
kernel/drivers/video/samsung/cw210_640*480.c
kernel/drivers/char/cw210_beep.c                             蜂鸣器
kernel/drivers/char/cw210_leds.c                             LED
kernel/drivers/input/touchscreen/cw210_ts.c                  触摸屏
kernel/drivers/input/keyboard/cw210_hs0038.c                 红外
```

关键源码事实：

| 项 | 值 / 位置 |
|---|---|
| `PHYS_OFFSET` | `0x20000000`（`arch/arm/mach-s5pv210/include/mach/memory.h`） |
| 解压目标（zreladdr） | `0x20008000` |
| 调试串口宏 | `arch/arm/mach-s5pv210/include/mach/debug-macro.S`：`add rx, rx, #(0x400 * CONFIG_DEBUG_S3C_UART)` |
| 解压器 putc 串口 | `arch/arm/plat-samsung/include/plat/uncompress.h`：`uart_base = S3C_PA_UART + (S3C_UART_OFFSET * CONFIG_S3C_LOWLEVEL_UART_PORT)` |
| printk 直通 | `kernel/printk.c`：`#ifdef CONFIG_DEBUG_LL  printascii(printk_buf);` |

`smdkv210_android_defconfig` 里 `CONFIG_CMDLINE="console=ttySAC2,115200"`，与预编译 Android 内核的内建 cmdline **逐字一致**，可据此确认该 defconfig 就是编 Android 内核用的。

---

## 二、用现代环境编译 2.6.35 的已知障碍

| 现象 | 原因 | 处理 |
|---|---|---|
| `make: *** empty variable name. Stop.` | 源码解压不完整（缺 `scripts/Kbuild.include`） | 重新完整解压，确认文件数约 34,098 |
| `kernel/timeconst.h] Error 255` | `kernel/timeconst.pl` 用了 `defined(@val)`，Perl 5.22+ 为致命错误 | `sed -i 's/if (!defined(@val))/if (!@val)/' kernel/timeconst.pl` |
| `wext-priv.c / wext-spy.c: 'struct net_device' has no member named 'wireless_handlers' / 'wireless_data'` | `WEXT_SPY`/`WEXT_PRIV` 被打开但 `WIRELESS_EXT` 未开，且 Kconfig 不允许手动关闭 | 注释 `net/wireless/Makefile` 中 `obj-$(CONFIG_WEXT_SPY)` 与 `obj-$(CONFIG_WEXT_PRIV)` 两行 |
| `undefined reference to '__tracepoint_kmalloc' / 'kmem_cache_alloc_notrace'` | 该源码树中 `CONFIG_TRACING` 无法通过 Kconfig 打开（非提示符号，`oldconfig` 会丢弃），但 `mm/slub.c` 仍引用 `trace_kmalloc()` | **未解决**。建议给 `arch/arm/Kconfig` 的 `CONFIG_ARCH_S5PV210` 加 `select TRACING`，从配置层正确打开 |

编译命令：

```bash
export PATH=<toolchain>/bin:$PATH
export ARCH=arm
export CROSS_COMPILE=arm-none-linux-gnueabi-
make mrproper
make cw210_defconfig          # Linux 配置（已验证可编译出能启动的内核）
# 或 make smdkv210_android_defconfig   # Android 配置
make -j16 zImage
```

产物：`arch/arm/boot/zImage`

---

## 三、u-boot 源码

解压后为 U-Boot 1.3.4 的 CW210 定制版。默认环境包含：

```
bootdelay=3
ethaddr=00:40:5c:26:0a:5b
lcdtype=X800Y480
mtdids=nand0=s5pv210-nand
mtdparts=mtdparts=s5pv210-nand:1m@0(bios),1m(params),3m(logo),5m(kernel),-(root)
bootcmd=nand read 0x20008000 0x500000 0xb80000 ; bootm 0x20008000
bootargs=console=ttySAC0,115200 root=/dev/ram rw rdinit=/linuxrc mem=512M ignore_loglevel
```

支持从环境变量指定机器 ID（串口会打印 `Using machid 0x%x from environment`）。

> ⚠️ 本板实测必须使用 `machid 0x998`（u-boot `bdinfo` 的 `arch_number`）。设成 `0x3F80` 会让内核静默挂死。

---

## 四、交叉工具链（未入库）

**Sourcery G++ Lite 2009q3-67**，GCC 4.4.1，前缀 `arm-none-linux-gnueabi-`。

- 原始包：培训资料 `env/交叉编译器包/arm-2009q3.tar.bz2`（261.9MB），**CRC 损坏**，需 WinRAR/Bandizip 容错解压
- 是 **32 位 x86 程序**，在现代 Linux 上需安装 32 位运行库：
  ```bash
  sudo dpkg --add-architecture i386
  sudo apt-get update
  sudo apt-get install -y libc6:i386 libstdc++6:i386
  ```
- 解压后目录形如 `arm-2009q3/arm-2009q3/{bin,lib,libexec,arm-none-linux-gnueabi,share}`
- 验证：`arm-none-linux-gnueabi-gcc --version` 应输出 `Sourcery G++ Lite 2009q3-67) 4.4.1`
