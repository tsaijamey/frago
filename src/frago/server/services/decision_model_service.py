"""Decision model configuration service.

Reads and writes ``~/.frago/config.json -> decision_model`` and keeps
``~/.frago/profiles.json`` decision fields in sync for ``frago-core``.

Decision models do not have fixed providers or preset model catalogs; users
configure custom endpoints directly under two request modes (``wire``):
1. ``ollama`` — Ollama ``/api/generate`` raw prompt + ``logprobs`` mode.
2. ``decisions`` — HTTP structured Decision API (``POST`` JSON
   ``{model, state, questions, images?, temperature?}`` -> ``{answers}``).
"""

from __future__ import annotations

import logging
from typing import Any

from frago.init.config_manager import load_config, save_config
from frago.init.configurator import _mask_api_key
from frago.init.models import Config, DecisionModelConfig, DecisionWireMode
from frago.init.profile_manager import load_profiles, save_profiles

logger = logging.getLogger(__name__)

VALID_WIRES: tuple[DecisionWireMode, ...] = ("ollama", "decisions")


class DecisionModelService:
    """Read and write custom decision model configuration."""

    @classmethod
    def get_settings(cls) -> dict[str, Any]:
        """Return current decision model configuration."""
        cfg = cls._load_decision_config()
        if cfg is None:
            return {
                "configured": False,
                "enabled": False,
                "wire": "decisions",
                "url": None,
                "model": "",
                "has_api_key": False,
                "api_key_masked": "",
                "temperature": None,
            }

        has_key = bool(cfg.api_key)
        wire: DecisionWireMode = cfg.wire if cfg.wire in VALID_WIRES else "decisions"
        return {
            "configured": True,
            "enabled": bool(cfg.enabled),
            "wire": wire,
            "url": cfg.url,
            "model": cfg.model,
            "has_api_key": has_key,
            "api_key_masked": _mask_api_key(cfg.api_key) if has_key else "",
            "temperature": cfg.temperature,
        }

    @classmethod
    def update_settings(
        cls,
        *,
        enabled: bool = True,
        wire: str = "decisions",
        url: str | None = None,
        model: str = "",
        api_key: str | None = None,
        clear_api_key: bool = False,
        temperature: float | None = None,
    ) -> dict[str, Any]:
        """Validate and persist custom decision model configuration to ~/.frago/config.json."""
        if wire not in VALID_WIRES:
            raise ValueError(
                f"Unsupported decision model wire mode {wire!r}; expected one of {VALID_WIRES}"
            )

        clean_url = url.strip() if isinstance(url, str) else None
        clean_url = clean_url or None
        clean_model = model.strip() if isinstance(model, str) else ""

        if not clean_url:
            raise ValueError("Endpoint URL is required")
        if not clean_model:
            raise ValueError("Model name is required")

        if temperature is not None and temperature <= 0:
            raise ValueError("Temperature must be greater than 0")

        config = load_config() or Config()
        existing = config.decision_model or cls._load_decision_config()

        if clear_api_key:
            resolved_key = ""
        elif api_key is not None and api_key.strip():
            resolved_key = api_key.strip()
        elif existing is not None:
            resolved_key = existing.api_key
        else:
            resolved_key = ""

        config.decision_model = DecisionModelConfig(
            enabled=bool(enabled),
            wire=wire,  # type: ignore[arg-type]
            url=clean_url,
            model=clean_model,
            api_key=resolved_key,
            temperature=temperature,
        )
        save_config(config)
        cls._sync_profile_decision_fields(config.decision_model)
        return cls.get_settings()

    @classmethod
    def reset_settings(cls) -> dict[str, Any]:
        """Remove decision model configuration from ~/.frago/config.json."""
        config = load_config()
        if config is not None and config.decision_model is not None:
            config.decision_model = None
            save_config(config)
        cls._sync_profile_decision_fields(None)
        return cls.get_settings()

    @classmethod
    def _load_decision_config(cls) -> DecisionModelConfig | None:
        """Read config.decision_model, falling back to legacy profile fields if present."""
        try:
            config = load_config()
            if config is not None and config.decision_model is not None:
                return config.decision_model
        except Exception as exc:
            logger.warning("Failed to read decision_model from config.json: %s", exc)

        try:
            store = load_profiles()
            for profile in store.profiles:
                if profile.decision_url and profile.decision_model:
                    wire: DecisionWireMode = (
                        "ollama"
                        if ":11434" in profile.decision_url
                        and not profile.decision_url.rstrip("/").endswith("/systemone")
                        and not profile.decision_url.rstrip("/").endswith("/decisions")
                        else "decisions"
                    )
                    return DecisionModelConfig(
                        enabled=True,
                        wire=wire,
                        url=profile.decision_url,
                        model=profile.decision_model,
                        api_key=profile.decision_api_key or "",
                    )
        except Exception as exc:
            logger.debug("Failed to inspect profiles.json for decision fields: %s", exc)

        return None

    @classmethod
    def _sync_profile_decision_fields(
        cls, decision_cfg: DecisionModelConfig | None
    ) -> None:
        """Keep profiles.json decision_* fields aligned for frago-core compatibility."""
        try:
            store = load_profiles()
            if not store.profiles:
                return

            target_id = store.lightagent_profile_id or store.active_profile_id
            target = next(
                (p for p in store.profiles if p.id == target_id),
                store.profiles[0],
            )

            changed = False
            if (
                decision_cfg is not None
                and decision_cfg.enabled
                and decision_cfg.url
                and decision_cfg.model
            ):
                new_key = decision_cfg.api_key or None
                if (
                    target.decision_url != decision_cfg.url
                    or target.decision_model != decision_cfg.model
                    or target.decision_api_key != new_key
                ):
                    target.decision_url = decision_cfg.url
                    target.decision_model = decision_cfg.model
                    target.decision_api_key = new_key
                    changed = True
            else:
                for p in store.profiles:
                    if (
                        p.decision_url is not None
                        or p.decision_model is not None
                        or p.decision_api_key is not None
                    ):
                        p.decision_url = None
                        p.decision_model = None
                        p.decision_api_key = None
                        changed = True

            if changed:
                save_profiles(store)
        except Exception as exc:
            logger.warning("Failed to sync decision fields to profiles.json: %s", exc)
