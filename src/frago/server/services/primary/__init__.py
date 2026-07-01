"""Primary Agent service subpackage.

承接 primary_agent_service.py 的拆分（spec 20260629-arch-refactor-server Phase 4）。
门面类 PrimaryAgentService 仍持有全部状态与单例；本子包按职责簇放无状态/接 svc 的
自由函数与 helper，门面 re-export 保对外符号不变。

第一步落地：helpers.py —— 模块级无状态校验/渲染 helper。
"""
