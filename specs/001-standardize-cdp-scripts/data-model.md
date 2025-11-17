# 数据模型：CDP Shell脚本标准化

**特性**: 标准化CDP Shell脚本  
**生成日期**: 2025-11-15

## 实体定义

### 1. CDPScript（CDP脚本）

**描述**: 表示一个CDP shell脚本文件及其元数据

**属性**:
- `name`: string - 脚本文件名（如 cdp_click.sh）
- `path`: string - 脚本完整路径
- `type`: enum - 脚本类型 ['share', 'generate', 'help']
- `status`: enum - 标准化状态 ['standardized', 'needs_update', 'special_case']
- `implementation`: enum - 当前实现方式 ['websocat', 'curl', 'nc', 'none']
- `cdp_methods`: array<string> - 使用的CDP方法列表
- `dependencies`: array<string> - 依赖的工具列表
- `purpose`: string - 脚本功能描述

**验证规则**:
- name必须以cdp_开头，以.sh结尾
- path必须存在且可执行
- status转换：needs_update → standardized（单向）
- implementation必须与实际代码匹配

### 2. StandardizationTask（标准化任务）

**描述**: 表示一个脚本的标准化任务

**属性**:
- `script_name`: string - 目标脚本名称
- `priority`: enum - 优先级 ['high', 'medium', 'low']  
- `current_issues`: array<string> - 当前存在的问题列表
- `required_changes`: array<string> - 需要的修改列表
- `estimated_effort`: enum - 预计工作量 ['simple', 'moderate', 'complex']
- `completion_status`: enum - 完成状态 ['pending', 'in_progress', 'completed', 'verified']

**验证规则**:
- script_name必须对应存在的CDPScript
- priority基于问题严重程度自动计算
- completion_status转换：pending → in_progress → completed → verified

### 3. CDPCommand（CDP命令）

**描述**: CDP协议命令的标准化表示

**属性**:
- `id`: number - 命令ID（递增）
- `method`: string - CDP方法名（如 Page.navigate）
- `params`: object - 命令参数
- `response_handler`: string - 响应处理方式
- `error_handler`: string - 错误处理方式

**验证规则**:
- id必须唯一且递增
- method必须是有效的CDP方法
- params必须符合CDP协议规范

### 4. TestCase（测试用例）

**描述**: 脚本功能测试用例

**属性**:
- `test_id`: string - 测试ID
- `script_name`: string - 测试的脚本
- `test_type`: enum - 测试类型 ['functional', 'integration', 'performance']
- `input`: object - 测试输入参数
- `expected_output`: string - 预期输出
- `actual_output`: string - 实际输出（运行后填充）
- `status`: enum - 测试状态 ['pending', 'passed', 'failed', 'skipped']

**验证规则**:
- test_id格式：test_{script_name}_{type}_{序号}
- expected_output必须定义
- status自动根据比对结果更新

## 实体关系

```
CDPScript (1) ←→ (1) StandardizationTask
    ↓
    使用多个
    ↓
CDPCommand (n)
    ↓
    验证通过
    ↓
TestCase (n)
```

### 关系说明

1. **CDPScript - StandardizationTask**: 一对一关系
   - 每个需要标准化的脚本对应一个任务
   - 任务完成后脚本状态更新

2. **CDPScript - CDPCommand**: 一对多关系
   - 一个脚本可能使用多个CDP命令
   - 命令定义脚本的功能实现

3. **CDPScript - TestCase**: 一对多关系
   - 每个脚本有多个测试用例
   - 测试验证标准化后的功能

## 状态转换

### CDPScript状态机
```
needs_update → [标准化] → standardized → [验证] → standardized
     ↑                                                    ↓
     └────────────── [发现问题] ←─────────────────────────┘
```

### StandardizationTask状态机
```
pending → in_progress → completed → verified
            ↓               ↓
         [失败]          [测试失败]
            ↓               ↓
         pending ←──────────┘
```

## 数据约束

### 唯一性约束
- CDPScript.name必须唯一
- CDPCommand.id在会话内唯一
- TestCase.test_id全局唯一

### 引用完整性
- StandardizationTask.script_name必须引用存在的CDPScript
- TestCase.script_name必须引用存在的CDPScript

### 业务规则
- 只有status为'standardized'的脚本才能通过测试
- priority为'high'的任务必须优先完成
- 所有脚本必须有至少一个functional测试用例

## 数据示例

### CDPScript示例
```json
{
  "name": "cdp_click.sh",
  "path": "/scripts/share/cdp_click.sh",
  "type": "share",
  "status": "needs_update",
  "implementation": "curl",
  "cdp_methods": ["Runtime.evaluate"],
  "dependencies": ["curl", "python3"],
  "purpose": "点击页面元素"
}
```

### StandardizationTask示例
```json
{
  "script_name": "cdp_click.sh",
  "priority": "high",
  "current_issues": [
    "使用curl而非websocat",
    "依赖Python解析JSON",
    "缺少CDP连接检查"
  ],
  "required_changes": [
    "改用websocat通信",
    "使用Shell原生JSON解析",
    "添加环境检查"
  ],
  "estimated_effort": "moderate",
  "completion_status": "pending"
}
```

## 数据持久化

### 运行时数据
- 脚本清单：扫描文件系统动态生成
- 任务状态：内存中维护，可导出为JSON

### 持久化数据
- 测试结果：保存在tests/results/目录
- 标准化记录：保存在docs/standardization-log.md

## 数据访问模式

### 查询模式
1. 列出所有需要标准化的脚本
2. 按优先级获取任务列表
3. 查询特定脚本的测试结果

### 更新模式
1. 更新脚本标准化状态
2. 记录任务完成情况
3. 保存测试执行结果

## 性能考虑

- 脚本扫描使用文件系统缓存
- 测试结果批量写入减少I/O
- CDP命令使用连接池复用WebSocket连接