// ruflo-kb — local Agent CLI panel (right sidebar, persistent).
(() => {
  "use strict";

  window.App = window.App || {};

  App.setupAgentPanel = function setupAgentPanel() {
    const panel   = document.getElementById("agentPanel");
    const dot     = document.getElementById("agentStatusDot");
    const text    = document.getElementById("agentStatusText");
    const hint    = document.getElementById("agentInstallHint");
    const list    = document.getElementById("agentList");
    const input   = document.getElementById("agentInput");
    const sendBtn = document.getElementById("agentSendBtn");
    const newBtn  = document.getElementById("agentNewBtn");
    const toggle  = document.getElementById("agentToggleBtn");

    function setEnabled(on) {
      input.disabled = !on || App.state.agentBusy;
      sendBtn.disabled = !on || App.state.agentBusy;
    }

    function setStatus(available, info) {
      App.state.agentAvailable = available;
      dot.classList.toggle("ok", !!available);
      dot.classList.toggle("bad", !available);
      if (available) {
        text.textContent = info && info.version ? `v${info.version.split(" ")[0]}` : "可用";
        text.title = info && info.version ? info.version : "claude code";
        hint.style.display = "none";
      } else {
        text.textContent = "未安装";
        text.title = info && info.error ? info.error : "";
        hint.innerHTML = `未检测到 claude code。请先安装并登录：<br><code>npm install -g @anthropic-ai/claude-code</code><br>然后运行 <code>claude</code> 登录。`;
        hint.style.display = "block";
      }
      setEnabled(available);
    }

    function appendMsg(kind, html, klass) {
      const wrap = document.createElement("div");
      wrap.className = "agent-msg " + (klass || kind);
      wrap.innerHTML = html;
      list.appendChild(wrap);
      list.scrollTop = list.scrollHeight;
      return wrap;
    }

    function appendUserBubble(text) {
      return appendMsg("user", `<div class="agent-bubble user-bubble">${App.escapeHtml(text).replace(/\n/g,"<br>")}</div>`);
    }
    function appendAssistantPlaceholder() {
      return appendMsg("assistant", `<div class="agent-bubble assistant-bubble thinking">Claude 思考中… (可能数十秒)</div>`, "assistant");
    }
    function appendToolBadge(name) {
      return appendMsg("tool", `<span class="agent-tool">🔧 ${App.escapeHtml(name)}</span>`);
    }
    function appendUsage(inTok, outTok) {
      return appendMsg("usage", `<span class="agent-usage">${inTok} in / ${outTok} out</span>`);
    }

    // ---- Boot probe ----
    App.api("/api/v1/agent-cli/status").then(r => setStatus(!!r.available, r)).catch(() => setStatus(false, {error: "探测失败"}));

    // ---- New session ----
    newBtn.addEventListener("click", () => {
      App.state.agentSessionId = null;
      list.innerHTML = "";
    });

    // ---- Collapse toggle ----
    toggle.addEventListener("click", () => panel.classList.toggle("collapsed"));

    // ---- Send ----
    input.addEventListener("keydown", e => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); doSend(); }
    });
    sendBtn.addEventListener("click", doSend);

    async function doSend() {
      if (App.state.agentBusy) return;
      const msg = input.value.trim();
      if (!msg) return;
      input.value = "";
      appendUserBubble(msg);
      const placeholder = appendAssistantPlaceholder();
      App.state.agentBusy = true;
      setEnabled(App.state.agentAvailable);
      let bubble = placeholder.querySelector(".agent-bubble");
      let streamed = "";

      const controller = new AbortController();
      try {
        const res = await fetch(window.location.origin + "/api/v1/agent-cli/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: msg, sessionId: App.state.agentSessionId }),
          signal: controller.signal,
        });
        if (!res.ok || !res.body) {
          const t = await res.text();
          bubble.classList.remove("thinking");
          bubble.classList.add("error");
          bubble.textContent = `请求失败 ${res.status}: ${t.slice(0, 200)}`;
          return;
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder("utf-8");
        let buffer = "";
        while (true) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          let idx;
          while ((idx = buffer.indexOf("\n\n")) !== -1) {
            const frame = buffer.slice(0, idx);
            buffer = buffer.slice(idx + 2);
            handleFrame(frame);
          }
        }
        if (buffer.trim()) handleFrame(buffer);
      } catch (e) {
        if (e.name !== "AbortError" && placeholder.isConnected) {
          bubble.classList.remove("thinking");
          bubble.classList.add("error");
          bubble.textContent = "失败: " + (e.message || e);
        }
      } finally {
        App.state.agentBusy = false;
        setEnabled(App.state.agentAvailable);
        input.focus();
      }

      function handleFrame(frame) {
        let event = "message", dataLines = [];
        for (const line of frame.split("\n")) {
          if (line.startsWith("event: ")) event = line.slice(7).trim();
          else if (line.startsWith("data: ")) dataLines.push(line.slice(6));
        }
        if (!dataLines.length) return;
        let data;
        try { data = JSON.parse(dataLines.join("\n")); } catch { return; }

        if (event === "start") {
          bubble.classList.remove("thinking");
          bubble.classList.remove("error");
          bubble.textContent = "";
          streamed = "";
          return;
        }
        if (event === "text_delta") {
          if (bubble.classList.contains("thinking") || bubble.classList.contains("error")) {
            bubble.classList.remove("thinking");
            bubble.classList.remove("error");
            bubble.textContent = "";
            streamed = "";
          }
          streamed += (data.delta || "");
          bubble.innerHTML = App.renderMd(streamed);
          list.scrollTop = list.scrollHeight;
          return;
        }
        if (event === "thinking_delta") {
          const existing = placeholder.previousElementSibling;
          if (existing && existing.classList && existing.classList.contains("agent-msg") && existing.dataset.thinking) {
            existing.querySelector(".agent-bubble").textContent += data.delta || "";
          } else {
            const w = document.createElement("div");
            w.className = "agent-msg assistant";
            w.dataset.thinking = "1";
            w.innerHTML = `<div class="agent-bubble assistant-bubble thinking">${App.escapeHtml(data.delta || "")}</div>`;
            list.insertBefore(w, placeholder);
          }
          list.scrollTop = list.scrollHeight;
          return;
        }
        if (event === "tool_use") {
          appendToolBadge(data.name || "tool");
          return;
        }
        if (event === "usage") {
          appendUsage(data.input_tokens || 0, data.output_tokens || 0);
          return;
        }
        if (event === "done") {
          if (data.sessionId) App.state.agentSessionId = data.sessionId;
          if (data.fullText) {
            streamed = data.fullText;
            bubble.innerHTML = App.renderMd(streamed);
          }
          return;
        }
        if (event === "error") {
          bubble.classList.remove("thinking");
          bubble.classList.add("error");
          bubble.textContent = data.message || "未知错误";
          return;
        }
      }
    }
  };
})();
