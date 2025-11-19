# /auvima.merge

合成最终视频

## 用法
```
/auvima.merge [project_name]
```

## 任务流程

1. 检查项目目录下的所有clips
2. 验证所有必要文件是否存在
3. 按shot编号顺序合并视频片段
4. 合并对应的音频轨道
5. 生成最终输出视频

## 输出文件

- `outputs/final_output.mp4` - 最终视频
- `outputs/merge_report.json` - 合成报告
- `merge.done` - 完成标记（供pipeline检测，位于项目根目录）

## 实现脚本位置
`src/auvima_merge.py`