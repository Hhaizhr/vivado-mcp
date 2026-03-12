# 贡献指南

感谢你对 vivado-mcp 的关注！以下是参与贡献的说明。

## 开发环境搭建

```bash
# 克隆仓库
git clone https://github.com/mapleleavessssssss-wq/vivado-mcp.git
cd vivado-mcp

# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# 或 .venv\Scripts\activate  # Windows

# 安装开发依赖
pip install -e ".[dev]"
```

## 代码风格

- 使用 [ruff](https://docs.astral.sh/ruff/) 进行代码检查和格式化
- 行宽限制 100 字符
- 源码注释和 docstring 使用中文
- 遵循 PEP 8 命名规范

```bash
# 检查
ruff check src/ tests/

# 自动修复
ruff check --fix src/ tests/
```

## 测试

```bash
# 运行所有测试（不需要 Vivado 安装）
pytest

# 运行特定测试
pytest tests/test_tcl_utils.py -v
```

## PR 流程

1. Fork 本仓库
2. 创建功能分支 (`git checkout -b feature/my-feature`)
3. 编写代码和测试
4. 确保 `ruff check` 和 `pytest` 通过
5. 提交 PR，描述你的更改

## 安全相关

如果发现安全漏洞，请通过 Issue 私密报告，不要在公开 Issue 中公布细节。
