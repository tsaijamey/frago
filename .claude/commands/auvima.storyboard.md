# /auvima.storyboard

分镜规划阶段 - 基于收集的信息生成分镜脚本（原auvima.plan）

## 用法
```
/auvima.storyboard [project_name]
```

## 前置条件
- 必须已完成 `/auvima.start`
- `research/report.json` 必须存在

## 主要任务

1. 读取并分析research/report.json
2. 根据内容类型设计叙事结构
3. 规划每个镜头的内容和时长
4. 预估音频文本和时长
5. 生成分镜JSON序列

## 分镜结构设计

### 根据内容类型的不同结构
- **资讯分析**：观点-论据-反驳-总结
- **GitHub项目**：介绍-功能-代码-使用
- **产品介绍**：定位-功能-演示-价值
- **MVP开发**：需求-设计-编码-演示

### 时长控制
- 单个分镜：10-30秒
- 总时长：3-5分钟
- 音频预估：中文180-200字/分钟

## 输出文件

```
projects/<project_name>/
├── shots/
│   ├── shot_001.json
│   ├── shot_002.json
│   ├── shot_003.json
│   └── ...
└── storyboard.done     # 完成标记（pipeline检测用）
```

## 分镜JSON格式（详细版）

```json
{
  "shot_id": "shot_001",
  "sequence": 1,
  "duration": 15,
  "type": "browser_recording",
  "title": "GitHub项目主页介绍",
  
  "scene_setup": {
    "description": "展示langchain项目的GitHub主页，让观众了解项目的基本信息和受欢迎程度",
    "start_url": "https://github.com/langchain-ai/langchain",
    "initial_state": "页面完全加载，位于页面顶部",
    "viewport": "1280x960窗口，确保README内容可见"
  },
  
  "focus_points": [
    {
      "element": "项目标题和描述",
      "selector": ".repository-content h1",
      "importance": "high",
      "display_duration": 3,
      "visual_effect": "spotlight"
    },
    {
      "element": "Star数和Fork数",
      "selector": ".social-count",
      "importance": "high", 
      "display_duration": 2,
      "visual_effect": "highlight",
      "annotation": "73k+ Stars"
    },
    {
      "element": "README开头部分",
      "selector": "#readme article",
      "importance": "medium",
      "display_duration": 5,
      "visual_effect": "none",
      "action": "slow_scroll"
    }
  ],
  
  "actions_timeline": [
    {
      "time": 0,
      "action": "navigate",
      "target": "https://github.com/langchain-ai/langchain",
      "wait_for": ".repository-content",
      "duration": 0
    },
    {
      "time": 0.5,
      "action": "prepare",
      "description": "等待页面稳定，准备开始录制",
      "duration": 1.5
    },
    {
      "time": 2,
      "action": "spotlight",
      "target": ".repository-content h1",
      "description": "聚焦项目标题",
      "duration": 3
    },
    {
      "time": 5,
      "action": "highlight_multiple",
      "targets": [".social-count"],
      "color": "#FFD700",
      "description": "高亮显示Star和Fork数",
      "duration": 2
    },
    {
      "time": 7,
      "action": "scroll_to",
      "target": "#readme",
      "speed": "slow",
      "description": "平滑滚动到README",
      "duration": 2
    },
    {
      "time": 9,
      "action": "scroll_content",
      "pixels": 300,
      "intervals": 2,
      "description": "缓慢滚动展示README内容",
      "duration": 4
    },
    {
      "time": 13,
      "action": "clear_effects",
      "description": "清除所有视觉效果",
      "duration": 1
    },
    {
      "time": 14,
      "action": "hold",
      "description": "保持画面1秒作为结尾",
      "duration": 1
    }
  ],
  
  "expected_results": {
    "visual_confirmation": [
      "页面顶部显示langchain/langchain仓库名",
      "Star数显示为73k+（或更高）",
      "README标题'🦜️🔗 LangChain'清晰可见",
      "Installation部分出现在视野中"
    ],
    "key_information": [
      "项目是关于LLM应用开发的框架",
      "项目非常受欢迎（高Star数）",
      "有详细的文档和说明"
    ]
  },
  
  "narration": {
    "text": "LangChain是一个强大的框架，用于开发基于语言模型的应用程序。从GitHub上超过7万颗星的数量可以看出，这个项目在开发者社区中非常受欢迎。",
    "duration_estimate": 12,
    "sync_points": [
      {"time": 2, "text": "LangChain是一个强大的框架"},
      {"time": 5, "text": "超过7万颗星"},
      {"time": 9, "text": "在开发者社区中非常受欢迎"}
    ]
  },
  
  "technical_notes": {
    "recording_tips": [
      "确保Chrome窗口位置在(20,20)",
      "录制区域为1280x960",
      "使用30fps帧率",
      "预留2秒头部缓冲，1秒尾部缓冲"
    ],
    "potential_issues": [
      "页面加载可能需要额外时间",
      "Star数是动态的，注释文本可能需要更新",
      "README内容可能很长，注意滚动速度"
    ]
  },
  
  "source_refs": ["report.json#sources[0]"],
  
  "quality_criteria": {
    "must_have": [
      "项目名称清晰可见",
      "Star数完整展示",
      "README开头内容展示"
    ],
    "nice_to_have": [
      "贡献者头像",
      "最近更新时间",
      "主要编程语言标签"
    ]
  }
}
```

