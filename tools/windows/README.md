# tools/windows —— Windows 侧辅助工具

## zadig-2.9.exe

| 项 | 值 |
|---|---|
| 文件 | `zadig-2.9.exe` |
| 版本 | 2.9 |
| 大小 | 5,334,088 字节（5.09 MB） |
| PE 头 | `4D 5A`（正常 Windows 可执行文件） |
| SHA256 | `4ECAA95DF3DA3621486A043AEF8B3050B8BAFE7C901402871E816229EF82039B` |
| 官方来源 | <https://zadig.akeo.ie/> |
| 许可证 | GPLv3（源码见官网及 <https://github.com/pbatard/libwdi>） |

> 本仓库仅为方便同型号板卡维护而附带该工具，版权归原作者 Pete Batard 所有。

---

### 为什么需要它

S5PV210 的 **iROM USB 下载模式**（拨码 1=ON、4=ON）下，板子枚举出来的设备在 Windows 上会被装上**默认驱动**，导致 `dnw` / `libusb` 类工具**无法打开设备**。

典型现象：

- 设备管理器里能看到设备，但 `dnw.py` / DNW 工具提示找不到设备或读取失败
- 反复插拔、换 USB 口都无效
- 用 DNW 下载 BL1（`x210_usb.bin` 到 `0xD0020010`）时，程序无响应或直接报错

**根因**：这类 iROM 下载设备不是标准 CDC/WinUSB 设备，Windows 自带的驱动无法被用户态 USB 库访问。

**解决办法**：用 Zadig 把该设备的驱动替换为 **WinUSB**（或 libusb-win32），之后 `dnw` 即可正常识别。

---

### 使用步骤

1. **板子进入 USB 下载模式**：拨码 **1=ON、2=OFF、3=OFF、4=ON**，USB OTG 线连到 PC，然后**上电**（部分板子需按住 KEYON 键进入）
2. 运行 `zadig-2.9.exe`（需要管理员权限）
3. 菜单 **Options → List All Devices**（必须勾选，否则可能看不到目标设备）
4. 在下拉框里选中目标设备（通常显示为 `S5PV210` / `Samsung ...` / 未知 USB 设备一类的名称）
5. 右侧目标驱动选择 **WinUSB**（本项目实测选 WinUSB 即可；若不行可改选 `libusb-win32`）
6. 点 **Install Driver**（或 **Replace Driver**），等待完成
7. 打开设备管理器确认该设备已归到 **Universal Serial Bus devices → WinUSB device**（或 libusb 分类）下
8. 此时再跑 `dnw.py`，应能正常枚举到设备并下载 BL1/BL2

---

### 与本项目的关联

本项目用 USB 下载方式加载过：

| 文件 | 载入地址 | 作用 |
|---|---|---|
| `bin/bootloader/x210_usb.bin` | `0xD0020010` | BL1 |
| `bin/bootloader/u-boot_nomenu.bin` | `0x23E00000` | BL2（临时 u-boot，不写 NAND） |

这条链路**只在 NAND 里的 bootloader 损坏、或需要在 USB 下载档下临时获得 u-boot 命令行时才会用到**。正常 NAND 启动（拨码 1=ON，其余 OFF）不需要 Zadig，也不需要 USB 连接。

---

### 注意

- 替换驱动会改变该 USB 设备在 Windows 上的驱动绑定。若之后需要恢复原驱动，可在设备管理器中「卸载设备」并勾选删除驱动，然后重新插拔。
- 请勿用 Zadig 去替换键盘、鼠标、U 盘等正常设备的驱动。
- 如果手头没有该文件，可从官网下载对应版本：<https://zadig.akeo.ie/>
