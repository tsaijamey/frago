# better-git-checkout

分类: 偏好（BETTER）

## 解决什么问题
agent 在用户说"撤回"、"还原"时倾向于直接 `git checkout .` 或 `git checkout -- <file>`，这是粗粒度操作，可能丢掉用户想保留的更改。大多数场景有更精确的替代方案。

## 执行前必须确认的问题

```
用户的真实意图是什么？
├─ 放弃工作区所有更改 → git checkout . 可以，但先确认用户理解后果
├─ 放弃某个文件的所有更改 → git checkout -- <file> 可以
├─ 只撤销文件中的部分更改 → 不要用 checkout，见下方
└─ 切换分支 → 先确认工作区是否干净
```

## 部分更改的精确还原

用户只想撤销文件中的某几处修改，保留其他修改：

```bash
# Step 1: 看清楚差异范围
git diff <file>

# Step 2: 用 Edit 工具精确还原特定代码段
# 把不想要的改动手动改回去，保留想要的改动
```

**禁止**对这种场景使用 `git checkout -- <file>`，那会把所有改动一起丢掉。

## 不要做
- 不要在用户说"撤回这个改动"时直接 `git checkout .` — 先用 `git diff` 确认范围
- 不要在工作区有未提交改动时 `git checkout <branch>` 切换分支 — 先 stash 或 commit
- 不要用 `git checkout` 撤销已经 commit 的内容 — 那需要 `git revert`
