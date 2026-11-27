# USB 摄像头实时显示到 LCD（含开机自启动）

记录时间：2026-11-27
目标板：CW210 / ME210-BOX（S5PV210，LCD 800×480）
摄像头：`USB2.0 PC CAMERA`，VID:PID = `1908:2310`，**UVC 1.00 设备**

---

## 一、结论先行

| 问题 | 结论 |
|---|---|
| 原系统能直接认摄像头吗 | **不能**。内核配置里没有 `CONFIG_USB_VIDEO_CLASS`，插上只枚举 USB 设备，不产生 `/dev/videoN` |
| 现在的方案 | 编译 `uvcvideo.ko` 模块 → 放进 cramfs → 开机 `insmod` → 启动用户态程序推图到 `/dev/fb0` |
| 实测帧率 | **28~29 fps**（640×480 YUYV → 800×480 XRGB8888） |
| 是否开机自启 | **是**，冷启动无需任何手工操作 |

---

## 二、为什么原内核不支持

内核配置文件 `config_CW210_linux_V1.0` 中：

```
CONFIG_MEDIA_SUPPORT=y
CONFIG_VIDEO_DEV=y
CONFIG_VIDEO_V4L2=y
CONFIG_VIDEO_CAPTURE_DRIVERS=y
CONFIG_FB_S3C=y
CONFIG_FB_S3C_LCD800480=y
CONFIG_USB_EHCI_HCD=y
CONFIG_USB_OHCI_HCD=y
CONFIG_USB_STORAGE=y
# 没有 CONFIG_USB_VIDEO_CLASS
```

运行中的设备节点只有 SoC 自带的三路 FIMC 和 TVOUT：

```
/dev/video0  -> s3c-fimc0
/dev/video1  -> s3c-fimc1
/dev/video2  -> s3c-fimc2
/dev/video14 -> S5PC1xx TVOUT ctrl
/dev/video21 -> S5PC1xx TVOUT for Video
```

确认摄像头是 UVC 设备（读 USB 接口类码）：

```
cat /sys/bus/usb/devices/1-1.4:1.0/bInterfaceClass   -> 0e  (Video Class)
cat /sys/bus/usb/devices/1-1.4:1.1/bInterfaceClass   -> 0e
cat /sys/bus/usb/devices/1-1.4:1.2/bInterfaceClass   -> 01  (Audio)
cat /sys/bus/usb/devices/1-1.4:1.3/bInterfaceClass   -> 01
```

---

## 三、编译 uvcvideo.ko

### 3.1 两个必须注意的坑

**坑 1：只改 `CONFIG_USB_VIDEO_CLASS=m` 会被 oldconfig 删掉。**

`drivers/media/video/uvc/Kconfig` 是被包在条件里的：

```
menuconfig V4L_USB_DRIVERS
	bool "V4L USB devices"
	depends on USB
	default y

if V4L_USB_DRIVERS && USB
source "drivers/media/video/uvc/Kconfig"
```

原 config 没有打开 `V4L_USB_DRIVERS`，所以 UVC 符号是"未知符号"，`make oldconfig` 直接把它删了。
**必须先开总开关，再开子项：**

```bash
scripts/config --enable V4L_USB_DRIVERS
scripts/config --module USB_VIDEO_CLASS
yes "" | make oldconfig
make modules_prepare        # 必须重跑，否则 include/config/auto.conf 不更新
```

**坑 2：工具链放在中文路径下会导致 `cc1` 找不到。**

`arm-2009q3` 放在 `...\三星\...\交叉编译器包\...` 时，`arm-linux-gcc` 报：

```
arm-linux-gcc: error trying to exec 'cc1': execvp: No such file or directory
```

但直接运行 `libexec/gcc/arm-none-linux-gnueabi/4.4.1/cc1` 是正常的。
**把工具链拷贝到纯 ASCII 路径**（如 `~/tc_full`）后立即正常。

另外老版 gcc（4.4.1，32 位程序）在 9p 挂载的 `/mnt/g` 上编译会报
`Value too large for defined data type`（inode 号超过 32 位），
**源码要拷到本地 ext4 再编译**。

### 3.2 编译命令

