"""环境变量加载器

支持三级优先级配置：
1. 项目级 (.frago/.env) - 最高优先级
2. 用户级 (~/.frago/.env)
3. 系统环境 (os.environ) - 最低优先级

还支持：
- Workflow 上下文共享
- CLI --env 参数覆盖
"""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class EnvVarDefinition:
    """环境变量定义"""
    required: bool = False
    default: str | None = None
    description: str = ""


@dataclass
class WorkflowContext:
    """Workflow 执行上下文，用于跨 Recipe 共享环境变量"""
    shared_env: dict[str, str] = field(default_factory=dict)

    def set(self, key: str, value: str) -> None:
        """设置共享环境变量"""
        self.shared_env[key] = value

    def get(self, key: str, default: str | None = None) -> str | None:
        """获取共享环境变量"""
        return self.shared_env.get(key, default)

    def update(self, env_dict: dict[str, str]) -> None:
        """批量更新共享环境变量"""
        self.shared_env.update(env_dict)

    def as_dict(self) -> dict[str, str]:
        """返回所有共享环境变量"""
        return dict(self.shared_env)


class EnvLoader:
    """环境变量加载器"""

    # 用户级配置文件路径
    USER_ENV_PATH = Path.home() / ".frago" / ".env"
    # 项目级配置文件路径（相对于当前工作目录）
    PROJECT_ENV_PATH = Path(".frago") / ".env"

    def __init__(self, project_root: Path | None = None):
        """
        初始化环境变量加载器

        Args:
            project_root: 项目根目录，默认为当前工作目录
        """
        self.project_root = project_root or Path.cwd()
        self._cache: dict[str, str] | None = None

    def load_env_file(self, path: Path) -> dict[str, str]:
        """
        解析 .env 文件

        支持格式：
        - KEY=value
        - KEY="value with spaces"
        - KEY='value with spaces'
        - # 注释行
        - 空行

        Args:
            path: .env 文件路径

        Returns:
            环境变量字典
        """
        env_vars: dict[str, str] = {}

        if not path.exists():
            return env_vars

        try:
            content = path.read_text(encoding='utf-8')
        except Exception:
            return env_vars

        for line in content.splitlines():
            line = line.strip()

            # 跳过空行和注释
            if not line or line.startswith('#'):
                continue

            # 解析 KEY=VALUE
            match = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)=(.*)$', line)
            if not match:
                continue

            key = match.group(1)
            value = match.group(2).strip()

            # 移除引号
            if (value.startswith('"') and value.endswith('"')) or \
               (value.startswith("'") and value.endswith("'")):
                value = value[1:-1]

            env_vars[key] = value

        return env_vars

    def load_all(self, clear_cache: bool = False) -> dict[str, str]:
        """
        加载所有层级的环境变量（按优先级合并）

        优先级（高到低）：
        1. 项目级 (.frago/.env)
        2. 用户级 (~/.frago/.env)
        3. 系统环境 (os.environ)

        Args:
            clear_cache: 是否清除缓存重新加载

        Returns:
            合并后的环境变量字典
        """
        if self._cache is not None and not clear_cache:
            return dict(self._cache)

        # 从系统环境开始（最低优先级）
        merged: dict[str, str] = dict(os.environ)

        # 用户级覆盖
        user_env = self.load_env_file(self.USER_ENV_PATH)
        merged.update(user_env)

        # 项目级覆盖（最高优先级）
        project_env_path = self.project_root / self.PROJECT_ENV_PATH
        project_env = self.load_env_file(project_env_path)
        merged.update(project_env)

        self._cache = merged
        return dict(merged)

    def resolve_for_recipe(
        self,
        env_definitions: dict[str, dict[str, Any]],
        cli_overrides: dict[str, str] | None = None,
        workflow_context: WorkflowContext | None = None
    ) -> dict[str, str]:
        """
        为 Recipe 解析环境变量

        优先级（高到低）：
        1. CLI --env 参数
        2. Workflow 上下文共享变量
        3. 项目级 .env
        4. 用户级 .env
        5. 系统环境
        6. Recipe 定义的默认值

        Args:
            env_definitions: Recipe 元数据中的 env 定义
            cli_overrides: CLI --env 参数提供的覆盖值
            workflow_context: Workflow 执行上下文

        Returns:
            完整的环境变量字典（继承系统环境 + 配置覆盖）

        Raises:
            ValueError: 缺少必需的环境变量
        """
        cli_overrides = cli_overrides or {}

        # 加载所有层级
        merged = self.load_all()

        # Workflow 上下文覆盖
        if workflow_context:
            merged.update(workflow_context.as_dict())

        # CLI 覆盖（最高优先级）
        merged.update(cli_overrides)

        # 验证并应用默认值
        missing_required: list[str] = []

        for var_name, var_def in env_definitions.items():
            definition = EnvVarDefinition(
                required=var_def.get('required', False),
                default=var_def.get('default'),
                description=var_def.get('description', '')
            )

            if var_name not in merged:
                if definition.default is not None:
                    # 应用默认值
                    merged[var_name] = str(definition.default)
                elif definition.required:
                    # 记录缺失的必需变量
                    desc = f" ({definition.description})" if definition.description else ""
                    missing_required.append(f"{var_name}{desc}")

        if missing_required:
            raise ValueError(
                f"缺少必需的环境变量: {', '.join(missing_required)}\n"
                f"请在 ~/.frago/.env 或 .frago/.env 中配置，或通过 --env 参数提供"
            )

        return merged

    def get_recipe_env_subset(
        self,
        env_definitions: dict[str, dict[str, Any]],
        cli_overrides: dict[str, str] | None = None,
        workflow_context: WorkflowContext | None = None
    ) -> dict[str, str]:
        """
        获取 Recipe 声明的环境变量子集（仅返回声明的变量）

        用于调试或日志，避免泄露完整环境

        Args:
            env_definitions: Recipe 元数据中的 env 定义
            cli_overrides: CLI --env 参数
            workflow_context: Workflow 执行上下文

        Returns:
            仅包含 Recipe 声明的环境变量
        """
        full_env = self.resolve_for_recipe(env_definitions, cli_overrides, workflow_context)
        return {k: full_env[k] for k in env_definitions if k in full_env}


