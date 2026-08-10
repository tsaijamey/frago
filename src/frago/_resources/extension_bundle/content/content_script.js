// frago bridge — content script.
//
// Two jobs:
//
// 1. Announce the page, which also wakes the service worker.
// 2. Report that someone is *using* this page.
//
// The second one is what keeps a group alive. A group closes itself
// after 30 minutes of silence, and the service worker can see commands
// and tab activation on its own — but not scrolling, clicking or typing
// inside a page. A person reading a long article the agent opened is not
// silence, so those count too. Throttled hard: one ping a minute is
// plenty to reset a 30-minute clock, and page interaction can fire
// hundreds of times a second.

(() => {
    if (window.__fragoBridgeInjected) return;
    window.__fragoBridgeInjected = true;

    const ACTIVITY_THROTTLE_MS = 60_000;
    let lastPing = 0;

    function ping() {
        const now = Date.now();
        if (now - lastPing < ACTIVITY_THROTTLE_MS) return;
        lastPing = now;
        try {
            chrome.runtime.sendMessage({ type: "frago.activity" });
        } catch (_) { /* SW may be asleep or context invalidated; ignore */ }
    }

    for (const evt of ["scroll", "pointerdown", "keydown"]) {
        window.addEventListener(evt, ping, { passive: true, capture: true });
    }

    try {
        chrome.runtime.sendMessage({ type: "frago.content_ready",
                                     url: location.href });
    } catch (_) { /* SW may be asleep; ignore */ }
})();
