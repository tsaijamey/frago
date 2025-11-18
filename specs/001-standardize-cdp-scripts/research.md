# 研究报告：CDP Shell脚本标准化

**特性**: 标准化CDP Shell脚本  
**日期**: 2025-11-15  
**状态**: 完成

## 执行摘要

项目中共有16个CDP相关shell脚本，存在三种不同的实现方式：
- 5个脚本使用websocat（标准方式）
- 9个脚本使用curl+Python（简化方式）  
- 1个脚本使用nc（特殊实现）
- 1个帮助文档脚本

需要将所有脚本标准化为使用websocat通信方式。

## 技术决策

### 1. CDP通信方式选择

**决策**: 统一使用websocat工具进行WebSocket通信

**理由**: 
- websocat是专门的WebSocket客户端工具，稳定可靠
- 支持完整的CDP协议功能，不限于JavaScript执行
- 已有5个脚本成功使用，证明方案可行
- 纯Shell实现，无需Python依赖

**考虑的替代方案**:
- curl + Python：功能受限，只能执行JavaScript，需要Python依赖
- nc（netcat）：手动构建WebSocket帧复杂易错，不稳定
- wscat：需要Node.js环境，增加依赖

### 2. 错误处理机制

**决策**: 采用三级错误检查机制

**理由**:
- 环境检查：确保CDP服务运行和工具安装
- 连接检查：验证WebSocket连接可用
- 执行检查：解析响应确认命令成功

**考虑的替代方案**:
- 简单返回码检查：不能提供足够的错误信息
- 异常捕获：Shell脚本异常处理能力有限

### 3. 脚本组织结构  

**决策**: 保持现有目录结构，创建通用函数库

**理由**:
- 避免破坏现有调用路径
- 通过函数库实现代码复用
- 便于增量式迁移

**考虑的替代方案**:
- 重组目录结构：影响太大，可能破坏现有工作流
- 单一脚本整合：不利于模块化维护

## 研究发现

### 现有脚本清单和状态

#### 已标准化（使用websocat）- 5个
1. `scripts/share/cdp_status.sh` - ✅ 状态检查和环境验证
2. `scripts/share/cdp_navigate.sh` - ✅ 页面导航
3. `scripts/share/cdp_screenshot.sh` - ✅ 截图功能  
4. `scripts/share/cdp_get_content.sh` - ✅ 获取页面内容
5. `scripts/generate/cdp_annotate.sh` - ✅ 元素标注

#### 需要标准化（使用curl+Python）- 9个
1. `scripts/share/cdp_click.sh` - 点击操作
2. `scripts/share/cdp_scroll.sh` - 滚动页面
3. `scripts/share/cdp_wait.sh` - 等待元素
4. `scripts/share/cdp_get_title.sh` - 获取标题
5. `scripts/share/cdp_zoom.sh` - 缩放效果
6. `scripts/generate/cdp_highlight.sh` - 高亮效果
7. `scripts/generate/cdp_pointer.sh` - 指针动画  
8. `scripts/generate/cdp_spotlight.sh` - 聚光灯效果
9. `scripts/generate/cdp_clear_effects.sh` - 清除效果

#### 需要重写（使用nc）- 1个
1. `scripts/share/cdp_exec_js.sh` - JavaScript执行（使用nc手动构建WebSocket）

#### 文档脚本 - 1个
1. `scripts/share/cdp_help.sh` - 帮助文档（无需修改）

### 主要问题分析

1. **实现不一致**
   - 三种不同的通信方式导致维护困难
   - 功能能力不一致（curl方式功能受限）

2. **错误处理缺失**  
   - curl脚本缺少CDP运行检查
   - nc脚本几乎没有错误处理
   - 错误信息不明确

3. **Python依赖问题**
   - 9个脚本使用Python解析JSON
   - 违反纯Shell脚本的技术约束
   - 增加了不必要的依赖

4. **nc实现的特殊问题**
   - 手动构建WebSocket协议复杂易错
   - 不支持大消息传输
   - 缺乏健壮性

## 实施建议

### 阶段1：创建通用函数库
创建`scripts/share/cdp_common.sh`，包含：
- CDP环境检查函数
- WebSocket URL获取函数
- 标准错误处理函数
- JSON响应解析函数（使用jq或awk）

### 阶段2：标准化高优先级脚本
优先修改影响功能的脚本：
- `cdp_exec_js.sh` - 替换nc实现
- `cdp_click.sh` - 支持更复杂的点击操作
- `cdp_wait.sh` - 使用原生CDP等待方法

### 阶段3：标准化其余脚本
批量修改使用curl的脚本：
- 统一使用websocat通信
- 移除Python依赖
- 添加完整错误处理

### 阶段4：测试验证
- 为每个脚本创建功能测试
- 验证标准化后功能不变
- 性能基准测试

## CDP协议映射

### 常用CDP方法映射
| 脚本功能 | 当前实现 | CDP标准方法 |
|---------|---------|------------|
| 点击元素 | Runtime.evaluate | DOM.getDocument + Input.dispatchMouseEvent |
| 滚动页面 | Runtime.evaluate | Input.dispatchMouseEvent (wheel) |
| 等待元素 | Runtime.evaluate (循环) | Page.waitForSelector |
| 获取标题 | Runtime.evaluate | Runtime.evaluate 或 DOM API |
| 执行JS | Runtime.evaluate | Runtime.evaluate |
| 视觉效果 | Runtime.evaluate | Runtime.evaluate (保持) |

## 风险评估

### 低风险
- websocat已在5个脚本中验证可行
- 保持向后兼容的接口
- 增量式迁移降低影响

### 中风险  
- 需要在所有使用环境安装websocat
- JSON解析从Python改为Shell工具（jq/awk）

### 缓解措施
- 提供websocat安装脚本
- 创建兼容性测试套件
- 保留原脚本备份直到验证完成

## 结论

标准化CDP脚本为使用websocat是必要且可行的。通过创建通用函数库和分阶段实施，可以安全地完成迁移，提高代码一致性和可维护性。