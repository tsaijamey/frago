/**
 * frago-core bridge for opencode.
 *
 * Feeds opencode's plugin events into the same `frago-core --engine` entry
 * that Claude Code drives, so both runtimes surface identical knowledge
 * injections from the same `~/.frago/hook-rules.json`.
 *
 * The binary is runtime-agnostic: it reads a Claude Code shaped hook event
 * on stdin and answers with `{hookSpecificOutput:{additionalContext}}`.
 * Nothing here needs to change when routing rules change.
 *
 * Event mapping (opencode -> Claude Code):
 *   chat.message (first of a session) -> SessionStart, then UserPromptSubmit
 *   chat.message (subsequent)         -> UserPromptSubmit
 *   tool.execute.before               -> PreToolUse
 *
 * PreToolUse is the one place the two runtimes differ. Claude Code lets a
 * PreToolUse hook return context that reaches the model before the tool
 * runs; opencode's `tool.execute.before` can only rewrite arguments. So the
 * context is held and prepended to that same call's result in
 * `tool.execute.after`. The model still sees it attached to the tool it
 * belongs to, one step later than under Claude Code.
 *
 * That same gap used to void denials outright. Claude Code refuses the call
 * on a `permissionDecision: deny`; opencode has no equivalent, so a rule that
 * blocks an install still watched it run and only complained afterwards —
 * with the software already on the machine. Rewriting is the lever that does
 * exist: a denied command is swapped for one that reports the refusal and
 * exits non-zero, so the original never runs. Verified against opencode
 * 1.18.5. Denials of tool calls that carry no command remain unenforceable.
 *
 * Deployed by frago.init.opencode_plugin. Do not edit in place — edit the
 * packaged copy under src/frago/resources/opencode/.
 */

import { spawn } from "node:child_process"
import { readFileSync } from "node:fs"
import os from "node:os"
import path from "node:path"
import { fileURLToPath } from "node:url"

const HOOK_TIMEOUT_MS = 10_000

/**
 * Paired markers wrapping every injection this bridge appends to a message.
 * Read from disk rather than inlined because frago's archive layer strips the
 * wrapped spans back out of user text — the two sides must agree exactly, so
 * they share one file (injection-markers.json).
 */
const MARKERS = loadInjectionMarkers()

function loadInjectionMarkers() {
  try {
    const data = JSON.parse(readResource("injection-markers.json"))
    if (typeof data.begin === "string" && typeof data.end === "string") return data
  } catch {}
  // Unreadable markers mean an injection could not be told apart from the
  // user's own words afterwards. Dropping the injection is the lesser harm.
  return null
}

/**
 * opencode names its tools in lowercase and its arguments in camelCase;
 * Claude Code uses PascalCase tool names and snake_case arguments. The
 * routing rules in ~/.frago/hook-rules.json are written against the Claude
 * Code shape, so events are translated here rather than teaching the rules
 * engine a second vocabulary.
 *
 * The table is shared with `frago hook-rules add`, which normalises rules
 * written from an opencode session into the same vocabulary. It is read from
 * disk rather than inlined so the two never drift apart.
 */
const TOOL_NAMES = loadToolNameMap()

function readResource(filename) {
  const here = path.dirname(fileURLToPath(import.meta.url))
  return readFileSync(path.join(here, filename), "utf8")
}

function loadToolNameMap() {
  try {
    return JSON.parse(readResource("tool-name-map.json")).map
  } catch {
    // Degrade to no mapping rather than taking the session down: PascalCase
    // fallback below still covers the common single-word tools.
    return {}
  }
}

function toClaudeToolName(tool) {
  const mapped = TOOL_NAMES[tool.toLowerCase()]
  if (mapped) return mapped
  // Unknown tool (custom or newly added upstream): PascalCase it so
  // name-based rules still have a chance to match.
  return tool.charAt(0).toUpperCase() + tool.slice(1)
}

function toClaudeToolInput(args) {
  const input = { ...(args ?? {}) }
  // Path rules match on `file_path`; opencode supplies `filePath`.
  if (input.file_path === undefined && typeof input.filePath === "string") {
    input.file_path = input.filePath
  }
  return input
}

function hookBinaryPath() {
  const name = process.platform === "win32" ? "frago-core.exe" : "frago-core"
  return path.join(os.homedir(), ".frago", "bin", name)
}

/**
 * Run the frago-core binary against one event payload.
 *
 * --engine selects the hook entry: the default (no-arg) entry of frago-core is
 * the agentic kernel, and invoking it bare would launch that instead of
 * routing this event.
 *
 * Resolves to the engine's `hookSpecificOutput` object, or null. Callers pick
 * the field they need: injections read `additionalContext`, the PreToolUse
 * path also reads `permissionDecision`.
 *
 * Every failure mode (missing binary, non-zero exit, unparseable stdout,
 * timeout) resolves to null. A knowledge-injection layer must never be able
 * to break the agent it is advising.
 */
function runHook(payload) {
  return new Promise((resolve) => {
    let child
    try {
      child = spawn(hookBinaryPath(), ["--engine"], { stdio: ["pipe", "pipe", "ignore"] })
    } catch {
      return resolve(null)
    }

    let stdout = ""
    let settled = false
    const finish = (value) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      resolve(value)
    }

    const timer = setTimeout(() => {
      try {
        child.kill()
      } catch {}
      finish(null)
    }, HOOK_TIMEOUT_MS)

    child.on("error", () => finish(null))
    child.stdout.on("data", (chunk) => {
      stdout += chunk
    })
    child.on("close", () => {
      try {
        const out = JSON.parse(stdout).hookSpecificOutput
        const hasContext = typeof out?.additionalContext === "string" && out.additionalContext.trim()
        const hasDecision = typeof out?.permissionDecision === "string"
        finish(hasContext || hasDecision ? out : null)
      } catch {
        finish(null)
      }
    })

    try {
      child.stdin.write(JSON.stringify(payload))
      child.stdin.end()
    } catch {
      finish(null)
    }
  })
}

