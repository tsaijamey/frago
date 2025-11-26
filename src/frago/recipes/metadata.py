"""Recipe 元数据解析和验证"""
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .exceptions import MetadataParseError, RecipeValidationError


@dataclass
class RecipeMetadata:
    """Recipe 元数据"""
    name: str
    type: str  # atomic | workflow
    runtime: str  # chrome-js | python | shell
    version: str
    description: str  # AI 可理解字段
    use_cases: list[str]  # AI 可理解字段
    output_targets: list[str]  # AI 可理解字段: stdout | file | clipboard
    inputs: dict[str, dict[str, Any]] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)  # AI 可理解字段
    env: dict[str, dict[str, Any]] = field(default_factory=dict)  # 环境变量定义
    system_packages: bool = False  # 使用系统 Python（用于依赖 dbus 等系统包）


def parse_metadata_file(path: Path) -> RecipeMetadata:
    """
    从 Markdown 文件的 YAML frontmatter 解析元数据
    
    Args:
        path: 元数据文件路径（.md 文件）
    
    Returns:
        RecipeMetadata 对象
    
    Raises:
        MetadataParseError: 解析失败时抛出
    """
    try:
        content = path.read_text(encoding='utf-8')
    except Exception as e:
        raise MetadataParseError(str(path), f"无法读取文件: {e}")
    
    # 提取 YAML frontmatter
    if not content.startswith('---'):
        raise MetadataParseError(str(path), "文件不以 '---' 开头，缺少 YAML frontmatter")
    
    parts = content.split('---', 2)
    if len(parts) < 3:
        raise MetadataParseError(str(path), "YAML frontmatter 格式错误，缺少结束的 '---'")
    
    yaml_content = parts[1].strip()
    
    # 解析 YAML
    try:
        data = yaml.safe_load(yaml_content)
    except yaml.YAMLError as e:
        raise MetadataParseError(str(path), f"YAML 解析失败: {e}")
    
    if not isinstance(data, dict):
        raise MetadataParseError(str(path), "YAML frontmatter 必须是字典格式")
    
    # 构建 RecipeMetadata 对象
    try:
        metadata = RecipeMetadata(
            name=data['name'],
            type=data['type'],
            runtime=data['runtime'],
            version=data['version'],
            description=data['description'],
            use_cases=data['use_cases'],
            output_targets=data['output_targets'],
            inputs=data.get('inputs', {}),
            outputs=data.get('outputs', {}),
            dependencies=data.get('dependencies', []),
            tags=data.get('tags', []),
            env=data.get('env', {}),
            system_packages=data.get('system_packages', False),
        )
    except KeyError as e:
        raise MetadataParseError(str(path), f"缺少必需字段: {e}")
    except Exception as e:
        raise MetadataParseError(str(path), f"元数据构建失败: {e}")
    
    return metadata


