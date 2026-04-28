// Popup status fill — must live in its own file because MV3's default
// CSP (`script-src 'self'`) blocks inline <script> tags.
//
// `frago.popup.status` is answered by the service worker; see
// background/service_worker.js -> chrome.runtime.onMessage handler.

document.getElementById("eid").textContent = chrome.runtime.id;

chrome.runtime.sendMessage({ type: "frago.popup.status" }, (resp) => {
    const el = document.getElementById("status");
    if (chrome.runtime.lastError || !resp) {
        el.textContent = "no response";
        return;
    }
    el.textContent = resp.ok ? "connected" : "disconnected";
});
