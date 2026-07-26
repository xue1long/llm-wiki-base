// ruflo-kb web frontend — single-page app, no build, no framework.
// All views share one api() wrapper and a module-level projectId.
//
// Pitfalls handled (see FRONTEND_DESIGN.md §10):
//   1. projectId must be a UUID (fetched from /api/v1/projects on boot).
//   2. files/content path is relative to wiki root (no "wiki/" prefix),
//      but list/search return paths WITH the "wiki/" prefix — strip it.
//   3. Search `content` is a 300-char snippet, not the full text.
//   5. Ingest is async (HTTP 200 only means "queued").
//   6. Chat is non-streaming and may take a while; show "thinking" + 502.
//   8. marked CDN may be blocked offline; fall back to <pre>.

(() => {
  "use strict";

  // ---------- Module state ----------
  const state = {
    projectId: null,
    projectName: null,
    sessionId: null,        // knowledge-base chat session (persists across view switches)
    currentView: "search",
    // When set, browse view auto-selects this wiki-relative path after load.
    pendingBrowseTarget: null,
    // Local agent CLI state
    agentSessionId: null,   // persisted across panel reloads
    agentAvailable: false,  // last probed status
    agentBusy: false,       // a stream is in flight
  };

  // ---------- Path normalization ----------
  // Search/list/chat references may return paths in three forms observed in
  // the wild: "wiki/foo/bar.md" (relative), absolute Windows
  // ("E:\\proj\\wiki\\foo\\bar.md"), or absolute POSIX ("/home/x/wiki/...").
  // Normalize to a wiki-relative forward-slash path so all callers agree.
  function normalizeWikiPath(p) {
    if (!p) return "";
    let s = String(p).replace(/\\/g, "/");
    // Strip the optional "/.../" prefix and the mandatory "wiki/" segment.
    s = s.replace(/^(.*\/)?wiki\//, "");
    return s;
  }

  // ---------- API wrapper ----------
  async function api(path, { method = "GET", body, signal } = {}) {
    const url = window.location.origin + path;
    const opts = { method, headers: { "Content-Type": "application/json" } };
    if (body !== undefined) opts.body = JSON.stringify(body);
    if (signal) opts.signal = signal;
    let res;
    try {
      res = await fetch(url, opts);
    } catch (e) {
      if (e.name === "AbortError") throw e;
      throw new Error("网络错误: " + (e.message || e));
    }
    const text = await res.text();
    let data;
    try { data = text ? JSON.parse(text) : {}; }
    catch { data = { raw: text }; }
    if (!res.ok) {
      const detail = (data && (data.detail || data.message)) || res.statusText;
      throw new Error(`${res.status} ${detail}`);
    }
    return data;
  }

  // ---------- Markdown rendering ----------
  function renderMd(md) {
    if (typeof window.marked === "function" || (window.marked && window.marked.parse)) {
      try { return window.marked.parse(md); } catch (e) { /* fall through */ }
    }
    const escaped = md.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    return `<pre class="no-md-fallback">${escaped}</pre>`;
  }

  // ---------- YAML frontmatter (minimal regex, no library) ----------
  // Walks the YAML block line-by-line. Scalar keys map to strings; keys whose
  // value is empty (followed by indented or "- "-prefixed lines) collect a
  // list of strings. Nested mappings (e.g. "- target: x\n  type: y") are
  // rendered as a multi-line JSON-ish blob inside the list item.
  function parseFrontmatter(md) {
    const m = md.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?/);
    if (!m) return { fm: null, body: md };
    const block = m[1];
    const body = md.slice(m[0].length);
    const fm = {};
    const lines = block.split(/\r?\n/);
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      const kv = line.match(/^([A-Za-z_][\w-]*)\s*:\s*(.*)$/);
      if (!kv) { i++; continue; }
      const key = kv[1];
      let v = kv[2].trim();
      // strip surrounding quotes
      if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
        v = v.slice(1, -1);
      }
      if (v !== "") { fm[key] = v; i++; continue; }
      // empty value: collect list items / nested mapping on following lines
      const items = [];
      i++;
      while (i < lines.length) {
        const nxt = lines[i];
        if (!nxt.startsWith(" ") && !nxt.startsWith("-")) break;  // end of this key
        if (nxt.startsWith("- ")) {
          // list item; collect the "- key: val" + subsequent indented continuations
          const first = nxt.slice(2);
          const subKv = first.match(/^([A-Za-z_][\w-]*)\s*:\s*(.*)$/);
          if (subKv) {
            const sub = { [subKv[1]]: unquote(subKv[2].trim()) };
            i++;
            while (i < lines.length && (lines[i].startsWith("  ") || lines[i].startsWith("\t"))) {
              const ckv = lines[i].match(/^\s+([A-Za-z_][\w-]*)\s*:\s*(.*)$/);
              if (ckv) sub[ckv[1]] = unquote(ckv[2].trim());
              i++;
            }
            items.push(sub);
          } else {
            items.push(first.trim());
            i++;
          }
        } else {
          items.push(nxt.trim());
          i++;
        }
      }
      fm[key] = items;
    }
    return { fm, body };

    function unquote(s) {
      if ((s.startsWith('"') && s.endsWith('"')) || (s.startsWith("'") && s.endsWith("'"))) {
        return s.slice(1, -1);
      }
      return s;
    }
  }

  function renderFrontmatter(fm) {
    if (!fm) return "";
    const keys = Object.keys(fm);
    if (!keys.length) return "";
    const rows = keys.map(k => {
      const v = fm[k];
      if (Array.isArray(v)) {
        const lis = v.map(item => {
          if (item && typeof item === "object") {
            const kv = Object.entries(item).map(([kk, vv]) => `<span class="stat-key">${escapeHtml(kk)}:</span> ${escapeHtml(String(vv))}`).join(" · ");
            return `<li>${kv}</li>`;
          }
          return `<li>${escapeHtml(String(item))}</li>`;
        }).join("");
        return `<div class="fm-row"><span class="stat-key">${escapeHtml(k)}:</span><ul class="fm-list">${lis}</ul></div>`;
      }
      return `<div class="fm-row"><span class="stat-key">${escapeHtml(k)}:</span> ${escapeHtml(String(v))}</div>`;
    }).join("");
    return `<div class="reader-fm">${rows}</div>`;
  }

  function escapeHtml(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // ---------- Banner (top error/ok messages) ----------
  function setBanner(msg, kind = "err") {
    const el = document.getElementById("banner");
    el.innerHTML = msg ? `<div class="banner-${kind}">${escapeHtml(msg)}</div>` : "";
  }

  // ---------- Boot ----------
  async function boot() {
    try {
      // First try the "current" project endpoint (matches server's CWD). This
      // avoids the legacy pitfall of picking whatever project happens to be
      // first in the registry, which is often a stale test fixture.
      let chosen = null;
      try {
        chosen = await api("/api/v1/projects/current");
      } catch { /* fall through to list-based selection */ }
      if (!chosen) {
        const data = await api("/api/v1/projects");
        const list = data.projects || [];
        if (!list.length) {
          setBanner("未找到已注册项目，请先 python -m src.cli project init", "err");
          document.getElementById("projectName").textContent = "(无项目)";
          return;
        }
        const sorted = [...list].sort((a, b) => (b.last_opened || 0) - (a.last_opened || 0));
        chosen = sorted[0] || list[0];
      }
      state.projectId = chosen.id;
      state.projectName = chosen.name;
      document.getElementById("projectName").textContent = state.projectName;
      // health
      try {
        const h = await api("/health");
        const ok = h.ok === true;
        const dot = document.getElementById("healthDot");
        dot.classList.add(ok ? "ok" : "bad");
        document.getElementById("healthText").textContent = ok ? `v${h.version || "?"}` : "异常";
      } catch { /* leave grey */ }
      showView("search");
    } catch (e) {
      setBanner("启动失败: " + e.message, "err");
    }
  }

  // ---------- View router ----------
  function showView(name) {
    state.currentView = name;
    document.querySelectorAll(".nav-btn").forEach(b => {
      b.classList.toggle("active", b.dataset.view === name);
    });
    setBanner("");
    const content = document.getElementById("content");
    content.innerHTML = "";
    if (!state.projectId && name !== "status") {
      content.innerHTML = `<div class="card">需要先注册项目。</div>`;
      return;
    }
    const fn = { search: renderSearch, browse: renderBrowse, ingest: renderIngest, chat: renderChat, graph: renderGraph, status: renderStatus }[name];
    if (fn) fn(content);
  }

  // ---------- A. Search ----------
  function renderSearch(root) {
    root.innerHTML = `
      <div class="search-bar">
        <input type="text" id="qInput" placeholder="输入搜索关键词..." autofocus />
        <select id="modeSel">
          <option value="hybrid">混合 (hybrid)</option>
          <option value="keyword">关键词</option>
          <option value="vector">向量</option>
        </select>
        <input type="number" id="topK" value="10" min="1" max="50" />
        <button id="qBtn">搜索</button>
      </div>
      <div id="searchNote" class="card" style="background:#f9fafb;color:#6b7280;font-size:12px;">
        注：当前后端统一走混合检索，模式下拉仅供参考。
      </div>
      <div id="results"></div>
    `;
    const input = document.getElementById("qInput");
    const btn = document.getElementById("qBtn");
    const trigger = () => doSearch();
    btn.addEventListener("click", trigger);
    input.addEventListener("keydown", e => { if (e.key === "Enter") trigger(); });

    async function doSearch() {
      const q = input.value.trim();
      if (!q) { setBanner("请输入关键词", "warn"); return; }
      btn.disabled = true; btn.textContent = "搜索中...";
      setBanner("");
      try {
        const data = await api(`/api/v1/projects/${state.projectId}/search`, {
          method: "POST",
          body: { query: q, topK: parseInt(document.getElementById("topK").value || "10", 10), mode: document.getElementById("modeSel").value },
        });
        renderResults(data.results || []);
      } catch (e) {
        setBanner("搜索失败: " + e.message, "err");
        document.getElementById("results").innerHTML = "";
      } finally {
        btn.disabled = false; btn.textContent = "搜索";
      }
    }

    function renderResults(results) {
      const out = document.getElementById("results");
      if (!results.length) {
        out.innerHTML = `<div class="card">无结果。</div>`;
        return;
      }
      out.innerHTML = results.map((r, i) => {
        const badge = r.source === "semantic"
          ? `<span class="badge badge-semantic">semantic</span>`
          : `<span class="badge badge-keyword">keyword</span>`;
        const displayPath = normalizeWikiPath(r.path);
        return `
          <div class="card" data-idx="${i}">
            <div class="card-title">${escapeHtml(r.title || displayPath)}</div>
            <div class="card-meta">${badge} <span>score ${(r.score ?? 0).toFixed(3)}</span></div>
            <div class="card-snippet">${escapeHtml(r.content || "")}</div>
            <div class="card-path">${escapeHtml(displayPath)}</div>
            <div class="fulltext" id="ft-${i}" style="display:none;margin-top:12px;padding-top:12px;border-top:1px solid #e5e7eb;"></div>
          </div>
        `;
      }).join("");
      // bind click on each card to expand full content
      out.querySelectorAll(".card").forEach(card => {
        card.addEventListener("click", async (ev) => {
          // avoid double-fire when clicking inside fulltext
          if (ev.target.closest(".fulltext")) return;
          const idx = card.dataset.idx;
          const ft = document.getElementById(`ft-${idx}`);
          if (!ft) return;
          if (ft.style.display !== "none") { ft.style.display = "none"; return; }
          const path = results[idx].path;
          ft.innerHTML = "加载中...";
          ft.style.display = "block";
          try {
            const stripped = normalizeWikiPath(path);
            const fc = await api(`/api/v1/projects/${state.projectId}/files/content?path=${encodeURIComponent(stripped)}`);
            const { fm, body } = parseFrontmatter(fc.content || "");
            ft.innerHTML = renderFrontmatter(fm) + `<div class="reader-body">${renderMd(body)}</div>`;
          } catch (e) {
            ft.innerHTML = `<div class="banner-err">加载失败: ${escapeHtml(e.message)}</div>`;
          }
        });
      });
    }
  }

  // ---------- B. Browse ----------
  function renderBrowse(root) {
    root.innerHTML = `
      <div class="browse-grid">
        <div class="browse-tree" id="tree"><div class="card">加载中...</div></div>
        <div class="browse-reader" id="reader"><div style="color:#6b7280;">从左侧选择一个文件。</div></div>
      </div>
    `;
    loadTree();

    async function loadTree() {
      try {
        const data = await api(`/api/v1/projects/${state.projectId}/files?root=wiki&recursive=true&max_files=2000`);
        const files = (data.files || []).filter(f => !f.isDir && f.path.endsWith(".md"));
        renderTree(files);
      } catch (e) {
        document.getElementById("tree").innerHTML = `<div class="banner-err">列表加载失败: ${escapeHtml(e.message)}</div>`;
      }
    }

    function renderTree(files) {
      // Group: system (index.md/log.md) + first-level subdir under wiki/.
      // Normalize absolute paths to wiki-relative first.
      const groups = new Map();
      for (const f of files) {
        const rel = normalizeWikiPath(f.path || "");
        if (!rel.endsWith(".md")) continue;
        const parts = rel.split("/");
        let groupKey;
        if (parts.length === 1) groupKey = "系统";          // index.md, log.md
        else groupKey = parts[0];                            // concepts / sources / ...
        if (!groups.has(groupKey)) groups.set(groupKey, []);
        groups.get(groupKey).push({ path: rel, name: parts[parts.length - 1] });
      }
      // sort groups: 系统 first, then others alphabetically
      const sortedKeys = Array.from(groups.keys()).sort((a, b) => {
        if (a === "系统") return -1; if (b === "系统") return 1;
        return a.localeCompare(b);
      });
      const tree = document.getElementById("tree");
      tree.innerHTML = sortedKeys.map(gk => `
        <div class="tree-group">
          <div class="tree-group-title">${escapeHtml(gk)}</div>
          <div class="tree-files">
            ${groups.get(gk).sort((a, b) => a.name.localeCompare(b.name)).map(f => {
              const disp = f.name.replace(/\.md$/, "");
              return `<div class="tree-file" data-path="${escapeHtml(f.path)}">${escapeHtml(disp)}</div>`;
            }).join("")}
          </div>
        </div>
      `).join("");
      // group toggle
      tree.querySelectorAll(".tree-group-title").forEach(t => {
        t.addEventListener("click", () => t.parentElement.classList.toggle("collapsed"));
      });
      // file click
      tree.querySelectorAll(".tree-file").forEach(el => {
        el.addEventListener("click", () => {
          tree.querySelectorAll(".tree-file").forEach(x => x.classList.remove("active"));
          el.classList.add("active");
          loadReader(el.dataset.path);
        });
      });

      // If we navigated here with a pending target (e.g., from a chat ref),
      // pre-select that file once the tree is built.
      const target = state.pendingBrowseTarget;
      if (target) {
        state.pendingBrowseTarget = null;
        const node = tree.querySelector(`.tree-file[data-path="${CSS.escape(target)}"]`);
        if (node) {
          // ensure the group is expanded
          let p = node.parentElement;
          while (p && !p.classList.contains("tree-group")) p = p.parentElement;
          if (p) p.classList.remove("collapsed");
          node.click();
        }
      }
    }

    async function loadReader(path) {
      const reader = document.getElementById("reader");
      reader.innerHTML = `<div style="color:#6b7280;">加载中...</div>`;
      try {
        const stripped = normalizeWikiPath(path);
        const fc = await api(`/api/v1/projects/${state.projectId}/files/content?path=${encodeURIComponent(stripped)}`);
        const { fm, body } = parseFrontmatter(fc.content || "");
        reader.innerHTML = renderFrontmatter(fm) + `<div class="reader-body">${renderMd(body)}</div>`;
      } catch (e) {
        reader.innerHTML = `<div class="banner-err">读取失败: ${escapeHtml(e.message)}</div>`;
      }
    }
  }

  // ---------- C. Ingest ----------
  function renderIngest(root) {
    root.innerHTML = `
      <div class="ingest-card">
        <h2>摄取</h2>
        <p style="color:#6b7280;">提交一个 URL 或一个本地文件的绝对路径，系统会把内容加入知识库。后台异步处理，本页只显示是否成功入队。</p>
        <input type="text" class="ingest-input" id="srcInput" placeholder="https://... 或 C:\\path\\to\\file.md" />
        <div>
          <button class="ingest-btn" id="ingBtn">提交摄取</button>
        </div>
        <div class="ingest-result" id="ingResult"></div>
        <div class="ingest-hint">注：仅支持单个 URL 或单个文件路径；文件夹摄取暂未接线。</div>
      </div>
    `;
    document.getElementById("ingBtn").addEventListener("click", submit);
    document.getElementById("srcInput").addEventListener("keydown", e => { if (e.key === "Enter") submit(); });

    async function submit() {
      const src = document.getElementById("srcInput").value.trim();
      const out = document.getElementById("ingResult");
      if (!src) { out.innerHTML = `<div class="banner-warn">请输入 URL 或文件路径。</div>`; return; }
      const btn = document.getElementById("ingBtn");
      btn.disabled = true; btn.textContent = "提交中...";
      out.innerHTML = "";
      try {
        const r = await api(`/api/v1/projects/${state.projectId}/ingest`, {
          method: "POST",
          body: { source: src, folderContext: null },
        });
        if (r.status === "ignored") {
          out.innerHTML = `<div class="banner-warn">已存在，已跳过（reason=${escapeHtml(r.reason || "Duplicate")}）。</div>`;
          return;
        }
        if (r.status !== "queued" || !r.taskId) {
          out.innerHTML = `<div class="banner-warn">未识别状态: ${escapeHtml(JSON.stringify(r))}</div>`;
          return;
        }
        // 14.1: render an in-place progress panel and poll until terminal.
        const panel = document.createElement("div");
        panel.className = "ingest-progress";
        panel.dataset.taskId = r.taskId;
        panel.innerHTML = `
          <div class="banner-ok">已入队 (taskId=${escapeHtml(r.taskId)})</div>
          <div class="progress-row">
            <div class="progress-bar"><div class="progress-fill" style="width:0%"></div></div>
            <span class="progress-status">queued</span>
          </div>
          <div class="progress-stages"></div>
        `;
        out.appendChild(panel);
        const fill = panel.querySelector(".progress-fill");
        const statusEl = panel.querySelector(".progress-status");
        const stagesEl = panel.querySelector(".progress-stages");

        const POLL_MS = 1500;
        const MAX_POLLS = 240;  // ~6 min cap
        for (let i = 0; i < MAX_POLLS; i++) {
          await new Promise(r => setTimeout(r, POLL_MS));
          let rec;
          try {
            rec = await api(`/api/v1/projects/${state.projectId}/ingest/status/${encodeURIComponent(r.taskId)}`);
          } catch (e) {
            // 404 (pruned) or transient error — show last status, stop polling.
            statusEl.textContent = "查询失败: " + e.message;
            break;
          }
          statusEl.textContent = rec.status;
          const stages = Array.isArray(rec.stages) ? rec.stages : [];
          stagesEl.innerHTML = stages.length
            ? stages.map(s => `<span class="stage-badge">${escapeHtml(s.name)}</span>`).join(" · ")
            : "<span style='color:#9ca3af'>等待阶段事件...</span>";
          // Heuristic progress bar: 0% queued, 30% collector, 60% processor, 100% done
          const pct = ({
            queued: 5, running: 30, finished: 100,
            succeeded: 100, failed: 100, ignored: 100,
          }[rec.status]) ?? (stages.length >= 3 ? 95 : stages.length === 2 ? 70 : stages.length === 1 ? 40 : 30);
          fill.style.width = pct + "%";
          if (rec.status === "succeeded" || rec.status === "failed") {
            if (rec.status === "succeeded") {
              panel.querySelector(".banner-ok").outerHTML = `<div class="banner-ok">✓ 摄取完成</div>`;
            } else {
              const msg = rec.error ? `: ${escapeHtml(rec.error)}` : "";
              panel.querySelector(".banner-ok").outerHTML = `<div class="banner-err">✗ 摄取失败${msg}</div>`;
            }
            break;
          }
        }
      } catch (e) {
        out.innerHTML = `<div class="banner-err">摄取失败: ${escapeHtml(e.message)}</div>`;
      } finally {
        btn.disabled = false; btn.textContent = "提交摄取";
      }
    }
  }

  // ---------- D. Chat ----------
  // Session state persists across view switches (Bug fix #13).
  // In-flight requests are aborted if the user navigates away (Bug fix #14).
  function renderChat(root) {
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
    let inflight = null;  // AbortController for the current request

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
      appendMsg("user", escapeHtml(msg).replace(/\n/g, "<br>"));
      const placeholder = appendMsg("thinking", "思考中...");
      btn.disabled = true;
      const controller = new AbortController();
      inflight = controller;
      try {
        const r = await api(`/api/v1/projects/${state.projectId}/chat`, {
          method: "POST",
          body: { message: msg, sessionId: state.sessionId },
          signal: controller.signal,
        });
        inflight = null;
        // If the user navigated away while we were waiting, the placeholder is
        // detached. Bail out silently — the response is effectively dropped.
        if (!placeholder.isConnected) return;
        state.sessionId = r.sessionId || state.sessionId;
        placeholder.classList.remove("thinking");
        const bubble = placeholder.querySelector(".chat-bubble");
        bubble.innerHTML = renderMd(r.message && r.message.content || "");
        // references (14.7 citations panel)
        if (Array.isArray(r.references) && r.references.length) {
          const refsHtml = `<div class="citations-panel"><div class="citations-title">引用 (${r.references.length})</div>${
            r.references.map(ref => {
              const raw = ref.path || "";
              const norm = normalizeWikiPath(raw);
              const title = ref.title || norm || "(无标题)";
              const snippet = (ref.content || ref.snippet || "").slice(0, 180);
              const score = typeof ref.score === "number" ? `score ${ref.score.toFixed(2)}` : "";
              return `<div class="citation-card" data-path="${escapeHtml(norm)}">
                <div class="citation-title">${escapeHtml(title)}</div>
                <div class="citation-path">${escapeHtml(norm)} ${score ? `<span class="citation-score">${escapeHtml(score)}</span>` : ""}</div>
                ${snippet ? `<div class="citation-snippet">${escapeHtml(snippet)}</div>` : ""}
              </div>`;
            }).join("")
          }</div>`;
          bubble.insertAdjacentHTML("beforeend", refsHtml);
          bubble.querySelectorAll(".citation-card").forEach(el => {
            el.addEventListener("click", () => {
              const target = el.dataset.path;
              if (!target) return;
              state.pendingBrowseTarget = target;
              showView("browse");
            });
          });
        }
        // usage meta
        if (r.usage) {
          bubble.insertAdjacentHTML("beforeend",
            `<div class="chat-meta">iterations=${r.usage.iterations ?? "?"} · toolCalls=${r.usage.toolCalls ?? "?"}</div>`);
        }
      } catch (e) {
        if (!placeholder.isConnected) return;  // navigated away
        if (e.name === "AbortError") return;    // intentional cancel
        placeholder.classList.remove("thinking");
        placeholder.classList.add("error");
        placeholder.querySelector(".chat-bubble").textContent = "失败: " + e.message;
      } finally {
        inflight = null;
        btn.disabled = false;
        if (input.isConnected) input.focus();
      }
    }

    // Abort the in-flight request when the user navigates away.
    // showView() runs BEFORE content.innerHTML is cleared, so we attach the
    // abort handler at the document level: a click on a nav button means the
    // user is leaving chat.
    document.addEventListener("click", function abortOnNav(e) {
      const nav = e.target.closest && e.target.closest(".nav-btn");
      if (!nav || nav.dataset.view === "chat") return;
      if (inflight) { inflight.abort(); inflight = null; }
    });
  }

  // ---------- G. Wiki Graph (14.4) ----------
  // SVG-based force-directed graph. Layout is a simple Fruchterman-Reingold
  // variant run for a fixed number of iterations on each load. Click a node
  // to jump to that page in browse view.
  function renderGraph(root) {
    root.innerHTML = `
      <div class="graph-toolbar">
        <span id="graphStats">加载中...</span>
        <span class="graph-legend">
          <span class="legend-item"><span class="legend-dot" style="background:#2563eb"></span>concept</span>
          <span class="legend-item"><span class="legend-dot" style="background:#16a34a"></span>entity</span>
          <span class="legend-item"><span class="legend-dot" style="background:#d97706"></span>source</span>
          <span class="legend-item"><span class="legend-dot" style="background:#6b7280"></span>other</span>
        </span>
      </div>
      <div class="graph-canvas-wrap"><svg id="graphSvg" class="graph-canvas"></svg></div>
    `;
    const svg = root.querySelector("#graphSvg");
    api(`/api/v1/projects/${state.projectId}/wiki/graph`)
      .then(g => {
        root.querySelector("#graphStats").textContent =
          `${g.counts.nodes} 节点 / ${g.counts.edges} 关系`;
        drawGraph(svg, g);
      })
      .catch(e => {
        root.querySelector("#graphStats").textContent = "加载失败: " + e.message;
      });
  }

  function drawGraph(svg, g) {
    const width = svg.clientWidth || 800;
    const height = svg.clientHeight || 600;
    svg.setAttribute("viewBox", `0 0 ${width} ${height}`);
    svg.innerHTML = "";

    // Initial position: random in a circle.
    const cx = width / 2, cy = height / 2;
    const R = Math.min(width, height) * 0.35;
    const nodes = g.nodes.map((n, i) => ({
      ...n,
      x: cx + R * Math.cos(2 * Math.PI * i / g.nodes.length),
      y: cy + R * Math.sin(2 * Math.PI * i / g.nodes.length),
      vx: 0, vy: 0,
    }));
    const nodeById = new Map(nodes.map(n => [n.id, n]));
    const edges = g.edges.filter(e => nodeById.has(e.source) && nodeById.has(e.target));

    const TYPE_COLOR = {
      concept: "#2563eb",
      entity:  "#16a34a",
      source:  "#d97706",
      synthesis: "#9333ea",
    };
    function color(n) { return TYPE_COLOR[n.type] || "#6b7280"; }

    // Build SVG defs for arrowheads.
    const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
    defs.innerHTML = `<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5"
        markerWidth="6" markerHeight="6" orient="auto-start-reverse">
      <path d="M 0 0 L 10 5 L 0 10 z" fill="#9ca3af" />
    </marker>`;
    svg.appendChild(defs);

    // Edge layer
    const edgesG = document.createElementNS("http://www.w3.org/2000/svg", "g");
    svg.appendChild(edgesG);
    // Node layer
    const nodesG = document.createElementNS("http://www.w3.org/2000/svg", "g");
    svg.appendChild(nodesG);

    function renderEdges() {
      edgesG.innerHTML = "";
      for (const e of edges) {
        const s = nodeById.get(e.source), t = nodeById.get(e.target);
        const ln = document.createElementNS("http://www.w3.org/2000/svg", "line");
        ln.setAttribute("x1", s.x); ln.setAttribute("y1", s.y);
        ln.setAttribute("x2", t.x); ln.setAttribute("y2", t.y);
        ln.setAttribute("stroke", "#9ca3af");
        ln.setAttribute("stroke-width", String(Math.min(2.5, Math.max(0.5, e.weight || 1))));
        ln.setAttribute("opacity", "0.45");
        ln.setAttribute("marker-end", "url(#arrow)");
        edgesG.appendChild(ln);
      }
    }

    function renderNodes() {
      nodesG.innerHTML = "";
      for (const n of nodes) {
        const g_el = document.createElementNS("http://www.w3.org/2000/svg", "g");
        g_el.setAttribute("transform", `translate(${n.x},${n.y})`);
        g_el.style.cursor = "pointer";
        const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        c.setAttribute("r", "8");
        c.setAttribute("fill", color(n));
        c.setAttribute("stroke", "#ffffff"); c.setAttribute("stroke-width", "1.5");
        const t = document.createElementNS("http://www.w3.org/2000/svg", "title");
        t.textContent = n.title + (n.type ? ` (${n.type})` : "");
        g_el.appendChild(c); g_el.appendChild(t);
        const txt = document.createElementNS("http://www.w3.org/2000/svg", "text");
        txt.setAttribute("x", 11); txt.setAttribute("y", 4);
        txt.setAttribute("font-size", "10"); txt.setAttribute("fill", "#1f2329");
        txt.textContent = (n.title || n.id).slice(0, 22);
        g_el.appendChild(txt);
        g_el.addEventListener("click", () => {
          state.pendingBrowseTarget = n.path;
          showView("browse");
        });
        nodesG.appendChild(g_el);
      }
    }

    // Simple Fruchterman-Reingold style iterations.
    const iterations = 120;
    const area = width * height;
    const k = Math.sqrt(area / Math.max(1, nodes.length)) * 0.6;  // ideal distance
    let temperature = Math.min(width, height) * 0.1;

    function step() {
      // Repulsive (between all pairs)
      for (let i = 0; i < nodes.length; i++) {
        nodes[i].vx = 0; nodes[i].vy = 0;
        for (let j = 0; j < nodes.length; j++) {
          if (i === j) continue;
          const dx = nodes[i].x - nodes[j].x;
          const dy = nodes[i].y - nodes[j].y;
          const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
          const rep = (k * k) / dist;
          nodes[i].vx += (dx / dist) * rep;
          nodes[i].vy += (dy / dist) * rep;
        }
      }
      // Attractive (along edges)
      for (const e of edges) {
        const s = nodeById.get(e.source), t = nodeById.get(e.target);
        const dx = s.x - t.x, dy = s.y - t.y;
        const dist = Math.sqrt(dx * dx + dy * dy) || 0.01;
        const attr = (dist * dist) / k;
        const ux = dx / dist, uy = dy / dist;
        s.vx -= ux * attr; s.vy -= uy * attr;
        t.vx += ux * attr; t.vy += uy * attr;
      }
      // Apply with temperature, clamped to viewport, recenter drift
      let mx = 0, my = 0;
      for (const n of nodes) {
        const disp = Math.sqrt(n.vx * n.vx + n.vy * n.vy) || 0.01;
        const capped = Math.min(disp, temperature) / disp;
        n.x += n.vx * capped; n.y += n.vy * capped;
        n.x = Math.max(20, Math.min(width - 20, n.x));
        n.y = Math.max(20, Math.min(height - 20, n.y));
        mx += n.x; my += n.y;
      }
      // Re-center if drift detected
      mx /= nodes.length; my /= nodes.length;
      const dxC = cx - mx, dyC = cy - my;
      if (Math.abs(dxC) > 1 || Math.abs(dyC) > 1) {
        for (const n of nodes) { n.x += dxC; n.y += dyC; }
      }
      temperature *= 0.97;
    }

    let frame = 0;
    function animate() {
      if (frame++ >= iterations) {
        renderEdges(); renderNodes();
        return;
      }
      step();
      if (frame % 4 === 0) {  // redraw every 4 steps for speed
        renderEdges(); renderNodes();
      }
      requestAnimationFrame(animate);
    }
    renderEdges(); renderNodes();
    requestAnimationFrame(animate);
  }

  // ---------- E. Status ----------
  function renderStatus(root) {
    root.innerHTML = `
      <div class="status-toolbar"><button id="refreshBtn">刷新</button></div>
      <div class="status-grid" id="statusGrid">
        <div class="stat-card">加载中...</div>
      </div>
    `;
    document.getElementById("refreshBtn").addEventListener("click", () => renderStatus(root));
    loadAll();

    async function loadAll() {
      const grid = document.getElementById("statusGrid");
      grid.innerHTML = `<div class="stat-card">加载中...</div>`;
      // Fire all in parallel; tolerate individual failures.
      const tasks = {
        health: api("/health").catch(e => ({ __err: e.message })),
        project: api(`/api/v1/projects/${state.projectId}`).catch(e => ({ __err: e.message })),
        files:   api(`/api/v1/projects/${state.projectId}/files?root=wiki`).catch(e => ({ __err: e.message })),
        reviews: api(`/api/v1/projects/${state.projectId}/reviews?status=open`).catch(e => ({ __err: e.message })),
        schema:  api(`/api/v1/projects/${state.projectId}/schema`).catch(e => ({ __err: e.message })),
        lint:    api(`/api/v1/projects/${state.projectId}/lint`).catch(e => ({ __err: e.message })),
      };
      const [health, project, files, reviews, schema, lint] = await Promise.all(Object.values(tasks));
      grid.innerHTML = "";

      grid.insertAdjacentHTML("beforeend", statCard("服务健康", [
        ["ok", health.__err ? "❌ " + health.__err : (health.ok ? "true" : "false")],
        ["status", health.__err ? "-" : (health.status || "-")],
        ["version", health.__err ? "-" : (health.version || "-")],
        ["agent.chat", health.__err ? "-" : (health.agent && health.agent.chat)],
        ["agent.streaming", health.__err ? "-" : (health.agent && health.agent.streaming)],
      ]));

      grid.insertAdjacentHTML("beforeend", statCard("项目", [
        ["name", project.__err ? "-" : (project.name || "-")],
        ["id", project.__err ? "-" : (project.id || "-")],
        ["path", project.__err ? "-" : (project.path || "-")],
        ["schema_version", project.__err ? "-" : (project.schema_version || "-")],
        ["last_opened", project.__err ? "-" : formatTime(project.last_opened)],
      ]));

      grid.insertAdjacentHTML("beforeend", statCard("统计", [
        ["wiki 页面总数", files.__err ? "-" : (files.totalCount ?? "-")],
        ["待审核数", reviews.__err ? "-" : (reviews.count ?? "-")],
      ]));

      const migrations = (schema.__err || !Array.isArray(schema.schemas)) ? []
        : schema.schemas.map(s => `${s.schema} (${s.from}→${s.to})`);
      grid.insertAdjacentHTML("beforeend", statCard("Schema", [
        ["current", schema.__err ? "-" : (schema.schema_version || "-")],
        ["迁移", schema.__err ? "-" : (migrations.join(", ") || "(无)")],
      ]));

      // Lint card (14.5)
      if (!lint.__err && lint.summary) {
        const s = lint.summary;
        const rows = [
          ["节点", s.nodes],
          ["关系", s.edges],
          ["孤立页", s.orphans],
          ["悬空引用", s.dangling],
        ];
        grid.insertAdjacentHTML("beforeend", statCard("Lint (14.5)", rows));
        // Detailed issue list
        const detail = `<div class="stat-card"><h3>Lint 明细</h3>
          ${lint.orphans && lint.orphans.length ? `
            <div class="lint-section">孤儿页 (${lint.orphans.length})</div>
            <ul class="lint-list">${lint.orphans.slice(0, 8).map(o => `<li><code>${escapeHtml(o.id)}</code> — ${escapeHtml(o.title || "")}</li>`).join("")}</ul>
          ` : ""}
          ${lint.dangling && lint.dangling.length ? `
            <div class="lint-section">悬空引用 (${lint.dangling.length})</div>
            <ul class="lint-list">${lint.dangling.slice(0, 8).map(d => `<li><code>${escapeHtml(d.source)}</code> → <code>${escapeHtml(d.target)}</code> (${escapeHtml(d.type || "?")})</li>`).join("")}</ul>
          ` : ""}
        </div>`;
        grid.insertAdjacentHTML("beforeend", detail);
      } else if (lint.__err) {
        grid.insertAdjacentHTML("beforeend", statCard("Lint (14.5)", [["错误", lint.__err]]));
      }
    }

    function statCard(title, rows) {
      return `<div class="stat-card"><h3>${escapeHtml(title)}</h3>${rows.map(([k, v]) =>
        `<div class="stat-row"><span class="stat-key">${escapeHtml(k)}</span><span class="stat-val">${escapeHtml(String(v))}</span></div>`
      ).join("")}</div>`;
    }

    function formatTime(ms) {
      if (!ms) return "-";
      try { return new Date(ms).toLocaleString(); } catch { return String(ms); }
    }
  }

  // ---------- Wire up nav ----------
  document.getElementById("nav").addEventListener("click", e => {
    const btn = e.target.closest(".nav-btn");
    if (!btn) return;
    showView(btn.dataset.view);
  });

  // ---------- Intercept wiki-internal links ----------
  // Markdown rendered by marked produces <a href="other.md"> for internal
  // links. Without this handler, clicking such a link triggers a full-page
  // navigation to e.g. http://127.0.0.1:8765/other.md, which 404s and loses
  // the SPA shell. We route the link through browse instead.
  document.addEventListener("click", e => {
    const a = e.target.closest && e.target.closest("a[href]");
    if (!a) return;
    const href = a.getAttribute("href") || "";
    // Only intercept plain .md links (relative or absolute wiki path).
    if (!/\.md(\?|#|$)/.test(href)) return;
    e.preventDefault();
    const normalized = normalizeWikiPath(href.split("#")[0].split("?")[0]);
    if (!normalized) return;
    state.pendingBrowseTarget = normalized;
    showView("browse");
  });

  // ---------- F. Agent Panel (right side, persistent) ----------
  // SPEC: FRONTEND_DESIGN.md §4.4 / §5.7 / §7F.
  // The panel is mounted once on boot and survives view switches. Status is
  // probed at boot; chat uses fetch + ReadableStream to consume SSE.
  setupAgentPanel();

  function setupAgentPanel() {
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
      input.disabled = !on || state.agentBusy;
      sendBtn.disabled = !on || state.agentBusy;
    }

    function setStatus(available, info) {
      state.agentAvailable = available;
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
      return appendMsg("user", `<div class="agent-bubble user-bubble">${escapeHtml(text).replace(/\n/g,"<br>")}</div>`);
    }
    function appendAssistantPlaceholder() {
      return appendMsg("assistant", `<div class="agent-bubble assistant-bubble thinking">Claude 思考中… (可能数十秒)</div>`, "assistant");
    }
    function appendToolBadge(name) {
      return appendMsg("tool", `<span class="agent-tool">🔧 ${escapeHtml(name)}</span>`);
    }
    function appendUsage(inTok, outTok) {
      return appendMsg("usage", `<span class="agent-usage">${inTok} in / ${outTok} out</span>`);
    }

    // ---- Boot probe ----
    api("/api/v1/agent-cli/status").then(r => setStatus(!!r.available, r)).catch(() => setStatus(false, {error: "探测失败"}));

    // ---- New session ----
    newBtn.addEventListener("click", () => {
      state.agentSessionId = null;
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
      if (state.agentBusy) return;
      const msg = input.value.trim();
      if (!msg) return;
      input.value = "";
      appendUserBubble(msg);
      const placeholder = appendAssistantPlaceholder();
      state.agentBusy = true;
      setEnabled(state.agentAvailable);
      // Track the bubble we'll fill with the streamed reply.
      let bubble = placeholder.querySelector(".agent-bubble");
      let streamed = "";  // accumulated visible text

      const controller = new AbortController();
      try {
        const res = await fetch(window.location.origin + "/api/v1/agent-cli/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message: msg, sessionId: state.agentSessionId }),
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
        // Parse SSE frames separated by blank lines.
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
        state.agentBusy = false;
        setEnabled(state.agentAvailable);
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
          bubble.innerHTML = renderMd(streamed);
          list.scrollTop = list.scrollHeight;
          return;
        }
        if (event === "thinking_delta") {
          // Surface thinking as a subtle italic bubble above the main reply.
          const existing = placeholder.previousElementSibling;
          if (existing && existing.classList && existing.classList.contains("agent-msg") && existing.dataset.thinking) {
            existing.querySelector(".agent-bubble").textContent += data.delta || "";
          } else {
            const w = document.createElement("div");
            w.className = "agent-msg assistant";
            w.dataset.thinking = "1";
            w.innerHTML = `<div class="agent-bubble assistant-bubble thinking">${escapeHtml(data.delta || "")}</div>`;
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
          if (data.sessionId) state.agentSessionId = data.sessionId;
          if (data.fullText) {
            streamed = data.fullText;
            bubble.innerHTML = renderMd(streamed);
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
  }

  // ---------- Go ----------
  boot();
})();