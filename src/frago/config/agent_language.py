"""The language agents are asked to reply in.

Set under WebUI → Settings → Appearance as ``agent_language`` in
~/.frago/gui_config.json. Left empty it follows the interface language there
(``language``: en → English, zh → Simplified Chinese), so a user who never
touches it gets agents speaking the same language as the WebUI they read.

A SessionStart hook rule runs ``frago config agent-language --for-hook`` and
injects what it prints, which is why each instruction is written in its own
language: the request itself already reads the way the agent is asked to reply.
"""


# code → (native name, instruction written in that language)
AGENT_LANGUAGES: dict[str, tuple[str, str]] = {
    "en": (
        "English",
        "You MUST reply to the user in English. Code, commands, file paths and "
        "quoted original text stay as they are.",
    ),
    "zh-Hans": (
        "简体中文",
        "必须用简体中文回复用户。代码、命令、文件路径和引用的原文保持原样。",
    ),
    "zh-Hant": (
        "繁體中文",
        "必須用繁體中文回覆使用者。程式碼、指令、檔案路徑與引用的原文保持原樣。",
    ),
    "de": (
        "Deutsch",
        "Du MUSST dem Benutzer auf Deutsch antworten. Code, Befehle, "
        "Dateipfade und zitierter Originaltext bleiben unverändert.",
    ),
    "fr": (
        "Français",
        "Tu DOIS répondre à l'utilisateur en français. Le code, les "
        "commandes, les chemins de fichiers et les citations restent tels quels.",
    ),
    "es": (
        "Español",
        "DEBES responder al usuario en español. El código, los comandos, "
        "las rutas de archivos y el texto citado se mantienen tal cual.",
    ),
    "ja": (
        "日本語",
        "ユーザーへの返答は必ず日本語で行うこと。コード、コマンド、ファイルパス、"
        "引用した原文はそのまま残す。",
    ),
}

# Interface language (Appearance) → agent language used when none is chosen.
_FOLLOW_INTERFACE = {"en": "en", "zh": "zh-Hans"}


def resolve_agent_language(
    agent_language: str | None, interface_language: str | None
) -> str:
    """The agent language in effect: the chosen one, else the interface's."""
    if agent_language in AGENT_LANGUAGES:
        return agent_language
    return _FOLLOW_INTERFACE.get(interface_language or "en", "en")


def hook_text(code: str) -> str:
    """What the SessionStart hook injects for ``code``."""
    name, instruction = AGENT_LANGUAGES[code]
    return f"---\n【agent language: {name}】\n{instruction}\n---"
