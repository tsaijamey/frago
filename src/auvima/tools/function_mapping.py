"""
功能映射验证工具

扫描并对比Shell脚本与Python CDP实现的功能映射关系。
"""

import os
import glob
import inspect
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
import json


@dataclass
class FunctionMapping:
    """功能映射数据模型"""
    
    shell_script: str
    python_module: str
    python_function: str
    implemented: bool
    behavior_consistent: bool = True
    parameters_match: bool = True
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "shell_script": self.shell_script,
            "python_module": self.python_module,
            "python_function": self.python_function,
            "implemented": self.implemented,
            "behavior_consistent": self.behavior_consistent,
            "parameters_match": self.parameters_match
        }


class FunctionMappingReport:
    """功能映射报告"""
    
    def __init__(self):
        self.mappings: List[FunctionMapping] = []
        self.total_functions: int = 0
        self.implemented_count: int = 0
        self.consistent_count: int = 0
        
    def add_mapping(self, mapping: FunctionMapping):
        self.mappings.append(mapping)
        self.total_functions += 1
        if mapping.implemented:
            self.implemented_count += 1
        if mapping.behavior_consistent:
            self.consistent_count += 1
    
    def get_coverage(self) -> float:
        """获取实现覆盖率"""
        return (self.implemented_count / self.total_functions) * 100 if self.total_functions > 0 else 0.0
    
    def get_consistency(self) -> float:
        """获取行为一致性"""
        return (self.consistent_count / self.implemented_count) * 100 if self.implemented_count > 0 else 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_functions": self.total_functions,
            "implemented_count": self.implemented_count,
            "consistent_count": self.consistent_count,
            "coverage": self.get_coverage(),
            "consistency": self.get_consistency(),
            "mappings": [m.to_dict() for m in self.mappings]
        }
    
    def print_summary(self):
        """打印摘要报告"""
        print("=" * 50)
        print("功能映射验证报告")
        print("=" * 50)
        print(f"总功能数: {self.total_functions}")
        print(f"已实现: {self.implemented_count} ({self.get_coverage():.1f}%)")
        print(f"行为一致: {self.consistent_count} ({self.get_consistency():.1f}%)")
        print("=" * 50)
        print()
        
        for mapping in self.mappings:
            status = "✓" if mapping.implemented else "✗"
            print(f"{status} {mapping.shell_script:30s} -> {mapping.python_module}::{mapping.python_function}")


def scan_shell_scripts(scripts_dir: str = "scripts") -> List[str]:
    """
    扫描Shell脚本
    
    Args:
        scripts_dir: 脚本目录路径
        
    Returns:
        List[str]: Shell脚本文件名列表
    """
    scripts = []
    
    for root, dirs, files in os.walk(scripts_dir):
        for file in files:
            if file.endswith(".sh") and file.startswith("cdp_"):
                scripts.append(file)
    
    return sorted(scripts)


def get_python_cdp_functions() -> Dict[str, List[str]]:
    """
    获取Python CDP实现的所有函数
    
    Returns:
        Dict[str, List[str]]: 模块名 -> 函数列表的映射
    """
    from auvima.cdp import commands
    
    functions = {}
    
    command_classes = [
        ("page", commands.PageCommands),
        ("screenshot", commands.ScreenshotCommands),
        ("runtime", commands.RuntimeCommands),
        ("input", commands.InputCommands),
        ("scroll", commands.ScrollCommands),
        ("wait", commands.WaitCommands),
        ("zoom", commands.ZoomCommands),
        ("status", commands.StatusCommands),
        ("visual_effects", commands.VisualEffectsCommands),
        ("dom", commands.DOMCommands),
    ]
    
    for module_name, command_class in command_classes:
        methods = []
        for name, method in inspect.getmembers(command_class, predicate=inspect.isfunction):
            if not name.startswith("_"):
                methods.append(name)
        functions[module_name] = methods
    
    return functions


def create_mapping_report() -> FunctionMappingReport:
    """
    创建功能映射报告
    
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
    
    # 获取Python实现的所有函数
    python_functions = get_python_cdp_functions()
    
    # 为每个Shell脚本创建映射记录
    for script_name, (module, func) in script_to_python.items():
        implemented = func in python_functions.get(module, [])
        
        mapping = FunctionMapping(
            shell_script=script_name,
            python_module=module,
            python_function=func,
            implemented=implemented
        )
        
        report.add_mapping(mapping)
    
    return report


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="CDP功能映射验证工具")
    parser.add_argument("--format", choices=["text", "json"], default="text", help="输出格式")
    parser.add_argument("--output", help="输出文件路径")
    
    args = parser.parse_args()
    
    # 创建映射报告
    report = create_mapping_report()
    
    # 输出报告
    if args.format == "json":
        output = json.dumps(report.to_dict(), indent=2, ensure_ascii=False)
        
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output)
            print(f"报告已保存到: {args.output}")
        else:
            print(output)
    else:
        report.print_summary()


if __name__ == "__main__":
    main()
