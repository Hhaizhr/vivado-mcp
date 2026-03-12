# IP 调试实践手册

> 基于 PCIe GT 引脚映射调试经验编写。涵盖 `inspect_ip_params`、`compare_xci` 两个新工具的实战用法，以及与现有诊断工具的组合工作流。

---

## 目录

1. [工具概览](#1-工具概览)
2. [案例一：PCIe GT 引脚映射冲突排查](#2-案例一pcie-gt-引脚映射冲突排查)
3. [案例二：XCI 配置迁移验证](#3-案例二xci-配置迁移验证)
4. [案例三：IP 参数探索与隐藏参数发现](#4-案例三ip-参数探索与隐藏参数发现)
5. [组合工作流](#5-组合工作流)
6. [架构差异：7-Series vs UltraScale+](#6-架构差异7-series-vs-ultrascale)
7. [常见 IP 配置问题清单](#7-常见-ip-配置问题清单)
8. [高级技巧](#8-高级技巧)

---

## 1. 工具概览

### `inspect_ip_params` — 查询 IP 所有配置参数

**原理**：通过 Vivado Tcl API `list_property` + `get_property` 获取 IP 实例的所有 `CONFIG.*` 属性。这些属性包含 GUI 中不可见的隐藏参数，比 IP Customization 界面显示的参数更多。

**前置条件**：需要活跃的 Vivado 会话 + 已打开的项目。

```
inspect_ip_params(ip_name="xdma_0")                    # 列出所有参数
inspect_ip_params(ip_name="xdma_0", filter_keyword="gt")  # 只看 GT 相关
inspect_ip_params(ip_name="xdma_0", filter_keyword="lane") # 只看 Lane 相关
```

### `compare_xci` — 对比两个 XCI 配置文件

**原理**：XCI 文件是 XML 格式，包含 IP 的所有 `spirit:configurableElementValue` 参数。工具直接解析 XML 并逐参数对比。

**前置条件**：无需 Vivado 会话，只需 XCI 文件路径可访问。

```
compare_xci(
    file_a="path/to/working.xci",    # 基准（正常工作的配置）
    file_b="path/to/broken.xci",     # 待检查（有问题的配置）
)
```

---

## 2. 案例一：PCIe GT 引脚映射冲突排查

### 2.1 问题表现

实现完成后出现 16 条 `[Vivado 12-1411]` CRITICAL WARNING：

```
CRITICAL WARNING: [Vivado 12-1411] Cannot set LOC property of port pcie_7x_mgt_rtl_0_rxp[0],
because the PACKAGE_PIN AA4 is occupied by pcie_7x_mgt_rtl_0_rxn[7]
```

PCIe 链路无法建立，LTSSM 卡在 Detect 状态。

### 2.2 排查步骤

**步骤 1：确认 CRITICAL WARNING 分类**

```
get_critical_warnings(run_name="impl_1")
```

输出：
```
!! 发现 16 条 CRITICAL WARNING !!
--- [Vivado 12-1411] GT_PIN_CONFLICT (16 条) ---
  受影响端口: rxp[0]~rxp[7], txp[0]~txp[7]
  约束文件: board_pins.xdc
  建议: GT端口PACKAGE_PIN约束与IP内部LOC冲突...
  诊断: 运行 inspect_ip_params(filter_keyword='gt') 确认 IP 支持哪些 GT 参数
```

**步骤 2：查看 IP 的 GT 配置参数**

```
inspect_ip_params(ip_name="xdma_0", filter_keyword="gt")
```

输出：
```
=== IP 参数报告: xdma_0 ===
VLNV: xilinx.com:ip:xdma:4.1
过滤关键词: 'gt' (匹配 5 条)

  PCIE_GT_DEVICE                 GTX
  GT_LOC_NUM                     4
  GT_CHANNEL_LOC                 X0Y4 X0Y5 X0Y6 X0Y7
  DISABLE_GT_LOC                 false
  GT_DEBUG_PORTS                 false
```

关键发现：`GT_CHANNEL_LOC` 显示 IP 将 Lane 0 映射到 `X0Y4`，但 PCB 走线是 Lane 0 连接到 `X0Y0`。

**步骤 3：验证 IO 实际分配**

```
verify_io_placement_tool()
```

输出确认 XDC 中 rxp[0]=AA4 但实际放在了 M6，16 个 GT 端口全部不匹配。

**步骤 4：组合 IO 报告和 IP 参数生成映射表**

```
get_io_report()
```

让 AI 助手将 `get_io_report` 的 Bank/Site 数据与 `inspect_ip_params` 的 GT_CHANNEL_LOC 对照，生成映射表：

```
Lane  | IP 内部 GT LOC | XDC PACKAGE_PIN | 实际 Site       | 状态
------|----------------|-----------------|-----------------|------
  0   | X0Y4           | AA4 (Bank 115)  | M6 (Bank 116)   | 冲突
  1   | X0Y5           | AB6 (Bank 115)  | L4 (Bank 116)   | 冲突
  ...
```

### 2.3 修复方案

**方案 A（推荐）：删除 XDC 中 GT PACKAGE_PIN 约束**

删除 `board_pins.xdc` 中所有 `rxp`/`rxn`/`txp`/`txn` 的 `PACKAGE_PIN` 约束，让 IP 自动放置 GT 端口。

**方案 B：修正 XDC 引脚顺序**

调整 XDC 中 GT 引脚的分配顺序，使 Lane 0→7 与 IP 内部 GT LOC 映射一致。

> **注意**：对于 7-Series `pcie_7x` IP，`DISABLE_GT_LOC=true` 不会生效。详见[第 6 节](#6-架构差异7-series-vs-ultrascale)。

---

## 3. 案例二：XCI 配置迁移验证

### 3.1 场景

将 PCIe 设计从 Board A 迁移到 Board B，需要确认 IP 配置的所有差异。

### 3.2 操作步骤

```
compare_xci(
    file_a="board_a/xdma_0.xci",    # Board A 的正常配置
    file_b="board_b/xdma_0.xci",    # Board B 的修改后配置
)
```

输出：
```
=== XCI 配置对比 ===
文件 A: board_a/xdma_0.xci
文件 B: board_b/xdma_0.xci
IP 类型匹配: 是
相同参数: 45, 差异参数: 4

--- 差异参数 ---
  PF0_DEVICE_ID
    A: 9024
    B: 9038
  PL_LINK_CAP_MAX_LINK_SPEED
    A: 5.0_GT/s
    B: 8.0_GT/s
  PCIE_LANE_REVERSAL
    A: false
    B: true
  AXISTEN_IF_WIDTH
    A: 64_bit
    B: 128_bit
```

### 3.3 分析要点

1. **PF0_DEVICE_ID** — 板卡标识变更，正常
2. **PL_LINK_CAP_MAX_LINK_SPEED** — 速度从 Gen2 升到 Gen3，需确认 Board B 的 GT 支持 8.0 GT/s
3. **PCIE_LANE_REVERSAL** — Board B 启用了 Lane Reversal，需确认 PCB 走线是否反向
4. **AXISTEN_IF_WIDTH** — AXI 总线宽度翻倍，下游逻辑需适配

### 3.4 全量对比

如果需要确认所有参数（包括相同的）：

```
compare_xci(file_a="board_a/xdma_0.xci", file_b="board_b/xdma_0.xci", show_all=True)
```

---

## 4. 案例三：IP 参数探索与隐藏参数发现

### 4.1 场景

需要了解 IP 到底有哪些可配置项，特别是 GUI 中看不到的参数。

### 4.2 分类探索

```
# 查看所有参数（可能很多）
inspect_ip_params(ip_name="xdma_0")

# 按类别过滤
inspect_ip_params(ip_name="xdma_0", filter_keyword="pcie")   # PCIe 协议参数
inspect_ip_params(ip_name="xdma_0", filter_keyword="axi")    # AXI 接口参数
inspect_ip_params(ip_name="xdma_0", filter_keyword="dma")    # DMA 引擎参数
inspect_ip_params(ip_name="xdma_0", filter_keyword="bar")    # BAR 配置
inspect_ip_params(ip_name="xdma_0", filter_keyword="debug")  # 调试端口
inspect_ip_params(ip_name="xdma_0", filter_keyword="clock")  # 时钟配置
```

### 4.3 典型隐藏参数

以下参数在 Vivado GUI 的 IP Customization 界面中通常不可见，但可通过 `inspect_ip_params` 发现：

| 参数 | 说明 | 影响 |
|------|------|------|
| `DISABLE_GT_LOC` | 禁用 IP 自动生成的 GT LOC 约束 | 仅 UltraScale+ 有效 |
| `GT_DEBUG_PORTS` | 暴露 GT DRP 调试端口 | 可用于运行时调整 GT 参数 |
| `PCIE_EXT_CLK` | 使用外部时钟输入 | 多 IP 共享时钟时使用 |
| `PCIE_EXT_GT_COMMON` | 使用外部 GT Common | 多 GT Quad 共享时使用 |
| `DEDICATE_PERST` | 专用 PERST# 引脚 | 影响复位信号路由 |

---

## 5. 组合工作流

### 5.1 完整 PCIe 调试流程

```
1. get_critical_warnings(run_name="impl_1")
   └─ 确认是否有 [12-1411] GT 引脚冲突

2. inspect_ip_params(ip_name="xdma_0", filter_keyword="gt")
   └─ 查看 GT_CHANNEL_LOC 和 DISABLE_GT_LOC 设置

3. verify_io_placement_tool()
   └─ 对比 XDC 约束与实际 IO 分配

4. get_io_report()
   └─ 获取所有端口的 Bank/Site 详情

5. 让 AI 组合 2+4 的数据生成 GT 通道映射表
   └─ 对照 PCB 原理图确认走线

6. 修复 XDC 后重新 run_implementation
   └─ 再次 get_critical_warnings 验证修复
```

### 5.2 IP 版本升级验证流程

```
1. compare_xci(file_a="old_version.xci", file_b="new_version.xci")
   └─ 确认参数差异

2. inspect_ip_params(ip_name="ip_name")
   └─ 在新版本中验证关键参数是否生效

3. run_synthesis + run_implementation
   └─ 自动诊断检测新引入的 CRITICAL WARNING

4. get_critical_warnings
   └─ 对比升级前后的 warning 变化
```

### 5.3 多板卡适配流程

```
1. compare_xci(file_a="board_a.xci", file_b="board_b.xci")
   └─ 列出配置差异

2. 逐项确认差异是否正确：
   - 器件型号/速度等级
   - RefClk 频率
   - Lane Width / Speed
   - Lane Reversal
   - GT Location

3. inspect_ip_params(filter_keyword="loc")
   └─ 验证 GT Location 与新板卡 PCB 匹配

4. 修改 XDC 适配新板卡引脚
```

---

## 6. 架构差异：7-Series vs UltraScale+

这是 IP 配置调试中**最容易踩的坑**。两代架构在 GT LOC 约束处理上有根本区别：

### 7-Series（pcie_7x IP）

```
GT LOC 约束来源: IP 内部 .ttcl 模板文件
生成方式:        无条件生成（没有 if 判断）
disable_gt_loc:  参数存在但不会传递到子 IP，设了也无效
修复方法:        只能删除 XDC 中的 GT PACKAGE_PIN，或修正引脚顺序
```

**技术细节**：`pcie_7x` IP 的 `.ttcl` 模板直接将 `GT_CHANNEL_LOC` 硬编码为 LOC 约束，没有条件分支。即使在 IP Customization 中设置 `Disable GT Channel LOC Constraint = true`，该参数只影响顶层 IP 的 XCI，不会传递到内部子 IP `pcie2_ip`。

### UltraScale+（GT Wizard IP）

```
GT LOC 约束来源: GT Wizard 参数化生成
生成方式:        条件生成（受 disable_gt_loc 控制）
disable_gt_loc:  有效，设为 true 后不生成 GT LOC 约束
修复方法:        设置 disable_gt_loc=true，然后在 XDC 中手动指定 GT LOC
```

### 如何判断当前架构

```
inspect_ip_params(ip_name="xdma_0", filter_keyword="gt_device")
```

- 输出 `GTX` → 7-Series
- 输出 `GTH` → 可能是 7-Series(Kintex-7) 或 UltraScale
- 输出 `GTY` → UltraScale+

---

## 7. 常见 IP 配置问题清单

| 问题 | 检查方法 | 关键参数 |
|------|---------|---------|
| Lane Width 不对 | `inspect_ip_params(filter='width')` | `PL_LINK_CAP_MAX_LINK_WIDTH` |
| RefClk 频率错误 | `inspect_ip_params(filter='clk')` | `REF_CLK_FREQ`, `PCIE_REFCLK_FREQ` |
| Lane 翻转不匹配 | `inspect_ip_params(filter='reversal')` | `PCIE_LANE_REVERSAL` |
| GT 位置冲突 | `inspect_ip_params(filter='gt')` | `GT_CHANNEL_LOC`, `PCIE_GT_DEVICE` |
| Link Speed 不达标 | `inspect_ip_params(filter='speed')` | `PL_LINK_CAP_MAX_LINK_SPEED` |
| BAR 大小不对 | `inspect_ip_params(filter='bar')` | `PF0_BAR*_SCALE`, `PF0_BAR*_SIZE` |
| DMA 通道配置 | `inspect_ip_params(filter='dma')` | `NUM_OF_DMA*` |
| Device/Vendor ID | `inspect_ip_params(filter='device_id')` | `PF0_DEVICE_ID`, `PF0_VENDOR_ID` |

---

## 8. 高级技巧

### 8.1 查看 xgui/*.tcl 文件

IP 的 `xgui/*.tcl` 文件包含参数的条件可见性逻辑——哪些参数在什么条件下显示或隐藏。可以直接用 `run_tcl` 搜索：

```
run_tcl(command="glob -nocomplain [get_property IP_DIR [get_ips xdma_0]]/xgui/*.tcl")
```

然后读取文件内容，搜索 `PARAM_VALUE.` 查找所有可配置参数及其条件。

### 8.2 对比 IP 内部约束文件

IP 内部的 XDC 约束文件可以通过 `run_tcl` 找到：

```
run_tcl(command="get_files -of_objects [get_ips xdma_0] -filter {FILE_TYPE == XDC}")
```

### 8.3 批量检查多个 IP

如果项目中有多个 IP，可以逐个检查：

```
# 先列出所有 IP
run_tcl(command="get_ips")

# 然后逐个检查
inspect_ip_params(ip_name="xdma_0")
inspect_ip_params(ip_name="clk_wiz_0")
inspect_ip_params(ip_name="mig_0")
```

### 8.4 XCI 文件位置

XCI 文件通常位于：

```
<project_dir>/<project_name>.srcs/sources_1/ip/<ip_name>/<ip_name>.xci
```

可以通过 `run_tcl` 获取精确路径：

```
run_tcl(command="get_files -of_objects [get_ips xdma_0] -filter {FILE_TYPE == XCI}")
```

### 8.5 结合 CRITICAL WARNING 分类的修复策略

| Warning ID | 推荐的 IP 调试动作 |
|---|---|
| `Vivado 12-1411` | `inspect_ip_params(filter='gt')` 查看 GT LOC，判断架构后选择修复方案 |
| `Vivado 12-1790` | `inspect_ip_params(filter='loc')` 确认 IP 是否有 LOC 相关参数 |
| `Vivado 12-4385` | `inspect_ip_params(filter='clock')` 检查时钟引脚配置 |
| `DRC NSTD-1` | `get_io_report()` 查看哪些端口缺少 IOSTANDARD |
| `DRC UCIO-1` | `get_io_report()` + `verify_io_placement()` 定位未约束的端口 |