```bash
export PATH=$HOME/tc_full/bin:$PATH
export ARCH=arm
export CROSS_COMPILE=arm-linux-
cd $HOME/kern                     # 内核源码 2.6.35.7
cp config_CW210_linux_V1.0 .config
# ... 按 3.1 打开 V4L_USB_DRIVERS / USB_VIDEO_CLASS ...
make modules_prepare
make M=drivers/media/video/uvc modules
```

产物：`drivers/media/video/uvc/uvcvideo.ko`（70,747 字节）

**vermagic 必须与运行内核完全一致**：

```
vermagic=2.6.35.7-Concenwit preempt mod_unload ARMv7
```

对应运行内核：`Linux version 2.6.35.7-Concenwit (gcc 4.4.6) #5 PREEMPT ... armv7l`
（`CONFIG_MODVERSIONS` 未开启，所以不依赖 `Module.symvers`。）

---

## 四、用户态程序 uvc2fb

源码：[`src/uvc/uvc2fb.c`](../src/uvc/uvc2fb.c)

流程：

```
open(/dev/videoN)
  -> VIDIOC_S_FMT        YUYV 640x480
  -> VIDIOC_REQBUFS      4 个 mmap 缓冲
  -> VIDIOC_STREAMON
  -> 循环: select -> DQBUF -> YUYV 转 XRGB8888 + 缩放到 800x480 -> 写 /dev/fb0 -> QBUF
```

要点：

- **自动找设备**：不带参数时扫描 `/dev/video0..11`，匹配 `cap.card` 含 "USB" 或 `cap.driver` 含 "uvcvideo"，避免写死节点号
- **帧缓冲自适应**：通过 `FBIOGET_VSCREENINFO` 读取 32/16bpp 与 RGB 位偏移，本板实测 `800x480 32bpp line=3200 RGB(16/8,8/8,0/8)`
- **横向映射表**：预先算好 `x -> 源像素偏移`，避免每像素除法
- **帧率统计**：每 100 帧打印 `avg fps` 与 `worst ms`
- **断流看门狗**：连续 6 次 `select` 超时（约 12 秒）主动退出，交给外层守护重启

交叉编译（静态链接，避免 rootfs 里的 glibc 版本问题）：

```bash
arm-linux-gcc -O2 -static -Wall -o uvc2fb uvc2fb.c
```

---

## 五、把改动做进 cramfs

rootfs 是 **cramfs 只读**，`/tmp` 是 tmpfs（重启即丢），所以自启动必须改镜像。

### 5.1 导出当前镜像

```text
# 板子上
cat /proc/mtd                                   # 确认 mtd2 = rootfs，起始 0x700000
od -A d -t x4 -N 16 /dev/mtdblock2              # 前 16 字节
#   0000000 28cd3d45 00364000 00000003 00000000
#   magic=0x28cd3d45  size=0x364000=3,555,328
dd if=/dev/mtdblock2 of=/tmp/rootfs.cramfs bs=1024 count=3472
```

再通过板子自带的 ftpd 取回（注意：`/etc/inetd.conf` 里是 `ftpd -w /tmp/`，**ftp 根目录就是 /tmp**，所以 URL 用相对路径）：

```
ftp://192.168.1.6/rootfs.cramfs
```

### 5.2 解包 / 修改 / 打包

```bash
fsck.cramfs --extract=$HOME/rootfs_ext rootfs.cramfs     # 目录不要预先创建

cp uvcvideo.ko $HOME/rootfs_ext/lib/modules/
cp uvc2fb      $HOME/rootfs_ext/usr/bin/
chmod 755      $HOME/rootfs_ext/lib/modules/uvcvideo.ko $HOME/rootfs_ext/usr/bin/uvc2fb

# 在 /etc/init.d/rcS 末尾追加（见 5.3）

unshare -r mkfs.cramfs -b 4096 -n CW210 $HOME/rootfs_ext rootfs_uvc.cramfs
fsck.cramfs rootfs_uvc.cramfs
```

**为什么要 `unshare -r`**：`mkfs.cramfs` 会把源文件的 uid/gid 写进镜像。普通用户打包含出来全是 1000:1000；
用 `unshare -r` 把自己映射成 root，镜像里记录的就是 0:0。

### 5.3 rcS 追加内容

