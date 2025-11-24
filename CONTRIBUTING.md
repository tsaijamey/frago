# Contributing to Frago

感谢您对 Frago 项目的关注！我们欢迎各种形式的贡献。

## 如何贡献

### 报告问题

如果您发现bug或有功能建议，请：

1. 检查是否已存在相关Issue
2. 创建新Issue并详细描述问题
3. 提供复现步骤和环境信息

### 提交代码

1. Fork 项目仓库
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交您的更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建Pull Request

### 代码规范

- Python代码遵循PEP 8
- Shell脚本遵循ShellCheck规范
- 提供清晰的注释和文档
- 确保所有测试通过

### 开发环境设置

```bash
# 克隆仓库
git clone https://github.com/tsaijamey/Frago.git
cd Frago

# 设置Python环境
cd src
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 安装系统依赖
brew install ffmpeg
brew install uv
```

### 测试

运行测试前请确保：

1. Chrome CDP在9222端口运行
2. 已授权屏幕录制权限
3. 所有依赖已正确安装

## 需要帮助的领域

- 🎥 视频处理算法优化
- 🎤 音频合成引擎集成
- 🌍 多语言支持
- 📖 文档完善
- 🐛 Bug修复
- ⚡ 性能优化

## 行为准则

请参与者遵循以下准则：

- 使用友好和包容的语言
- 尊重不同的观点和经验
- 优雅地接受建设性批评
- 专注于对社区最有利的事情

## 联系方式

如有问题，请通过以下方式联系：

- 在GitHub上创建Issue
- 参与项目Discussions

感谢您的贡献！