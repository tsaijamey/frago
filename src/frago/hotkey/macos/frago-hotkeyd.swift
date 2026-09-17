// frago-hotkeyd — frago 的全局快捷键常驻进程（macOS）
//
// 它只做两件事：
//   1. 按 ~/.frago/hotkeys.json 这张登记表绑住那些键；
//   2. 键被按下时，做那条登记说的事。
//
// 形态：LSUIElement + NSApplication(.accessory)。不进程序坞、没有窗口。
// 这个形态是必需的，不是装饰：同样的 RegisterEventHotKey 写在普通命令行程序里
// （不建 NSApplication、不 run()），登记会成功而事件永远不来。
//
// 授权：登记热键本身不需要任何授权（实测：AXIsProcessTrusted() == false 时
// RegisterEventHotKey 照样返回 0 并收得到按键）。只有「替人操作当前应用」那一类
// ——合成按键——才要辅助功能授权。所以没授权时零授权那类动作照常工作，要授权的
// 那类明确报缺授权，绝不静默失效。

import AppKit
import Carbon.HIToolbox
import Foundation

// MARK: - 固定位置

let fragoHome = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".frago")
let registryURL = fragoHome.appendingPathComponent("hotkeys.json")
let statusURL = fragoHome.appendingPathComponent("hotkeys-status.json")

let daemonVersion = "1"

// MARK: - 登记表模型

struct Action {
    var kind: String            // "run" | "quote_paste"
    var argv: [String]          // kind == "run"
    var wrapper: String         // kind == "quote_paste"
    var tail: String
    var releaseDelay: Double
    var restoreDelay: Double
}

struct Binding {
    var id: String
    var key: String             // 规范写法，如 "ctrl+alt+cmd+r"
    var label: String
    var enabled: Bool
    var action: Action
    var needsAccessibility: Bool { action.kind == "quote_paste" }
}

/// 一条登记当前的实况：绑上了没有、为什么没绑上、上一次按下发生了什么。
struct BindingState {
    var bound = false
    var error: String? = nil
    var lastFired: String? = nil
    var lastError: String? = nil
}

// MARK: - 键位解析

/// 键名 → Carbon 虚拟键码。登记表里写的是键名（"r"、"f5"、"space"），
/// 键码是本机键盘布局无关的物理位置，两边只在这里换算一次。
let keyCodes: [String: UInt32] = [
    "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04, "g": 0x05,
    "z": 0x06, "x": 0x07, "c": 0x08, "v": 0x09, "b": 0x0B, "q": 0x0C,
    "w": 0x0D, "e": 0x0E, "r": 0x0F, "y": 0x10, "t": 0x11, "o": 0x1F,
    "u": 0x20, "i": 0x22, "p": 0x23, "l": 0x25, "j": 0x26, "k": 0x28,
    "n": 0x2D, "m": 0x2E,
    "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15, "5": 0x17, "6": 0x16,
    "7": 0x1A, "8": 0x1C, "9": 0x19, "0": 0x1D,
    "=": 0x18, "-": 0x1B, "]": 0x1E, "[": 0x21, "'": 0x27, ";": 0x29,
    "\\": 0x2A, ",": 0x2B, "/": 0x2C, ".": 0x2F, "`": 0x32,
    "return": 0x24, "tab": 0x30, "space": 0x31, "delete": 0x33,
    "escape": 0x35, "forwarddelete": 0x75, "help": 0x72,
    "home": 0x73, "pageup": 0x74, "end": 0x77, "pagedown": 0x79,
    "left": 0x7B, "right": 0x7C, "down": 0x7D, "up": 0x7E,
    "f1": 0x7A, "f2": 0x78, "f3": 0x63, "f4": 0x76, "f5": 0x60,
    "f6": 0x61, "f7": 0x62, "f8": 0x64, "f9": 0x65, "f10": 0x6D,
    "f11": 0x67, "f12": 0x6F, "f13": 0x69, "f14": 0x6B, "f15": 0x71,
    "f16": 0x6A, "f17": 0x40, "f18": 0x4F, "f19": 0x50, "f20": 0x5A,
]

struct ParsedKey {
    var mods: UInt32
    var code: UInt32
}

