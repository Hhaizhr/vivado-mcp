# Vivado MCP 工具速查手册

> 21 个工具 + 5 个 Prompt 的完整参数速查。所有工具均为异步函数，`session_id` 默认 `"default"`。

---

## 一、会话管理（3 个）

### `start_session` — 启动 Vivado 会话

```
start_session(
    session_id="default",   # 会话 ID（字母/数字/下划线/连字符，最长 64 字符）
    vivado_path="",         # Vivado 可执行文件路径（空则自动检测）
    timeout=60,             # 启动超时秒数
)
```

### `stop_session` — 关闭会话

```
stop_session(session_id="default")
```

### `list_sessions` — 列出所有活跃会话

```
list_sessions()
```

返回每个会话的 ID、状态、命令计数等信息。

---

## 二、Tcl 执行（2 个）

### `run_tcl` — 执行任意 Vivado Tcl 命令

```
run_tcl(
    command="...",          # Tcl 命令（支持多行、任意 Vivado API）
    session_id="default",
    timeout=120,            # 超时秒数
)
```

最核心的工具——其他所有工具无法覆盖的操作都可以通过此工具完成。

### `vivado_help` — 查询 Tcl 命令帮助

```
vivado_help(
    tcl_command="",         # 要查询的命令名（空则列出常用命令）
    session_id="",          # 空则不需要活跃会话
)
```

---

## 三、项目管理（4 个）

### `create_project` — 创建新项目

```
create_project(
    name="my_proj",         # 项目名称
    directory="./projects", # 项目目录
    part="",                # FPGA 器件型号（如 "xc7a35tcpg236-1"）
    board_part="",          # 开发板型号（如 "digilentinc.com:basys3:part0:1.1"）
    force=False,            # 覆盖已存在的同名项目
    session_id="default",
)
```

`part` 和 `board_part` 二选一，`board_part` 会自动推断 `part`。

### `open_project` — 打开已有项目

```
open_project(
    xpr_path="./my_proj/my_proj.xpr",  # .xpr 文件路径
    session_id="default",
)
```

### `close_project` — 关闭当前项目

```
close_project(session_id="default")
```

### `add_files` — 添加源文件

```
add_files(
    files="./src/top.v ./src/counter.v",  # 空格分隔的文件路径列表
    fileset="sources_1",                   # 目标 fileset（约束用 "constrs_1"）
    session_id="default",
)
```

---

## 四、设计流程（5 个）

### `run_synthesis` — 运行综合

```
run_synthesis(
    run_name="synth_1",        # 综合 run 名称
    jobs=4,                     # 并行任务数
    timeout_minutes=30,
    session_id="default",
)
```

自动执行 `reset_run → launch_runs → wait_on_run`。完成后自动诊断并报告 CRITICAL WARNING 数量。

### `run_implementation` — 运行实现

```
run_implementation(
    run_name="impl_1",
    jobs=4,
    timeout_minutes=60,
    session_id="default",
)
```

与 `run_synthesis` 相同的自动诊断机制。

### `generate_bitstream` — 生成比特流

```
generate_bitstream(
    impl_run="impl_1",
    jobs=4,
    timeout_minutes=30,
    force=False,               # True 跳过 CRITICAL WARNING 安全检查
    session_id="default",
)
```

`force=False`（默认）时，检测到 CRITICAL WARNING 会**阻止生成**并展示前 10 条样本。

### `get_status` — 查询运行状态

```
get_status(
    run_name="",               # 留空显示所有 run；指定则显示该 run 详情
    session_id="default",
)
```

### `program_device` — 编程 FPGA 设备

```
program_device(
    bitstream_path="./impl_1/top.bit",  # .bit 文件路径
    target="*",                          # 设备过滤器（默认第一个可用）
    hw_server_url="localhost:3121",
    session_id="default",
)
```

---

## 五、报告（3 个）

### `report` — 统一报告接口

```
report(
    report_type="utilization",  # 报告类型（见下表）
    options="",                  # 额外 Vivado 选项（如 "-cells [get_cells ...]"）
    session_id="default",
    timeout=120,
)
```

支持的 `report_type`：

| 类型 | Vivado 命令 |
|------|------------|
| `utilization` | `report_utilization` |
| `timing` | `report_timing_summary` |
| `power` | `report_power` |
| `drc` | `report_drc` |
| `io` | `report_io` |
| `clock` | `report_clocks` |
| `clock_interaction` | `report_clock_interaction` |
| `methodology` | `report_methodology` |
| `congestion` | `report_design_analysis -congestion` |
| `complexity` | `report_design_analysis -complexity` |
| `qor` | `report_qor_assessment` |

### `get_io_report` — 结构化 IO 报告

```
get_io_report(session_id="default")
```

返回 **JSON**，含所有端口的引脚、Bank、Site、方向、IO 标准，自动分类 GT/GPIO。

### `get_timing_report` — 结构化时序报告

```
get_timing_report(session_id="default")
```

