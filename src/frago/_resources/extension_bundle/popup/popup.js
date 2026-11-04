// Popup status fill — must live in its own file because MV3's default
// CSP (`script-src 'self'`) blocks inline <script> tags.
//
// `frago.popup.status` and `frago.proxy.get` are answered by the service
// worker; see background/service-worker-v14.js -> chrome.runtime.onMessage.

document.getElementById("eid").textContent = chrome.runtime.id;

chrome.runtime.sendMessage({ type: "frago.popup.status" }, (resp) => {
    const el = document.getElementById("status");
    if (chrome.runtime.lastError || !resp) {
        el.textContent = "no response";
        return;
    }
    el.textContent = resp.ok ? "connected" : "disconnected";
});

chrome.runtime.sendMessage({ type: "frago.proxy.get" }, (resp) => {
    const el = document.getElementById("proxy-status");
    if (chrome.runtime.lastError || !resp || !resp.ok) {
        el.textContent = "direct";
        return;
    }
    el.textContent = resp.active && resp.proxyUrl ? resp.proxyUrl : "direct (off)";
});

document.getElementById("open-options").addEventListener("click", () => {
    chrome.runtime.openOptionsPage();
});