func parseKey(_ spec: String) -> ParsedKey? {
    let parts = spec.lowercased().split(separator: "+").map(String.init)
    guard let last = parts.last, let code = keyCodes[last] else { return nil }
    var mods: UInt32 = 0
    for part in parts.dropLast() {
        switch part {
        case "cmd", "command": mods |= UInt32(cmdKey)
        case "ctrl", "control": mods |= UInt32(controlKey)
        case "alt", "opt", "option": mods |= UInt32(optionKey)
        case "shift": mods |= UInt32(shiftKey)
        default: return nil
        }
    }
    return ParsedKey(mods: mods, code: code)
}

// MARK: - 起进程

/// 起一条命令，起完就走，绝不等它跑完。
///
/// 环境必须在这里自己配齐。launchd 起来的进程环境是光的——PATH 里没有
/// `~/.local/bin`，而 frago 起 python 配方要用住在那儿的 uv。这一条不补，
/// 表现就是按下去什么都不发生：不报错、不留痕。
func launch(_ argv: [String]) throws {
    guard let exe = argv.first else { return }
    let home = FileManager.default.homeDirectoryForCurrentUser.path
    var env = ProcessInfo.processInfo.environment
    let wanted = [
        "\(home)/.local/bin", "/opt/homebrew/bin", "/usr/local/bin",
        "/usr/bin", "/bin", "/usr/sbin", "/sbin",
    ]
    var path = wanted
    for dir in (env["PATH"] ?? "").split(separator: ":").map(String.init) {
        if !path.contains(dir) { path.append(dir) }
    }
    env["PATH"] = path.joined(separator: ":")
    env["HOME"] = home
    if env["LANG"] == nil { env["LANG"] = "en_US.UTF-8" }

    let task = Process()
    task.executableURL = URL(fileURLWithPath: exe)
    task.arguments = Array(argv.dropFirst())
    task.environment = env
    task.currentDirectoryURL = URL(fileURLWithPath: home)
    task.standardOutput = FileHandle.nullDevice
    task.standardError = FileHandle.nullDevice
    task.standardInput = FileHandle.nullDevice
    // 收尸用。不设它，跑完的孩子会一直挂在进程表上。
    task.terminationHandler = { _ in }
    try task.run()
}

// MARK: - 辅助功能授权

/// 问一句「现在有授权吗」，不打扰人。
func hasAccessibility() -> Bool { AXIsProcessTrusted() }

/// 让系统自己弹那个「是否允许控制这台电脑」的框。
///
/// 这个调用给不了任何权限。它只做两件事：把本程序登记进「辅助功能」那张名单里
/// （登记进去是**关着**的），并把系统设置的那一页打开。开关只有人能拨，在系统设置
/// 里亲手拨。程序这边没有任何代劳的办法，也不该有——所以这里没有「成功」这回事，
/// 返回值只是顺手报一下当前是关是开。
func promptForAccessibility() -> Bool {
    let key = kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String
    return AXIsProcessTrustedWithOptions([key: true] as CFDictionary)
}

/// 给人看一句话。后台进程没有窗口，出事只能靠通知说出口。
func notify(_ title: String, _ body: String) {
    let script = "display notification \(quoteAppleScript(body)) with title \(quoteAppleScript(title))"
    try? launch(["/usr/bin/osascript", "-e", script])
}

func quoteAppleScript(_ s: String) -> String {
    "\"" + s.replacingOccurrences(of: "\\", with: "\\\\")
            .replacingOccurrences(of: "\"", with: "\\\"") + "\""
}

// MARK: - 引用粘贴（要辅助功能授权）

