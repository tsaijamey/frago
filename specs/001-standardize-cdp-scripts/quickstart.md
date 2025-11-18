# 快速开始：CDP Shell脚本标准化

## 概述

本指南帮助您快速开始CDP脚本标准化工作。所有脚本将统一使用websocat工具与Chrome DevTools Protocol通信。

## 前置要求

### 1. 安装websocat
```bash
# macOS
brew install websocat

# 或从GitHub下载
curl -L https://github.com/vi/websocat/releases/latest/download/websocat.aarch64-apple-darwin -o /usr/local/bin/websocat
chmod +x /usr/local/bin/websocat
```

### 2. 确保Chrome CDP运行
```bash
# 检查CDP状态
./scripts/share/cdp_status.sh

# 如果未运行，启动Chrome with CDP
google-chrome --remote-debugging-port=9222 --headless
```

### 3. 安装JSON处理工具（可选但推荐）
```bash
# 安装jq用于JSON处理
brew install jq
```

## 快速验证

### 测试标准化脚本
```bash
# 测试已标准化的脚本
./scripts/share/cdp_navigate.sh "https://example.com"
./scripts/share/cdp_status.sh --screenshot output.png
```

## 标准化流程

### 步骤1：识别需要标准化的脚本
```bash
# 运行检查工具（待创建）
./tools/check_scripts.sh

# 手动检查
grep -l "curl.*json/runtime/evaluate" scripts/**/*.sh
grep -l "nc -U" scripts/**/*.sh
```

### 步骤2：理解标准模板

查看已标准化的参考实现：
- `scripts/share/cdp_status.sh` - 基础模板
- `scripts/share/cdp_navigate.sh` - 带参数处理
- `scripts/share/cdp_screenshot.sh` - 复杂响应处理

### 步骤3：修改脚本

#### 原始实现（curl方式）：
```bash
# 旧的实现方式
response=$(curl -s -X POST "127.0.0.1:${CDP_PORT}/json/runtime/evaluate" \
  -d "{\"expression\": \"document.querySelector('$selector').click()\"}" \
  -H "Content-Type: application/json")
```

#### 标准化实现（websocat方式）：
```bash
# 新的标准化方式
# 1. 获取WebSocket URL
ws_url=$(curl -s "127.0.0.1:${CDP_PORT}/json" | grep -o '"webSocketDebuggerUrl":"[^"]*' | cut -d'"' -f4 | head -1)

# 2. 发送CDP命令
response=$(echo '{"id":1,"method":"Runtime.evaluate","params":{"expression":"document.querySelector('"'$selector'"').click()"}}' | \
  websocat -t -n1 "$ws_url")

# 3. 检查结果
if echo "$response" | grep -q '"result"'; then
  echo "✓ clicked: $selector"
else
  echo "✗ failed to click: $selector"
  exit 1
fi
```

### 步骤4：添加标准错误处理

```bash
#!/bin/bash

# 标准错误处理模板
set -e

# 检查参数
if [ $# -lt 1 ]; then
  echo "Usage: $0 <selector>"
  exit 2
fi

# 检查websocat
if ! command -v websocat &> /dev/null; then
  echo "✗ websocat is not installed"
  echo "  Install: brew install websocat"
  exit 4
fi

# 检查CDP
CDP_PORT=${CDP_PORT:-9222}
if ! curl -s "127.0.0.1:${CDP_PORT}/json" > /dev/null 2>&1; then
  echo "✗ CDP is not running on port ${CDP_PORT}"
  exit 3
fi
```

### 步骤5：测试标准化脚本

```bash
# 功能测试
./scripts/share/cdp_click.sh "button.submit"

# 错误处理测试
CDP_PORT=9999 ./scripts/share/cdp_click.sh "button"  # 应报告CDP未运行

# 性能测试
time ./scripts/share/cdp_click.sh "button"
```

## 标准化检查清单

每个脚本标准化时检查：

- [ ] 使用websocat替代curl/nc
- [ ] 添加websocat安装检查
- [ ] 添加CDP运行状态检查
- [ ] 实现标准错误处理
- [ ] 使用标准输出格式（✓/✗前缀）
- [ ] 移除Python依赖
- [ ] 添加参数验证
- [ ] 保持向后兼容的接口
- [ ] 创建对应的测试脚本
- [ ] 更新脚本头部注释

## 常见问题

### Q: 如何处理复杂的JSON响应？
A: 使用jq或awk进行解析：
```bash
# 使用jq
result=$(echo "$response" | jq -r '.result.value')

# 使用awk（无需额外依赖）
result=$(echo "$response" | awk -F'"value":' '{print $2}' | awk -F'[,}]' '{print $1}')
```

### Q: 如何处理base64编码的数据（如截图）？
A: 参考cdp_screenshot.sh的实现：
```bash
# 提取base64数据
screenshot_data=$(echo "$response" | sed -n 's/.*"data":"\([^"]*\)".*/\1/p')
# 解码并保存
echo "$screenshot_data" | base64 -d > "$output_file"
```

### Q: 如何调试脚本？
A: 设置DEBUG环境变量：
```bash
DEBUG=1 ./scripts/share/cdp_click.sh "button"
```

## 测试命令示例

```bash
# 批量测试所有标准化脚本
for script in scripts/**/*.sh; do
  echo "Testing: $script"
  $script --help || true
done

# 性能基准测试
./tools/benchmark.sh
```

## 获取帮助

- 查看脚本帮助：`./scripts/share/cdp_help.sh`
- 查看标准实现：`cat scripts/share/cdp_status.sh`
- 查看完整文档：`specs/001-standardize-cdp-scripts/`

## 下一步

1. 完成高优先级脚本标准化（cdp_exec_js.sh、cdp_click.sh、cdp_wait.sh）
2. 创建自动化测试套件
3. 批量标准化剩余脚本
4. 性能优化和文档完善