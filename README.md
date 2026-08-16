<div align="center">

<img src="docs/images/logo.png" width="72" alt="frago" />

# frago

**Turn your computer into an operating system for AI agents**

English · [简体中文](README.zh-CN.md) · [User Guide](docs/user-guide.md) · [Recipes](docs/recipes.md) · [Discussions](https://github.com/tsaijamey/frago/discussions)

[![Release](https://img.shields.io/github/v/release/tsaijamey/frago?style=flat-square&color=12a150)](https://github.com/tsaijamey/frago/releases/latest)
[![License](https://img.shields.io/badge/license-AGPL--3.0-12a150?style=flat-square)](LICENSE)
[![Stars](https://img.shields.io/github/stars/tsaijamey/frago?style=flat-square&color=12a150)](https://github.com/tsaijamey/frago/stargazers)
[![Platform](https://img.shields.io/badge/macOS%20·%20Windows%20·%20Linux-12a150?style=flat-square)](https://github.com/tsaijamey/frago/releases/latest)

<img src="docs/images/hero-workbench.png" width="880" alt="The frago session workbench: a thousand sessions on the left, the agent's live receipts in the middle" />

</div>

> frago is not affiliated with OpenClaw. frago predates OpenClaw by approximately one month.

## Why frago

CLI agents are genuinely good, up to a point — and not nearly as convenient as they look, especially for ordinary people.

For an agent, a CLI may well be the best possible form: it makes driving the system easy. **For a human, it isn't.**

And almost no CLI agent can use the browser you've already signed into — Twitter, say — so even though they can drive *a* browser, they can't go read Twitter for you on their own.

They also do nothing on their own account for several agents driving a browser at once, so two jobs end up stepping on each other's tabs.

As it turns out, **what most people are short of today isn't options — it's** a prepared agent OS, something that lets them install any capable CLI and **get going as quickly as with ordinary software.**

As it stands, once you've set up a CLI agent on your machine you still spend hours on more configuration, and when you switch computers it all starts over. That drag does nothing for making money or getting faster with AI.

## frago in one line

Is frago another OpenClaw, another Hermes?

No.

Say you and your agent, working together, are Tony Stark. frago is the Iron Man suit.

Stark on his own is just an extremely clever man. But to fly, to go a round with the Hulk, to save the world — clever isn't enough. He has to put the suit on first.

## What frago does for the agent

This half the agent uses itself. You never see most of it.

| Subsystem / command | What it gives you |
|---|---|
| **Recipes**<br>`frago recipe` | Lets the agent learn to *build tools for itself* instead of waiting for you to configure more tools. frago covers the standard and the dependencies: packages are declared at the top of the script and installed into an isolated environment at run time, secrets are injected by the framework, and recipes call each other over a fixed JSON contract — the agent just writes the script, and what it writes is a tool it can re-run |
| **Banking experience as it goes**<br>`frago def <domain>` | It saves what it learned while working, instead of leaving it for "spare time" and another agent with half the context |
| **Built-in ground rules**<br>`frago book` | Most setups expect you to write your own agent.md, which isn't friendly. frago ships with a body of pitfall-avoiding knowledge that's there the moment you install |
| **Browser**<br>`frago browser` | There are plenty of projects that let an agent drive a browser, and they're all complicated — a pile of things to install. frago ships a lightweight extension instead: all you need is Edge (which you go on using yourself), and the agent handles everything browser-side through frago's infrastructure — in the browser you're already signed into, each agent in its own tab group, never stepping on each other |
| **Session companion**<br>`frago hook-rules` | Learns you from the way you put things — what's allowed, what isn't — and does its best not to make the same mistake twice |
| **Agent OS && frago desktop**<br>`frago desktop` | A desktop that looks exactly like macOS/Linux, built for the agent. It started as a way to have the agent drive an interface and record video by itself; then it turned out that an agent always having a window it *can show you* is a fine thing in its own right. There's more to find here |
| **Delegating on your behalf**<br>`frago agent` | Orchestration is a hollow idea — ten agents aren't ten times smarter than one, just ten times messier. frago's position: one agent that talks with you in real time understands what you want, and then issues the work on your behalf. Trust that an agent writes a better, more precise prompt than a person does |
| **Finding things**<br>`frago context` | Where output belongs, where last time's ended up — the agent looks it up instead of asking you |
| **External intake**<br>`frago channel` · `frago reply` | Takes tasks in from outside channels and sends results back, so the agent isn't limited to working while you watch |

## What frago does for you

This half is the human's window.

| Subsystem / command | What it gives you |
|---|---|
| **Server && WebUI**<br>`frago start` · `frago server` | Supports the mainstream CLI agents, and lets you manage sessions from a web page |
| **Providers**<br>`frago profile` | Manages several providers for people who don't live in a CLI, while the agent knows from built-in knowledge how to use them |
| **Session search**<br>`frago session search` | Searches past sessions by meaning across Claude Code and opencode, instead of relying on remembering a keyword |
| **Scheduling & daemons**<br>`frago schedule` · `frago daemon` | Recipes run on a clock and long jobs sit in the background without you watching |
| **Recipe market**<br>`frago market` · `frago recipe share` | Publish your recipes, install other people's |
| **Install & upkeep**<br>`frago client` · `frago update` · `frago autostart` | Desktop client, self-update, start on boot — a new computer doesn't mean starting over |

## What you can do with it

Those were commands. These are scenarios — all carried by recipes, and the recipes are written by your agent on the spot:

- **You stop needing Office**, because you can simply have the agent build you one to a recipe's spec
- **You stop reshooting a tutorial video for the seventh time** — perform it once on the virtual stage and the recording is the deliverable
- **You stop handing meeting audio to a third party** — transcription, key points and action items all happen on your own machine
- **You stop copy-pasting between five websites** — the agent walks it in one pass, in the browser you're already signed into
- **You stop hand-collating research** — fetch, dedupe, write up and file it in one recipe
- **You stop having to remember how you did it last time** — once it works, it's code you can re-run

### 🖥 The agent lives in a terminal. frago moves it into a web page.

#### Task: "Open this site and read me the title and the first sentence"

<p align="center"><img src="docs/images/feedback-detail.png" width="780" alt="One tool call, fully accounted for: command, success badge, timestamp, return value" /></p>

First, what frago does *not* do: the command, the `success`, the timestamp and the return value
are **produced by whichever cli-agent you run**. This machine runs Claude Code and opencode side
by side; the session above happens to be the former. They already emit all of that — it just
scrolls past in their own terminal windows, which makes it hard to manage.

frago doesn't produce receipts, and **it doesn't pick a side**. It reads **every** agent's records,
normalizes them into one shape, and turns them into one web page.

|  | In a terminal | In frago |
|---|---|---|
| **Past sessions** | A resume-style picker that's awkward to use | 1,299 sessions in one list, searchable by title, directory or session id |
| **Switching cli-agent** | Each one keeps its own records, in its own format | Normalized into one shape, merged into one list (above: 1,201 Claude Code + 98 opencode) |
| **Reading a session back** | Page up, screen by screen | Laid out card by card, bucketed as `running / done / stopped / errored` |
| **Continuing the conversation** | Find that terminal window again | Type on the page |
| **Usage** | Count it yourself | A usage calendar |

For people who live in a CLI, this is a convenience.
For people who don't, it's **the line between using an agent and not**.

(Those two `PreToolUse:Bash` rows above are the session companion stepping in — one reporting the receipt, one adding context. More below.)

This next layer is the part frago does itself:

| Layer | What frago does | What you get |
|---|---|---|
| **Logins** | Drives your browser's **own real profile** | Sites you're already signed into just work |
| **Anti-bot** | It *is* a real browser, not a simulation | Checks pass on their own |
| **Concurrency** | Each agent stays in its own real tab group | Two agents work at once without collision; the tab strip shows whose pages are whose |

### 🛠 Once it works, the agent builds itself a tool

#### Task: "I want to re-run this backtest myself and tweak the parameters"

<p align="center"><img src="docs/images/etf-dashboard.png" width="800" alt="ETF backtest dashboard: parameter panel, equity curve, per-trade P&L" /></p>

<p align="center"><sub>A <b>simulated</b> backtest on ¥100,000 of virtual capital, shown to illustrate the interface. Not investment advice.</sub></p>

> **This is just one of them.** That screenshot is one of **317 personal recipes** on a single
> development machine, picked because it photographs well. frago is not a trading tool — other
> recipes on that same machine cut video, draft articles, transcribe meetings, pull arXiv papers,
> scrape public neuroscience datasets, synthesize speech, generate storyboards, keep a ledger of
> past sessions, and pick universities. **What your recipes look like depends on what you keep
> asking an agent to do.**

This is the real difference between frago and "an agent that's good at things": the path that
worked doesn't rot in a chat log. It freezes into a **Recipe** — real, deterministic Python or shell.

|  | The first time | Every time after |
|---|---|---|
| **Who does it** | The agent works it out step by step | A piece of deterministic code |
| **Model involved** | Yes | **No** |
| **Result** | This way today, maybe another way tomorrow | Identical to last time |
| **Tokens** | Burned | **None** |

**A Recipe is a tool the agent builds for itself, not documentation for humans.**

|  | The agent-facing side | The human-facing side |
|---|---|---|
| **Form** | `recipe.md` + deterministic code | A page at `/app/<name>` |
| **How it's used** | `recipe list --format json` to discover · `run` · `schedule` | Open it, tune parameters, read results |
| **Required?** | Yes — this *is* the recipe | **No** — plenty of recipes have no UI at all and are complete software anyway |

Only when a person genuinely needs to look — as with the backtest above, where a human tunes the
parameters and reads the curve — does a recipe hang an interface off the side. The UI is the
optional layer, not the point.

### 🎬 And when you need to show it, there's a stage

#### Task: "Record what you just did as a tutorial video"

<p align="center"><img src="docs/images/agent-os-stage.png" width="760" alt="The agent_os stage: a fake macOS desktop inside a browser, with a real terminal and real pages underneath" /></p>

It looks like a macOS desktop; underneath it is all real. That terminal is a real tmux
session, that browser window is a real tab, and the mouse movement and clicks are reproducible.
Perform once, record it, replay it whenever — instead of reshooting your screen a seventh time.

## How it works

<p align="center"><img src="docs/images/how-it-works.svg" width="860" alt="How frago works: you say something → the agent works on real browser, files and screen, receipting each step → what worked freezes into a Recipe → optionally a window for humans; the session companion runs underneath the whole time" /></p>

The band across the bottom is the **session companion**, the layer most people underrate.
It comes in two:

| Layer | What it is | Model? | Match speed | Cost |
|---|---|---|---|---|
| **frago-core** | Static rules compiled into a 3 MB native binary | **No** | 34–961 ms measured on this machine, scaling with payload size | **Zero** |
| **Lightweight AI** | Adds one line of context at the right moment, to *your* standards | Yes, but only a short prompt | One call | Negligible |

Its only job is to keep the agent from drifting:

| A common drift | What the companion does |
|---|---|
| Guessing from memory when it should open the browser | Stops it there and points it at the real browser |
| Inventing a new directory for output | Points it at the place that already exists |
| Repeating a mistake you corrected once | Reminds it next time the same situation comes up |

Because the static layer is free and the AI layer only ever runs a short prompt,
**it's cheap enough to leave on permanently**. The settings page shows the live state of both
layers, in plain language.

## Examples: recipes I built for myself

**Illustration only.** These are **not built into frago and don't ship with it**, and they are not a
recommended list — they're private recipes on my own machine, grown around my own life and work.
They're here to answer one question: what can a recipe look like?

frago installs blank. Your recipes grow out of **your** agent doing **your** repetitive work,
and will most likely have nothing to do with any of these.

| Recipe | What the agent does | What a person sees |
|--------|--------------------|--------------------|
| `agent_os` | Reassembles a real tmux session and a real browser tab into a scriptable virtual macOS desktop | The live stage at `/app/agent_os` |
| `etf_backtest_dashboard_v5` | Runs zero-parameter backtests of A-share / cross-border ETF strategies, one set after another | Parameter sliders, net-value curves, per-trade P&L |
| `etf_kdj_ths_auto_trade` | Watches 5-minute KDJ signals and places orders in the Tonghuashun client | Trade receipts and position checks (no LLM in the loop) |
| `gaokao_henan_volunteer_analysis` | Converts score to province rank, matches universities to a family's budget and region, and flags disguised-private or overpriced programs | A report with a verification checklist, plus a web view |
| `meeting_copilot` | Transcribes a live meeting, extracts points, questions and actions from local materials, and can voice-clone a reply onto the mic | A scrolling transcript and question list |
| `article_studio` | One persistent editor agent per article — interviews you, rewrites in your voice, writes back into HTML | Article list on the left, reading and writing panes on the right |

## Install

| Platform | Download |
|----------|----------|
| **macOS (Apple Silicon)** | [.dmg](https://github.com/tsaijamey/frago/releases/latest) |
| **macOS (Intel)** | [.dmg](https://github.com/tsaijamey/frago/releases/latest) |
| **Windows** | [.msi](https://github.com/tsaijamey/frago/releases/latest) |
| **Linux** | [.deb](https://github.com/tsaijamey/frago/releases/latest) · [.rpm](https://github.com/tsaijamey/frago/releases/latest) · [.AppImage](https://github.com/tsaijamey/frago/releases/latest) |

> All downloads on the [Releases page](https://github.com/tsaijamey/frago/releases/latest). Current release: **v1.2.101**.

Install, open, configure one model profile, and go. The desktop app checks and installs everything it needs — no terminal, no environment setup, no dependencies to manage yourself.

## Documentation

- [User Guide](docs/user-guide.md) — getting started after install
- [Concepts](docs/concepts.md) — how Recipes, Runs, Sessions and prompting work together
- [Recipe System](docs/recipes.md) — the recipe command surface, end to end
- [Examples](docs/examples.md) — practical Run + Recipe + browser workflows
- [Browser Support](docs/browser-support.md) — backends, ports, tab groups, the desktop stage
- [Developer Docs](docs/developer.md) — CLI, architecture, development setup

Inside the product, `frago book` reads the shipped knowledge base — the canonical operational manual that stays in sync with the code.

## License

AGPL-3.0 — see [LICENSE](LICENSE)

## Contributing

- [Submit an Issue](https://github.com/tsaijamey/frago/issues)
- [Discussions](https://github.com/tsaijamey/frago/discussions)
- [Community recipes](community-recipes/README.md)

---

<div align="center"><sub>Created with Claude Code</sub></div>