/**
 * Wrap injected context so it reads as system-supplied, not user-authored,
 * and so the archive layer can strip it back out. Null when the markers are
 * unavailable — the caller then injects nothing at all.
 */
function frame(context) {
  if (!MARKERS) return null
  // The preamble states whose words these are. Without it an injection reads
  // as something the user typed, and gets weighed as chatter rather than as a
  // rule. Absent or blank in the data file, the span still ships — a missing
  // sentence is no reason to withhold the knowledge itself.
  const preamble =
    typeof MARKERS.preamble === "string" && MARKERS.preamble.trim()
      ? `${MARKERS.preamble.trim()}\n\n`
      : ""
  return `${MARKERS.begin}\n${preamble}${context}\n${MARKERS.end}`
}

/** The engine's injected text, or null when this response carries none. */
function injectionOf(result) {
  const ctx = result?.additionalContext
  return typeof ctx === "string" && ctx.trim() ? ctx : null
}

/** Wrap an arbitrary string as one POSIX single-quoted shell word. */
function shellQuote(value) {
  return `'${String(value).replace(/'/g, `'\\''`)}'`
}

/**
 * Build the command that replaces a denied one.
 *
 * opencode never asks a plugin whether a tool call should run — it only offers
 * a chance to rewrite the arguments before it does. Swapping the command for
 * one that merely reports the refusal is therefore the only way to stop a
 * denied command here, and the original never executes.
 *
 * Measured against deepseek-v4-flash, two details are not optional:
 *
 * - A non-zero exit does not read as "refused" to the model. It saw only the
 *   stderr text and treated it as ordinary output. The reason has to say what
 *   happened in full; the exit status carries none of that meaning.
 * - It retried the identical command four times before giving up, and on one
 *   of those turns it copied the replacement command and ran that instead.
 *   Hence the explicit no-retry line, and hence the replacement itself must
 *   stay harmless when executed on its own.
 */
function denialCommand(reason, original) {
  const body = [
    "【本次调用已被 frago 规则拦截，命令未执行】",
    "",
    reason,
    "",
    `被拦下的原命令：${original}`,
    "",
    "重试同一条命令不会有不同结果，NEVER 重试；NEVER 换一种写法或另一个工具绕过。",
  ].join("\n")
  return `printf '%s\\n' ${shellQuote(body)} >&2; exit 1`
}

export const FragoHookPlugin = async ({ directory }) => {
  // Sessions whose SessionStart has already fired. opencode has no
  // session-start hook, so it is derived from the first chat.message.
  const started = new Set()
  // callID -> context awaiting attachment to that call's result.
  const pending = new Map()

  return {
    "chat.message": async (input, output) => {
      const sessionID = input.sessionID
      if (!sessionID) return

      const prompt = (output.parts || [])
        .filter((p) => p.type === "text" && typeof p.text === "string")
        .map((p) => p.text)
        .join("\n")

      const events = []
      if (!started.has(sessionID)) {
        started.add(sessionID)
        events.push({
          session_id: sessionID,
          hook_event_name: "SessionStart",
          source: "startup",
          cwd: directory,
        })
      }
      events.push({
        session_id: sessionID,
        hook_event_name: "UserPromptSubmit",
        prompt,
        cwd: directory,
      })

      const contexts = (await Promise.all(events.map(runHook))).map(injectionOf).filter(Boolean)
      if (!contexts.length) return

      // opencode validates message parts against a schema on the way in, so
      // synthesising a new part is fragile across versions. Editing an
      // existing text part in place is the stable path.
      //
      // The span goes in front of what the user wrote, not after it. Order
      // decides what the model has in hand while it reads the request: rules
      // first means it interprets the task already knowing the boundaries;
      // rules last means it has formed an approach and must then talk itself
      // out of it. The failure this addresses is exactly that shape — a build
      // fails, the model concludes a tool is missing, and by the time the
      // rule saying "install nothing" arrives it is already reaching for the
      // package manager.
      const framed = frame(contexts.join("\n\n"))
      if (!framed) return

      const texts = (output.parts || []).filter((p) => p.type === "text")
      const target = texts[0]
      if (!target) return
      target.text = `${framed}\n\n${target.text}`
    },

    "tool.execute.before": async (input, output) => {
      if (!input.sessionID || !input.tool) return
      const result = await runHook({
        session_id: input.sessionID,
        hook_event_name: "PreToolUse",
        tool_name: toClaudeToolName(input.tool),
        tool_input: toClaudeToolInput(output.args),
        cwd: directory,
      })
      if (!result) return

      // A denial only takes effect on tool calls that carry a command to
      // swap. Rules that deny anything else (a write, a fetch) still cannot
      // be enforced here; those fall through to the injection path below, so
      // the model at least reads the reason one step later.
      const original = output?.args?.command
      if (result.permissionDecision === "deny" && typeof original === "string") {
        const reason =
          typeof result.permissionDecisionReason === "string" && result.permissionDecisionReason.trim()
            ? result.permissionDecisionReason
            : "该命令被规则拒绝执行。"
        output.args.command = denialCommand(reason, original)
        return
      }

      const context = injectionOf(result)
      if (context) pending.set(input.callID, context)
    },

    "tool.execute.after": async (input, output) => {
      const context = pending.get(input.callID)
      if (!context) return
      pending.delete(input.callID)
      const framed = frame(context)
      if (!framed) return
      output.output = `${framed}\n\n${output.output ?? ""}`
    },
  }
}
