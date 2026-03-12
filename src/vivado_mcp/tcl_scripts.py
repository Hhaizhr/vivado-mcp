"""诊断用 Tcl 脚本模板。

所有 Tcl 脚本要求：
- Tcl 8.5 兼容（Vivado 2019.1）
- 输出带 VMCP_ 前缀的结构化标记，便于 Python 解析
- 使用 string match 而非高级正则（性能 + 兼容性）
- Python 的 {run_name} / {impl_run} 占位符由 .format() 填充
  （注意：Tcl 花括号在 Python f-string 中需要双写 {{ }}）
"""

# --------------------------------------------------------------------------- #
#  轻量计数：统计 runme.log 中 error / critical_warning / warning 数量
#  用于 _launch_and_wait 后快速诊断（<2s）
# --------------------------------------------------------------------------- #

COUNT_WARNINGS = """\
set __run_dir [get_property DIRECTORY [get_runs {run_name}]]
set __log "$__run_dir/runme.log"
if {{[file exists $__log]}} {{
    set __fp [open $__log r]
    set __err 0
    set __cw 0
    set __w 0
    while {{[gets $__fp __line] >= 0}} {{
        if {{[string match "CRITICAL WARNING:*" $__line]}} {{
            incr __cw
        }} elseif {{[string match "ERROR:*" $__line]}} {{
            incr __err
        }} elseif {{[string match "WARNING:*" $__line]}} {{
            incr __w
        }}
    }}
    close $__fp
    puts "VMCP_DIAG:errors=$__err,critical_warnings=$__cw,warnings=$__w"
}} else {{
    puts "VMCP_DIAG:errors=-1,critical_warnings=-1,warnings=-1"
}}
"""

# --------------------------------------------------------------------------- #
#  提取 CRITICAL WARNING 详情：逐行扫描 runme.log，只输出 CW 行
#  格式：VMCP_CW:行号|原始文本
# --------------------------------------------------------------------------- #

EXTRACT_CRITICAL_WARNINGS = """\
set __run_dir [get_property DIRECTORY [get_runs {run_name}]]
set __log "$__run_dir/runme.log"
if {{[file exists $__log]}} {{
    set __fp [open $__log r]
    set __ln 0
    while {{[gets $__fp __line] >= 0}} {{
        incr __ln
        if {{[string match "CRITICAL WARNING:*" $__line]}} {{
            puts "VMCP_CW:$__ln|$__line"
        }}
    }}
    close $__fp
    puts "VMCP_CW_DONE"
}} else {{
    puts "VMCP_CW_ERROR:runme.log not found at $__log"
}}
"""

# --------------------------------------------------------------------------- #
#  提取 XDC 中的 PACKAGE_PIN 约束
#  自动读取项目 constrs_1 中所有 XDC 文件，过滤 PACKAGE_PIN 行
#  格式：VMCP_XDC_PIN:文件路径|行号|引脚|端口
# --------------------------------------------------------------------------- #

EXTRACT_XDC_PACKAGE_PINS = """\
set __xdc_files [get_files -of_objects [get_filesets constrs_1] -filter {{FILE_TYPE == XDC}}]
foreach __xf $__xdc_files {{
    set __fp [open $__xf r]
    set __ln 0
    while {{[gets $__fp __line] >= 0}} {{
        incr __ln
        set __re {{set_property\\s+PACKAGE_PIN\\s+(\\S+)\\s+\\[get_ports\\s+(.+?)\\]}}
        if {{[regexp -nocase $__re $__line -> __pin __port]}} {{
            set __port [string trim $__port "{{ }}"]
            puts "VMCP_XDC_PIN:$__xf|$__ln|$__pin|$__port"
        }}
    }}
    close $__fp
}}
puts "VMCP_XDC_PIN_DONE"
"""

# --------------------------------------------------------------------------- #
#  Bitstream 前置检查：查询实现状态 + CRITICAL WARNING 计数 + 前 10 条样本
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
#  查询 IP 实例的所有 CONFIG.* 参数
#  格式：VMCP_IP_INFO:vlnv / VMCP_IP_PARAM:name|value / VMCP_IP_PARAM_DONE
# --------------------------------------------------------------------------- #

INSPECT_IP_PARAMS = """\
set __ip [get_ips {ip_name}]
if {{$__ip eq ""}} {{
    puts "VMCP_IP_PARAM_ERROR:IP '{ip_name}' not found"
}} else {{
    set __vlnv [get_property VLNV $__ip]
    puts "VMCP_IP_INFO:$__vlnv"
    set __props [list_property $__ip]
    foreach __p $__props {{
        if {{[string match "CONFIG.*" $__p]}} {{
            set __val [get_property $__p $__ip]
            puts "VMCP_IP_PARAM:$__p|$__val"
        }}
    }}
    puts "VMCP_IP_PARAM_DONE"
}}
"""

CHECK_PRE_BITSTREAM = """\
set __impl [get_runs {impl_run}]
set __status [get_property STATUS $__impl]
set __dir [get_property DIRECTORY $__impl]
set __log "$__dir/runme.log"
set __cw 0
set __samples [list]
if {{[file exists $__log]}} {{
    set __fp [open $__log r]
    while {{[gets $__fp __line] >= 0}} {{
        if {{[string match "CRITICAL WARNING:*" $__line]}} {{
            incr __cw
            if {{$__cw <= 10}} {{
                lappend __samples $__line
            }}
        }}
    }}
    close $__fp
}}
puts "VMCP_PRE_BIT:status=$__status,critical_warnings=$__cw"
foreach __s $__samples {{
    puts "VMCP_PRE_BIT_CW:$__s"
}}
puts "VMCP_PRE_BIT_DONE"
"""
