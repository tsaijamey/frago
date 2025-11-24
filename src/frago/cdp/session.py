"""
CDP会话实现

实现WebSocket连接的CDP会话管理。
"""

import json
import uuid
import threading
import queue
import time
from typing import Dict, Any, Optional, Callable

import websocket

from .client import CDPClient
from .config import CDPConfig
from .logger import get_logger
from .exceptions import ConnectionError, TimeoutError, CDPError
from .types import CDPRequest, CDPResponse
# 延迟导入以避免循环导入
# from .commands import PageCommands, InputCommands, RuntimeCommands, DOMCommands


class CDPSession(CDPClient):
    """CDP会话类"""
    
    def __init__(self, config: Optional[CDPConfig] = None):
        """
        初始化CDP会话
        
        Args:
            config: CDP配置，如果为None则使用默认配置
        """
        super().__init__(config)
        self.ws: Optional[websocket.WebSocket] = None
        self._request_id = 0
        self._pending_requests: Dict[int, Dict] = {}
        self._event_handlers: Dict[str, Callable] = {}
        self._message_queue = queue.Queue()
        self._listener_thread: Optional[threading.Thread] = None
        self._running = False
        self._lock = threading.RLock()
        
        # 延迟初始化命令封装
        self._page = None
        self._input = None
        self._runtime = None
        self._dom = None
        self._screenshot = None
        self._scroll = None
        self._wait = None
        self._zoom = None
        self._status = None
        self._visual_effects = None
    
    def connect(self) -> None:
        """建立WebSocket连接

        性能优化：
        - 连接超时默认5秒（本地连接优化）
        - 禁用不必要的握手检查以加速连接
        - 支持快速失败机制
        """
        try:
            start_time = time.time()

            # 动态获取WebSocket URL
            ws_url = self._get_websocket_url()
            self.logger.info(f"Connecting to CDP at {ws_url}")

            # 准备WebSocket连接参数（性能优化）
            ws_options = {
                "timeout": 1.0,  # 接收消息超时设置为1秒，用于定期检查_running状态
                "skip_utf8_validation": True,  # 跳过UTF-8验证以提升性能
                "enable_multithread": True      # 启用多线程支持
            }

            # 配置代理参数
            if self.config.proxy_host and self.config.proxy_port and not self.config.no_proxy:
                ws_options["http_proxy_host"] = self.config.proxy_host
                ws_options["http_proxy_port"] = self.config.proxy_port

                if self.config.proxy_username and self.config.proxy_password:
                    ws_options["http_proxy_auth"] = (
                        self.config.proxy_username,
                        self.config.proxy_password
                    )

                self.logger.debug(f"Using proxy: {self.config.proxy_host}:{self.config.proxy_port}")
            elif self.config.no_proxy:
                self.logger.debug("Proxy bypassed (no_proxy=True)")

            # 创建WebSocket连接
            self.ws = websocket.create_connection(
                ws_url,
                **ws_options
            )

            self._connected = True
            self._running = True

            # 记录连接时间
            elapsed = (time.time() - start_time) * 1000  # 转换为毫秒
            self.logger.info(f"CDP connection established in {elapsed:.2f}ms")

            # 启动消息监听线程
            self._start_message_listener()

        except Exception as e:
            self._connected = False
            self._running = False
            elapsed = (time.time() - start_time) * 1000
            self.logger.error(f"Connection failed after {elapsed:.2f}ms: {e}")
            raise ConnectionError(f"Failed to connect to CDP: {e}")

    def _get_websocket_url(self) -> str:
        """动态获取WebSocket调试URL

        优先获取第一个page的WebSocket URL，如果没有page则使用browser URL

        Returns:
            str: WebSocket URL
        """
        import requests
        try:
            # 首先尝试获取pages列表
            response = requests.get(
                f"{self.config.http_url}/json/list",
                timeout=self.config.connect_timeout
            )
            response.raise_for_status()
            pages = response.json()

            # 查找第一个可用的page
            for page in pages:
                if page.get('type') == 'page' and page.get('webSocketDebuggerUrl'):
                    self.logger.debug(f"Using page: {page.get('title', 'Unknown')}")
                    return page['webSocketDebuggerUrl']

            # 如果没有page，使用browser endpoint
            response = requests.get(
                f"{self.config.http_url}/json/version",
                timeout=self.config.connect_timeout
            )
            response.raise_for_status()
            version_info = response.json()
            return version_info['webSocketDebuggerUrl']
        except Exception:
            # 回退到静态URL
            return self.config.websocket_url
    
    def disconnect(self) -> None:
        """断开WebSocket连接"""
        # 停止消息监听线程
        self._running = False
        
        if self._listener_thread and self._listener_thread.is_alive():
            self._listener_thread.join(timeout=5.0)
        
        if self.ws:
            try:
                self.ws.close()
                self.logger.info("CDP connection closed")
            except Exception as e:
                self.logger.warning(f"Error closing CDP connection: {e}")
            finally:
                self.ws = None
                self._connected = False
    
    def send_command(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        发送CDP命令
        
        Args:
            method: CDP方法名
            params: 命令参数
            
        Returns:
            Dict[str, Any]: 命令结果
            
        Raises:
            CDPError: 命令执行失败
        """
        if not self.connected:
            raise ConnectionError("Not connected to CDP")
        
        # 生成请求ID
        with self._lock:
            request_id = self._request_id
            self._request_id += 1
        
        # 构建请求
        request: CDPRequest = {
            "id": request_id,
            "method": method,
            "params": params or {}
        }
        
        # 发送请求
        try:
            self.ws.send(json.dumps(request))
            self.logger.debug(f"Sent CDP command: {method} (id: {request_id})")
        except Exception as e:
            raise CDPError(f"Failed to send CDP command: {e}")
        
        # 等待响应
        return self._wait_for_response(request_id)
    
    def _validate_response(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """
        验证CDP响应
        
        Args:
            response: CDP响应
            
        Returns:
            Dict[str, Any]: 验证后的响应
            
        Raises:
            CDPError: 响应错误
        """
        if "error" in response:
            error = response["error"]
            raise CDPError(f"CDP error: {error.get('message', 'Unknown error')} (code: {error.get('code')})")
        
        return response
    
    def _wait_for_response(self, request_id: int) -> Dict[str, Any]:
        """
        等待指定请求ID的响应
        
        Args:
            request_id: 请求ID
            
        Returns:
            Dict[str, Any]: 响应数据
            
        Raises:
            TimeoutError: 等待超时
            CDPError: 响应错误
        """
        start_time = time.time()
        timeout = self.config.command_timeout
        
        # 注册等待的请求
        with self._lock:
            self._pending_requests[request_id] = {
                "start_time": start_time,
                "timeout": timeout
            }
        
        try:
            while time.time() - start_time < timeout:
                # 检查消息队列中是否有我们的响应
                try:
                    # 非阻塞获取消息
                    message = self._message_queue.get_nowait()
                    response = json.loads(message)
                    
                    # 如果是我们等待的响应
                    if response.get("id") == request_id:
                        return self._validate_response(response)
                    
                    # 如果是事件，调用事件处理器
                    elif "method" in response:
                        self._handle_event(response)
                        
                except queue.Empty:
                    # 没有消息，短暂休眠后继续
                    time.sleep(0.01)
                    continue
                except Exception as e:
                    self.logger.error(f"Error processing message: {e}")
                    continue
            
            raise TimeoutError(f"Command timeout after {timeout} seconds")
        
        finally:
            # 清理等待的请求
            with self._lock:
                self._pending_requests.pop(request_id, None)
    
    def _start_message_listener(self) -> None:
        """启动消息监听线程"""
        self._listener_thread = threading.Thread(
            target=self._message_listener,
            daemon=True,
            name="CDPMessageListener"
        )
        self._listener_thread.start()
    
    def _message_listener(self) -> None:
        """消息监听线程主函数"""
        while self._running and self.ws:
            try:
                # 接收消息
                message = self.ws.recv()

                # 将消息放入队列
                self._message_queue.put(message)

            except websocket.WebSocketConnectionClosedException:
                self.logger.warning("WebSocket connection closed")
                break
            except websocket.WebSocketTimeoutException:
                # 超时是正常的，用于定期检查_running状态，不记录为错误
                continue
            except Exception as e:
                self.logger.error(f"Error in message listener: {e}")
                # 短暂休眠后继续
                time.sleep(0.1)
    
    def _handle_event(self, event: Dict[str, Any]) -> None:
        """
        处理CDP事件
        
        Args:
            event: 事件数据
        """
        method = event.get("method")
        params = event.get("params", {})
        
        if method in self._event_handlers:
            try:
                self._event_handlers[method](params)
            except Exception as e:
                self.logger.error(f"Error in event handler for {method}: {e}")
    
    def on_event(self, event_name: str) -> Callable:
        """
        事件处理器装饰器
        
        Args:
            event_name: 事件名称
            
        Returns:
            Callable: 装饰器函数
        """
        def decorator(handler: Callable) -> Callable:
            self._event_handlers[event_name] = handler
            return handler
        return decorator
    
    def health_check(self) -> bool:
        """
        执行连接健康检查
        
        Returns:
            bool: 连接是否健康
        """
        if not self.connected:
            return False
        
        try:
            # 发送一个简单的ping命令来检查连接
            result = self.send_command("Runtime.evaluate", {
                "expression": "1",
                "returnByValue": True
            })
            return "result" in result
        except Exception as e:
            self.logger.warning(f"Health check failed: {e}")
            return False

    # CLI便利方法
    def navigate(self, url: str) -> None:
        """导航到指定URL"""
        self.page.navigate(url)

    def click(self, selector: str, wait_timeout: int = 10) -> None:
        """点击指定选择器的元素"""
        # 先等待元素出现
        self.page.wait_for_selector(selector, timeout=wait_timeout)

        # 获取元素位置并点击
        result = self.dom.get_document()
        # CDP返回格式: {"id": ..., "result": {"root": {...}}}
        node_id = result.get("result", {}).get("root", {}).get("nodeId")

        if not node_id:
            raise CDPError("无法获取文档节点")

        query_result = self.dom.query_selector(node_id, selector)
        # CDP返回格式: {"id": ..., "result": {"nodeId": ...}}
        element_node_id = query_result.get("result", {}).get("nodeId")

        if not element_node_id:
            raise CDPError(f"未找到元素: {selector}")

        box_model = self.dom.get_box_model(element_node_id)
        # CDP返回格式: {"id": ..., "result": {"model": {"content": [...]}}}
        content = box_model.get("result", {}).get("model", {}).get("content", [])

        if not content:
            raise CDPError(f"无法获取元素位置: {selector}")

        # 计算元素中心点
        x = (content[0] + content[2]) / 2
        y = (content[1] + content[5]) / 2

        self.input.click(x, y)

    def take_screenshot(self, output_file: str, full_page: bool = False, quality: int = 80) -> None:
        """截取页面截图并保存到文件（便利方法）"""
        # 委托给screenshot commands
        self.screenshot.capture(output_file, full_page=full_page, quality=quality)

    def evaluate(self, script: str, return_by_value: bool = True) -> Any:
        """执行JavaScript代码"""
        response = self.runtime.evaluate(script, return_by_value=return_by_value)
        # CDP返回格式: {'id': ..., 'result': {'result': {'value': ...}}}
        if return_by_value and response:
            result = response.get("result", {})
            if "result" in result:
                return result["result"].get("value")
        return response

    def get_title(self) -> str:
        """获取页面标题"""
        result = self.evaluate("document.title")
        return result or ""

    def scroll(self, distance: int) -> None:
        """滚动页面"""
        self.evaluate(f"window.scrollBy(0, {distance})")

    def wait(self, seconds: float) -> None:
        """等待指定秒数"""
        import time
        time.sleep(seconds)

    def zoom(self, factor: float) -> None:
        """设置页面缩放比例"""
        self.evaluate(f"document.body.style.zoom = '{factor}'")

    def clear_effects(self) -> None:
        """清除所有视觉效果"""
        self.evaluate("""
            document.querySelectorAll('[style*="highlight"], [style*="pointer"], [style*="spotlight"]').forEach(el => {
                el.style.removeProperty('background-color');
                el.style.removeProperty('border');
                el.style.removeProperty('box-shadow');
            });
        """)

    def highlight(self, selector: str, color: str = "yellow", border_width: int = 3) -> None:
        """
        高亮显示指定元素

        Args:
            selector: CSS选择器
            color: 高亮颜色，默认yellow
            border_width: 边框宽度（像素），默认3
        """
        self.evaluate(f"""
            (function() {{
                document.querySelectorAll('{selector}').forEach(el => {{
                    el.style.border = '{border_width}px solid {color}';
                    el.style.outline = '{border_width}px solid {color}';
                    el.setAttribute('data-frago-highlight', 'true');
                }});
                return true;
            }})()
        """, return_by_value=True)

    def pointer(self, selector: str) -> None:
        """在元素上显示鼠标指针"""
        self.evaluate(f"""
            document.querySelectorAll('{selector}').forEach(el => {{
                el.style.cursor = 'pointer';
                el.style.boxShadow = '0 0 10px rgba(255, 0, 0, 0.5)';
            }});
        """)

    def spotlight(self, selector: str) -> None:
        """聚光灯效果显示元素"""
        self.evaluate(f"""
            document.querySelectorAll('{selector}').forEach(el => {{
                el.style.boxShadow = '0 0 20px rgba(255, 255, 0, 0.8)';
                el.style.zIndex = '9999';
                el.style.position = 'relative';
            }});
        """)

    def annotate(self, selector: str, text: str, position: str = "top") -> None:
        """在元素上添加标注"""
        self.evaluate(f"""
            document.querySelectorAll('{selector}').forEach(el => {{
                const annotation = document.createElement('div');
                annotation.textContent = '{text}';
                annotation.style.position = 'absolute';
                annotation.style.background = 'rgba(255, 255, 0, 0.9)';
                annotation.style.padding = '5px';
                annotation.style.borderRadius = '3px';
                annotation.style.fontSize = '12px';
                annotation.style.zIndex = '10000';
                
                const rect = el.getBoundingClientRect();
                switch('{position}') {{
                    case 'top':
                        annotation.style.top = (rect.top + window.scrollY - 30) + 'px';
                        annotation.style.left = rect.left + 'px';
                        break;
                    case 'bottom':
                        annotation.style.top = (rect.bottom + window.scrollY + 5) + 'px';
                        annotation.style.left = rect.left + 'px';
                        break;
                    case 'left':
                        annotation.style.top = rect.top + window.scrollY + 'px';
                        annotation.style.left = (rect.left - 150) + 'px';
                        break;
                    case 'right':
                        annotation.style.top = rect.top + window.scrollY + 'px';
                        annotation.style.left = (rect.right + 5) + 'px';
                        break;
                }}
                
                document.body.appendChild(annotation);
            }});
        """)

    def wait_for_selector(self, selector: str, timeout: Optional[float] = None) -> None:
        """等待选择器匹配的元素出现"""
        self.page.wait_for_selector(selector, timeout=timeout)

    # 延迟加载命令类的属性访问器
    @property
    def page(self):
        if self._page is None:
            from .commands.page import PageCommands
            self._page = PageCommands(self)
        return self._page

    @property
    def input(self):
        if self._input is None:
            from .commands.input import InputCommands
            self._input = InputCommands(self)
        return self._input

    @property
    def runtime(self):
        if self._runtime is None:
            from .commands.runtime import RuntimeCommands
            self._runtime = RuntimeCommands(self)
        return self._runtime

    @property
    def dom(self):
        if self._dom is None:
            from .commands.dom import DOMCommands
            self._dom = DOMCommands(self)
        return self._dom
    
    @property
    def screenshot(self):
        if self._screenshot is None:
            from .commands.screenshot import ScreenshotCommands
            self._screenshot = ScreenshotCommands(self)
        return self._screenshot
    
    @property
    def scroll(self):
        if self._scroll is None:
            from .commands.scroll import ScrollCommands
            self._scroll = ScrollCommands(self)
        return self._scroll
    
    @property
    def wait(self):
        if self._wait is None:
            from .commands.wait import WaitCommands
            self._wait = WaitCommands(self)
        return self._wait
    
    @property
    def zoom(self):
        if self._zoom is None:
            from .commands.zoom import ZoomCommands
            self._zoom = ZoomCommands(self)
        return self._zoom
    
    @property
    def status(self):
        if self._status is None:
            from .commands.status import StatusCommands
            self._status = StatusCommands(self)
        return self._status
    
    @property
    def visual_effects(self):
        if self._visual_effects is None:
            from .commands.visual_effects import VisualEffectsCommands
            self._visual_effects = VisualEffectsCommands(self)
        return self._visual_effects