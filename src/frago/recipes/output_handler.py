"""Recipe 输出处理器"""
import json
from pathlib import Path
from typing import Any


class OutputHandler:
    """统一处理 Recipe 输出到不同目标的静态类"""
    
    @staticmethod
    def handle(data: dict[str, Any], target: str, options: dict[str, Any] | None = None) -> None:
        """
        处理 Recipe 输出
        
        Args:
            data: Recipe 返回的 JSON 数据
            target: 输出目标 ('stdout' | 'file' | 'clipboard')
            options: 目标特定选项（如 file 需要 'path'）
        
        Raises:
            ValueError: 无效的目标类型或缺少必需选项
            RuntimeError: 输出处理失败
        """
        options = options or {}
        
        if target == 'stdout':
            OutputHandler._to_stdout(data)
        elif target == 'file':
            OutputHandler._to_file(data, options)
        elif target == 'clipboard':
            OutputHandler._to_clipboard(data)
        else:
            raise ValueError(f"无效的输出目标: '{target}'，有效值: stdout, file, clipboard")
    
    @staticmethod
    def _to_stdout(data: dict[str, Any]) -> None:
        """输出到标准输出"""
        json_str = json.dumps(data, ensure_ascii=False, indent=2)
        print(json_str)
    
    @staticmethod
    def _to_file(data: dict[str, Any], options: dict[str, Any]) -> None:
        """输出到文件"""
        if 'path' not in options:
            raise ValueError("file 输出目标需要 'path' 选项")
        
        file_path = Path(options['path'])
        
        # 创建父目录（如需要）
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 写入文件
        json_str = json.dumps(data, ensure_ascii=False, indent=2)
        try:
            file_path.write_text(json_str, encoding='utf-8')
        except Exception as e:
            raise RuntimeError(f"写入文件失败: {file_path} - {e}")
    
    @staticmethod
    def _to_clipboard(data: dict[str, Any]) -> None:
        """输出到剪贴板"""
        try:
            import pyperclip
        except ImportError:
            raise RuntimeError(
                "clipboard 输出需要安装可选依赖 pyperclip。\n"
                "安装方法:\n"
                "  pip install frago-cli[clipboard]     # 仅剪贴板功能\n"
                "  pip install frago-cli[all]           # 所有可选功能\n"
                "  uv tool install 'frago-cli[clipboard]'  # uv 用户"
            )
        
        json_str = json.dumps(data, ensure_ascii=False)
        try:
            pyperclip.copy(json_str)
        except Exception as e:
            raise RuntimeError(f"复制到剪贴板失败: {e}")