```sh
# ---- USB 摄像头开机自启（守护重启） ----
[ -e /lib/modules/uvcvideo.ko ] && insmod /lib/modules/uvcvideo.ko
sleep 3
(
    while true; do
        /usr/bin/uvc2fb > /tmp/uvc.log 2>&1
        sleep 3
    done
) &
```

### 5.4 烧录（u-boot，TFTP）

PC 上开 TFTP 服务（根目录放镜像），板子进 u-boot：

```text
setenv ipaddr 192.168.1.6
setenv serverip 192.168.1.13
tftp 0x30000000 rootfs_uvc.cramfs
nand erase 0x700000 0x400000
nand write 0x30000000 0x700000 0x3c2000
boot
```

新镜像大小 **3,940,352 字节 = 0x3C2000**，擦除 4MB 足够覆盖旧镜像（3,555,328 = 0x364000）。

---

## 六、实测验证

| 时间点 | 进程 PID | URB 报错数 | 画面是否刷新 |
|---|---|---|---|
| 18 秒 | 79 | 0 | 是（2 秒间隔两帧 908,596 字节不同） |
| 116 秒 | 79（未重启） | 0 | 是（908,764 字节不同） |
| 209 秒 | 79（未重启） | 0 | 是（900,338 字节不同） |

- 帧率：28~29 fps（摄像头本身 30fps 上限）
- 最差单帧间隔 435.6ms，且**只在启动首帧出现一次**（自动曝光收敛），之后 20 秒内不再增长
- 内存：675MB 中仅用 30MB
- CPU：约 83%（软件 YUYV→RGB 转换 + 缩放）

屏幕截图（从 `/dev/fb0` 导出还原）：[uvc_lcd_screenshot.png](uvc_lcd_screenshot.png)

---

## 七、已知问题

### 7.1 热重启会让摄像头卡死（重要）

用 `reboot` 命令或 u-boot 的 `boot` 重启时，**摄像头供电不断**，驱动再次绑定后会出现：

```
uvcvideo: Failed to resubmit video URB (-27).
uvcvideo: Failed to set UVC probe control : -110 (exp. 26).
```

表现为：设备能枚举、`/dev/video3` 在，但控制传输超时，收不到任何帧。

**解决办法：断电重上电**（拔 DC 电源 10 秒）。冷启动完全正常。

> 这是 uvcvideo 2.6.35 老驱动在这类廉价 UVC 摄像头上的问题，不是本项目代码导致。

### 7.2 守护循环的能力边界

守护循环只处理**软件层断流**（连续 12 秒无帧 → 退出 → 3 秒后重启）。
如果是 USB 设备本身卡死（7.1 的情形），重启程序无效，只能断电。

### 7.3 其他

- 程序直接写 `/dev/fb0`，运行时会覆盖屏幕上的其他内容
- 退出后画面停在最后一帧
- 只支持 **YUYV** 格式；若换 MJPEG-only 的摄像头，需要额外的 JPEG 解码

---

## 八、回滚

烧回改动前的镜像（保留 splash、无摄像头功能）：

```text
tftp 0x30000000 rootfs_splash.cramfs
nand erase 0x700000 0x400000
nand write 0x30000000 0x700000 0x364000
boot
```

该镜像即 `bin/rootfs/rootfs_splash.cramfs`（3,555,328 字节 = 0x364000，
md5 `36757c531463d8d9d40ef05fba24cffe`），与本次改动前从板上 dump 出来的镜像逐字节一致。

若要回到达内原始系统：`bin/rootfs/rootfs.cramfs`（3,301,376 字节，0x326000）。

---

## 九、文件清单

| 文件 | 说明 |
|---|---|
| `bin/uvc/uvcvideo.ko` | UVC 内核模块（70,747 字节） |
| `bin/uvc/uvc2fb` | 显示程序（静态，660,141 字节） |
| `src/uvc/uvc2fb.c` | 显示程序源码 |
| `bin/rootfs/rootfs_uvc.cramfs` | **当前运行的镜像**（含自启动，3,940,352 字节） |
| `bin/rootfs/rootfs_splash.cramfs` | 改动前镜像（保留 Coca-Cola 开机画面，回滚用） |
| `bin/rootfs/rootfs.cramfs` | 达内原始镜像 |
| `docs/uvc_lcd_screenshot.png` | LCD 实际画面截图 |
