"""
视觉效果相关CDP命令

封装视觉效果功能的CDP命令，包括高亮、指针、聚光灯、标注等。
"""

from typing import Dict, Any, Optional

from ..logger import get_logger


class VisualEffectsCommands:
    """视觉效果命令类"""
    
    def __init__(self, session):
        """
        初始化视觉效果命令
        
        Args:
            session: CDP会话实例
        """
        self.session = session
        self.logger = get_logger()
    
    def highlight(self, selector: str, color: str = "magenta", border_width: int = 3) -> None:
        """
        高亮显示指定元素
        
        Args:
            selector: CSS选择器
            color: 高亮颜色
            border_width: 边框宽度（像素）
        """
        self.logger.info(f"Highlighting element: {selector} with color {color}")
        
        script = f"""
        (function() {{
            const element = document.querySelector('{selector}');
            if (element) {{
                element.style.border = '{border_width}px solid {color}';
                element.style.outline = '{border_width}px solid {color}';
                element.setAttribute('data-frago-highlight', 'true');
            }}
        }})();
        """
        
        self.session.send_command("Runtime.evaluate", {"expression": script})
    
    def spotlight(self, selector: str, opacity: float = 0.7) -> None:
        """
        聚光灯效果突出显示元素
        
        Args:
            selector: CSS选择器
            opacity: 遮罩透明度（0-1）
        """
        self.logger.info(f"Applying spotlight to element: {selector}")
        
        script = f"""
        (function() {{
            const element = document.querySelector('{selector}');
            if (element) {{
                const overlay = document.createElement('div');
                overlay.id = 'frago-spotlight';
                overlay.style.position = 'fixed';
                overlay.style.top = '0';
                overlay.style.left = '0';
                overlay.style.width = '100%';
                overlay.style.height = '100%';
                overlay.style.backgroundColor = 'rgba(0, 0, 0, {opacity})';
                overlay.style.zIndex = '999998';
                overlay.style.pointerEvents = 'none';
                document.body.appendChild(overlay);
                
                const rect = element.getBoundingClientRect();
                element.style.position = 'relative';
                element.style.zIndex = '999999';
            }}
        }})();
        """
        
        self.session.send_command("Runtime.evaluate", {"expression": script})
    
    def annotate(self, selector: str, text: str, position: str = "top") -> None:
        """
        在元素上添加标注文本
        
        Args:
            selector: CSS选择器
            text: 标注文本
            position: 标注位置（"top", "bottom", "left", "right"）
        """
        self.logger.info(f"Adding annotation to element: {selector}")
        
        position_map = {
            "top": "bottom: 100%; left: 50%; transform: translateX(-50%);",
            "bottom": "top: 100%; left: 50%; transform: translateX(-50%);",
            "left": "right: 100%; top: 50%; transform: translateY(-50%);",
            "right": "left: 100%; top: 50%; transform: translateY(-50%);"
        }
        
        position_style = position_map.get(position, position_map["top"])
        
        script = f"""
        (function() {{
            const element = document.querySelector('{selector}');
            if (element) {{
                const annotation = document.createElement('div');
                annotation.className = 'frago-annotation';
                annotation.textContent = '{text}';
                annotation.style.position = 'absolute';
                annotation.style.cssText += '{position_style}';
                annotation.style.padding = '4px 8px';
                annotation.style.backgroundColor = 'rgba(0, 0, 0, 0.8)';
                annotation.style.color = 'white';
                annotation.style.fontSize = '12px';
                annotation.style.borderRadius = '4px';
                annotation.style.whiteSpace = 'nowrap';
                annotation.style.zIndex = '999999';
                annotation.style.pointerEvents = 'none';
                
                element.style.position = 'relative';
                element.appendChild(annotation);
            }}
        }})();
        """
        
        self.session.send_command("Runtime.evaluate", {"expression": script})
    
    def clear_effects(self) -> None:
        """清除所有由Frago添加的视觉效果"""
        self.logger.info("Clearing all visual effects")
        
        script = """
        (function() {
            document.querySelectorAll('[data-frago-highlight]').forEach(el => {
                el.style.border = '';
                el.style.outline = '';
                el.removeAttribute('data-frago-highlight');
            });
            
            ['frago-spotlight'].forEach(id => {
                const element = document.getElementById(id);
                if (element) element.remove();
            });
            
            document.querySelectorAll('.frago-annotation').forEach(el => el.remove());
        })();
        """
        
        self.session.send_command("Runtime.evaluate", {"expression": script})