## 关键改进：为Generate提供充分信息

### 1. scene_setup - 场景设置
- **start_url**: 明确的起始URL
- **initial_state**: 页面应该处于什么状态
- **viewport**: 窗口设置要求

### 2. focus_points - 焦点内容
- **selector**: 精确的CSS选择器
- **importance**: 重要程度（决定展示时长）
- **visual_effect**: 使用什么视觉效果
- **annotation**: 需要添加的说明文字

### 3. actions_timeline - 时间轴动作
- **精确到秒的时间点**
- **具体的动作类型和参数**
- **每个动作的预期效果描述**
- **动作持续时间**

### 4. expected_results - 预期结果
- **visual_confirmation**: 视觉上应该看到什么
- **key_information**: 必须传达的关键信息

### 5. technical_notes - 技术注意事项
- **recording_tips**: 录制建议
- **potential_issues**: 可能的问题和解决方案

### 6. quality_criteria - 质量标准
- **must_have**: 必须展示的内容
- **nice_to_have**: 加分项

## 其他类型分镜示例

### 类型2：代码展示（code_display）
```json
{
  "shot_id": "shot_005",
  "type": "code_display",
  "title": "展示核心代码实现",
  
  "scene_setup": {
    "description": "打开VS Code展示关键代码文件",
    "file_path": "/path/to/langchain/core.py",
    "initial_line": 45,
    "syntax_theme": "dark"
  },
  
  "focus_points": [
    {
      "lines": "45-60",
      "description": "类定义和初始化",
      "highlight_color": "#FFD700",
      "duration": 5
    },
    {
      "lines": "75-90", 
      "description": "核心算法实现",
      "add_comment": "// 这里是关键逻辑",
      "duration": 8
    }
  ]
}
```

### 类型3：MVP开发演示（development）
```json
{
  "shot_id": "shot_008",
  "type": "development",
  "title": "创建React组件",
  
  "scene_setup": {
    "description": "在终端和编辑器中展示开发过程",
    "tools": ["terminal", "vscode"],
    "project_path": "/Users/demo/todo-app"
  },
  
  "actions_timeline": [
    {
      "time": 0,
      "action": "terminal_command",
      "command": "npx create-react-app todo-app",
      "show_output": true,
      "duration": 5
    },
    {
      "time": 5,
      "action": "open_editor",
      "file": "src/App.js",
      "duration": 2
    },
    {
      "time": 7,
      "action": "type_code",
      "content": "const TodoItem = ({task}) => {...}",
      "typing_speed": "medium",
      "duration": 10
    }
  ]
}
```

### 类型4：产品功能演示（product_demo）
```json
{
  "shot_id": "shot_010",
  "type": "product_demo",
  "title": "Notion数据库功能",
  
  "scene_setup": {
    "description": "演示Notion的数据库创建和使用",
    "start_url": "https://notion.so",
    "login_state": "已登录到demo账号"
  },
  
  "user_interactions": [
    {
      "action": "click",
      "target": "新建页面按钮",
      "expected": "弹出模板选择"
    },
    {
      "action": "select",
      "option": "数据库-表格视图",
      "expected": "创建空白数据库"
    },
    {
      "action": "input",
      "field": "数据库标题",
      "value": "项目管理看板",
      "expected": "标题更新"
    },
    {
      "action": "demonstrate",
      "feature": "添加字段、筛选、排序",
      "duration": 15
    }
  ]
}
```

## 分镜质量检查清单

生成每个分镜后，确保包含：

### ✅ 必需信息
- [ ] 明确的起始状态（URL/文件/应用）
- [ ] 具体的CSS选择器或操作目标
- [ ] 精确的时间轴（每个动作的开始和持续时间）
- [ ] 预期的视觉结果描述
- [ ] 关键信息点列表

### ✅ 技术细节
- [ ] 录制参数（分辨率、帧率、区域）
- [ ] 需要等待的元素或状态
- [ ] 可能的错误情况和处理方法

### ✅ 质量标准
- [ ] must_have：必须展示的内容
- [ ] nice_to_have：额外加分项
- [ ] 时长是否合理（不要太短或太长）

## 分镜设计原则

1. **可执行性**：每个动作都要有明确的执行方法
2. **可验证性**：每个结果都要能够被检查
3. **容错性**：考虑可能的异常情况
4. **精确性**：时间、选择器、参数都要准确
5. **完整性**：包含generate需要的所有信息

## 完成标记

**必须**在所有分镜文件生成后创建 `storyboard.done` 空文件，位于项目根目录。

## 质量要求

- 覆盖report中的核心信息
- 分镜之间逻辑连贯
- 音频时长 ≤ 视频时长
- 视觉效果适度使用

## 实现脚本
`scripts/auvima_storyboard.py` (待实现)