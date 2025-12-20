"""Skill 注册表 - 扫描和管理 Claude Code Skills"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml


@dataclass
class Skill:
    """有效的 Skill"""
    name: str
    description: str
    path: Path


@dataclass
class InvalidSkill:
    """无效的 Skill（不符合规范）"""
    dir_name: str
    path: Path
    reason: str


class SkillRegistry:
    """Skill 注册表

    扫描 ~/.claude/skills/ 目录下的所有 skill，
    解析 SKILL.md 的 YAML frontmatter 获取元数据。
    """

    def __init__(self, skills_dir: Optional[Path] = None):
        """初始化 SkillRegistry

        Args:
            skills_dir: skills 目录路径，默认为 ~/.claude/skills/
        """
        self.skills_dir = skills_dir or (Path.home() / '.claude' / 'skills')
        self.skills: list[Skill] = []
        self.invalid_skills: list[InvalidSkill] = []

    def scan(self) -> None:
        """扫描 skills 目录，加载所有有效的 skill"""
        self.skills.clear()
        self.invalid_skills.clear()

        if not self.skills_dir.exists():
            return

        for skill_dir in sorted(self.skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue

            # 跳过隐藏目录
            if skill_dir.name.startswith('.'):
                continue

            skill_md = skill_dir / 'SKILL.md'

            # 检查 SKILL.md 是否存在
            if not skill_md.exists():
                self.invalid_skills.append(InvalidSkill(
                    dir_name=skill_dir.name,
                    path=skill_dir,
                    reason="缺少 SKILL.md 文件"
                ))
                continue

            # 解析 SKILL.md
            try:
                metadata = self._parse_skill_md(skill_md)
            except Exception as e:
                self.invalid_skills.append(InvalidSkill(
                    dir_name=skill_dir.name,
                    path=skill_dir,
                    reason=str(e)
                ))
                continue

            # 验证必需字段
            name = metadata.get('name')
            description = metadata.get('description')

            if not name:
                self.invalid_skills.append(InvalidSkill(
                    dir_name=skill_dir.name,
                    path=skill_dir,
                    reason="缺少 name 字段"
                ))
                continue

            if not description:
                self.invalid_skills.append(InvalidSkill(
                    dir_name=skill_dir.name,
                    path=skill_dir,
                    reason="缺少 description 字段"
                ))
                continue

            # 添加有效 skill
            self.skills.append(Skill(
                name=name,
                description=description,
                path=skill_dir
            ))

    def _parse_skill_md(self, path: Path) -> dict:
        """解析 SKILL.md 文件的 YAML frontmatter

        Args:
            path: SKILL.md 文件路径

        Returns:
            解析后的元数据字典

        Raises:
            Exception: 解析失败时抛出
        """
        content = path.read_text(encoding='utf-8')

        # 检查 frontmatter 开头
        if not content.startswith('---'):
            raise Exception("文件不以 '---' 开头，缺少 YAML frontmatter")

        # 分割获取 YAML 部分
        parts = content.split('---', 2)
        if len(parts) < 3:
            raise Exception("YAML frontmatter 格式错误，缺少结束的 '---'")

        yaml_content = parts[1].strip()

        # 解析 YAML
        try:
            data = yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            raise Exception(f"YAML 解析失败: {e}")

        if not isinstance(data, dict):
            raise Exception("YAML frontmatter 必须是字典格式")

        return data

    def list_all(self) -> list[Skill]:
        """获取所有有效的 skill 列表（按名称排序）"""
        return sorted(self.skills, key=lambda s: s.name)

    def get_invalid(self) -> list[InvalidSkill]:
        """获取所有无效的 skill 列表"""
        return self.invalid_skills
