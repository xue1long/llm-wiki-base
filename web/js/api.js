// ruflo-kb — core utilities: API, markdown, frontmatter, banner.
(() => {
  "use strict";

  window.App = window.App || {};

  // ---------- Path normalization ----------
  App.normalizeWikiPath = function normalizeWikiPath(p) {
    if (!p) return "";
    let s = String(p).replace(/\\/g, "/");
    s = s.replace(/^(.*\/)?wiki\//, "");
    return s;
  };

  // ---------- API wrapper ----------
  App.api = async function api(path, { method = "GET", body, signal } = {}) {
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
  };

  // ---------- Markdown rendering ----------
  App.renderMd = function renderMd(md) {
    if (typeof window.marked === "function" || (window.marked && window.marked.parse)) {
      try { return window.marked.parse(md); } catch (e) { /* fall through */ }
    }
    const escaped = md.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    return `<pre class="no-md-fallback">${escaped}</pre>`;
  };

  // ---------- YAML frontmatter (minimal regex, no library) ----------
  App.parseFrontmatter = function parseFrontmatter(md) {
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
      if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
        v = v.slice(1, -1);
      }
      if (v !== "") { fm[key] = v; i++; continue; }
      const items = [];
      i++;
      while (i < lines.length) {
        const nxt = lines[i];
        if (!nxt.startsWith(" ") && !nxt.startsWith("-")) break;
        if (nxt.startsWith("- ")) {
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
  };

  App.renderFrontmatter = function renderFrontmatter(fm) {
    if (!fm) return "";
    const keys = Object.keys(fm);
    if (!keys.length) return "";
    const rows = keys.map(k => {
      const v = fm[k];
      if (Array.isArray(v)) {
        const lis = v.map(item => {
          if (item && typeof item === "object") {
            const kv = Object.entries(item).map(([kk, vv]) => `<span class="stat-key">${App.escapeHtml(kk)}:</span> ${App.escapeHtml(String(vv))}`).join(" · ");
            return `<li>${kv}</li>`;
          }
          return `<li>${App.escapeHtml(String(item))}</li>`;
        }).join("");
        return `<div class="fm-row"><span class="stat-key">${App.escapeHtml(k)}:</span><ul class="fm-list">${lis}</ul></div>`;
      }
      return `<div class="fm-row"><span class="stat-key">${App.escapeHtml(k)}:</span> ${App.escapeHtml(String(v))}</div>`;
    }).join("");
    return `<div class="reader-fm">${rows}</div>`;
  };

  App.escapeHtml = function escapeHtml(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  };

  // ---------- Banner ----------
  App.setBanner = function setBanner(msg, kind) {
    const el = document.getElementById("banner");
    el.innerHTML = msg ? `<div class="banner-${kind || "err"}">${App.escapeHtml(msg)}</div>` : "";
  };
})();
