"""单元测试 - ContextManager

测试上下文管理、环境变量优先级、失效处理
"""

import json
import os
import pytest
from pathlib import Path
from datetime import datetime

from frago.run.context import ContextManager
from frago.run.manager import RunManager
from frago.run.exceptions import ContextNotSetError, RunNotFoundError


@pytest.fixture
def temp_project_root(tmp_path):
    """创建临时项目根目录"""
    return tmp_path


@pytest.fixture
def temp_projects_dir(temp_project_root):
    """创建临时projects目录"""
    projects_dir = temp_project_root / "projects"
    projects_dir.mkdir()
    return projects_dir


@pytest.fixture
def context_manager(temp_project_root, temp_projects_dir):
    """创建ContextManager实例"""
    return ContextManager(temp_project_root, temp_projects_dir)


@pytest.fixture
def manager(temp_projects_dir):
    """创建RunManager实例"""
    return RunManager(temp_projects_dir)


class TestSetCurrentRun:
    """测试set_current_run方法"""

    def test_set_current_run_success(self, context_manager, manager, temp_project_root):
        """测试成功设置上下文"""
        # 创建run
        instance = manager.create_run("测试任务")

        # 设置上下文
        context = context_manager.set_current_run(instance.run_id, instance.theme_description)

        assert context.run_id == instance.run_id
        assert context.theme_description == instance.theme_description

        # 验证配置文件
        config_file = temp_project_root / ".frago" / "current_project"
        assert config_file.exists()

        config_data = json.loads(config_file.read_text())
        assert config_data["run_id"] == instance.run_id

    def test_set_current_run_not_found(self, context_manager):
        """测试设置不存在的run"""
        with pytest.raises(RunNotFoundError):
            context_manager.set_current_run("non-existent", "测试")

    def test_set_current_run_updates_metadata(self, context_manager, manager, temp_projects_dir):
        """测试设置上下文时更新run的last_accessed"""
        instance = manager.create_run("测试")

        # 读取初始metadata
        metadata_file = temp_projects_dir / instance.run_id / ".metadata.json"
        initial_metadata = json.loads(metadata_file.read_text())
        initial_time = initial_metadata["last_accessed"]

        import time
        time.sleep(0.1)

        # 设置上下文
        context_manager.set_current_run(instance.run_id, instance.theme_description)

        # 验证metadata更新
        updated_metadata = json.loads(metadata_file.read_text())
        assert updated_metadata["last_accessed"] > initial_time


class TestGetCurrentRun:
    """测试get_current_run方法"""

    def test_get_current_run_from_file(self, context_manager, manager):
        """测试从配置文件读取上下文"""
        instance = manager.create_run("测试")
        context_manager.set_current_run(instance.run_id, instance.theme_description)

        # 读取上下文
        context = context_manager.get_current_run()
        assert context.run_id == instance.run_id

    def test_get_current_run_not_set(self, context_manager):
        """测试未设置上下文"""
        with pytest.raises(ContextNotSetError):
            context_manager.get_current_run()

    def test_get_current_run_from_env(self, context_manager, manager, monkeypatch):
        """测试从环境变量读取上下文(优先级高)"""
        instance = manager.create_run("测试")

        # 设置环境变量
        monkeypatch.setenv("FRAGO_CURRENT_RUN", instance.run_id)

        # 读取上下文(不需要先set_current_run)
        context = context_manager.get_current_run()
        assert context.run_id == instance.run_id

    def test_get_current_run_env_overrides_file(self, context_manager, manager, monkeypatch):
        """测试环境变量优先级高于配置文件"""
        run1 = manager.create_run("任务1")
        run2 = manager.create_run("任务2")

        # 设置配置文件
        context_manager.set_current_run(run1.run_id, run1.theme_description)

        # 设置环境变量(不同的run)
        monkeypatch.setenv("FRAGO_CURRENT_RUN", run2.run_id)

        # 环境变量优先
        context = context_manager.get_current_run()
        assert context.run_id == run2.run_id

    def test_get_current_run_invalid_file(self, context_manager, temp_project_root):
        """测试配置文件损坏"""
        # 创建损坏的配置文件
        config_file = temp_project_root / ".frago" / "current_project"
        config_file.parent.mkdir(exist_ok=True)
        config_file.write_text("这不是有效的JSON")

        # 应该抛出FileSystemError
        from frago.run.exceptions import FileSystemError

        with pytest.raises(FileSystemError):
            context_manager.get_current_run()

    def test_get_current_run_deleted_run(self, context_manager, manager, temp_projects_dir):
        """测试指向已删除run的上下文"""
        instance = manager.create_run("测试")
        context_manager.set_current_run(instance.run_id, instance.theme_description)

        # 删除run目录
        import shutil
        shutil.rmtree(temp_projects_dir / instance.run_id)

        # 应该抛出RunNotFoundError并清空配置
        with pytest.raises(RunNotFoundError):
            context_manager.get_current_run()


class TestGetCurrentRunId:
    """测试get_current_run_id方法"""

    def test_get_current_run_id_exists(self, context_manager, manager):
        """测试获取当前run_id"""
        instance = manager.create_run("测试")
        context_manager.set_current_run(instance.run_id, instance.theme_description)

        run_id = context_manager.get_current_run_id()
        assert run_id == instance.run_id

    def test_get_current_run_id_not_set(self, context_manager):
        """测试未设置时返回None"""
        run_id = context_manager.get_current_run_id()
        assert run_id is None


class TestClearContext:
    """测试_clear_context方法"""

    def test_clear_context(self, context_manager, manager, temp_project_root):
        """测试清空上下文配置"""
        instance = manager.create_run("测试")
        context_manager.set_current_run(instance.run_id, instance.theme_description)

        config_file = temp_project_root / ".frago" / "current_project"
        assert config_file.exists()

        # 清空上下文
        context_manager._clear_context()

        assert not config_file.exists()
