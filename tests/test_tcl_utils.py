"""tcl_utils.py 单元测试。

重点覆盖：
- wrap_command 十六进制编码防注入
- validate_identifier 白名单验证
- tcl_quote 特殊字符转义
- to_tcl_path 路径转换
- clean_output ANSI 清洗
- TclResult.summary 截断逻辑
"""

import pytest

from vivado_mcp.vivado.tcl_utils import (
    MAX_OUTPUT_CHARS,
    TclResult,
    clean_output,
    generate_sentinel,
    make_sentinel_pattern,
    tcl_quote,
    to_tcl_path,
    validate_identifier,
    wrap_command,
)

# ====================================================================== #
#  wrap_command：十六进制编码防注入
# ====================================================================== #

class TestWrapCommand:
    """wrap_command 安全性测试。"""

    def test_basic_command(self):
        """基本命令能正确编码和包装。"""
        result = wrap_command("puts hello", "VMCP_test123")
        # 验证包含十六进制编码
        hex_encoded = "puts hello".encode("utf-8").hex()
        assert hex_encoded in result
        # 验证不直接包含原始命令
        assert 'catch {puts hello}' not in result
        # 验证包含 sentinel
        assert "VMCP_test123" in result
        # 验证包含 binary format H*
        assert "binary format H*" in result

    def test_unbalanced_braces_safe(self):
        """不平衡花括号不会突破 catch 块——这是修复前的致命注入漏洞。"""
        malicious = '} ; exec rm -rf / ; {'
        result = wrap_command(malicious, "VMCP_sentinel")
        # 编码后的命令中不应包含裸花括号
        hex_encoded = malicious.encode("utf-8").hex()
        assert hex_encoded in result
        # 原始的恶意字符串不应直接出现在 catch {} 内
        assert 'catch {' + malicious not in result

    def test_dollar_sign_safe(self):
        """美元符号不会被 Tcl 变量替换。"""
        cmd = 'puts "$env(HOME)"'
        result = wrap_command(cmd, "VMCP_test")
        # 十六进制中不可能包含 $
        hex_part = cmd.encode("utf-8").hex()
        assert hex_part in result
        assert "$env" not in result.split("binary format")[0]

    def test_bracket_safe(self):
        """方括号不会被 Tcl 命令替换。"""
        cmd = 'puts [exec whoami]'
        result = wrap_command(cmd, "VMCP_test")
        hex_part = cmd.encode("utf-8").hex()
        assert hex_part in result

    def test_multiline_command(self):
        """多行命令正确编码。"""
        cmd = "set a 1\nset b 2\nputs $a"
        result = wrap_command(cmd, "VMCP_multi")
        hex_part = cmd.encode("utf-8").hex()
        assert hex_part in result

    def test_unicode_command(self):
        """中文等 Unicode 字符正确编码。"""
        cmd = 'puts "你好世界"'
        result = wrap_command(cmd, "VMCP_unicode")
        hex_part = cmd.encode("utf-8").hex()
        assert hex_part in result

    def test_sentinel_in_output(self):
        """哨兵标记出现在正确位置。"""
        result = wrap_command("version", "VMCP_abc123")
        assert '<<<VMCP_abc123_RC=$__rc>>>' in result
        assert 'flush stdout' in result

    def test_uplevel_global_scope(self):
        """命令在全局作用域执行（uplevel #0）。"""
        result = wrap_command("set x 1", "VMCP_scope")
        assert "uplevel #0" in result


# ====================================================================== #
#  validate_identifier：白名单验证
# ====================================================================== #

class TestValidateIdentifier:
    """validate_identifier 标识符验证测试。"""

    def test_valid_identifiers(self):
        """合法标识符通过验证。"""
        valid_ids = [
            "synth_1", "impl_1", "sources_1", "constrs_1",
            "xc7a35tcpg236-1", "my_run.2",
            "digilentinc.com:basys3:part0:1.1",
        ]
        for vid in valid_ids:
            assert validate_identifier(vid, "test") == vid

    def test_rejects_injection_semicolon(self):
        """拒绝含分号的注入尝试。"""
        with pytest.raises(ValueError, match="非法字符"):
            validate_identifier("synth_1; exec rm -rf /", "run_name")

    def test_rejects_injection_brackets(self):
        """拒绝含方括号的注入尝试。"""
        with pytest.raises(ValueError, match="非法字符"):
            validate_identifier("synth_1[exec]", "run_name")

    def test_rejects_spaces(self):
        """拒绝含空格的值。"""
        with pytest.raises(ValueError, match="非法字符"):
            validate_identifier("synth 1", "run_name")

    def test_rejects_dollar(self):
        """拒绝含美元符号的值。"""
        with pytest.raises(ValueError, match="非法字符"):
            validate_identifier("$HOME", "path")

    def test_rejects_empty(self):
        """拒绝空字符串。"""
        with pytest.raises(ValueError, match="非法字符"):
            validate_identifier("", "name")

    def test_rejects_braces(self):
        """拒绝含花括号的值。"""
        with pytest.raises(ValueError, match="非法字符"):
            validate_identifier("{bad}", "name")


# ====================================================================== #
#  tcl_quote：特殊字符转义
# ====================================================================== #

