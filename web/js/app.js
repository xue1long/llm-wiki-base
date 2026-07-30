// ruflo-kb — init entry point (nav wiring, wiki link interceptor, boot).
(() => {
  "use strict";

  // ---------- Wire up nav ----------
  document.getElementById("nav").addEventListener("click", e => {
    const btn = e.target.closest(".nav-btn");
    if (!btn) return;
    App.showView(btn.dataset.view);
  });

  // ---------- Intercept wiki-internal links ----------
  document.addEventListener("click", e => {
    const a = e.target.closest && e.target.closest("a[href]");
    if (!a) return;
    const href = a.getAttribute("href") || "";
    if (!/\.md(\?|#|$)/.test(href)) return;
    e.preventDefault();
    const normalized = App.normalizeWikiPath(href.split("#")[0].split("?")[0]);
    if (!normalized) return;
    App.state.pendingBrowseTarget = normalized;
    App.showView("browse");
  });

  // ---------- Agent Panel ----------
  App.setupAgentPanel();

  // ---------- Go ----------
  App.boot();
})();
