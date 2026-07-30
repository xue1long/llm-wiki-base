// ruflo-kb — knowledge-base chat view.
(() => {
  "use strict";

  window.App = window.App || {};

  App.renderChat = function renderChat(root) {
    root.innerHTML = `
      <div class="chat-wrap">
        <div class="chat-list" id="chatList"></div>
        <div class="chat-input">
          <textarea id="chatInput" placeholder="说点什么… (Enter 发送，Shift+Enter 换行)"></textarea>
          <button id="chatBtn">发送</button>
        </div>
      </div>
    `;
    const list = document.getElementById("chatList");
    const input = document.getElementById("chatInput");
    const btn = document.getElementById("chatBtn");
    let inflight = null;

    input.addEventListener("keydown", e => {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
    });
    btn.addEventListener("click", send);

    function appendMsg(role, content) {
      const wrap = document.createElement("div");
      wrap.className = "chat-msg " + role;
      wrap.innerHTML = `<div class="chat-bubble">${content}</div>`;
      list.appendChild(wrap);
      list.scrollTop = list.scrollHeight;
      return wrap;
    }

    async function send() {
      const msg = input.value.trim();
      if (!msg || btn.disabled) return;
      input.value = "";
      appendMsg("user", App.escapeHtml(msg).replace(/\n/g, "<br>"));
      const placeholder = appendMsg("thinking", "思考中...");
      btn.disabled = true;
      const controller = new AbortController();
      inflight = controller;
      try {
        const r = await App.api(`/api/v1/projects/${App.state.projectId}/chat`, {
          method: "POST",
          body: { message: msg, sessionId: App.state.sessionId },
          signal: controller.signal,
        });
        inflight = null;
        if (!placeholder.isConnected) return;
        App.state.sessionId = r.sessionId || App.state.sessionId;
        placeholder.classList.remove("thinking");
        const bubble = placeholder.querySelector(".chat-bubble");
        bubble.innerHTML = App.renderMd(r.message && r.message.content || "");
        if (Array.isArray(r.references) && r.references.length) {
          const refsHtml = `<div class="citations-panel"><div class="citations-title">引用 (${r.references.length})</div>${
            r.references.map(ref => {
              const raw = ref.path || "";
              const norm = App.normalizeWikiPath(raw);
              const title = ref.title || norm || "(无标题)";
              const snippet = (ref.content || ref.snippet || "").slice(0, 180);
              const score = typeof ref.score === "number" ? `score ${ref.score.toFixed(2)}` : "";
              return `<div class="citation-card" data-path="${App.escapeHtml(norm)}">
                <div class="citation-title">${App.escapeHtml(title)}</div>
                <div class="citation-path">${App.escapeHtml(norm)} ${score ? `<span class="citation-score">${App.escapeHtml(score)}</span>` : ""}</div>
                ${snippet ? `<div class="citation-snippet">${App.escapeHtml(snippet)}</div>` : ""}
              </div>`;
            }).join("")
          }</div>`;
          bubble.insertAdjacentHTML("beforeend", refsHtml);
          bubble.querySelectorAll(".citation-card").forEach(el => {
            el.addEventListener("click", () => {
              const target = el.dataset.path;
              if (!target) return;
              App.state.pendingBrowseTarget = target;
              App.showView("browse");
            });
          });
        }
        if (r.usage) {
          bubble.insertAdjacentHTML("beforeend",
            `<div class="chat-meta">iterations=${r.usage.iterations ?? "?"} · toolCalls=${r.usage.toolCalls ?? "?"}</div>`);
        }
      } catch (e) {
        if (!placeholder.isConnected) return;
        if (e.name === "AbortError") return;
        placeholder.classList.remove("thinking");
        placeholder.classList.add("error");
        placeholder.querySelector(".chat-bubble").textContent = "失败: " + e.message;
      } finally {
        inflight = null;
        btn.disabled = false;
        if (input.isConnected) input.focus();
      }
    }

    document.addEventListener("click", function abortOnNav(e) {
      const nav = e.target.closest && e.target.closest(".nav-btn");
      if (!nav || nav.dataset.view === "chat") return;
      if (inflight) { inflight.abort(); inflight = null; }
    });
  };
})();
