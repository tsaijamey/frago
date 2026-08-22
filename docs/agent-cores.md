# Agent Cores Compared: Claude Code / codex / opencode

frago calls a cli-agent a **core**: the thing that holds the session, edits the code,
and fires the hooks. Three are supported today. This page sets out what they share,
where they genuinely differ, and how the same task is spelled in each.

## Versions this page is pinned to

| Core | Version | Where the binary comes from |
|---|---|---|
| Claude Code | 2.1.235 | Official native installer, `~/.local/share/claude/versions/<version>` |
| codex (OpenAI Codex CLI) | 0.147.0 | Homebrew cask, `/opt/homebrew/Caskroom/codex/<version>/bin/codex` |
| opencode | 1.18.15 | Native binary |

All three move fast. **Everything below was checked against those versions on a real
machine**, not paraphrased from docs. Re-verify before trusting it on another version:
each of these has changed the meaning of an existing switch at least once in the past
six months (for instance codex 0.147 dropped `wire_api = "chat"`, so any third-party
provider guide written in 2025 now fails to load the config at all).

---

## In one line each

- **Claude Code** — Anthropic's official CLI. The thickest ecosystem (skills, plugins,
  subagents, an SDK, cloud review), three model tiers, and permissions enforced by
  policy rather than by a sandbox.
- **codex** — OpenAI's official CLI. The only one of the three that ships a **real
  operating-system sandbox**; one `config.toml` serves the CLI, the desktop app and the
  VS Code extension alike; its hook protocol is deliberately shaped like Claude Code's.
- **opencode** — Community, open source. **A different extension model entirely**:
  plugins are in-process JavaScript and reach far deeper than the other two allow. Ships
  a headless server, a web UI and ACP, which makes it the easiest of the three to embed
  in another program.

---

## Equivalent capabilities

All three have these; only the spelling differs.

| Capability | Claude Code | codex | opencode |
|---|---|---|---|
| Interactive TUI | `claude` | `codex` | `opencode` |
| One-shot, non-interactive | `claude -p "<prompt>"` | `codex exec "<prompt>"` | `opencode run "<prompt>"` |
| Resume a session | `claude --resume <uuid>` | `codex resume <uuid>` | `opencode -s <id>` |
| Resume the latest | `claude --continue` | `codex resume --last` | `opencode -c` |
| Fork a session | `--fork-session` | `codex fork` | `--fork` |
| Pick a model | `--model` | `-m` / `-c model=…` | `-m <provider>/<model>` |
| MCP client | `claude mcp` | `codex mcp` | `opencode mcp` |
| Acts as an MCP server | yes | `codex mcp-server` | yes |
| Subagents | `--agents` / `claude agents` | `spawn_agent` tool + subagent events | `opencode agent` |
| Self-diagnosis | `claude doctor` | `codex doctor` | `opencode debug` |
| Import another agent's config | `claude import` | external-agent migration flow | — |
| Self-update | `claude update` | `codex update` | `opencode upgrade` |
| Project instruction file | `CLAUDE.md` | `AGENTS.md` | `AGENTS.md` (walked up from cwd to the project root; `instructions` in config adds more) |

