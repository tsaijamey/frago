# Frago PyPI 发布前检查清单

## 1. 代码质量检查

- [ ] 运行所有测试: `uv run pytest`
- [ ] 检查代码风格: `uv run ruff check src/`
- [ ] 类型检查: `uv run mypy src/frago`
- [ ] 确保没有未提交的更改: `git status`

## 2. 版本管理

- [ ] 更新版本号 (pyproject.toml 和 src/frago/__init__.py)
- [ ] 创建版本标签: `git tag v0.1.0`
- [ ] 推送标签: `git push origin v0.1.0`

## 3. 文档检查

- [ ] README.md 内容准确且最新
- [ ] LICENSE 文件存在
- [ ] CHANGELOG.md 记录了版本变更（可选但推荐）
- [ ] 所有文档链接可访问

## 4. 依赖检查

- [ ] 确认所有依赖在 PyPI 上可用
- [ ] 版本范围合理（不要过于严格）
- [ ] 可选依赖正确标记

## 5. 构建测试

- [ ] 本地构建成功: `uv build`
- [ ] 检查生成的文件: `ls -lh dist/`
- [ ] 验证包内容: `tar tzf dist/frago-*.tar.gz | head -20`
- [ ] 测试安装: `pip install dist/frago-*.whl`

## 6. PyPI 准备

- [ ] 注册 PyPI 账号: https://pypi.org/account/register/
- [ ] 生成 API Token: https://pypi.org/manage/account/token/
- [ ] 安装发布工具: `uv add --dev twine`

## 7. 测试发布 (TestPyPI)

- [ ] 上传到 TestPyPI: `uv run twine upload --repository testpypi dist/*`
- [ ] 从 TestPyPI 安装测试: `pip install --index-url https://test.pypi.org/simple/ frago`
- [ ] 验证功能正常

## 8. 正式发布

- [ ] 上传到 PyPI: `uv run twine upload dist/*`
- [ ] 验证 PyPI 页面: https://pypi.org/project/frago/
- [ ] 测试正式安装: `pip install frago`

## 9. 发布后

- [ ] 创建 GitHub Release
- [ ] 更新文档中的安装说明
- [ ] 社区公告（如果适用）
- [ ] 开始下一个版本的开发

## 当前版本信息

- 版本: 0.1.0
- 最后检查日期: 2025-11-24
