# structured-data

分类: 偏好（BETTER）

## 是什么
frago def 提供结构化数据的定义、存取和查询能力。比手写 JSON 文件更规范，支持 schema 验证和版本管理。

## 怎么用
  frago def list                                    # 查看已有定义
  frago def get <name>                              # 获取定义内容
  frago def set <name> --params '{"key": "value"}'  # 设置定义

## 什么时候用
- 需要存储任务执行过程中的结构化数据时
- 需要在多个步骤之间传递配置或参数时
- 需要持久化中间结果供后续使用时

## 不要做
- 不要手写 JSON 文件到临时目录
- 不要用环境变量传递复杂结构化数据