返回格式化文本，含 WNS/TNS/WHS/THS + PASS/FAIL 判定 + 最差路径详情。

---

## 六、诊断（2 个）

### `get_critical_warnings` — 提取并分类 CRITICAL WARNING

```
get_critical_warnings(
    run_name="impl_1",         # run 名称（对应 runme.log）
    session_id="default",
)
```

返回按 warning ID 聚合的分类报告，含中文修复建议。已知分类：

| Warning ID | 分类标签 | 说明 |
|---|---|---|
| `Vivado 12-1411` | `GT_PIN_CONFLICT` | GT 端口 PACKAGE_PIN 约束与 IP 内部 LOC 冲突 |
| `Vivado 12-2285` | `GT_LOC_CONFLICT` | Cell 级 LOC 与已占用 BEL 冲突 |
| `Vivado 12-4739` | `TIMING_CONSTRAINT` | 时钟约束问题 |
| `Vivado 12-180` | `CLOCK_NOT_FOUND` | 时钟约束目标不存在 |
| `Vivado 12-1790` | `MISSING_PIN_CONSTRAINT` | 端口缺少 PACKAGE_PIN / LOC 约束 |
| `Vivado 12-4385` | `CLOCK_PLACEMENT` | 时钟输入未放在专用时钟引脚 |
| `Synth 8-3295` | `UNCONNECTED_PORT` | 模块端口未连接 |
| `DRC RTSTAT-1` | `UNROUTED_NET` | 存在未布线网络 |
| `DRC BIVC-1` | `IO_STANDARD_MISMATCH` | Bank 内 IOSTANDARD 不一致 |
| `DRC NSTD-1` | `UNSPECIFIED_IOSTANDARD` | 端口未指定 IOSTANDARD |
| `DRC UCIO-1` | `UNCONSTRAINED_IO` | 端口未约束到物理引脚 |
| `Timing 38-282` | `TIMING_VIOLATION` | 时序违例 |

### `verify_io_placement` — 验证 IO 引脚分配

```
verify_io_placement_tool(session_id="default")
```

自动读取项目 XDC 的 PACKAGE_PIN 约束，与 `report_io` 实际分配对比。GT 端口不匹配标记为 **CRITICAL**。

---

## 七、IP 调试（2 个）

### `inspect_ip_params` — 查询 IP 所有配置参数

```
inspect_ip_params(
    ip_name="xdma_0",         # IP 实例名称
    filter_keyword="",         # 过滤关键词（不区分大小写，匹配名称或值）
    session_id="default",
)
```

通过 Vivado Tcl API `list_property + get_property` 获取所有 CONFIG.* 参数，**含 GUI 中不可见的隐藏参数**。

常用过滤关键词：`gt`、`lane`、`loc`、`pcie`、`clock`、`width`

### `compare_xci` — 对比两个 XCI 文件

```
compare_xci(
    file_a="path/to/golden.xci",   # 基准配置
    file_b="path/to/suspect.xci",  # 待检查配置
    show_all=False,                 # True 显示所有参数（默认仅差异）
)
```

**无需 Vivado 会话**，纯 Python 解析 XML。安全限制：`.xci` 扩展名 + 文件大小 < 10MB。

---

## 八、Prompts — 工作流引导（5 个）

Prompt 不是工具，而是预定义的工作流引导模板，由 AI 助手调用后生成操作步骤。

| Prompt | 说明 | 核心工具 |
|--------|------|---------|
| `fpga_workflow` | 标准 FPGA 开发流程（创建→综合→实现→比特流） | 全流程 |
| `debug_timing` | 时序违例调试（WNS 分析→修复策略） | `get_timing_report`, `report` |
| `debug_gt_mapping` | GT 引脚映射调试（含 7-Series vs UltraScale+ 差异） | `get_critical_warnings`, `verify_io_placement`, `inspect_ip_params` |
| `debug_ip_config` | IP 配置问题诊断（参数查询+XCI对比+xgui搜索） | `inspect_ip_params`, `compare_xci` |
| `debug_pcie` | PCIe 系统化调试（物理→时钟→时序→协议，4 层排查） | 全诊断工具 |

---

## 九、快速场景索引

| 场景 | 使用工具 |
|------|---------|
| PCIe 链路不通 | `debug_pcie` → `get_critical_warnings` → `verify_io_placement` → `inspect_ip_params(filter='gt')` |
| GT 引脚冲突 [12-1411] | `get_critical_warnings` → `inspect_ip_params(filter='gt')` → 删除 XDC GT PACKAGE_PIN |
| 时序违例 | `debug_timing` → `get_timing_report` → `report(type='congestion')` |
| 对比两版 IP 配置 | `compare_xci(file_a, file_b)` |
| 查看 IP 隐藏参数 | `inspect_ip_params(ip_name='xdma_0')` |
| 综合后快速检查 | `get_critical_warnings(run_name='synth_1')` |
| 引脚分配验证 | `verify_io_placement` + `get_io_report` |
| 资源利用率过高 | `report(type='utilization')` + `report(type='congestion')` |
