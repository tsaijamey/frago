// Popup status fill & Side Panel fallback launcher

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

document.getElementById("open-sidepanel").addEventListener("click", async () => {
    try {
        const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
        if (chrome.sidePanel?.open && tab?.windowId != null) {
            await chrome.sidePanel.open({ windowId: tab.windowId });
            window.close();
            return;
        }
    } catch (_) { /* fallback below */ }
    chrome.tabs.create({ url: chrome.runtime.getURL("sidepanel/index.html") });
    window.close();
});

document.getElementById("open-options").addEventListener("click", () => {
    chrome.runtime.openOptionsPage();
});
