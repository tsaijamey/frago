"""Run实例自动发现

使用RapidFuzz模糊匹配寻找相似的run实例
"""

from pathlib import Path
from typing import Dict, List

from rapidfuzz import fuzz

from .manager import RunManager


class RunDiscovery:
    """Run实例发现器"""

    def __init__(self, manager: RunManager):
        """初始化发现器

        Args:
            manager: RunManager实例
        """
        self.manager = manager

    def discover_similar_runs(
        self, task_description: str, threshold: int = 60, max_results: int = 5
    ) -> List[Dict]:
        """发现相似的run实例

        Args:
            task_description: 用户任务描述
            threshold: 相似度阈值（0-100）
            max_results: 最大返回数量

        Returns:
            相似run列表（包含相似度分数）
        """
        all_runs = self.manager.list_runs()

        # 计算相似度
        results = []
        for run in all_runs:
            # 使用多种算法并取最大值，以提高中文匹配准确性
            theme = run["theme_description"]
            similarity = max(
                fuzz.token_sort_ratio(task_description, theme),  # 忽略词序
                fuzz.partial_ratio(task_description, theme),     # 部分匹配
                fuzz.token_set_ratio(task_description, theme)    # 集合匹配
            )

            if similarity >= threshold:
                results.append(
                    {
                        **run,
                        "similarity": similarity,
                    }
                )

        # 按相似度降序排序（相似度越高越靠前），相同相似度时按时间降序（时间越晚越靠前）
        # ISO 8601字符串可以直接比较，较晚的时间字符串值较大
        results.sort(key=lambda r: (r["similarity"], r["last_accessed"]), reverse=True)

        return results[:max_results]

    def find_best_match(self, task_description: str, threshold: int = 80) -> Dict | None:
        """查找最佳匹配的run实例

        Args:
            task_description: 用户任务描述
            threshold: 相似度阈值（高阈值，仅返回非常相似的）

        Returns:
            最佳匹配run或None
        """
        matches = self.discover_similar_runs(task_description, threshold=threshold, max_results=1)
        return matches[0] if matches else None
