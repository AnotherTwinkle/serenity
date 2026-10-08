let nativePort = null;

// ---------- Core logic (unchanged behavior extracted) ----------
async function handleRunScript() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tabs[0]) return;

  let url = tabs[0].url;

  const results = await chrome.scripting.executeScript({
    target: { tabId: tabs[0].id },
    func: () => {
      const video = document.querySelector("video");
      return video ? video.currentTime : null;
    }
  });

  const timeS = results[0].result;
  if (timeS != null && !url.includes("&t=")) {
    const seconds = Math.floor(timeS);
    url = url + "&t=" + seconds + "s";
  }

  if (!nativePort) {
    console.error("Native port not connected");
    return;
  }

  console.log("Sending URL:", encodeURIComponent(url));
  nativePort.postMessage({ url: url });
}


// ---------- Native connection ----------
function connectNativeHost() {
  console.log("Connecting to native host...");

  nativePort = chrome.runtime.connectNative("com.serenity.runner");

  nativePort.onMessage.addListener((msg) => {
    console.log("Received from native:", msg);

    if (msg.intent === "handoff-request") {
      handleRunScript();
    }
  });

  nativePort.onDisconnect.addListener(() => {
    if (chrome.runtime.lastError) {
      console.error("Disconnected:", chrome.runtime.lastError.message);
    } else {
      console.warn("Native host disconnected");
    }

    nativePort = null;

    // Reconnect automatically
    setTimeout(connectNativeHost, 1000);
  });
}


// ---------- Startup ----------
connectNativeHost();


// ---------- Command listener (unchanged behavior) ----------
chrome.commands.onCommand.addListener((command) => {
  if (command === "run-script") {
    handleRunScript();
  }
});