class TestTclQuote:
    """tcl_quote 字符串引用测试。"""

    def test_simple_string(self):
        """简单字符串正确双引号包裹。"""
        assert tcl_quote("hello") == '"hello"'

    def test_dollar_sign(self):
        """$ 被反斜杠转义。"""
        assert tcl_quote("$HOME") == '"\\$HOME"'

    def test_brackets(self):
        """方括号被转义。"""
        result = tcl_quote("[exec whoami]")
        assert result == '"\\[exec whoami\\]"'

    def test_braces(self):
        """花括号被转义。"""
        result = tcl_quote("{bad}")
        assert result == '"\\{bad\\}"'

    def test_double_quote(self):
        """双引号被转义。"""
        result = tcl_quote('say "hi"')
        assert result == '"say \\"hi\\""'

    def test_backslash(self):
        """反斜杠被转义（且不影响后续转义）。"""
        result = tcl_quote("C:\\path\\$dir")
        assert result == '"C:\\\\path\\\\\\$dir"'

    def test_combined_special_chars(self):
        """多种特殊字符组合正确处理。"""
        result = tcl_quote("$[{test}]")
        assert "\\$" in result
        assert "\\[" in result
        assert "\\{" in result
        assert "\\}" in result
        assert "\\]" in result


# ====================================================================== #
#  to_tcl_path：路径转换
# ====================================================================== #

class TestToTclPath:
    """to_tcl_path 路径转换测试。"""

    def test_backslash_to_forward(self):
        """反斜杠转换为正斜杠。"""
        result = to_tcl_path("C:\\Users\\test\\project")
        assert "\\" not in result or result.startswith('"')
        assert "C:/Users/test/project" in result

    def test_path_with_spaces(self):
        """含空格路径被安全引用。"""
        result = to_tcl_path("C:\\My Projects\\test")
        assert "C:/My Projects/test" in result
        # 应该用双引号包裹
        assert result.startswith('"') and result.endswith('"')

    def test_path_with_dollar(self):
        """路径含 $ 不会触发 Tcl 变量替换。"""
        result = to_tcl_path("C:\\$HOME\\project")
        assert "\\$" in result

    def test_path_with_brackets(self):
        """路径含 [] 不会触发 Tcl 命令替换。"""
        result = to_tcl_path("C:\\test[1]\\file")
        assert "\\[" in result
        assert "\\]" in result

    def test_forward_slash_passthrough(self):
        """已经是正斜杠的路径直接处理。"""
        result = to_tcl_path("/opt/Xilinx/Vivado/2019.1")
        assert "/opt/Xilinx/Vivado/2019.1" in result


# ====================================================================== #
#  clean_output：输出清洗
# ====================================================================== #

class TestCleanOutput:
    """clean_output 输出清洗测试。"""

    def test_strips_ansi(self):
        """清除 ANSI 转义序列。"""
        raw = "\x1b[32mOK\x1b[0m done"
        assert clean_output(raw) == "OK done"

    def test_strips_vivado_prompt(self):
        """清除 Vivado% 提示符。"""
        raw = "Vivado% some output\nVivado some more"
        result = clean_output(raw)
        assert "Vivado%" not in result
        assert "some output" in result

    def test_collapses_blank_lines(self):
        """连续 3+ 空行合并为 2 行。"""
        raw = "line1\n\n\n\n\nline2"
        result = clean_output(raw)
        assert "\n\n\n" not in result
        assert "line1\n\nline2" == result

    def test_strips_whitespace(self):
        """去除首尾空白。"""
        raw = "  \n  output  \n  "
        assert clean_output(raw) == "output"


# ====================================================================== #
#  TclResult.summary：摘要与截断
# ====================================================================== #

class TestTclResult:
    """TclResult 摘要生成测试。"""

    def test_ok_result(self):
        """正常结果返回输出内容。"""
        r = TclResult(output="hello world", return_code=0, is_error=False)
        assert r.summary == "hello world"

    def test_empty_ok_result(self):
        """无输出的成功结果返回提示信息。"""
        r = TclResult(output="  ", return_code=0, is_error=False)
        assert "[OK]" in r.summary

    def test_error_result(self):
        """错误结果包含 [ERROR] 前缀。"""
        r = TclResult(output="not found", return_code=1, is_error=True)
        assert r.summary.startswith("[ERROR]")
        assert "not found" in r.summary

    def test_truncation(self):
        """超长输出被截断。"""
        long_output = "x" * (MAX_OUTPUT_CHARS + 1000)
        r = TclResult(output=long_output, return_code=0, is_error=False)
        summary = r.summary
        assert len(summary) < len(long_output)
        assert "截断" in summary
        assert "-file" in summary


# ====================================================================== #
#  generate_sentinel & make_sentinel_pattern
# ====================================================================== #

class TestSentinel:
    """哨兵标记生成与匹配测试。"""

    def test_generate_unique(self):
        """每次生成不同的哨兵。"""
        s1 = generate_sentinel()
        s2 = generate_sentinel()
        assert s1 != s2
        assert s1.startswith("VMCP_")

    def test_pattern_matches(self):
        """哨兵模式正确匹配输出行。"""
        sentinel = "VMCP_abc123def45"
        pattern = make_sentinel_pattern(sentinel)
        m = pattern.search(f"<<<{sentinel}_RC=0>>>")
        assert m is not None
        assert m.group(1) == "0"

    def test_pattern_matches_error(self):
        """哨兵模式匹配非零返回码。"""
        sentinel = "VMCP_test"
        pattern = make_sentinel_pattern(sentinel)
        m = pattern.search(f"<<<{sentinel}_RC=1>>>")
        assert m is not None
        assert m.group(1) == "1"