def validate_metadata(metadata: RecipeMetadata) -> None:
    """
    验证元数据的有效性
    
    Args:
        metadata: 要验证的元数据对象
    
    Raises:
        RecipeValidationError: 验证失败时抛出
    """
    errors = []
    
    # 验证 name
    if not metadata.name or not re.match(r'^[a-zA-Z0-9_-]+$', metadata.name):
        errors.append("name 必须仅包含字母、数字、下划线、连字符")
    
    # 验证 type
    if metadata.type not in ['atomic', 'workflow']:
        errors.append(f"type 必须是 'atomic' 或 'workflow'，当前值: '{metadata.type}'")
    
    # 验证 runtime
    if metadata.runtime not in ['chrome-js', 'python', 'shell']:
        errors.append(f"runtime 必须是 'chrome-js', 'python' 或 'shell'，当前值: '{metadata.runtime}'")
    
    # 验证 version
    if not re.match(r'^\d+\.\d+(\.\d+)?$', metadata.version):
        errors.append(f"version 格式无效: '{metadata.version}'，期望格式: '1.0' 或 '1.0.0'")
    
    # AI 字段验证
    if not metadata.description or len(metadata.description) > 200:
        errors.append("description 必须存在且长度 <= 200 字符")
    
    if not metadata.use_cases or len(metadata.use_cases) == 0:
        errors.append("use_cases 必须包含至少一个使用场景")
    
    if not metadata.output_targets or len(metadata.output_targets) == 0:
        errors.append("output_targets 必须包含至少一个输出目标")
    
    for target in metadata.output_targets:
        if target not in ['stdout', 'file', 'clipboard']:
            errors.append(f"output_targets 包含无效值: '{target}'，有效值: stdout, file, clipboard")
    
    # 验证 inputs
    for param_name, param_def in metadata.inputs.items():
        if 'type' not in param_def or 'required' not in param_def:
            errors.append(f"输入参数 '{param_name}' 缺少 'type' 或 'required' 字段")

    # 验证 env
    for env_name, env_def in metadata.env.items():
        # 环境变量名必须符合规范
        if not re.match(r'^[A-Za-z_][A-Za-z0-9_]*$', env_name):
            errors.append(f"环境变量 '{env_name}' 名称无效，必须以字母或下划线开头")
        # env_def 应该是字典
        if not isinstance(env_def, dict):
            errors.append(f"环境变量 '{env_name}' 定义必须是字典格式")
        else:
            # required 字段如果存在必须是布尔值
            if 'required' in env_def and not isinstance(env_def['required'], bool):
                errors.append(f"环境变量 '{env_name}' 的 'required' 字段必须是布尔值")
            # default 字段如果存在必须是字符串
            if 'default' in env_def and not isinstance(env_def['default'], str):
                errors.append(f"环境变量 '{env_name}' 的 'default' 字段必须是字符串")

    if errors:
        raise RecipeValidationError(metadata.name, errors)


def validate_params(metadata: RecipeMetadata, params: dict[str, Any]) -> None:
    """
    验证运行时提供的参数是否符合元数据定义

    Args:
        metadata: Recipe 元数据
        params: 用户提供的参数

    Raises:
        RecipeValidationError: 参数验证失败时抛出
    """
    errors = []

    # 检查必需参数是否提供
    for param_name, param_def in metadata.inputs.items():
        if param_def.get('required', False):
            if param_name not in params:
                param_desc = param_def.get('description', '')
                error_msg = f"缺少必需参数: '{param_name}'"
                if param_desc:
                    error_msg += f" ({param_desc})"
                errors.append(error_msg)

    # 检查提供的参数类型
    for param_name, param_value in params.items():
        if param_name in metadata.inputs:
            param_def = metadata.inputs[param_name]
            expected_type = param_def.get('type')
            if expected_type:
                type_errors = check_param_type(param_name, param_value, expected_type)
                errors.extend(type_errors)

    if errors:
        raise RecipeValidationError(metadata.name, errors)


def check_param_type(param_name: str, value: Any, expected_type: str) -> list[str]:
    """
    检查参数值的类型是否符合预期

    Args:
        param_name: 参数名称
        value: 参数值
        expected_type: 期望的类型 (string, number, boolean, array, object)

    Returns:
        错误消息列表（为空表示验证通过）
    """
    errors = []

    # 类型映射
    type_checks = {
        'string': lambda v: isinstance(v, str),
        'number': lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
        'boolean': lambda v: isinstance(v, bool),
        'array': lambda v: isinstance(v, list),
        'object': lambda v: isinstance(v, dict),
    }

    if expected_type not in type_checks:
        # 未知类型，跳过检查
        return errors

    check_func = type_checks[expected_type]
    if not check_func(value):
        # 类型不匹配
        actual_type = type(value).__name__
        if isinstance(value, bool):
            actual_type = 'boolean'
        elif isinstance(value, (int, float)):
            actual_type = 'number'
        elif isinstance(value, str):
            actual_type = 'string'
        elif isinstance(value, list):
            actual_type = 'array'
        elif isinstance(value, dict):
            actual_type = 'object'

        errors.append(
            f"参数 '{param_name}' 类型错误: 期望 {expected_type}，实际 {actual_type}"
        )

    return errors
