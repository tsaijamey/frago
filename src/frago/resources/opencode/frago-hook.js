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
 * On top of the routing bridge, this plugin also reads images on behalf of
 * models that cannot see them — see the vision-context section further down.
 *
 * Deployed by frago.init.opencode_plugin. Do not edit in place — edit the
 * packaged copy under src/frago/resources/opencode/.
 */

import { spawn } from "node:child_process"
import { appendFileSync, existsSync, readFileSync, unlinkSync, writeFileSync } from "node:fs"
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

/**
 * Record why something was skipped, into the same log the Rust engine writes.
 *
 * Every failure path here degrades to silence on purpose — a knowledge layer
 * must not be able to break the session it advises. The cost is that a feature
 * which quietly stops working looks exactly like one that had nothing to say.
 * This is the seam where the difference is written down.
 */
function logError(msg) {
  try {
    appendFileSync(path.join(os.homedir(), ".frago", "hook-errors.log"), `[${Math.floor(Date.now() / 1000)}] bridge: ${msg}\n`)
  } catch {}
}

/**
 * Vision context: read images for models that cannot see them.
 *
 * A model without vision receives an attached screenshot as nothing at all —
 * deepseek answers "this model cannot read images" and the turn is wasted.
 * When one arrives, the image is handed to a multimodal model first and its
 * description is prepended to the message, so the blind model reads words
 * instead of missing a picture.
 *
 * Every knob lives in vision-context.json, including the gate deciding which
 * models this applies to. It is deliberately narrow: models that can already
 * see get nothing, because for them the call would be pure cost and pure
 * delay. And the delay is the whole design constraint — opencode holds the
 * message until this hook returns, so the user watches an idle prompt for as
 * long as the vision model takes. Measured on a 594x858 screenshot through
 * qwen/qwen3.7-flash: ~20s for a 500-token description, and the shared free
 * pool rate-limits often enough that retries are the norm, not the exception.
 * Hence the hard ceiling below — past it the description is abandoned and the
 * message goes out as the user wrote it, which is the correct failure: a slow
 * courtesy must never become a stuck session.
 */
const VISION = loadVisionConfig()

function loadVisionConfig() {
  try {
    const cfg = JSON.parse(readResource("vision-context.json"))
    if (cfg && cfg.enabled === true && typeof cfg.prompt === "string" && cfg.prompt.trim()) return cfg
  } catch {}
  // Missing or malformed config disables the feature. Guessing defaults here
  // would mean spending money on a model nobody configured.
  return null
}

/** Image attachments on this message, as data/http URLs the recipe accepts. */
function imageUrlsOf(parts) {
  return (parts || [])
    .filter(
      (p) => p?.type === "file" && typeof p.mime === "string" && p.mime.startsWith("image/") && typeof p.url === "string",
    )
    .map((p) => p.url)
}

/**
 * The model this message is headed for, as `providerID/modelID` lowercased.
 *
 * The same model reaches opencode under several provider prefixes
 * (opencode/deepseek-v4-flash-free, deepseek/deepseek-v4-pro,
 * openrouter/deepseek/…), so the gate matches the joined string rather than
 * either field alone.
 */
function modelKeyOf(input, output) {
  const model = input?.model ?? output?.message?.model
  if (!model) return null
  const provider = typeof model.providerID === "string" ? model.providerID : ""
  const id = typeof model.modelID === "string" ? model.modelID : ""
  if (!provider && !id) return null
  return `${provider}/${id}`.toLowerCase()
}

function visionApplies(modelKey) {
  if (!VISION || !modelKey) return false
  try {
    return new RegExp(VISION.model_gate ?? "", "i").test(modelKey)
  } catch {
    return false
  }
}

/**
 * Describe the images through the vision recipe.
 *
 * Params travel through a temp file rather than argv: a pasted screenshot is
 * ~160KB of base64 per image, and several of them on one command line would
 * run into the platform's argument limit.
 *
 * Resolves to the description text, or null on any failure — an unreadable
 * image must cost the user nothing but the wait already spent.
 */
function describeImages(urls) {
  const capped = urls.slice(0, VISION.max_images ?? 3)
  const paramsPath = path.join(os.tmpdir(), `frago-vision-${process.pid}-${Date.now()}.json`)
  try {
    writeFileSync(
      paramsPath,
      JSON.stringify({
        prompt: VISION.prompt,
        image_input: capped,
        model: VISION.model,
        max_tokens: VISION.max_tokens,
        retries: VISION.retries,
        // Reasoning models burn the whole output budget thinking and return an
        // empty description; this task needs none.
        reasoning_enabled: false,
      }),
    )
  } catch {
    return Promise.resolve(null)
  }

  return new Promise((resolve) => {
    let child
    const cleanup = () => {
      try {
        unlinkSync(paramsPath)
      } catch {}
    }
    try {
      child = spawn(fragoLauncher(), ["recipe", "run", VISION.recipe, "--params-file", paramsPath], {
        stdio: ["ignore", "pipe", "pipe"],
      })
    } catch (e) {
      logError(`vision spawn failed: ${e}`)
      cleanup()
      return resolve(null)
    }

    let stdout = ""
    let stderr = ""
    let settled = false
    const finish = (value) => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      cleanup()
      resolve(value)
    }
    const timer = setTimeout(() => {
      try {
        child.kill()
      } catch {}
      logError(`vision recipe timed out after ${VISION.timeout_ms ?? 45_000}ms`)
      finish(null)
    }, VISION.timeout_ms ?? 45_000)

    child.on("error", (e) => {
      logError(`vision recipe error: ${e}`)
      finish(null)
    })
    child.stdout.on("data", (chunk) => {
      stdout += chunk
    })
    child.stderr.on("data", (chunk) => {
      stderr += chunk
    })
    child.on("close", (code) => {
      const text = recipeText(stdout)
      if (!text || !text.trim()) {
        logError(`vision recipe produced no description (exit=${code}) ${stderr.slice(-400).replace(/\n/g, " ")}`)
        return finish(null)
      }
      finish(text.trim())
    })
  })
}

