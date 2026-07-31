/**
 * frago-hook bridge for opencode.
 *
 * Feeds opencode's plugin events into the same `frago-hook` binary that
 * Claude Code drives, so both runtimes surface identical knowledge
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
  const name = process.platform === "win32" ? "frago-hook.exe" : "frago-hook"
  return path.join(os.homedir(), ".frago", "bin", name)
}

/**
 * Run the frago-hook binary against one event payload.
 *
 * Every failure mode (missing binary, non-zero exit, unparseable stdout,
 * timeout) resolves to null. A knowledge-injection layer must never be able
 * to break the agent it is advising.
 */
function runHook(payload) {
  return new Promise((resolve) => {
    let child
    try {
      child = spawn(hookBinaryPath(), [], { stdio: ["pipe", "pipe", "ignore"] })
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
        const ctx = JSON.parse(stdout).hookSpecificOutput?.additionalContext
        finish(typeof ctx === "string" && ctx.trim() ? ctx : null)
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
  return `${MARKERS.begin}\n${context}\n${MARKERS.end}`
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

      const contexts = (await Promise.all(events.map(runHook))).filter(Boolean)
      if (!contexts.length) return

      // opencode validates message parts against a schema on the way in, so
      // synthesising a new part is fragile across versions. Appending to the
      // trailing text part is the stable path and lands in the same place
      // Claude Code puts additionalContext: attached to the user's turn.
      const framed = frame(contexts.join("\n\n"))
      if (!framed) return

      const texts = (output.parts || []).filter((p) => p.type === "text")
      const target = texts[texts.length - 1]
      if (!target) return
      target.text = `${target.text}\n\n${framed}`
    },

    "tool.execute.before": async (input, output) => {
      if (!input.sessionID || !input.tool) return
      const context = await runHook({
        session_id: input.sessionID,
        hook_event_name: "PreToolUse",
        tool_name: toClaudeToolName(input.tool),
        tool_input: toClaudeToolInput(output.args),
        cwd: directory,
      })
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
