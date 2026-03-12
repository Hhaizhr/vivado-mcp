"""入口模块：通过 python -m vivado_mcp 启动 MCP 服务器。"""

from vivado_mcp.server import mcp


def main() -> None:
    """启动 MCP 服务器（stdio 传输）。"""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
