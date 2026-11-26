# tools —— 操作脚本

全部为 Python 3 脚本，依赖：`pyserial`。Windows 下运行（串口 `COM3`，115200）。

安装依赖：

```
pip install pyserial
```

---

## 一、脚本清单

| 脚本 | 作用 |
|---|---|
| `tftp_srv.py` | 自研最小 TFTP 服务器，专为 u-boot 1.3.4 优化。根目录硬编码为 `G:\lcd\android_split`，端口 69 |
| `round_img.py` | 串口核心库：`send()` / `sync_prompt()` / `note()` / `alive()` / `stage()` |
| `restore_linux.py` | **一键恢复 Linux 系统**：TFTP 下发内核与 cramfs，写入 NAND，写回 bootargs/bootcmd/machid，`saveenv` 后自动重启并校验 |
| `fix_cramfs.py` | 只重写 cramfs 到 `0x700000` 并验证（修复 `bad compressed blocksize`） |
| `boot_fix.py` | 修正 `machid` 为 `0x998` 后重启验证 |
| `resume_flash.py` | 分段烧写 rootfs 到 NAND（6 段，每段 ≤20MB 以避开 u-boot 挂死） |
| `board_net.py` | 通过串口启用板子 `eth0`（`192.168.1.6`） |
| `board_check.py` | 查看板子 `ifconfig` / `ps` / 可用服务 |
| `rootfs_yaffs2_fix.py` | Android rootfs 布局转换：把 `name` 前后各 2 字节填充去掉，使其符合标准 yaffs2 |

---

## 二、使用前必读

### 1. 串口必须先释放

`COM3` 常被 SecureCRT 占用（即使界面显示"未连接"也锁端口）。运行脚本前**必须关闭 SecureCRT 的串口会话**，否则报 `PermissionError(13, '拒绝访问。')`。

### 2. TFTP 根目录

`tftp_srv.py` 中 `ROOT = r"G:\lcd\android_split"` 是硬编码的，使用前请改成你的镜像目录，或把镜像放进去。

### 3. `round_img.send()` 的两个坑

```python
# 判断提示符必须匹配完整字符串，不能只判断末字符 '#'
# 否则 tftp 进度条 "####" 会被误判为命令结束
if buf.rstrip().endswith(b"tarena #"):
    break

# tftp / nand 等长命令在等对端响应时会短暂静默，
# idle_limit 必须放宽（脚本中 tftp 传 600）
R.send(ser, "tftp 0x30000000 zImage", wait=120, idle_limit=600)
```

### 4. 板子供电

大文件传输时若只靠 USB 供电，可能中途掉电重启（现象：串口突然重新打印 BIOS 横幅）。建议接 5V 适配器。

### 5. `machid` 必须是 `0x998`

所有涉及启动的脚本都已固定使用 `0x998`。**不要改成 `0x3F80`**，否则内核静默挂死。

---

## 三、典型用法

```bash
# 1) 启动 TFTP 服务器（单独开一个窗口）
python tftp_srv.py

# 2) 一键恢复 Linux 系统（另开窗口，按提示给板子断电重上电）
python restore_linux.py

# 3) 只剩 cramfs 损坏时，单独修复 rootfs
python fix_cramfs.py

# 4) 系统起来后启用网络
python board_net.py

# 5) 重生成 Android 根文件系统（117MB，结果不在仓库内）
python rootfs_yaffs2_fix.py <原始 rootfs_android.bin> <输出目录>
```

---

## 四、`rootfs_yaffs2_fix.py` 说明

原始 Android rootfs 镜像（117,061,824 字节 / 55,427 页，页 2112 = 2048+64）的 yaffs2 ObjectHeader 与标准布局不兼容：

| 偏移 | 原始镜像 | 标准 yaffs2 |
|---|---|---|
| 0x00 | type (u32 LE) | 相同 |
| 0x04 | parentObjectId (u32 LE) | 相同 |
| 0x08 | **`FF FF` 多余填充** | name 起始 |
| 0x0A | name（256 字节） | — |
| 0x10A | **`FF FF` 多余填充** | — |
| 0x10C | mode | mode @0x108 |
| 0x124 | fileSize | fileSize @0x120 |

即 **name 前后各多 2 字节填充，导致尾部字段整体后移 4 字节**。内核按标准解析时 `/system` 的 name 会变成 `\xff\xffsystem`，整棵子树变孤儿。

修复方式（脚本已实现）：对每个 `chunk==0 && seq==0x1000 && 0<obj<0x40000` 的 ObjectHeader 页执行

```python
new[0:8]       = d[0:8]        # type + parent 原样保留
new[8:264]     = d[10:266]     # name 前移 2 字节
new[264:2044]  = d[268:2048]   # mode..尾部再前移 2 字节
new[2044:2048] = b'\x00' * 4   # 尾部补 0
```

数据页（`chunk>0`）与 OOB 全部不动。共处理 **788** 个 ObjectHeader 页。

校验结果：788 对象、0 个无效 parent、0 个成环、mode/fileSize 全正常，`/init`、`/system/bin/servicemanager`、`/system/bin/app_process` 等关键路径全部命中。