**Two of the three share an identical hook event set.** Claude Code 2.1.235 and codex
0.147 both implement `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `SessionStart`,
`SessionEnd`, `Stop`, `SubagentStart`, `SubagentStop`, `PreCompact`, `PostCompact` and
`PermissionRequest`; only Claude Code also has `Notification`. Their stdin payload fields
(`session_id`, `cwd`, `hook_event_name`, `prompt`, `tool_name`, `tool_input`,
`transcript_path`, `permission_mode`) and their stdout vocabulary
(`hookSpecificOutput.additionalContext`, `permissionDecision`, `updatedInput`,
`decision`, `systemMessage`, `continue`, `stopReason`, `suppressOutput`) match word for
word — codex's own schema even carries the note "Claude requires `reason` when
`decision` is `block`". **This is deliberate compatibility, not coincidence**, so a
command hook written for Claude Code transfers to codex essentially unchanged.

---

## Capabilities unique to one core

### Only codex

- **A real OS-level sandbox.** `codex sandbox <command>` runs model-generated commands
  under seatbelt on macOS and landlock/bwrap on Linux. Sandbox level (`read-only`,
  `workspace-write`, `danger-full-access`) is orthogonal to approval policy
  (`untrusted`, `on-request`, `never`). The other two enforce permissions **as policy**;
  the process itself is not confined.
- **One config for three front-ends.** `~/.codex/config.toml` serves the CLI, the
  ChatGPT desktop app and the VS Code extension. The cost: the latter two inherit a
  launchd environment and **cannot see variables exported from `~/.zshrc`**, so a key
  must either live in the config or be named by `env_key` pointing at a variable they
  actually have.
- **Whole config overridable from the command line.** `-c <dotted.path>=<TOML value>`
  can define an entire provider at launch with no file edited (verified: a clean home
  containing only `model = "gpt-5.6"` and zero provider definitions ran against DeepSeek
  purely through `-c`).
- **A hook trust gate.** Non-managed command hooks **do not run** until a human has
  reviewed and trusted them; trust is recorded against a hash of the hook definition
  under `hooks.state` in `config.toml`, and editing a hook re-arms the gate. Automation
  bypasses it with `--dangerously-bypass-hook-trust`. Neither of the other two has this
  gate — writing the config is enough.
- **Hook output spills to disk.** Model-visible hook output is capped around 2500 tokens;
  beyond that codex writes the full text to
  `<temp>/hook_outputs/<session>/<uuid>.txt` and shows the model a head-and-tail preview
  plus the path. Each handler can raise its own threshold with `additionalContextLimit`.
- **Background hooks.** `"async": true` runs a handler in the background without holding
  up the operation, up to eight concurrently per session.
- **Enterprise-managed hooks.** `[hooks]` in `requirements.toml` is administrator-pushed,
  trusted by policy and not disableable by the user;
  `allow_managed_hooks_only = true` suppresses every other hook source.
- **Plugin marketplace** (`codex plugin marketplace`), **goals**, **memories**,
  **remote control**, and **cloud tasks** (`codex cloud`).

### Only opencode

- **In-process plugins that reach much further.** A plugin is an ES module under
  `~/.config/opencode/plugin/` exporting hook functions that take effect by mutating an
  `output` object. The full surface, taken from the `@opencode-ai/plugin` type
  definitions:

  | Hook | What it can change |
  |---|---|
  | `chat.message` | Observe an incoming user message |
  | `chat.params` | temperature / topP / topK / maxOutputTokens sent to the model |
  | `chat.headers` | HTTP headers sent to the provider |
  | `permission.ask` | Settle a permission prompt as `allow` / `deny` / `ask` |
  | `command.execute.before` | What a slash command expands into |
  | `tool.execute.before` | **Tool arguments** (arguments only — cannot inject context, cannot deny outright) |
  | `tool.execute.after` | A tool's title, output and metadata |
  | `shell.env` | Environment variables the shell tool sees |
  | `tool` | **Define entirely new tools** |
  | `auth` / `provider` | Attach custom auth methods and providers |
  | `experimental.chat.messages.transform` | Rewrite the whole message history |
  | `experimental.chat.system.transform` | Rewrite the system prompt |
  | `session.compacting` | Intervene in context compaction |
  | `event` | Subscribe to the generic event stream |

- **Headless server and web UI.** `opencode serve` runs a headless HTTP server,
  `opencode web` also opens a web interface, and `opencode attach <url>` joins a running
  instance.
- **ACP (Agent Client Protocol) server**: `opencode acp`, for editor-class clients.
- **Session import/export**: `opencode export <session>` / `opencode import <file|url>` —
  a whole session can be moved elsewhere.
- **Usage statistics**: `opencode stats`.
- **`--pure`**: one run with no external plugins loaded at all.
- **GitHub agent** and `opencode pr <number>`, which checks out a PR branch straight
  into a session.

### Only Claude Code

- **Three model tiers**: primary / mid (sonnet) / fast (haiku), each configurable.
  codex has a single `model` slot (plus `review_model` for `codex review`); opencode has
  two (`model` and `small_model`).
- **The `Notification` hook event** (absent from the other two).
- **`--bare`**: skip hooks, LSP, plugin sync, auto-memory and `CLAUDE.md` discovery for
  one run. Invaluable when isolating "is an extension breaking this?".
- **Background agents**: `--bg` starts a session and returns immediately; manage them
  afterwards with `claude agents`.
- **`--output-format stream-json`**: turns a non-interactive run into a structured event
  stream — the most program-consumable output of the three.
- **Enterprise gateway**: `claude gateway` (auth and telemetry).
- **Cloud multi-agent review**: `claude ultrareview`.
- **Skills and plugin tooling**: `claude plugin`, `/skill-doctor`, `plugin eval`.
  (codex has skills and plugins too; the ecosystems and tooling maturity differ.)

---

## Usage differences: one task, three spellings

### 1. Run one unattended turn

```bash
claude -p "run the tests and report failures" --dangerously-skip-permissions
codex exec "run the tests and report failures" --dangerously-bypass-approvals-and-sandbox
opencode run "run the tests and report failures"
```

Notes:
- Claude Code's `-p` skips the one-time **directory trust** prompt on its own; the
  interactive TUI does not. Driving it through tmux therefore requires pre-writing trust
  into `projects[<path>].hasTrustDialogAccepted` in `~/.claude.json`.
- codex has the same gate, recorded as `[projects."<path>"] trust_level` in
  `config.toml`, and it **only honours persisted config** — overriding that key with
  `-c` on the command line was measured to have no effect.
- opencode has no equivalent launch switch. Permissions can only be pre-cleared through
  session-level config (`permission` inside `OPENCODE_CONFIG_CONTENT`), and without that
  an unattended run stalls on the first file write.

### 2. Point it at an endpoint and a model

The three mechanisms do not transfer. This is where third-party providers go wrong.

| | Claude Code | codex | opencode |
|---|---|---|---|
| Main channel | env `ANTHROPIC_BASE_URL` / `ANTHROPIC_MODEL` / `ANTHROPIC_API_KEY` | `[model_providers.<name>]` in `~/.codex/config.toml`, or `-c` at launch | `opencode.json`, or a whole JSON config through `OPENCODE_CONFIG_CONTENT` |
| Wire protocol | Anthropic Messages | **`responses` only** (`chat` removed in 0.147) | Whatever the provider's npm package speaks (`@ai-sdk/*`) |
| Where the key goes | Environment variable | `env_key` names an env var, or `experimental_bearer_token` in plain text in the config | `apiKey` in config, or credentials stored by `opencode providers` |
| URL completion | Appends `/v1/messages` itself, so the stored address carries **no** version segment | Full base_url, OpenAI convention | `@ai-sdk/anthropic` appends only `/messages`, so the address **must** carry `/v1` |

**The same vendor is usually a different URL for each core.** DeepSeek, for example, is
`https://api.deepseek.com/anthropic` for Claude Code and `https://api.deepseek.com/` for
codex. No reliable rule converts one into the other (DeepSeek drops `/anthropic`,
OpenRouter adds `/v1`), so "one profile feeds all three" requires storing a separate
address per core — never a string transformation.

### 3. Permissions and approvals

| | Claude Code | codex | opencode |
|---|---|---|---|
| Model | Permission modes: `default` / `acceptEdits` / `plan` / `dontAsk` / `bypassPermissions` | Sandbox level × approval policy, two orthogonal axes | **The most granular of the three**: `{action, resource, effect}` rules — actions include `read`, `edit`, `bash`, `webfetch`, `websearch`, `grep`, `glob`, `external_directory`, `question`, `plan_enter`; resources are globs; effects are `allow` / `ask` / `deny`; configurable per agent |
| Blanket switch | `--dangerously-skip-permissions` | `--dangerously-bypass-approvals-and-sandbox` | none; config only |
| Fine grain | `--allowedTools "Bash(git *) Edit"` | `matcher` regex + `PermissionRequest` hook | `permission.ask` plugin hook |
| Actually sandboxed | no | **yes** (seatbelt / landlock) | no |

### 4. Hooks: external command vs in-process

**Claude Code and codex: an external command and a JSON pipe.**

```jsonc
// Claude Code: the hooks section of ~/.claude/settings.json
// codex:       ~/.codex/hooks.json (inline [hooks] tables in config.toml also work)
{
  "hooks": {
    "PreToolUse": [
      { "matcher": "Bash",
        "hooks": [{ "type": "command", "command": "/path/to/my-hook", "timeout": 20 }] }
    ]
  }
}
```

The hook process reads one JSON object on stdin and writes one on stdout. Any language,
process-isolated — but it can only do what the event contract defines.

**opencode: an in-process JS module.**

```js
export const MyPlugin = async ({ client, $ }) => ({
  "tool.execute.before": async (input, output) => { output.args.cmd = "…" },
  "permission.ask":      async (input, output) => { output.status = "deny" },
})
```

Far more reach (see the table above), at the cost of having to write JavaScript that
runs inside opencode's process, where a throwing plugin affects its host.

**One concrete capability gap.** `PreToolUse` in Claude Code and codex can put context in
front of the model **before** a tool runs, and can refuse the call outright. opencode's
`tool.execute.before` can only rewrite arguments. frago's bridge plugin works around
both: injected context is held and appended to that same call's result in
`tool.execute.after` (the model still sees it, one step later), and a call to be refused
is **rewritten** into a command that reports the refusal and exits non-zero, so the
original never runs. The `permission.ask` route only fires when a permission is actually
requested, and unattended runs have usually pre-cleared permissions, so it cannot cover
this case.

---

## Session records: where they live, what shape they take

| | Location | Shape | Incrementally tailable |
|---|---|---|---|
| Claude Code | `~/.claude/projects/<encoded-path>/<uuid>.jsonl` | One record per line, append-only | Yes (byte offset) |
| codex | `~/.codex/sessions/<YYYY>/<MM>/<DD>/rollout-<local-time>-<uuid>.jsonl` | One record per line, append-only | Yes (same) |
| opencode | `~/.local/share/opencode/opencode.db` (SQLite) | Relational: `session` / `message` / `part` | Yes, but there is no "file plus offset" — it takes a part cursor |

Session id shapes: Claude Code uses a UUID, codex uses a **UUIDv7 (also UUID-shaped)**,
opencode prefixes with `ses_`. **The first two therefore share an id space**, so
deciding which core an id belongs to cannot be done from its shape alone — it takes a
look on disk.

The authoritative "is this turn finished?" signal:

- Claude Code — the transcript record carrying a terminal `stop_reason`
- codex — the `task_complete` event in the rollout (with `turn_id`,
  `last_agent_message`, and `error` when the turn failed)
- opencode — an assistant message with a completion time whose finish marker is not
  `tool-calls`

For all three, **do not decide completion by reading the screen**. Screen reading
misfires on the idle frames between tool calls; all three of these signals are
structured.

---

## What frago supports for each

| Capability | Claude Code | codex | opencode |
|---|---|---|---|
| Hook routing (knowledge injection + rules) | ✅ native command hooks | ✅ native command hooks, same binary | ✅ via a JS bridge plugin |
| Driven by `frago agent` | ✅ | ✅ | ✅ |
| Session workbench: list / records / search | ✅ | ✅ | ✅ |
| Session archival | ✅ | ✅ | ✅ |
| Sending from the workbench composer | ✅ | ❌ the channel is always claude | ❌ same |
| `--use-profile` model selection (that one session only) | ✅ | ❌ see below | ✅ |
| Activating a profile (written into the CLI's own config, so hand-started sessions follow it too) | ✅ | ❌ same reason | ✅ |

Two known gaps, both recorded as todos:

1. **The workbench can only send into Claude Code sessions**
   (`20260820-webui-composer-send-to-all`). The send endpoint is hard-wired to the
   claude channel; the other two cores' session ids do not exist in claude's records, so
   a message would silently open a brand-new session instead. The composer is therefore
   disabled for them, with the reason stated.
2. **Endpoint and model selection does not cover all three cores**
   (`20260820-per-harness-endpoint-and-model`). `frago agent`'s `--model`, `--endpoint`,
   `--api-key` and `--use-ccr` write `ANTHROPIC_*` unconditionally, none of which codex
   reads. `--use-profile` says out loud that it had no effect on codex; the other three
   switches are still silently ignored.

One thing about activation itself is worth spelling out: **activation has a scope, and
you pick it.** It used to write Claude Code and nothing else, without saying so, which
left the other two cores running whatever they were configured with while the person
believed they had switched models. Activating now asks which CLIs to write to; the ones
that cannot take a frago profile (codex) are still listed, disabled, with the reason
next to them. Unchecking a CLI hands it back to what it looked like before frago took it
over — opencode's model selection is copied back rather than left blank.

One further limit is a property of codex rather than a frago defect: **frago
`PreToolUse` rules keyed on `Edit` / `Write` or on a file path do not fire under codex.**
codex edits files through `apply_patch`, whose payload carries no `file_path` field.
Rules keyed on the shell command — the majority of the built-in set — work normally.

---

## Choosing between them

- **Thickest ecosystem, most mature tooling, three model tiers** → Claude Code.
- **A real sandbox, one config governing the CLI and two IDE front-ends, or you are
  already inside the ChatGPT ecosystem** → codex.
- **Embedding an agent in your own program (headless server / ACP / web), or needing to
  rewrite prompts, parameters and tool behaviour deeply** → opencode.

Inside frago the three can be mixed: the session workbench merges all three into one
list, and routing rules are written once and shared (each bridge absorbs its own
vocabulary differences). The default core is `agent_core` in `~/.frago/config.json`;
override it per run with `frago agent --agent-type <core>`.

---

## Related

- [Concepts](concepts.md) — frago's four pillars and the session record model
- [User Guide](user-guide.md) — everyday commands
- [Developer](developer.md) — the driver contract and how to extend it
