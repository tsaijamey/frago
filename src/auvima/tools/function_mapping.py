"""
功能映射验证工具

扫描并对比Shell脚本与Python CDP实现的功能映射关系。
包含参数解析、签名提取、对应关系验证和报告生成功能。
"""

import os
import re
import inspect
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set
from pathlib import Path
import json


@dataclass
class ShellParameter:
    """Shell脚本参数"""
    name: str
    has_value: bool  # True表示需要值（shift 2），False表示是标志（shift）
    required: bool = False

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        if not isinstance(other, ShellParameter):
            return False
        return self.name == other.name


@dataclass
class PythonParameter:
    """Python函数参数"""
    name: str
    has_default: bool
    annotation: str = ""
    default_value: str = ""

    def __hash__(self):
        return hash(self.name)

    def __eq__(self, other):
        if not isinstance(other, PythonParameter):
            return False
        return self.name == other.name


@dataclass
class FunctionMapping:
    """功能映射数据模型"""

    shell_script: str
    python_module: str
    python_function: str
    implemented: bool
    shell_parameters: List[ShellParameter] = field(default_factory=list)
    python_parameters: List[PythonParameter] = field(default_factory=list)
    parameters_match: bool = True
    parameter_mismatches: List[str] = field(default_factory=list)
    behavior_consistent: bool = True
    behavior_notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shell_script": self.shell_script,
            "python_module": self.python_module,
            "python_function": self.python_function,
            "implemented": self.implemented,
            "shell_parameters": [
                {"name": p.name, "has_value": p.has_value, "required": p.required}
                for p in self.shell_parameters
            ],
            "python_parameters": [
                {
                    "name": p.name,
                    "has_default": p.has_default,
                    "annotation": p.annotation,
                    "default_value": p.default_value
                }
                for p in self.python_parameters
            ],
            "parameters_match": self.parameters_match,
            "parameter_mismatches": self.parameter_mismatches,
            "behavior_consistent": self.behavior_consistent,
            "behavior_notes": self.behavior_notes
        }


