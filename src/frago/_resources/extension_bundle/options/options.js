// frago bridge — options page controller
//
// No proxy toggle exists by design:
//   - Non-empty proxyUrl -> proxy enabled (`fixed_servers`), bypassDomains take effect.
//   - Empty proxyUrl     -> nothing takes effect (`chrome.proxy.settings.clear`).

const PROXY_CONFIG_KEY = "fragoProxyConfig";
const BASE_BYPASS = [
    "<local>",
    "*.local",
    "10.0.0.0/8",
    "172.16.0.0/12",
    "192.168.0.0/16",
    "169.254.0.0/16",
];

const proxyInput = document.getElementById("proxy-url");
const clearProxyBtn = document.getElementById("clear-proxy-btn");
const bypassCard = document.getElementById("bypass-card");
const quickDomainInput = document.getElementById("quick-domain");
const addDomainBtn = document.getElementById("add-domain-btn");
const domainChipsEl = document.getElementById("domain-chips");
const bypassTextarea = document.getElementById("bypass-domains");
const builtinListEl = document.getElementById("builtin-list");
const saveBtn = document.getElementById("save-btn");
const toastEl = document.getElementById("toast");
const statusBanner = document.getElementById("status-banner");
const statusTitle = document.getElementById("status-title");
const statusDetail = document.getElementById("status-detail");
const statusBadge = document.getElementById("status-badge");

function normalizeProxyUrlInput(raw) {
    return String(raw || "")
        .trim()
        .replace(/：/g, ":")
        .replace(/。/g, ".")
        .replace(/　/g, " ");
}

function parseProxyUrl(raw) {
    const value = normalizeProxyUrlInput(raw);
    if (!value) return null;
    const withScheme = /^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(value)
        ? value
        : `http://${value}`;
    let parsed;
    try {
        parsed = new URL(withScheme);
    } catch (_) {
        throw new Error(`无效的代理地址格式: ${value}`);
    }
    let scheme = parsed.protocol.replace(/:$/, "").toLowerCase();
    if (scheme === "socks") scheme = "socks5";
    if (!["http", "https", "socks4", "socks5"].includes(scheme)) {
        throw new Error(`不支持的代理协议 "${scheme}"（仅支持 http / https / socks4 / socks5）`);
    }
    const port = Number(parsed.port);
    if (!parsed.hostname || !Number.isInteger(port) || port < 1 || port > 65535) {
        throw new Error("代理地址必须同时包含主机名与端口号（例如 127.0.0.1:7890）");
    }
    return {
        scheme,
        host: parsed.hostname,
        port,
        normalized: `${scheme}://${parsed.hostname}:${port}`,
    };
}

function parseDomainsText(raw) {
    if (!raw) return [];
    const seen = new Set();
    const out = [];
    for (const part of String(raw).split(/[\r\n,;]+/)) {
        const item = part.trim().replace(/。/g, ".");
        if (!item || item.startsWith("#")) continue;
        if (!seen.has(item)) {
            seen.add(item);
            out.push(item);
        }
    }
    return out;
}

function expandBypassRule(item) {
    const clean = String(item || "").trim();
    if (!clean) return [];
    if (
        clean.startsWith("<") ||
        clean.includes("/") ||
        /^\d+\.\d+\.\d+\.\d+$/.test(clean) ||
        clean.startsWith("[")
    ) {
        return [clean];
    }
    if (clean.startsWith("*.")) {
        const bare = clean.slice(2);
        return bare ? [clean, bare] : [clean];
    }
    if (!clean.includes("*")) {
        const hostOnly = clean.split(":")[0];
        if (hostOnly.includes(".") && hostOnly !== "localhost") {
            return [clean, `*.${clean}`];
        }
    }
    return [clean];
}

function mergeBypassEntries(userDomains) {
    const seen = new Set();
    const merged = [];
    const pushUnique = (entry) => {
        if (entry && !seen.has(entry)) {
            seen.add(entry);
            merged.push(entry);
        }
    };
    for (const item of BASE_BYPASS) {
        pushUnique(item);
    }
    for (const item of userDomains) {
        for (const expanded of expandBypassRule(item)) {
            pushUnique(expanded);
        }
    }
    return merged;
}

