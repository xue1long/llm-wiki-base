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
    // All registered projects (cached after boot)
    projects: [],
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
      // Fetch all projects, sorted by last_opened desc.
      const data = await api("/api/v1/projects");
      const list = data.projects || [];
      state.projects = list;
      if (!list.length) {
        setBanner("未找到已注册项目，请先新建项目", "err");
        document.getElementById("projectName").textContent = "(无项目)";
        return;
      }
      // Pick the first one (already sorted by last_opened desc).
      const chosen = list[0];
      state.projectId = chosen.id;
      state.projectName = chosen.name;
      document.getElementById("projectName").textContent = state.projectName;

      // Populate project selector and show it.
      const sel = document.getElementById("projectSelect");
      sel.innerHTML = list.map(p =>
        `<option value="${escapeHtml(p.id)}" ${p.id === chosen.id ? "selected" : ""}>${escapeHtml(p.name)}</option>`
      ).join("");
      sel.style.display = "block";
      document.getElementById("newProjectBtn").style.display = "inline-block";
      sel.addEventListener("change", () => switchProject(sel.value));
      document.getElementById("newProjectBtn").addEventListener("click", async () => {
        const name = window.prompt("输入项目名称：");
        if (!name || !name.trim()) return;
        try {
          await createProject(name.trim());
        } catch (e) {
          setBanner("创建失败: " + e.message, "err");
        }
      });

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

  // ---------- Project switch ----------
  async function switchProject(id) {
    const chosen = state.projects.find(p => p.id === id);
    if (!chosen) return;
    state.projectId = chosen.id;
    state.projectName = chosen.name;
    document.getElementById("projectName").textContent = state.projectName;
    state.sessionId = null;
    state.pendingBrowseTarget = null;
    try {
      await api(`/api/v1/projects/${id}/select`, { method: "POST" });
    } catch (e) {
      // non-fatal: the switch still works client-side
    }
    showView(state.currentView);
  }

  // ---------- New project ----------
  async function createProject(name) {
    const result = await api("/api/v1/projects", {
      method: "POST",
      body: { name },
    });
    const newProject = { id: result.id, name: result.name, path: result.path, last_opened: Date.now() };
    state.projects.unshift(newProject);
    const sel = document.getElementById("projectSelect");
    sel.insertBefore(
      Object.assign(document.createElement("option"), { value: newProject.id, textContent: newProject.name, selected: true }),
      sel.firstChild
    );
    sel.value = newProject.id;
    await switchProject(newProject.id);
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
    const fn = { search: renderSearch, browse: renderBrowse, ingest: renderIngest, chat: renderChat, graph: renderGraph, status: renderStatus, settings: renderSettings }[name];
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
  // Sub-view state: "wiki" or "raw"
  let _browseSub = "wiki";

  function renderBrowse(root) {
    root.innerHTML = `
      <div class="browse-tabs">
        <button class="browse-tab-btn active" data-sub="wiki">Wiki 文件</button>
        <button class="browse-tab-btn" data-sub="raw">Raw 文件</button>
        <div style="margin-left:auto;display:flex;gap:6px;">
          <button id="refreshRawBtn" style="display:none;" class="btn-sm">刷新</button>
          <button id="ingestAllRawBtn" style="display:none;" class="btn-primary">全部摄取</button>
        </div>
      </div>
      <div class="browse-grid">
        <div class="browse-tree" id="tree"><div class="card">加载中...</div></div>
        <div class="browse-reader" id="reader"><div style="color:#6b7280;">从左侧选择一个文件。</div></div>
      </div>
    `;
    document.querySelectorAll(".browse-tab-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        _browseSub = btn.dataset.sub;
        document.querySelectorAll(".browse-tab-btn").forEach(b => b.classList.toggle("active", b === btn));
        const isRaw = _browseSub === "raw";
        document.getElementById("ingestAllRawBtn").style.display = isRaw ? "inline-block" : "none";
        document.getElementById("refreshRawBtn").style.display = isRaw ? "inline-block" : "none";
        if (_browseSub === "wiki") loadTree();
        else renderBrowseRaw();
      });
    });

    // Refresh raw files list
    document.getElementById("refreshRawBtn").addEventListener("click", () => {
      if (_browseSub === "raw") renderBrowseRaw();
    });

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
      const groups = new Map();
      for (const f of files) {
        const rel = normalizeWikiPath(f.path || "");
        if (!rel.endsWith(".md")) continue;
        const parts = rel.split("/");
        const groupKey = parts.length === 1 ? "系统" : parts[0];
        if (!groups.has(groupKey)) groups.set(groupKey, []);
        groups.get(groupKey).push({ path: rel, name: parts[parts.length - 1] });
      }
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
      tree.querySelectorAll(".tree-group-title").forEach(t => {
        t.addEventListener("click", () => t.parentElement.classList.toggle("collapsed"));
      });
      tree.querySelectorAll(".tree-file").forEach(el => {
        el.addEventListener("click", () => {
          tree.querySelectorAll(".tree-file").forEach(x => x.classList.remove("active"));
          el.classList.add("active");
          loadReader(el.dataset.path);
        });
      });
      const target = state.pendingBrowseTarget;
      if (target) {
        state.pendingBrowseTarget = null;
        const node = tree.querySelector(`.tree-file[data-path="${CSS.escape(target)}"]`);
        if (node) {
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

  // ---------- B2. Raw Files ----------
  async function renderBrowseRaw() {
    const tree = document.getElementById("tree");
    const reader = document.getElementById("reader");
    reader.innerHTML = `<div style="color:#6b7280;">从左侧选择要摄取的文件。</div>`;
    tree.innerHTML = `<div class="card">加载中...</div>`;

    let rawFiles = [];
    try {
      const data = await api(`/api/v1/projects/${state.projectId}/raw-files`);
      rawFiles = data.files || [];
    } catch (e) {
      tree.innerHTML = `<div class="banner-err">加载失败: ${escapeHtml(e.message)}</div>`;
      return;
    }

    if (!rawFiles.length) {
      tree.innerHTML = `<div class="card">raw/sources 目录为空。</div>`;
      return;
    }

    tree.innerHTML = `
      <div id="rawFileList">
        ${rawFiles.map((f, i) => `
          <div class="raw-file-row" data-idx="${i}">
            <div class="raw-file-info">
              <div class="raw-file-name">${escapeHtml(f.name)}</div>
              <div class="raw-file-meta">${escapeHtml(f.ext)} · ${formatSize(f.size)}</div>
            </div>
            <div class="raw-file-actions" id="rawAction-${i}">
              ${f.ingested
                ? `<span class="badge badge-ingested">已摄取</span>`
                : `<button class="btn-ingest-one" data-path="${escapeHtml(f.path)}">摄取</button>`
              }
            </div>
          </div>
        `).join("")}
      </div>
    `;

    // Single file ingest
    tree.querySelectorAll(".btn-ingest-one").forEach(btn => {
      btn.addEventListener("click", async (e) => {
        e.stopPropagation();
        const path = btn.dataset.path;
        const row = btn.closest(".raw-file-row");
        const action = row.querySelector(".raw-file-actions");
        const progId = "prog-" + Math.random().toString(36).slice(2, 8);
        action.innerHTML = `
          <div id="${progId}" class="ingest-progress" style="margin-top:0; min-width:160px;">
            <div class="progress-row" style="align-items:center;">
              <div class="progress-bar" style="flex:1; height:6px; border-radius:3px;">
                <div class="progress-fill" style="height:6px; border-radius:3px; width:5%; transition:width 0.3s;"></div>
              </div>
              <span class="progress-status" style="font-size:11px; margin-left:8px; white-space:nowrap;">queued</span>
            </div>
          </div>`;
        const prog = document.getElementById(progId);
        const fill = prog.querySelector(".progress-fill");
        const statusEl = prog.querySelector(".progress-status");

        await ingestOneRaw(path, () => {
          action.innerHTML = `<span class="badge badge-ingested">已摄取</span>`;
        }, (err) => {
          prog.innerHTML = `<span class="badge badge-err" title="\${err}">失败</span>`;
          setTimeout(() => {
            action.innerHTML = `<button class="btn-ingest-one" data-path="\${escapeHtml(path)}">重试</button>`;
            action.querySelector(".btn-ingest-one").onclick = arguments.callee;
          }, 2500);
        }, (rec) => {
          const stages = Array.isArray(rec.stages) ? rec.stages : [];
          const stageName = stages.length ? stages[stages.length - 1].name : rec.status;
          statusEl.textContent = stageName || rec.status;
          const pct = ({
            queued: 5, running: 30, finished: 100,
            succeeded: 100, failed: 100, ignored: 100,
          }[rec.status]) ?? (stages.length >= 3 ? 95 : stages.length === 2 ? 70 : stages.length === 1 ? 40 : 30);
          fill.style.width = pct + "%";
        });
      });
    });

    // Batch ingest
    // Batch ingest all
    const ingestAllBtn = document.getElementById("ingestAllRawBtn");
    ingestAllBtn.addEventListener("click", async () => {
      const toIngest = rawFiles.filter(f => !f.ingested);
      if (!toIngest.length) { setBanner("没有需要摄取的文件", "warn"); return; }
      ingestAllBtn.disabled = true; ingestAllBtn.textContent = `摄取中 (0/${toIngest.length})...`;
      let done = 0;
      for (const f of toIngest) {
        await ingestOneRaw(f.path, () => {
          done++;
          ingestAllBtn.textContent = `摄取中 (${done}/${toIngest.length})...`;
          // update row
          const row = tree.querySelector(`.raw-file-row[data-idx="${rawFiles.indexOf(f)}"]`);
          if (row) {
            const action = row.querySelector(".raw-file-actions");
            action.innerHTML = `<span class="badge badge-ingested">已摄取</span>`;
          }
        }, (err) => {
          setBanner(`${f.name} 失败: ${err}`, "err");
        });
      }
      ingestAllBtn.disabled = false; ingestAllBtn.textContent = "全部摄取";
    });
  }

  async function ingestOneRaw(path, onDone, onError, onProgress) {
    try {
      const r = await api(`/api/v1/projects/${state.projectId}/ingest`, {
        method: "POST",
        body: { source: path, folderContext: null },
      });
      if (r.status === "ignored") { onDone(); return; }
      if (r.status !== "queued" || !r.taskId) { onError("未识别状态"); return; }
      const POLL_MS = 1500;
      for (let i = 0; i < 600; i++) {
        await new Promise(res => setTimeout(res, POLL_MS));
        let rec;
        try { rec = await api(`/api/v1/projects/${state.projectId}/ingest/status/${encodeURIComponent(r.taskId)}`); }
        catch { break; }
        if (onProgress) { onProgress(rec); }
        if (rec.status === "succeeded") { onDone(); return; }
        if (rec.status === "failed") { onError(rec.error || "failed"); return; }
        if (i === 239 && rec.status === "running") { i--; continue; }
      }
      onError("超时");
    } catch (e) {
      onError(e.message);
    }
  }

  function formatSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
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


  // ---------- Settings ----------
  function renderSettings(root) {
    root.innerHTML = '<div class="settings-card" id="settingsCard"><h2>LLM 提供商设置</h2><div id="settingsContent">加载中...</div></div>';
    loadSettings();

    async function loadSettings() {
      const out = document.getElementById('settingsContent');
      try {
        const data = await api('/api/v1/providers');
        renderProviderList(data.providers || []);
      } catch(e) {
        out.innerHTML = '<div class="banner-err">加载失败: ' + escapeHtml(e.message) + '</div>';
      }
    }

    function renderProviderList(providers) {
      const out = document.getElementById('settingsContent');
      const hasDefault = providers.some(p => p.is_default);

      let html = '<div class="settings-section"><h3>已配置</h3>';
      if (!providers.length) {
        html += '<p style="color:#6b7280">暂无提供商，请添加。</p>';
      }
      for (const p of providers) {
        const typeLabel = {openai:'OpenAI', anthropic:'Anthropic', ollama:'Ollama'}[p.type] || p.type;
        const model = p.default_chat_model || p.default_embedding_model || '';
        const baseUrl = p.base_url || '';
        html += '<div class="provider-row">'
          + '<div class="provider-info">'
          + '<span class="provider-name">' + escapeHtml(p.name) + '</span>'
          + '<span class="provider-type">' + escapeHtml(typeLabel) + '</span>'
          + (model ? '<span class="provider-model">' + escapeHtml(model) + '</span>' : '')
          + (baseUrl ? '<span class="provider-base-url">' + escapeHtml(baseUrl) + '</span>' : '')
          + (p.is_default ? ' <span class="badge badge-ingested" style="margin-left:6px;">默认</span>' : '')
          + '</div>'
          + '<div class="provider-actions">'
          + (!p.is_default ? '<button class="btn-sm" data-action="set-default" data-name="' + escapeHtml(p.name) + '">设为默认</button>' : '')
          + '<button class="btn-sm btn-danger" data-action="remove" data-name="' + escapeHtml(p.name) + '">删除</button>'
          + '</div></div>';
      }
      html += '</div>';

      // Presets for OpenAI-compatible Chinese providers
      const PROVIDER_PRESETS = {
        '': { base_url: '', model: '', label: '（自定义）' },
        'minimax': { base_url: 'https://api.minimax.chat/v1', model: 'MiniMax-Text-01', label: 'MiniMax' },
        'kimi': { base_url: 'https://api.moonshot.cn/v1', model: 'moonshot-v1-8k', label: 'Kimi / Moonshot' },
        'deepseek': { base_url: 'https://api.deepseek.com/v1', model: 'deepseek-chat', label: 'DeepSeek' },
        'glm': { base_url: 'https://open.bigmodel.cn/api/paas/v4', model: 'glm-4-plus', label: 'GLM / 智谱' },
        'openai': { base_url: 'https://api.openai.com/v1', model: 'gpt-4o', label: 'OpenAI（官方）' },
        'anthropic': { base_url: '', model: '', label: 'Anthropic' },
        'ollama': { base_url: 'http://127.0.0.1:11434', model: '', label: 'Ollama（本地）' },
      };

      html += '<div class="settings-section"><h3>添加提供商</h3>'
        + '<div class="add-provider-form">'
        + '<input id="provName" placeholder="名称" style="width:120px"/>'
        + '<select id="provPreset"><option value="">（选择预设）</option>'
        + Object.entries(PROVIDER_PRESETS).filter(([k]) => k !== '').map(([k, v]) =>
          '<option value="' + k + '">' + v.label + '</option>'
        ).join('')
        + '</select>'
        + '<select id="provType"><option value="openai">OpenAI 兼容</option><option value="anthropic">Anthropic</option><option value="ollama">Ollama</option></select>'
        + '</div>'
        + '<div class="add-provider-form" style="margin-top:6px;">'
        + '<input id="provBaseUrl" placeholder="Base URL（如 https://api.minimax.chat/v1）" style="width:280px"/>'
        + '<input id="provKey" type="password" placeholder="API Key（可留空，从环境变量读取）" style="width:220px"/>'
        + '<input id="provModel" placeholder="模型（如 MiniMax-Text-01）" style="width:160px"/>'
        + '<button class="btn-primary" id="addProvBtn">添加</button>'
        + '<div id="addProvResult" style="margin-top:6px"></div>'
        + '</div></div>';

      html += '<div class="settings-section"><h3>测试连接</h3>'
        + '<div style="display:flex;gap:8px;align-items:center;">'
        + '<select id="testProvName"><option value="">选择提供商...</option>'
        + providers.map(p => '<option value="' + escapeHtml(p.name) + '">' + escapeHtml(p.name) + '</option>').join('')
        + '</select>'
        + '<button class="btn-sm" id="testProvBtn">测试</button>'
        + '<span id="testProvResult" style="margin-left:8px;font-size:13px;"></span>'
        + '</div></div>';

      out.innerHTML = html;

      // Add provider
      // Preset auto-fill
      out.querySelector('#provPreset').addEventListener('change', () => {
        const preset = PROVIDER_PRESETS[out.querySelector('#provPreset').value];
        if (!preset) return;
        const nameEl = document.getElementById('provName');
        if (!nameEl.value.trim()) nameEl.value = out.querySelector('#provPreset').value;
        document.getElementById('provBaseUrl').value = preset.base_url || '';
        document.getElementById('provModel').value = preset.model || '';
        if (preset.label.includes('Anthropic')) {
          document.getElementById('provType').value = 'anthropic';
        } else if (preset.label.includes('Ollama')) {
          document.getElementById('provType').value = 'ollama';
        } else {
          document.getElementById('provType').value = 'openai';
        }
      });

      // Add provider
      out.querySelector('#addProvBtn').addEventListener('click', async () => {
        const name = document.getElementById('provName').value.trim();
        const type = document.getElementById('provType').value;
        const api_key = document.getElementById('provKey').value;
        const base_url = document.getElementById('provBaseUrl').value.trim();
        const model = document.getElementById('provModel').value.trim();
        const result = document.getElementById('addProvResult');
        if (!name) { result.innerHTML = '<span class="banner-warn">请输入名称</span>'; return; }
        result.innerHTML = '添加中...';
        try {
          const r = await api('/api/v1/providers', {
            method: 'POST',
            body: { name, type, api_key, base_url, chat_model: model, embedding_model: model }
          });
          result.innerHTML = '<span class="banner-ok">添加成功</span>';
          loadSettings();
        } catch(e) {
          result.innerHTML = '<span class="banner-err">失败: ' + escapeHtml(e.message) + '</span>';
        }
      });

      // Set default
      out.querySelectorAll('[data-action="set-default"]').forEach(btn => {
        btn.addEventListener('click', async () => {
          const name = btn.dataset.name;
          try {
            await api('/api/v1/providers/set-default', { method:'POST', body:{ name } });
            loadSettings();
          } catch(e) {
            alert('设置默认失败: ' + e.message);
          }
        });
      });

      // Remove
      out.querySelectorAll('[data-action="remove"]').forEach(btn => {
        btn.addEventListener('click', async () => {
          const name = btn.dataset.name;
          if (!confirm('确认删除提供商 ' + name + '？')) return;
          try {
            await api('/api/v1/providers/' + encodeURIComponent(name), { method:'DELETE' });
            loadSettings();
          } catch(e) {
            alert('删除失败: ' + e.message);
          }
        });
      });

      // Test connection
      const testBtn = out.querySelector('#testProvBtn');
      const testResult = out.querySelector('#testProvResult');
      testBtn.addEventListener('click', async () => {
        const name = document.getElementById('testProvName').value;
        if (!name) { testResult.textContent = '请选择提供商'; return; }
        testResult.textContent = '测试中...';
        try {
          const r = await api('/api/v1/providers/test?name=' + encodeURIComponent(name), { method:'POST' });
          testResult.textContent = r.ok ? '✓ ' + (r.detail || '正常') : '✗ ' + (r.error || '失败');
          testResult.style.color = r.ok ? '#166534' : '#991b1b';
        } catch(e) {
          testResult.textContent = '✗ ' + e.message;
          testResult.style.color = '#991b1b';
        }
      });
    }
  }


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