/// 读剪贴板、包成引用块、发一次粘贴、过一会儿把原内容还原。
///
/// 两处延迟照 quote_paste.lua 现在的做法搬，那份是调过的：
///   - 先等一下再发粘贴，等人的手指从修饰键上抬起来；
///   - 合成事件显式钉死修饰键（只 cmd），否则会跟人物理按着的 shift 叠成别的快捷键。
func quotePaste(_ action: Action, done: @escaping (String?) -> Void) {
    let board = NSPasteboard.general
    guard let original = board.string(forType: .string),
          !original.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
        notify("引用粘贴", "剪贴板是空的")
        done("剪贴板是空的")
        return
    }

    let body = original.replacingOccurrences(
        of: "\\s+$", with: "", options: .regularExpression)
    let wrapped = "\(action.wrapper)\n\(body)\n\(action.wrapper)\n\(action.tail)"
    board.clearContents()
    board.setString(wrapped, forType: .string)

    DispatchQueue.main.asyncAfter(deadline: .now() + action.releaseDelay) {
        // source 传 nil：不继承任何既有的按键状态，再显式给 flags 赋值，
        // 合成出来的就只有 cmd+v 这一个组合。
        let down = CGEvent(keyboardEventSource: nil, virtualKey: 0x09, keyDown: true)
        let up = CGEvent(keyboardEventSource: nil, virtualKey: 0x09, keyDown: false)
        down?.flags = .maskCommand
        up?.flags = .maskCommand
        down?.post(tap: .cghidEventTap)
        up?.post(tap: .cghidEventTap)
    }
    DispatchQueue.main.asyncAfter(deadline: .now() + action.restoreDelay) {
        board.clearContents()
        board.setString(original, forType: .string)
    }
    done(nil)
}

// MARK: - 主体

final class HotkeyDaemon {
    private var bindings: [Binding] = []
    private var states: [String: BindingState] = [:]
    private var refs: [EventHotKeyRef?] = []
    private var order: [Int: Int] = [:]      // 热键 id → bindings 下标
    private var lastStamp: String = ""
    private var handlerInstalled = false

    func start() {
        installHandler()
        reload()
        // 登记表是 frago 写的，写完这边就要跟上。比起监听文件事件，
        // 定时看一眼改动时间简单得多，也没有原子替换（写临时文件再改名）
        // 会把监听对象换掉那类坑。
        Timer.scheduledTimer(withTimeInterval: 1.5, repeats: true) { [weak self] _ in
            self?.reloadIfChanged()
        }
    }