async function applyDirectFromOptions(proxyUrlRaw, bypassDomains) {
    const rawUrl = normalizeProxyUrlInput(proxyUrlRaw);
    const stored = await chrome.storage.local.get(PROXY_CONFIG_KEY);
    const prevCfg = stored[PROXY_CONFIG_KEY] || {};
    await chrome.storage.local.set({
        [PROXY_CONFIG_KEY]: {
            proxyUrl: prevCfg.proxyUrl || "",
            bypassDomains,
        },
    });
    const parsed = rawUrl ? parseProxyUrl(rawUrl) : null;
    const nextCfg = {
        proxyUrl: parsed ? parsed.normalized : "",
        bypassDomains,
    };
    await chrome.storage.local.set({ [PROXY_CONFIG_KEY]: nextCfg });
    if (!parsed) {
        if (chrome.proxy?.settings) {
            await chrome.proxy.settings.clear({ scope: "regular" });
        }
        return {
            ok: true,
            active: false,
            proxyUrl: "",
            bypassDomains,
            effectiveBypass: [],
            baseBypass: BASE_BYPASS,
        };
    }
    const effectiveBypass = mergeBypassEntries(bypassDomains);
    if (chrome.proxy?.settings) {
        await chrome.proxy.settings.set({
            scope: "regular",
            value: {
                mode: "fixed_servers",
                rules: {
                    singleProxy: {
                        scheme: parsed.scheme,
                        host: parsed.host,
                        port: parsed.port,
                    },
                    bypassList: effectiveBypass,
                },
            },
        });
    }
    return {
        ok: true,
        active: true,
        proxyUrl: parsed.normalized,
        bypassDomains,
        effectiveBypass,
        baseBypass: BASE_BYPASS,
    };
}

function renderChips(domains) {
    domainChipsEl.textContent = "";
    for (const domain of domains) {
        const chip = document.createElement("span");
        chip.className = "chip";
        const text = document.createElement("span");
        text.textContent = domain;
        const removeBtn = document.createElement("button");
        removeBtn.type = "button";
        removeBtn.title = `移除 ${domain}`;
        removeBtn.textContent = "×";
        removeBtn.addEventListener("click", () => {
            const next = parseDomainsText(bypassTextarea.value).filter((d) => d !== domain);
            bypassTextarea.value = next.join("\n");
            renderChips(next);
            persistDomainsOnly(next);
        });
        chip.appendChild(text);
        chip.appendChild(removeBtn);
        domainChipsEl.appendChild(chip);
    }
}

async function persistDomainsOnly(bypassDomains) {
    try {
        const stored = await chrome.storage.local.get(PROXY_CONFIG_KEY);
        const prevCfg = stored[PROXY_CONFIG_KEY] || {};
        const candidateUrl = normalizeProxyUrlInput(proxyInput.value);
        let effectiveUrl = prevCfg.proxyUrl || "";
        if (candidateUrl) {
            try {
                effectiveUrl = parseProxyUrl(candidateUrl).normalized;
            } catch (_) {
                // Keep previously saved proxyUrl if input is incomplete
            }
        }
        const resp = await applyDirectFromOptions(effectiveUrl, bypassDomains);
        renderBanner(resp);
        showToast("直连域名列表已自动保存", false);
    } catch (_) {
        // Ignore transient storage errors during typing
    }
}

function renderBuiltins(baseBypass) {
    builtinListEl.textContent = "";
    for (const item of baseBypass || BASE_BYPASS) {
        const code = document.createElement("code");
        code.textContent = item;
        builtinListEl.appendChild(code);
    }
}

function updateCardInteractivity() {
    const hasAddress = proxyInput.value.trim().length > 0;
    bypassCard.classList.toggle("is-muted", !hasAddress);
}

function renderBanner({ active, proxyUrl, bypassDomains }) {
    const count = (bypassDomains || []).length;
    if (active && proxyUrl) {
        statusBanner.classList.add("is-active");
        statusTitle.textContent = `代理已生效：${proxyUrl}`;
        statusDetail.textContent = count > 0
            ? `已启用 ${count} 条自定义强制直连域名规则（外加内置私有网段直连）。`
            : "当前未配置自定义直连域名（仅内置私有网段直连）。";
        statusBadge.textContent = "生效中";
    } else {
        statusBanner.classList.remove("is-active");
        statusTitle.textContent = "当前未启用代理";
        statusDetail.textContent = "未填写代理地址，所有请求直连，代理与直连域名规则均不生效。";
        statusBadge.textContent = "不生效";
    }
}

