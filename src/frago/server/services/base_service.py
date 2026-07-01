"""BaseService — server service 层的抽象契约基类。

照搬 chrome/backends/base.py 的 ABC 范式：用抽象方法钉住「一个 service 该长什么样」，
让调用方只依赖契约、不依赖具体实现。单例采用与现有 service 一致的线程锁双检模式
（参见 version_service.VersionCheckService），以便现有 service 平滑接入。

设计约束（对照架构北极星无关，遵循 .claude/FRAGO.md）：
- service 是薄编排层；纯业务逻辑不带 Service 后缀，IO 收敛到 service 内部。
- "Agent" 一词专指外部 AI agent，service 命名不得借用。
"""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import ClassVar, Dict, Type


class BaseService(ABC):
    """所有 server service 的抽象基类。

    子类约定：
    - 通过 ``get_instance()`` 取单例，不直接 ``__init__``。
    - 在 ``_on_init()`` 里完成依赖加载 / 连接建立（仅首次实例化时调用一次）。

    示例::

        class FooService(BaseService):
            def _on_init(self) -> None:
                self._cache = load_cache()

        svc = FooService.get_instance()
    """

    # 按具体子类登记单例，避免不同 service 共享同一个 _instance 串台。
    _instances: ClassVar[Dict[Type["BaseService"], "BaseService"]] = {}
    _lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(self) -> None:
        # 子类不应覆盖 __init__；初始化逻辑写在 _on_init 钩子里。
        self._initialized: bool = False

    @classmethod
    def get_instance(cls) -> "BaseService":
        """取本类单例。线程安全双检锁，与现有 service 风格一致。"""
        if cls not in BaseService._instances:
            with BaseService._lock:
                if cls not in BaseService._instances:
                    inst = cls()
                    inst._on_init()
                    inst._initialized = True
                    BaseService._instances[cls] = inst
        return BaseService._instances[cls]

    @classmethod
    def reset_instance(cls) -> None:
        """清空本类单例。仅供测试隔离使用。"""
        with BaseService._lock:
            BaseService._instances.pop(cls, None)

    @abstractmethod
    def _on_init(self) -> None:
        """初始化钩子：子类在此加载依赖、建立连接。首次实例化时调用一次。"""
        raise NotImplementedError
