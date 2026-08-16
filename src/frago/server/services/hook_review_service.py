"""提示能力（prompting）两层的状态与开关。

frago 给 agent 的提示分两层，WebUI 需要把它们分开讲清楚：

- **静态规则**：编译进 frago-core 二进制的路由规则，叠加 ``~/.frago/hook-rules.json``
  里的用户规则。不需要任何配置就生效，判定在毫秒级，因此状态恒为"已生效"。
- **轻量 ai**：每次 UserPromptSubmit 把最近几轮会话连同规则索引交给一个便宜模型，
  换回一句该注入的提示。这一层要有可用的模型 profile 才存在。

这里只做**读**与**开关落盘**。引擎侧怎么消费 ``hook_review.enabled`` 不在本模块
职责内（见 frago-core ``src/review.rs`` 的 ``enabled_in``）。

判定 profile 是否可用时，本模块刻意逐条镜像 frago-core ``kernel/llm.rs``
``resolve_config`` 与 ``review.rs`` ``config`` 的规则。两边一旦分叉，WebUI 就会
对着用户宣称"已生效"而引擎其实一次都没调过——那比不显示状态更糟。镜像的规则：

1. 环境变量 ``FRAGO_KERNEL_API_KEY`` 非空时压过 profiles.json。
2. 否则读 ``~/.frago/profiles.json``，取 ``active_profile_id`` 指向的那条，
   没有则取第一条。
3. ``default_model`` 为空 → 引擎报错，等同没配。
4. ``endpoint_type=custom`` 但缺 ``url`` → 引擎报错，等同没配。
5. ``api_key`` 为空白 → 引擎不发请求（旧版会照发一次注定 401 的请求），
   单列一种状态，因为它比"没配"更需要人去处理。
6. 真正调用时用的是便宜档 ``haiku_model``，缺失才退回 ``default_model``。
"""

import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

PROFILES_PATH = Path.home() / ".frago" / "profiles.json"

# 与 frago-core kernel/llm.rs profile_config_from 的 endpoint_type 分支一致。
# 不在表里的类型引擎直接报错，UI 必须跟着算"不可用"，不能乐观地显示已生效。
_SUPPORTED_ENDPOINT_TYPES = {"deepseek", "custom", "anthropic", "official", "claude"}

# 轻量 ai 的四种状态。UI 按这个枚举取文案，值保持英文标识符。
STATUS_ENABLED = "enabled"
STATUS_DISABLED = "disabled"
STATUS_NOT_CONFIGURED = "not_configured"
STATUS_NO_KEY = "no_key"