/** Pull `raw_text` out of the recipe's stdout, tolerating leading noise. */
function recipeText(stdout) {
  const attempt = (s) => {
    try {
      const data = JSON.parse(s)
      return data?.success === true && typeof data.raw_text === "string" ? data.raw_text : null
    } catch {
      return null
    }
  }
  const direct = attempt(stdout.trim())
  if (direct) return direct
  const start = stdout.indexOf("{")
  const end = stdout.lastIndexOf("}")
  return start >= 0 && end > start ? attempt(stdout.slice(start, end + 1)) : null
}

/**
 * The frago CLI.
 *
 * uv installs it at ~/.local/bin, which is on the PATH of a shell but not
 * necessarily of an opencode launched from the desktop. The absolute path is
 * preferred when it exists so the feature does not quietly stop working
 * depending on how the editor was started.
 */
function fragoLauncher() {
  if (process.env.FRAGO_LAUNCHER) return process.env.FRAGO_LAUNCHER
  const installed = path.join(os.homedir(), ".local", "bin", "frago")
  return existsSync(installed) ? installed : "frago"
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

/**
 * Present the description as what it is: a stand-in read by another model,
 * not the image itself. Without that framing a blind model answers as though
 * it had looked, and quotes the description back as its own observation.
 *
 * `origin` says where the image came from, because the two cases read very
 * differently to the model: one is an attachment the user put on the message,
 * the other is a file the model itself just opened.
 */
function visionBlock(count, description, origin = "message") {
  const where = origin === "tool" ? "你刚读取的" : "这条消息附带的"
  const subject = count > 1 ? `${where} ${count} 张图片` : `${where}图片`
  return [
    `【${subject}，你的模型看不见，已由多模态模型代读，以下是转述】`,
    "",
    description,
    "",
    "转述可能遗漏细节。据此作答时说明依据的是转述，NEVER 声称自己看到了图片。",
  ].join("\n")
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
  // sessionID -> `provider/model`. Tool hooks are told which session they
  // belong to but not which model is driving it, and the vision gate needs
  // the model; the message hook sees both, and always fires first.
  const sessionModel = new Map()
  // Descriptions already paid for in this process, keyed by path and size.
  // An agent re-reading the same screenshot would otherwise wait out the
  // vision model a second time for an answer it already has.
  const described = new Map()

  return {
    "chat.message": async (input, output) => {
      const sessionID = input.sessionID
      if (!sessionID) return

      // Synthetic parts are opencode's own narration of an attachment ("Called
      // the Read tool with…"), not words the user typed. Feeding them to the
      // rules engine would have prompt rules matching on tool echo.
      const userTexts = (output.parts || []).filter(
        (p) => p.type === "text" && typeof p.text === "string" && p.synthetic !== true,
      )
      const prompt = userTexts.map((p) => p.text).join("\n")

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

      // The image description runs alongside the routing lookups rather than
      // after them: it is the slow one by two orders of magnitude, and making
      // the fast lookups wait behind it would add seconds to every turn.
      const modelKey = modelKeyOf(input, output)
      if (modelKey) sessionModel.set(sessionID, modelKey)

      const images = imageUrlsOf(output.parts)
      const wantsVision = images.length > 0 && visionApplies(modelKey)
      const [hookResults, description] = await Promise.all([
        Promise.all(events.map(runHook)),
        wantsVision ? describeImages(images) : Promise.resolve(null),
      ])

      const contexts = hookResults.map(injectionOf).filter(Boolean)
      if (description) contexts.push(visionBlock(images.length, description))
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

      // Attachments push opencode's own narration ahead of the user's words as
      // earlier text parts. Prepending to that one would bury the injection in
      // a tool echo the model skims past, so the user's own first text part is
      // the target whenever there is one.
      const target = userTexts[0] ?? (output.parts || []).find((p) => p.type === "text")
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
      const blocks = []
      const context = pending.get(input.callID)
      if (context) {
        pending.delete(input.callID)
        blocks.push(context)
      }

      // An image the model opened itself. opencode hands the picture back as
      // an attachment on the tool result, which a model without vision cannot
      // use: it reads "Image read successfully", sees nothing, and reports
      // that it cannot look at the file. Describing it here puts the contents
      // where such a model can actually read them.
      const images = imageUrlsOf(output?.attachments)
      if (images.length && visionApplies(sessionModel.get(input.sessionID))) {
        const key = `${input.args?.filePath ?? ""}|${images.map((u) => u.length).join(",")}`
        let description = described.get(key)
        if (description === undefined) {
          description = await describeImages(images)
          // Only successes are remembered. A failure here is usually the
          // vision model being rate-limited for a moment, and caching that
          // would make one bad minute mean this file can never be read again
          // for the rest of the session.
          if (description) {
            if (described.size >= 32) described.clear()
            described.set(key, description)
          }
        }
        if (description) blocks.push(visionBlock(images.length, description, "tool"))
      }

      if (!blocks.length) return
      const framed = frame(blocks.join("\n\n"))
      if (!framed) return
      output.output = `${framed}\n\n${output.output ?? ""}`
    },
  }
}
