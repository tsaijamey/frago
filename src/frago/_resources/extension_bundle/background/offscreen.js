// frago bridge — offscreen tab recorder.
//
// service worker 传来 tabCapture 的 streamId，这里 getUserMedia 拿到
// 媒体流，MediaRecorder 按 timeslice 切块编码，每块以 runtime message
// 交回 service worker（它再转发给 native host）。
// 停止时序：stop() → 最后一次 dataavailable → onstop 发 last 标记。

let recorder = null;
let stream = null;
let tabId = null;
let seq = 0;
let stopResolve = null;

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
    if (!msg || !msg.__frago_offscreen) return;
    if (msg.__frago_offscreen === "record_start") {
        startRec(msg)
            .then(() => sendResponse({ ok: true }))
            .catch((e) => sendResponse({ ok: false, error: String(e) }));
        return true;
    }
    if (msg.__frago_offscreen === "record_stop") {
        stopRec()
            .then((n) => sendResponse({ ok: true, chunks: n }))
            .catch((e) => sendResponse({ ok: false, error: String(e) }));
        return true;
    }
});

async function startRec({ streamId, tabId: tid, videoBitsPerSecond, timesliceMs }) {
    if (recorder) throw new Error("already recording");
    tabId = tid;
    seq = 0;
    stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: {
            mandatory: {
                chromeMediaSource: "tab",
                chromeMediaSourceId: streamId,
            },
        },
    });
    const mime = MediaRecorder.isTypeSupported("video/webm;codecs=vp9")
        ? "video/webm;codecs=vp9" : "video/webm";
    recorder = new MediaRecorder(stream, { mimeType: mime, videoBitsPerSecond });
    recorder.ondataavailable = async (e) => {
        if (!e.data || !e.data.size) return;
        const buf = new Uint8Array(await e.data.arrayBuffer());
        chrome.runtime.sendMessage({
            __frago_chunk: true,
            tabId,
            seq: seq++,
            data: b64(buf),
            mime: e.data.type,
            last: false,
        });
    };
    recorder.onstop = () => {
        // 空 data 的收尾标记：消费者据此知道文件完整了
        chrome.runtime.sendMessage({
            __frago_chunk: true, tabId, seq: seq, data: "", mime: "", last: true,
        });
        if (stopResolve) stopResolve(seq);
        cleanup();
    };
    recorder.start(timesliceMs);
}

function stopRec() {
    return new Promise((resolve, reject) => {
        if (!recorder) { reject(new Error("not recording")); return; }
        stopResolve = resolve;
        recorder.stop();
    });
}

function cleanup() {
    if (stream) stream.getTracks().forEach((t) => t.stop());
    recorder = null;
    stream = null;
    stopResolve = null;
}

function b64(buf) {
    let bin = "";
    const CH = 0x8000;
    for (let i = 0; i < buf.length; i += CH) {
        bin += String.fromCharCode.apply(null, buf.subarray(i, i + CH));
    }
    return btoa(bin);
}
