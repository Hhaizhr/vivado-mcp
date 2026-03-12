## PCIe GT Pins
set_property PACKAGE_PIN AA4 [get_ports {pcie_7x_mgt_rtl_0_rxp[0]}]
set_property PACKAGE_PIN AB6 [get_ports {pcie_7x_mgt_rtl_0_rxp[1]}]
set_property PACKAGE_PIN AC4 [get_ports {pcie_7x_mgt_rtl_0_rxp[2]}]
set_property PACKAGE_PIN AD6 [get_ports {pcie_7x_mgt_rtl_0_rxp[3]}]
set_property PACKAGE_PIN AE4 [get_ports {pcie_7x_mgt_rtl_0_rxp[4]}]
set_property PACKAGE_PIN AF6 [get_ports {pcie_7x_mgt_rtl_0_rxp[5]}]
set_property PACKAGE_PIN AG4 [get_ports {pcie_7x_mgt_rtl_0_rxp[6]}]
set_property PACKAGE_PIN AH6 [get_ports {pcie_7x_mgt_rtl_0_rxp[7]}]

set_property PACKAGE_PIN AA3 [get_ports {pcie_7x_mgt_rtl_0_txp[0]}]
set_property PACKAGE_PIN AB5 [get_ports {pcie_7x_mgt_rtl_0_txp[1]}]
set_property PACKAGE_PIN AC3 [get_ports {pcie_7x_mgt_rtl_0_txp[2]}]
set_property PACKAGE_PIN AD5 [get_ports {pcie_7x_mgt_rtl_0_txp[3]}]
set_property PACKAGE_PIN AE3 [get_ports {pcie_7x_mgt_rtl_0_txp[4]}]
set_property PACKAGE_PIN AF5 [get_ports {pcie_7x_mgt_rtl_0_txp[5]}]
set_property PACKAGE_PIN AG3 [get_ports {pcie_7x_mgt_rtl_0_txp[6]}]
set_property PACKAGE_PIN AH5 [get_ports {pcie_7x_mgt_rtl_0_txp[7]}]

## System Clock
set_property PACKAGE_PIN AB8 [get_ports sys_clk_p]
set_property PACKAGE_PIN AC8 [get_ports sys_clk_n]

## Reset
set_property PACKAGE_PIN Y25 [get_ports xdma_rst_n]
set_property IOSTANDARD LVCMOS25 [get_ports xdma_rst_n]
