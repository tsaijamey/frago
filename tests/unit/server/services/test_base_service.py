"""Tests for frago.server.services.base_service.BaseService ABC."""

import threading

import pytest

from frago.server.services.base_service import BaseService


def test_cannot_instantiate_without_on_init():
    """缺少 _on_init 实现的子类不可实例化（ABC 契约）。"""
    with pytest.raises(TypeError):
        BaseService()  # type: ignore[abstract]


def test_get_instance_is_singleton_per_subclass():
    """每个子类各自一个单例，互不串台。"""

    class FooService(BaseService):
        def _on_init(self) -> None:
            self.calls = getattr(self, "calls", 0) + 1

    class BarService(BaseService):
        def _on_init(self) -> None:
            self.tag = "bar"

    try:
        a = FooService.get_instance()
        b = FooService.get_instance()
        c = BarService.get_instance()

        assert a is b  # 同类同实例
        assert a is not c  # 不同类不串台
        assert isinstance(c, BarService)
        assert a.calls == 1  # _on_init 只调一次
        assert c.tag == "bar"
        assert a._initialized is True
    finally:
        FooService.reset_instance()
        BarService.reset_instance()


def test_on_init_called_once_under_concurrency():
    """并发取实例时 _on_init 仍只执行一次。"""

    class CountingService(BaseService):
        def _on_init(self) -> None:
            CountingService.init_count = getattr(CountingService, "init_count", 0) + 1

    instances = []

    def grab():
        instances.append(CountingService.get_instance())

    try:
        threads = [threading.Thread(target=grab) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert all(i is instances[0] for i in instances)
        assert CountingService.init_count == 1
    finally:
        CountingService.reset_instance()