let toastTimer = null;
function showToast(message, isError = false) {
    if (toastTimer) clearTimeout(toastTimer);
    toastEl.textContent = message;
    toastEl.className = `toast is-visible ${isError ? "is-err" : "is-ok"}`;
    toastTimer = setTimeout(() => {
        toastEl.className = "toast";
    }, 3500);
}

function addQuickDomain() {
    const candidate = quickDomainInput.value.trim();
    if (!candidate) return;
    const merged = parseDomainsText(`${bypassTextarea.value}\n${candidate}`);
    bypassTextarea.value = merged.join("\n");
    renderChips(merged);
    quickDomainInput.value = "";
    persistDomainsOnly(merged);
}

function handleSaveSuccess(resp) {
    proxyInput.value = resp.proxyUrl || "";
    updateCardInteractivity();
    renderBanner(resp);
    showToast(
        resp.active
            ? `已生效：代理 ${resp.proxyUrl}`
            : "已清空代理地址，当前全部流量直连",
        false
    );
}

function saveSettings() {
    const proxyUrl = normalizeProxyUrlInput(proxyInput.value);
    const bypassDomains = parseDomainsText(bypassTextarea.value);
    bypassTextarea.value = bypassDomains.join("\n");
    renderChips(bypassDomains);

    applyDirectFromOptions(proxyUrl, bypassDomains)
        .then((resp) => {
            chrome.runtime.sendMessage(
                {
                    type: "frago.proxy.save",
                    proxyUrl: resp.proxyUrl,
                    bypassDomains,
                },
                () => { void chrome.runtime.lastError; }
            );
            handleSaveSuccess(resp);
        })
        .catch((err) => showToast(String(err?.message || err), true));
}

async function loadInitialState() {
    renderBuiltins(BASE_BYPASS);
    try {
        const stored = await chrome.storage.local.get(PROXY_CONFIG_KEY);
        const cfg = stored[PROXY_CONFIG_KEY] || {};
        const rawUrl = String(cfg.proxyUrl || "").trim();
        const domains = Array.isArray(cfg.bypassDomains)
            ? cfg.bypassDomains
            : parseDomainsText(cfg.bypassDomains || "");
        let normalized = "";
        let active = false;
        if (rawUrl) {
            try {
                normalized = parseProxyUrl(rawUrl).normalized;
                active = true;
            } catch (_) {
                normalized = rawUrl;
            }
        }
        proxyInput.value = normalized;
        bypassTextarea.value = domains.join("\n");
        renderChips(domains);
        updateCardInteractivity();
        renderBanner({ active, proxyUrl: normalized, bypassDomains: domains });

        const params = new URLSearchParams(window.location.search);
        if (params.has("proxyUrl")) {
            proxyInput.value = params.get("proxyUrl") || "";
            updateCardInteractivity();
        }
        if (params.has("quickDomain")) {
            for (const d of params.getAll("quickDomain")) {
                quickDomainInput.value = d;
                addQuickDomain();
            }
        }
        if (params.has("proxyUrl")) {
            saveSettings();
        }
    } catch (_) {
        // Ignore storage read error
    }
}

proxyInput.addEventListener("input", updateCardInteractivity);
proxyInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
        e.preventDefault();
        saveSettings();
    }
});

clearProxyBtn.addEventListener("click", () => {
    proxyInput.value = "";
    updateCardInteractivity();
    saveSettings();
});

addDomainBtn.addEventListener("click", addQuickDomain);
quickDomainInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") {
        e.preventDefault();
        addQuickDomain();
    }
});

let domainSaveTimer = null;
bypassTextarea.addEventListener("input", () => {
    const next = parseDomainsText(bypassTextarea.value);
    renderChips(next);
    if (domainSaveTimer) clearTimeout(domainSaveTimer);
    domainSaveTimer = setTimeout(() => {
        persistDomainsOnly(next);
    }, 400);
});
bypassTextarea.addEventListener("change", () => {
    if (domainSaveTimer) clearTimeout(domainSaveTimer);
    persistDomainsOnly(parseDomainsText(bypassTextarea.value));
});
proxyInput.addEventListener("change", () => {
    const raw = normalizeProxyUrlInput(proxyInput.value);
    if (!raw) {
        saveSettings();
        return;
    }
    try {
        parseProxyUrl(raw);
        saveSettings();
    } catch (_) {
        // Wait for explicit click or valid address
    }
});

saveBtn.addEventListener("click", saveSettings);

loadInitialState();