    private func installHandler() {
        guard !handlerInstalled else { return }
        var spec = EventTypeSpec(
            eventClass: OSType(kEventClassKeyboard),
            eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), { _, event, _ -> OSStatus in
            var hkID = EventHotKeyID()
            GetEventParameter(event, EventParamName(kEventParamDirectObject),
                              EventParamType(typeEventHotKeyID), nil,
                              MemoryLayout<EventHotKeyID>.size, nil, &hkID)
            daemon.fire(Int(hkID.id))
            return noErr
        }, 1, &spec, nil, nil)
        handlerInstalled = true
    }

    // MARK: 登记表

    private func stamp() -> String {
        let attrs = try? FileManager.default.attributesOfItem(atPath: registryURL.path)
        let date = (attrs?[.modificationDate] as? Date)?.timeIntervalSince1970 ?? 0
        let size = (attrs?[.size] as? Int) ?? 0
        return "\(date)-\(size)"
    }

    private func reloadIfChanged() {
        if stamp() != lastStamp { reload() }
    }

    private func reload() {
        lastStamp = stamp()
        bindings = readRegistry()
        unregisterAll()
        registerAll()
        writeStatus()
    }

    private func readRegistry() -> [Binding] {
        guard let data = try? Data(contentsOf: registryURL),
              let root = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any],
              let raw = root["bindings"] as? [[String: Any]] else { return [] }
        return raw.compactMap { item in
            guard let id = item["id"] as? String,
                  let key = item["key"] as? String else { return nil }
            let a = item["action"] as? [String: Any] ?? [:]
            let action = Action(
                kind: a["kind"] as? String ?? "run",
                argv: a["argv"] as? [String] ?? [],
                wrapper: a["wrapper"] as? String ?? "\"\"\"",
                tail: a["tail"] as? String ?? ">>>> ",
                releaseDelay: a["release_delay"] as? Double ?? 0.12,
                restoreDelay: a["restore_delay"] as? Double ?? 0.6)
            return Binding(
                id: id, key: key,
                label: item["label"] as? String ?? id,
                enabled: item["enabled"] as? Bool ?? true,
                action: action)
        }
    }

    private func unregisterAll() {
        for ref in refs where ref != nil { UnregisterEventHotKey(ref!) }
        refs = []
        order = [:]
    }

    private func registerAll() {
        var fresh: [String: BindingState] = [:]
        for (index, binding) in bindings.enumerated() {
            // 上一轮记下的「上次按下发生了什么」要留住，重载不是失忆。
            var state = BindingState()
            if let old = states[binding.id] {
                state.lastFired = old.lastFired
                state.lastError = old.lastError
            }
            defer { fresh[binding.id] = state }

            guard binding.enabled else {
                state.error = "这条登记是停用的"
                continue
            }
            guard let parsed = parseKey(binding.key) else {
                state.error = "键位写法看不懂：\(binding.key)"
                continue
            }
            var ref: EventHotKeyRef?
            let hotKeyID = EventHotKeyID(
                signature: OSType(0x46524750),   // 'FRGO'
                id: UInt32(index + 1))
            let status = RegisterEventHotKey(
                parsed.code, parsed.mods, hotKeyID,
                GetApplicationEventTarget(), 0, &ref)
            if status == noErr, ref != nil {
                state.bound = true
                refs.append(ref)
                order[index + 1] = index
            } else {
                // 最常见的原因是这个组合已经被别的程序占住了。
                state.error = "登记不上（系统返回 \(status)），多半是这个组合已经被别的程序占了"
            }
        }
        states = fresh
    }

    // MARK: 按下了

    func fire(_ hotKeyID: Int) {
        guard let index = order[hotKeyID], index < bindings.count else { return }
        let binding = bindings[index]
        var state = states[binding.id] ?? BindingState()
        state.lastFired = isoNow()

        if binding.needsAccessibility && !AXIsProcessTrusted() {
            let msg = "缺辅助功能授权，这个键做不了。去「系统设置 → 隐私与安全性 → 辅助功能」里把 frago-hotkeyd 打开"
            state.lastError = msg
            states[binding.id] = state
            writeStatus()
            notify(binding.label, msg)
            return
        }

        switch binding.action.kind {
        case "quote_paste":
            quotePaste(binding.action) { [weak self] err in
                state.lastError = err
                self?.states[binding.id] = state
                self?.writeStatus()
            }
            return
        default:
            do {
                try launch(binding.action.argv)
                state.lastError = nil
            } catch {
                let msg = "起不来：\(error.localizedDescription)"
                state.lastError = msg
                notify(binding.label, msg)
            }
        }
        states[binding.id] = state
        writeStatus()
    }

    // MARK: 说出自己的状态

    private func writeStatus() {
        let rows: [[String: Any]] = bindings.map { binding in
            let state = states[binding.id] ?? BindingState()
            var row: [String: Any] = [
                "id": binding.id,
                "key": binding.key,
                "label": binding.label,
                "enabled": binding.enabled,
                "bound": state.bound,
                "needs_accessibility": binding.needsAccessibility,
            ]
            row["error"] = state.error ?? NSNull()
            row["last_fired"] = state.lastFired ?? NSNull()
            row["last_error"] = state.lastError ?? NSNull()
            return row
        }
        let payload: [String: Any] = [
            "pid": ProcessInfo.processInfo.processIdentifier,
            "daemon_version": daemonVersion,
            "updated_at": isoNow(),
            "accessibility": AXIsProcessTrusted(),
            "registry": registryURL.path,
            "bindings": rows,
        ]
        guard let data = try? JSONSerialization.data(
            withJSONObject: payload,
            options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]) else { return }
        let tmp = statusURL.appendingPathExtension("tmp")
        try? data.write(to: tmp)
        _ = try? FileManager.default.replaceItemAt(statusURL, withItemAt: tmp)
    }
}

func isoNow() -> String {
    let fmt = ISO8601DateFormatter()
    fmt.formatOptions = [.withInternetDateTime]
    return fmt.string(from: Date())
}

// MARK: - 起飞

// --check 只报一句状态就走，给安装流程确认这份二进制是活的。
if CommandLine.arguments.contains("--check") {
    print("frago-hotkeyd \(daemonVersion) accessibility=\(AXIsProcessTrusted())")
    exit(0)
}

let daemon = HotkeyDaemon()
let app = NSApplication.shared
app.setActivationPolicy(.accessory)
daemon.start()
app.run()