class HookReviewService:
    """读写 ``~/.frago/config.json -> hook_review``，并汇报两层提示能力的状态。"""

    @staticmethod
    def get_status() -> dict[str, Any]:
        """两层提示能力此刻的实际状态。

        Returns:
            ``{"enabled", "env_off", "static_rules", "lightweight_ai"}``
        """
        return {
            "enabled": HookReviewService._switch_enabled(),
            "env_off": os.environ.get("FRAGO_REVIEW", "").strip() == "off",
            "static_rules": HookReviewService._static_rules(),
            "lightweight_ai": HookReviewService._lightweight_ai(),
        }

    @staticmethod
    def set_enabled(enabled: bool) -> dict[str, Any]:
        """把开关落进 ``~/.frago/config.json -> hook_review.enabled``。

        写的是完整的一段（而非只改一个键），这样引擎读到的永远是完整结构。
        """
        from frago.init.config_manager import load_config, save_config
        from frago.init.models import HookReviewConfig

        config = load_config()
        config.hook_review = HookReviewConfig(enabled=enabled)
        save_config(config)
        return HookReviewService.get_status()

    # ── 开关 ──────────────────────────────────────────────────────────

    @staticmethod
    def _switch_enabled() -> bool:
        """段缺失即为开——与引擎的 ``enabled_in`` 同解。"""
        from frago.init.config_manager import load_config

        try:
            hook_review = load_config().hook_review
        except Exception as e:
            # 配置读不出来是别处要修的问题，不是"用户想关掉这一层"的表态。
            logger.warning("Failed to read hook_review switch, assuming on: %s", e)
            return True
        if hook_review is None:
            return True
        return bool(hook_review.enabled)

    # ── 静态规则 ──────────────────────────────────────────────────────

    @staticmethod
    def _static_rules() -> dict[str, Any]:
        """当前生效的规则条数（builtin 叠加用户文件，排除 disabled）。

        数不出来时 ``count`` 为 None——UI 据此只显示"已生效"而不编一个假数字。
        """
        try:
            from frago.cli.hook_rules_commands import _load_merged

            rules = _load_merged().get("rules", [])
            count = sum(1 for r in rules if not r.get("disabled", False))
            return {"available": True, "count": count}
        except Exception as e:
            logger.warning("Failed to count hook rules: %s", e)
            return {"available": True, "count": None}

    # ── 轻量 ai ───────────────────────────────────────────────────────

    @staticmethod
    def _lightweight_ai() -> dict[str, Any]:
        """轻量 ai 此刻处于四种状态里的哪一种。

        判定顺序有意如此：**没配**压过**被关掉**——对一个还没配模型的用户，
        "去配一个"才是能动的那一步，告诉他"这是你自己关的"只会让人困惑。
        开关关掉之后引擎在读 profile 之前就返回了，所以 ``disabled`` 又压过
        ``no_key``：既然一次都不会发请求，那就没有白等 1.4 秒这回事。
        """
        profile_state, name, model, detail = HookReviewService._resolve_profile()

        if profile_state == STATUS_NOT_CONFIGURED:
            status = STATUS_NOT_CONFIGURED
        elif not HookReviewService._switch_enabled():
            status = STATUS_DISABLED
        elif profile_state == STATUS_NO_KEY:
            status = STATUS_NO_KEY
        else:
            status = STATUS_ENABLED

        return {
            "status": status,
            "profile_name": name,
            "model": model,
            "detail": detail,
        }

    @staticmethod
    def _resolve_profile() -> tuple[str, str | None, str | None, str | None]:
        """镜像引擎的 profile 解析。

        Returns:
            ``(state, profile_name, model, detail)``。``state`` 只会是
            ``not_configured`` / ``no_key`` / ``enabled``（此处的 ``enabled``
            仅表示"profile 可用"，最终状态还要过开关那一关）。
            ``detail`` 是不可用的具体原因，给 UI 当补充说明，可为 None。
        """
        env_key = os.environ.get("FRAGO_KERNEL_API_KEY", "")
        env_model = os.environ.get("FRAGO_KERNEL_MODEL", "").strip()
        if env_key.strip():
            if not env_model:
                return (
                    STATUS_NOT_CONFIGURED,
                    None,
                    None,
                    "FRAGO_KERNEL_API_KEY is set but FRAGO_KERNEL_MODEL is empty",
                )
            return (STATUS_ENABLED, None, env_model, None)

        try:
            raw = PROFILES_PATH.read_text(encoding="utf-8")
        except OSError:
            return (STATUS_NOT_CONFIGURED, None, None, None)

        try:
            doc = json.loads(raw)
        except json.JSONDecodeError as e:
            return (STATUS_NOT_CONFIGURED, None, None, f"profiles.json parse failed: {e}")

        profiles = doc.get("profiles") or []
        if not isinstance(profiles, list) or not profiles:
            return (STATUS_NOT_CONFIGURED, None, None, None)

        active_id = doc.get("active_profile_id")
        profile = next(
            (p for p in profiles if isinstance(p, dict) and p.get("id") == active_id),
            None,
        )
        if profile is None:
            profile = next((p for p in profiles if isinstance(p, dict)), None)
        if profile is None:
            return (STATUS_NOT_CONFIGURED, None, None, None)

        name = profile.get("name") or profile.get("id")
        endpoint_type = (profile.get("endpoint_type") or "").strip()
        default_model = (profile.get("default_model") or "").strip()
        haiku_model = (profile.get("haiku_model") or "").strip()
        model = haiku_model or default_model or None

        if not default_model:
            return (STATUS_NOT_CONFIGURED, name, None, "profile has no default_model")
        if endpoint_type not in _SUPPORTED_ENDPOINT_TYPES:
            return (
                STATUS_NOT_CONFIGURED,
                name,
                model,
                f"unsupported endpoint_type '{endpoint_type}'",
            )
        if endpoint_type == "custom" and not (profile.get("url") or "").strip():
            return (
                STATUS_NOT_CONFIGURED,
                name,
                model,
                "endpoint_type=custom but url is missing",
            )
        if not (profile.get("api_key") or "").strip():
            return (STATUS_NO_KEY, name, model, None)

        return (STATUS_ENABLED, name, model, None)