def save_env_file(path: Path, env_vars: dict[str, str]) -> None:
    """
    完整覆盖写入 .env 文件

    Args:
        path: .env 文件路径
        env_vars: 环境变量字典

    Notes:
        - 会覆盖原有内容
        - 自动创建父目录
        - 每行格式: KEY=value
    """
    # 确保目录存在
    path.parent.mkdir(parents=True, exist_ok=True)

    # 生成内容
    lines = [f'{key}={value}' for key, value in env_vars.items()]

    # 写入文件
    path.write_text('\n'.join(lines) + '\n' if lines else '', encoding='utf-8')


def update_env_file(path: Path, updates: dict[str, str | None]) -> None:
    """
    更新 .env 文件（保留注释和格式）

    Args:
        path: .env 文件路径
        updates: 更新字典，value=None 表示删除该变量

    Notes:
        - 保留注释行和空行
        - 更新已存在的变量
        - 追加新变量
        - 删除 value=None 的变量
    """
    lines = []
    updated_keys = set()

    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            stripped = line.strip()

            # 保留空行和注释
            if not stripped or stripped.startswith('#'):
                lines.append(line)
                continue

            # 解析变量行
            match = re.match(r'^([A-Za-z_][A-Za-z0-9_]*)=(.*)$', stripped)
            if not match:
                lines.append(line)  # 保留不规范的行
                continue

            key = match.group(1)

            # 更新或删除
            if key in updates:
                if updates[key] is not None:
                    # 更新变量
                    lines.append(f'{key}={updates[key]}')
                # else: 删除变量，不添加此行
                updated_keys.add(key)
            else:
                # 保留未修改的变量
                lines.append(line)

    # 添加新变量
    for key, value in updates.items():
        if key not in updated_keys and value is not None:
            lines.append(f'{key}={value}')

    # 确保目录存在
    path.parent.mkdir(parents=True, exist_ok=True)

    # 写入文件
    path.write_text('\n'.join(lines) + '\n' if lines else '', encoding='utf-8')