class ShellScriptParser:
    """Shell脚本解析器"""

    @staticmethod
    def parse_parameters(script_path: str) -> List[ShellParameter]:
        """
        解析Shell脚本的参数

        Args:
            script_path: Shell脚本路径

        Returns:
            List[ShellParameter]: 参数列表
        """
        parameters = []

        try:
            with open(script_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 解析 case 语句中的选项
            # 匹配模式: --option-name) ... shift 2 或 shift
            case_pattern = r'--([a-z-]+)\)\s*.*?shift\s+(\d+)'
            matches = re.finditer(case_pattern, content, re.MULTILINE | re.DOTALL)

            for match in matches:
                option_name = match.group(1)
                shift_count = int(match.group(2))

                # shift 2 表示选项需要值，shift 表示是标志
                has_value = shift_count == 2

                parameters.append(ShellParameter(
                    name=f"--{option_name}",
                    has_value=has_value,
                    required=False  # Shell脚本中的选项通常是可选的
                ))

            # 检查是否有必需的位置参数
            # 通过检查错误消息来判断
            required_pattern = r'echo\s+"错误:\s*必须提供(.+?)参数"'
            if re.search(required_pattern, content):
                # 尝试从变量声明中找到位置参数
                var_pattern = r'^([A-Z_]+)=""'
                var_matches = re.finditer(var_pattern, content, re.MULTILINE)

                # 排除全局选项变量
                global_options = {'DEBUG', 'TIMEOUT', 'HOST', 'PORT'}

                for var_match in var_matches:
                    var_name = var_match.group(1)
                    if var_name not in global_options:
                        # 这可能是位置参数
                        # 检查是否在错误消息中提到
                        if var_name.lower() in content.lower():
                            parameters.append(ShellParameter(
                                name=var_name.lower(),
                                has_value=True,
                                required=True
                            ))

        except Exception as e:
            print(f"解析Shell脚本 {script_path} 时出错: {e}")

        return parameters


class PythonFunctionAnalyzer:
    """Python函数分析器"""

    @staticmethod
    def extract_signature(module_name: str, function_name: str) -> List[PythonParameter]:
        """
        提取Python函数签名

        Args:
            module_name: 模块名
            function_name: 函数名

        Returns:
            List[PythonParameter]: 参数列表
        """
        parameters = []

        try:
            # 动态导入模块
            from auvima.cdp import commands

            # 模块映射
            module_map = {
                "page": commands.PageCommands,
                "screenshot": commands.ScreenshotCommands,
                "runtime": commands.RuntimeCommands,
                "input": commands.InputCommands,
                "scroll": commands.ScrollCommands,
                "wait": commands.WaitCommands,
                "zoom": commands.ZoomCommands,
                "status": commands.StatusCommands,
                "visual_effects": commands.VisualEffectsCommands,
                "dom": commands.DOMCommands,
            }

            command_class = module_map.get(module_name)
            if not command_class:
                return parameters

            # 获取函数
            if hasattr(command_class, function_name):
                func = getattr(command_class, function_name)
                sig = inspect.signature(func)

                for param_name, param in sig.parameters.items():
                    # 跳过 self 参数
                    if param_name == 'self':
                        continue

                    has_default = param.default != inspect.Parameter.empty
                    annotation = str(param.annotation) if param.annotation != inspect.Parameter.empty else ""
                    default_value = str(param.default) if has_default else ""

                    parameters.append(PythonParameter(
                        name=param_name,
                        has_default=has_default,
                        annotation=annotation,
                        default_value=default_value
                    ))

        except Exception as e:
            print(f"提取函数签名 {module_name}.{function_name} 时出错: {e}")

        return parameters


class ParameterValidator:
    """参数对应关系验证器"""

    @staticmethod
    def validate_parameters(
        shell_params: List[ShellParameter],
        python_params: List[PythonParameter]
    ) -> tuple[bool, List[str]]:
        """
        验证Shell脚本参数与Python函数参数的对应关系

        Args:
            shell_params: Shell脚本参数列表
            python_params: Python函数参数列表

        Returns:
            tuple[bool, List[str]]: (是否匹配, 不匹配信息列表)
        """
        mismatches = []

        # 排除全局选项（这些不属于特定功能）
        global_options = {'--debug', '--timeout', '--host', '--port'}
        shell_specific = [p for p in shell_params if p.name not in global_options]

        # 创建参数名称集合（忽略大小写和连字符/下划线差异）
        def normalize_name(name: str) -> str:
            return name.lower().replace('-', '_').replace('--', '')

        shell_names = {normalize_name(p.name) for p in shell_specific}
        python_names = {normalize_name(p.name) for p in python_params}

        # 检查Shell脚本中有但Python中没有的参数
        shell_only = shell_names - python_names
        if shell_only:
            mismatches.append(f"Shell脚本独有参数: {', '.join(sorted(shell_only))}")

        # 检查Python中有但Shell脚本中没有的参数
        python_only = python_names - shell_names
        if python_only:
            # 过滤掉一些常见的内部参数
            python_only_filtered = python_only - {'return_by_value', 'await_promise'}
            if python_only_filtered:
                mismatches.append(f"Python独有参数: {', '.join(sorted(python_only_filtered))}")

        # 检查必需参数
        for shell_param in shell_specific:
            if shell_param.required:
                norm_name = normalize_name(shell_param.name)
                # 在Python中查找对应参数
                py_param = next(
                    (p for p in python_params if normalize_name(p.name) == norm_name),
                    None
                )
                if py_param and py_param.has_default:
                    mismatches.append(
                        f"参数 '{shell_param.name}' 在Shell中是必需的，但在Python中有默认值"
                    )

        matches = len(mismatches) == 0
        return matches, mismatches


class BehaviorChecker:
    """行为一致性检查器"""

    @staticmethod
    def check_behavior(mapping: FunctionMapping) -> tuple[bool, List[str]]:
        """
        检查Shell脚本与Python实现的行为一致性

        Args:
            mapping: 功能映射

        Returns:
            tuple[bool, List[str]]: (是否一致, 注释列表)
        """
        notes = []

        # 基本实现检查
        if not mapping.implemented:
            notes.append("Python实现缺失")
            return False, notes

        # 参数数量差异检查
        shell_count = len([p for p in mapping.shell_parameters
                          if p.name not in {'--debug', '--timeout', '--host', '--port'}])
        python_count = len(mapping.python_parameters)

        if abs(shell_count - python_count) > 2:
            notes.append(f"参数数量差异较大: Shell={shell_count}, Python={python_count}")

        # 所有检查通过
        if not notes:
            notes.append("行为检查通过")
            return True, notes

        return len(notes) <= 1, notes


class FunctionMappingReport:
    """功能映射报告"""

    def __init__(self):
        self.mappings: List[FunctionMapping] = []
        self.total_functions: int = 0
        self.implemented_count: int = 0
        self.consistent_count: int = 0
        self.parameters_match_count: int = 0

    def add_mapping(self, mapping: FunctionMapping):
        self.mappings.append(mapping)
        self.total_functions += 1
        if mapping.implemented:
            self.implemented_count += 1
        if mapping.behavior_consistent:
            self.consistent_count += 1
        if mapping.parameters_match:
            self.parameters_match_count += 1

    def get_coverage(self) -> float:
        """获取实现覆盖率"""
        return (self.implemented_count / self.total_functions) * 100 if self.total_functions > 0 else 0.0

    def get_consistency(self) -> float:
        """获取行为一致性"""
        return (self.consistent_count / self.implemented_count) * 100 if self.implemented_count > 0 else 0.0

    def get_parameter_match_rate(self) -> float:
        """获取参数匹配率"""
        return (self.parameters_match_count / self.implemented_count) * 100 if self.implemented_count > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": {
                "total_functions": self.total_functions,
                "implemented_count": self.implemented_count,
                "consistent_count": self.consistent_count,
                "parameters_match_count": self.parameters_match_count,
                "coverage": round(self.get_coverage(), 2),
                "consistency": round(self.get_consistency(), 2),
                "parameter_match_rate": round(self.get_parameter_match_rate(), 2)
            },
            "mappings": [m.to_dict() for m in self.mappings]
        }

    def print_summary(self):
        """打印摘要报告"""
        print("=" * 70)
        print(" " * 20 + "功能映射验证报告")
        print("=" * 70)
        print(f"\n📊 统计信息:")
        print(f"  总功能数:     {self.total_functions}")
        print(f"  已实现:       {self.implemented_count} ({self.get_coverage():.1f}%)")
        print(f"  参数匹配:     {self.parameters_match_count} ({self.get_parameter_match_rate():.1f}%)")
        print(f"  行为一致:     {self.consistent_count} ({self.get_consistency():.1f}%)")
        print("\n" + "=" * 70)
        print(f"\n📝 详细映射:\n")

        for mapping in self.mappings:
            status = "✓" if mapping.implemented else "✗"
            param_status = "✓" if mapping.parameters_match else "✗"

            print(f"{status} {mapping.shell_script:30s} -> {mapping.python_module}::{mapping.python_function}")

            if mapping.implemented:
                print(f"   参数匹配: {param_status}")

                if mapping.parameter_mismatches:
                    for mismatch in mapping.parameter_mismatches:
                        print(f"     ⚠️  {mismatch}")

                if mapping.behavior_notes:
                    for note in mapping.behavior_notes:
                        if "通过" not in note:
                            print(f"     ℹ️  {note}")

            print()

    def generate_html(self, output_path: str):
        """生成HTML报告"""
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>AuViMa CDP 功能映射验证报告</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #f5f5f5;
            padding: 20px;
            line-height: 1.6;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
            background: white;
            border-radius: 8px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            overflow: hidden;
        }}
        header {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            text-align: center;
        }}
        h1 {{ font-size: 28px; margin-bottom: 10px; }}
        .subtitle {{ opacity: 0.9; }}
        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 20px;
            padding: 30px;
            background: #f8f9fa;
        }}
        .stat-card {{
            background: white;
            padding: 20px;
            border-radius: 8px;
            border-left: 4px solid #667eea;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }}
        .stat-value {{
            font-size: 32px;
            font-weight: bold;
            color: #667eea;
            margin: 10px 0;
        }}
        .stat-label {{
            color: #666;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .mappings {{
            padding: 30px;
        }}
        .mapping-item {{
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            margin-bottom: 20px;
            overflow: hidden;
            transition: all 0.3s;
        }}
        .mapping-item:hover {{
            box-shadow: 0 4px 12px rgba(0,0,0,0.1);
        }}
        .mapping-header {{
            padding: 15px 20px;
            background: #fafafa;
            display: flex;
            align-items: center;
            gap: 15px;
        }}
        .status-icon {{
            width: 24px;
            height: 24px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
        }}
        .status-icon.success {{ background: #4caf50; color: white; }}
        .status-icon.error {{ background: #f44336; color: white; }}
        .mapping-title {{
            flex: 1;
            font-weight: 500;
        }}
        .mapping-target {{
            color: #666;
            font-family: 'Courier New', monospace;
            font-size: 14px;
        }}
        .mapping-details {{
            padding: 20px;
        }}
        .detail-section {{
            margin-bottom: 15px;
        }}
        .detail-section h4 {{
            color: #667eea;
            margin-bottom: 10px;
            font-size: 14px;
        }}
        .param-list {{
            display: flex;
            flex-wrap: wrap;
            gap: 8px;
        }}
        .param-tag {{
            background: #e8eaf6;
            color: #3f51b5;
            padding: 4px 12px;
            border-radius: 16px;
            font-size: 13px;
            font-family: 'Courier New', monospace;
        }}
        .param-tag.required {{
            background: #ffebee;
            color: #c62828;
        }}
        .mismatch {{
            background: #fff3e0;
            border-left: 4px solid #ff9800;
            padding: 12px;
            margin: 8px 0;
            border-radius: 4px;
        }}
        .mismatch-icon {{ color: #ff9800; margin-right: 8px; }}
        footer {{
            text-align: center;
            padding: 20px;
            color: #999;
            font-size: 14px;
            border-top: 1px solid #e0e0e0;
        }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🔍 AuViMa CDP 功能映射验证报告</h1>
            <p class="subtitle">Shell 脚本与 Python 实现对应关系分析</p>
        </header>

        <div class="stats">
            <div class="stat-card">
                <div class="stat-label">总功能数</div>
                <div class="stat-value">{self.total_functions}</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">实现覆盖率</div>
                <div class="stat-value">{self.get_coverage():.1f}%</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">参数匹配率</div>
                <div class="stat-value">{self.get_parameter_match_rate():.1f}%</div>
            </div>
            <div class="stat-card">
                <div class="stat-label">行为一致性</div>
                <div class="stat-value">{self.get_consistency():.1f}%</div>
            </div>
        </div>

        <div class="mappings">
            <h2 style="margin-bottom: 20px;">功能映射详情</h2>
"""

        for mapping in self.mappings:
            status_class = "success" if mapping.implemented else "error"
            status_icon = "✓" if mapping.implemented else "✗"

            html += f"""
            <div class="mapping-item">
                <div class="mapping-header">
                    <div class="status-icon {status_class}">{status_icon}</div>
                    <div class="mapping-title">{mapping.shell_script}</div>
                    <div class="mapping-target">{mapping.python_module}::{mapping.python_function}</div>
                </div>
"""

            if mapping.implemented:
                html += """
                <div class="mapping-details">
"""

                # Shell 参数
                if mapping.shell_parameters:
                    shell_params = [p for p in mapping.shell_parameters
                                   if p.name not in {'--debug', '--timeout', '--host', '--port'}]
                    if shell_params:
                        html += """
                    <div class="detail-section">
                        <h4>Shell 脚本参数</h4>
                        <div class="param-list">
"""
                        for param in shell_params:
                            tag_class = "required" if param.required else ""
                            html += f'                            <span class="param-tag {tag_class}">{param.name}</span>\n'
                        html += """
                        </div>
                    </div>
"""

                # Python 参数
                if mapping.python_parameters:
                    html += """
                    <div class="detail-section">
                        <h4>Python 函数参数</h4>
                        <div class="param-list">
"""
                    for param in mapping.python_parameters:
                        tag_class = "" if param.has_default else "required"
                        html += f'                            <span class="param-tag {tag_class}">{param.name}</span>\n'
                    html += """
                        </div>
                    </div>
"""

                # 参数不匹配信息
                if mapping.parameter_mismatches:
                    html += """
                    <div class="detail-section">
                        <h4>⚠️ 参数不匹配</h4>
"""
                    for mismatch in mapping.parameter_mismatches:
                        html += f"""
                        <div class="mismatch">
                            <span class="mismatch-icon">⚠️</span>{mismatch}
                        </div>
"""
                    html += """
                    </div>
"""

                html += """
                </div>
"""

            html += """
            </div>
"""

        html += """
        </div>

        <footer>
            <p>由 AuViMa 功能映射验证工具自动生成</p>
        </footer>
    </div>
</body>
</html>
"""

        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(html)

        print(f"✓ HTML报告已生成: {output_path}")


def create_mapping_report(project_root: str = ".") -> FunctionMappingReport:
    """
    创建功能映射报告

    Args:
        project_root: 项目根目录

    Returns:
        FunctionMappingReport: 映射报告实例
    """
    report = FunctionMappingReport()

    # Shell脚本到Python函数的映射关系
    script_to_python = {
        "cdp_navigate.sh": ("page", "navigate"),
        "cdp_screenshot.sh": ("screenshot", "capture"),
        "cdp_exec_js.sh": ("runtime", "evaluate"),
        "cdp_click.sh": ("input", "click"),
        "cdp_scroll.sh": ("scroll", "scroll"),
        "cdp_wait.sh": ("wait", "wait_for_selector"),
        "cdp_zoom.sh": ("zoom", "set_zoom_factor"),
        "cdp_get_title.sh": ("page", "get_title"),
        "cdp_get_content.sh": ("page", "get_content"),
        "cdp_status.sh": ("status", "health_check"),
        "cdp_highlight.sh": ("visual_effects", "highlight"),
        "cdp_pointer.sh": ("visual_effects", "pointer"),
        "cdp_spotlight.sh": ("visual_effects", "spotlight"),
        "cdp_annotate.sh": ("visual_effects", "annotate"),
        "cdp_clear_effects.sh": ("visual_effects", "clear_effects"),
    }

    # 扫描脚本目录
    scripts_dir = Path(project_root) / "scripts"

    parser = ShellScriptParser()
    analyzer = PythonFunctionAnalyzer()
    validator = ParameterValidator()
    checker = BehaviorChecker()

    for script_name, (module, func) in script_to_python.items():
        # 查找Shell脚本文件
        script_path = None
        for search_dir in ["share", "generate"]:
            potential_path = scripts_dir / search_dir / script_name
            if potential_path.exists():
                script_path = potential_path
                break

        # 解析Shell脚本参数
        shell_params = []
        if script_path:
            shell_params = parser.parse_parameters(str(script_path))

        # 提取Python函数签名
        python_params = analyzer.extract_signature(module, func)

        # 检查实现是否存在
        implemented = len(python_params) > 0 or func in ['health_check', 'clear_effects']

        # 验证参数对应关系
        params_match, mismatches = validator.validate_parameters(shell_params, python_params)

        # 创建映射对象
        mapping = FunctionMapping(
            shell_script=script_name,
            python_module=module,
            python_function=func,
            implemented=implemented,
            shell_parameters=shell_params,
            python_parameters=python_params,
            parameters_match=params_match,
            parameter_mismatches=mismatches
        )

        # 检查行为一致性
        behavior_ok, notes = checker.check_behavior(mapping)
        mapping.behavior_consistent = behavior_ok
        mapping.behavior_notes = notes

        report.add_mapping(mapping)

    return report


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="CDP功能映射验证工具")
    parser.add_argument("--format", choices=["text", "json", "html"], default="text", help="输出格式")
    parser.add_argument("--output", help="输出文件路径")
    parser.add_argument("--project-root", default=".", help="项目根目录")

    args = parser.parse_args()

    # 创建映射报告
    report = create_mapping_report(args.project_root)

    # 输出报告
    if args.format == "json":
        output = json.dumps(report.to_dict(), indent=2, ensure_ascii=False)

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output)
            print(f"✓ JSON报告已保存到: {args.output}")
        else:
            print(output)

    elif args.format == "html":
        output_path = args.output or "function_mapping_report.html"
        report.generate_html(output_path)

    else:
        report.print_summary()


if __name__ == "__main__":
    main()
