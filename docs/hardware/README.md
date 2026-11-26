# docs/hardware —— 硬件原理图与手册

本目录归档 CW210（ME210-BOX 底板）相关的原理图与芯片手册，便于排查接线、引脚定义、电气参数时离线查阅。

```
hardware/
├── schematic/                    原理图
│   ├── CW210-Peripherial_底板.pdf
│   ├── CW210_CORE_TARENA_核心板.pdf
│   └── CW210_CORE_LHGZ_核心板.pdf
└── manual/                       手册与数据手册
    ├── S5PV210_UM_REV1.1_SoC用户手册.pdf
    ├── S5PV210_iROM_ApplicationNote.pdf
    └── K9K8G08U0B_NAND数据手册.pdf
```

---

## 一、原理图（schematic/）

| 文件 | 大小 | 说明 |
|---|---|---|
| `CW210-Peripherial_底板.pdf` | 0.22 MB | **底板原理图**。原文件名 `CW210-Peripherial.pdf`，图纸工程 `H:\ME210-BOX-20120621.DDB`，日期 2012-06-21，A3 幅面 |
| `CW210_CORE_TARENA_核心板.pdf` | 0.38 MB | **核心板原理图（达内 TARENA 版）**。原文件名 `CW210_CORE_TARENA.pdf` |
| `CW210_CORE_LHGZ_核心板.pdf` | 0.39 MB | **核心板原理图（LHGZ 版）**。原文件名 `CW210_CORE_LHGZ.pdf` |

> 两块核心板版本不同，PCB 走线与部分外设定义可能有差异。**以实物板上丝印与对应版本图纸为准**，不确定时两份都对照看。

### 底板原理图页面索引（CW210-Peripherial.pdf，共 12 页）

图纸内的分页命名：

| 页 | 内容 |
|---|---|
| `1_POWER.Sch` | 电源 |
| `2_ETHERNER.Sch` | 以太网 |
| `3_USB@UART.Sch` | **USB 与串口（COM1/COM2、UART1/UART2、USB OTG、RS485、SW3/SW4）** |
| `4_AC97.Sch` | 音频 |
| `5_LCD@VGA.Sch` | LCD 与 VGA |
| `6_OTHER.Sch` | 其他 |
| `7_CONNERCTOR.Sch` | 连接器 |
| `8_SD@WIFI.Sch` | SD 卡与 WiFi |
| `9_TV@ADC.Sch` | TV / ADC |
| `10_HDMI.Sch` | HDMI |
| `11_CAMERAB.Sch` | 摄像头 |

**查接线先看第 3 页（`3_USB@UART.Sch`）**：COM1（DB9，经 SP3232EEN → UART0）、COM2（DB9 → UART1）、UART1/UART2 的 CON4 排针、MAX3485 的 RS485（UART2）、USB OTG、SW3/SW4 拨码都在这一页。

串口与拨码的实测结论见 [../04_接线与拨码配置.md](../04_接线与拨码配置.md)。

---

## 二、手册（manual/）

| 文件 | 大小 | 说明 |
|---|---|---|
| `S5PV210_UM_REV1.1_SoC用户手册.pdf` | 84.63 MB | **Samsung S5PV210 用户手册 Rev1.1**。SoC 级寄存器、时钟、GPIO、FIMD/FIMC/MFC、NAND 控制器、启动流程等的权威依据 |
| `S5PV210_iROM_ApplicationNote.pdf` | 0.68 MB | **iROM 应用笔记**。讲 S5PV210 上电启动流程、OM 拨码与启动介质选择、iROM USB 下载（这正是用 Zadig + DNW 刷机的原理依据） |
| `K9K8G08U0B_NAND数据手册.pdf` | 1.14 MB | **板载 NAND 数据手册**。1GB，2KB 页 + 64B OOB，128KB 块，4-bit ECC。计算 NAND 偏移与 OOB 布局时的依据 |

### 常用查询入口

| 想查什么 | 看哪里 |
|---|---|
| UART 寄存器基址 | `S5PV210_UM_REV1.1` → UART 章节（UART0 = `0xE2900000`，每个 UART 间隔 `0x400`） |
| 为什么 OM 拨码能选启动介质 | `S5PV210_iROM_ApplicationNote` |
| USB 下载模式为什么需要替换驱动 | `S5PV210_iROM_ApplicationNote`（iROM USB 下载章节） |
| NAND 页/块大小、OOB 容量 | `K9K8G08U0B` 数据手册 |
| NAND 偏移与分区换算 | [../04_接线与拨码配置.md](../04_接线与拨码配置.md) 与 [../../bin/README.md](../../bin/README.md) |

---

## 三、说明

- 以上文件均来自该板卡的配套培训资料，版权归原始厂商 / 培训机构所有，本仓库仅作技术归档与离线查阅用。
- `S5PV210_UM_REV1.1_SoC用户手册.pdf` 为 84.63 MB，接近 GitHub 单文件 100MB 上限；克隆仓库时体积较大，如只需原理图可只取 `schematic/` 目录。
