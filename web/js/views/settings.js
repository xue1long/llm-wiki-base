// ruflo-kb — LLM provider settings view (2.5: card grid, star toggle, modal form, test banner).
(() => {
  "use strict";

  window.App = window.App || {};

  App.renderSettings = function renderSettings(root) {
    root.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;">
        <h2 style="margin:0;">LLM 提供商设置</h2>
        <button class="btn-primary" id="openAddModalBtn">+ 添加</button>
      </div>
      <div class="provider-grid" id="providerGrid">
        <div class="provider-card"><div class="skeleton skeleton-line"></div><div class="skeleton skeleton-line short"></div></div>
      </div>
      <div class="settings-section" style="margin-top:24px;">
        <h3 style="font-size:14px;margin:0 0 8px;">测试连接</h3>
        <div style="display:flex;gap:8px;align-items:center;">
          <select id="testProvName" style="padding:5px 8px;border:1px solid var(--border-hover);border-radius:var(--radius-md);font-size:13px;background:var(--bg-surface);">
            <option value="">选择提供商...</option>
          </select>
          <button class="btn-sm" id="testProvBtn">测试</button>
          <span id="testProvResult" style="margin-left:8px;font-size:13px;"></span>
        </div>
      </div>
    `;

    document.getElementById("openAddModalBtn").addEventListener("click", () => showAddModal());
    loadSettings();

    async function loadSettings() {
      const grid = document.getElementById("providerGrid");
      try {
        const data = await App.api("/api/v1/providers");
        renderProviderCards(data.providers || []);
      } catch (e) {
        grid.innerHTML = `<div class="banner-err">加载失败: ${App.escapeHtml(e.message)}</div>`;
      }
    }

    function renderProviderCards(providers) {
      const grid = document.getElementById("providerGrid");
      const testSelect = document.getElementById("testProvName");

      if (!providers.length) {
        grid.innerHTML = `<div class="empty-state">
          <div class="empty-state-icon">⚙️</div>
          <div class="empty-state-title">暂无提供商</div>
          <div class="empty-state-desc">点击"+ 添加"配置 LLM 提供商</div>
        </div>`;
        testSelect.innerHTML = '<option value="">选择提供商...</option>';
        return;
      }

      testSelect.innerHTML = '<option value="">选择提供商...</option>' +
        providers.map(p => `<option value="${App.escapeHtml(p.name)}">${App.escapeHtml(p.name)}</option>`).join("");

      const typeLabels = { openai: "OpenAI", "openai-compatible": "OpenAI 兼容", anthropic: "Anthropic", ollama: "Ollama" };

      grid.innerHTML = providers.map(p => {
        const typeLabel = typeLabels[p.type] || p.type;
        const starIcon = p.is_default ? "★" : "☆";
        const starTitle = p.is_default ? "当前默认" : "设为默认";
        const starClass = p.is_default ? "star-active" : "";
        const model = p.default_chat_model || p.default_embedding_model || "—";
        const baseUrl = p.base_url || "—";
        const keyDisplay = p.api_key || "—";

        return `<div class="provider-card${p.is_default ? " default" : ""}">
          <div class="provider-card-header">
            <div class="provider-card-title">
              <span class="provider-card-name">${App.escapeHtml(p.name)}</span>
              <span class="provider-card-type">${App.escapeHtml(typeLabel)}</span>
            </div>
            <button class="star-btn ${starClass}" data-action="toggle-default" data-name="${App.escapeHtml(p.name)}" title="${starTitle}">${starIcon}</button>
          </div>
          <div class="provider-card-body">
            <div class="provider-card-field">
              <span class="provider-card-label">Model</span>
              <span class="provider-card-value">${App.escapeHtml(model)}</span>
            </div>
            <div class="provider-card-field">
              <span class="provider-card-label">Base URL</span>
              <span class="provider-card-value" style="font-size:11px;">${App.escapeHtml(baseUrl)}</span>
            </div>
            <div class="provider-card-field">
              <span class="provider-card-label">API Key</span>
              <span class="provider-card-value">${App.escapeHtml(keyDisplay)}</span>
            </div>
          </div>
          <div class="provider-card-test" id="testBanner-${App.escapeHtml(p.name)}" style="display:none;"></div>
          <div class="provider-card-actions">
            <button class="btn-sm" data-action="test" data-name="${App.escapeHtml(p.name)}">测试</button>
            <button class="btn-sm btn-danger" data-action="remove" data-name="${App.escapeHtml(p.name)}">删除</button>
          </div>
        </div>`;
      }).join("");

      // Star toggle
      grid.querySelectorAll('[data-action="toggle-default"]').forEach(btn => {
        btn.addEventListener("click", async () => {
          const name = btn.dataset.name;
          try {
            await App.api("/api/v1/providers/set-default", { method: "POST", body: { name } });
            loadSettings();
          } catch (e) {
            App.toast("设置默认失败: " + e.message, "error");
          }
        });
      });

      // Test button in card
      grid.querySelectorAll('[data-action="test"]').forEach(btn => {
        btn.addEventListener("click", async () => {
          const name = btn.dataset.name;
          const banner = document.getElementById("testBanner-" + App.escapeHtml(name));
          if (!banner) return;
          banner.style.display = "block";
          banner.innerHTML = '<span style="color:var(--text-muted);">测试中...</span>';
          banner.className = "provider-card-test testing";
          try {
            const r = await App.api("/api/v1/providers/test?name=" + encodeURIComponent(name), { method: "POST" });
            if (r.ok) {
              banner.innerHTML = '<span>✓ ' + App.escapeHtml(r.detail || "连接正常") + '</span>';
              banner.className = "provider-card-test success";
            } else {
              banner.innerHTML = '<span>✗ ' + App.escapeHtml(r.error || "连接失败") + '</span>';
              banner.className = "provider-card-test error";
            }
          } catch (e) {
            banner.innerHTML = '<span>✗ ' + App.escapeHtml(e.message) + '</span>';
            banner.className = "provider-card-test error";
          }
        });
      });

      // Delete button
      grid.querySelectorAll('[data-action="remove"]').forEach(btn => {
        btn.addEventListener("click", async () => {
          const name = btn.dataset.name;
          if (!confirm("确认删除提供商「" + name + "」？")) return;
          try {
            await App.api("/api/v1/providers/" + encodeURIComponent(name), { method: "DELETE" });
            loadSettings();
          } catch (e) {
            App.toast("删除失败: " + e.message, "error");
          }
        });
      });

      // Wire up test select
      document.getElementById("testProvBtn").addEventListener("click", async () => {
        const name = document.getElementById("testProvName").value;
        const result = document.getElementById("testProvResult");
        if (!name) { result.textContent = "请选择提供商"; result.style.color = ""; return; }
        result.textContent = "测试中...";
        result.style.color = "";
        try {
          const r = await App.api("/api/v1/providers/test?name=" + encodeURIComponent(name), { method: "POST" });
          result.textContent = r.ok ? "✓ " + (r.detail || "正常") : "✗ " + (r.error || "失败");
          result.style.color = r.ok ? "var(--success)" : "var(--danger)";
        } catch (e) {
          result.textContent = "✗ " + e.message;
          result.style.color = "var(--danger)";
        }
      });
    }

    function showAddModal() {
      const existing = document.getElementById("addProviderModal");
      if (existing) existing.remove();

      const PROVIDER_PRESETS = {
        "minimax": { base_url: "https://api.minimax.chat/v1", model: "MiniMax-Text-01", label: "MiniMax" },
        "kimi": { base_url: "https://api.moonshot.cn/v1", model: "moonshot-v1-8k", label: "Kimi / Moonshot" },
        "deepseek": { base_url: "https://api.deepseek.com/v1", model: "deepseek-chat", label: "DeepSeek" },
        "glm": { base_url: "https://open.bigmodel.cn/api/paas/v4", model: "glm-4-plus", label: "GLM / 智谱" },
        "openai": { base_url: "https://api.openai.com/v1", model: "gpt-4o", label: "OpenAI（官方）" },
        "anthropic": { base_url: "", model: "", label: "Anthropic" },
        "ollama": { base_url: "http://127.0.0.1:11434", model: "", label: "Ollama（本地）" },
      };

      const modal = document.createElement("div");
      modal.id = "addProviderModal";
      modal.className = "modal-overlay";
      modal.innerHTML = `<div class="modal-card">
        <div class="modal-header">
          <h3>添加提供商</h3>
          <button class="modal-close" id="closeAddModal">&times;</button>
        </div>
        <div class="modal-body">
          <div class="modal-field">
            <label>名称</label>
            <input id="modalProvName" placeholder="如 my-openai" />
          </div>
          <div class="modal-field">
            <label>预设</label>
            <select id="modalProvPreset">
              <option value="">（自定义）</option>
              ${Object.entries(PROVIDER_PRESETS).map(([k, v]) =>
                `<option value="${k}">${v.label}</option>`
              ).join("")}
            </select>
          </div>
          <div class="modal-field">
            <label>类型</label>
            <select id="modalProvType">
              <option value="openai-compatible">OpenAI 兼容</option>
              <option value="openai">OpenAI（官方）</option>
              <option value="anthropic">Anthropic</option>
              <option value="ollama">Ollama</option>
            </select>
          </div>
          <div class="modal-field">
            <label>Base URL</label>
            <input id="modalProvBaseUrl" placeholder="https://api.example.com/v1" />
          </div>
          <div class="modal-field">
            <label>API Key</label>
            <input id="modalProvKey" type="password" placeholder="留空从环境变量读取" />
          </div>
          <div class="modal-field">
            <label>默认模型</label>
            <input id="modalProvModel" placeholder="如 gpt-4o" />
          </div>
          <div id="modalAddResult" style="margin-top:8px;"></div>
        </div>
        <div class="modal-footer">
          <button class="btn-sm" id="cancelAddModal">取消</button>
          <button class="btn-primary" id="confirmAddModal">添加</button>
        </div>
      </div>`;
      document.body.appendChild(modal);

      // Preset auto-fill
      modal.querySelector("#modalProvPreset").addEventListener("change", () => {
        const preset = PROVIDER_PRESETS[modal.querySelector("#modalProvPreset").value];
        if (!preset) return;
        const nameEl = document.getElementById("modalProvName");
        if (!nameEl.value.trim()) nameEl.value = modal.querySelector("#modalProvPreset").value;
        document.getElementById("modalProvBaseUrl").value = preset.base_url || "";
        document.getElementById("modalProvModel").value = preset.model || "";
        if (preset.label.includes("Anthropic")) {
          document.getElementById("modalProvType").value = "anthropic";
        } else if (preset.label.includes("Ollama")) {
          document.getElementById("modalProvType").value = "ollama";
        } else if (preset.label === "OpenAI（官方）") {
          document.getElementById("modalProvType").value = "openai";
        } else {
          document.getElementById("modalProvType").value = "openai-compatible";
        }
      });

      function closeModal() { modal.remove(); }
      modal.querySelector("#closeAddModal").addEventListener("click", closeModal);
      modal.querySelector("#cancelAddModal").addEventListener("click", closeModal);
      modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });

      modal.querySelector("#confirmAddModal").addEventListener("click", async () => {
        const name = document.getElementById("modalProvName").value.trim();
        const type = document.getElementById("modalProvType").value;
        const api_key = document.getElementById("modalProvKey").value;
        const base_url = document.getElementById("modalProvBaseUrl").value.trim();
        const model = document.getElementById("modalProvModel").value.trim();
        const result = document.getElementById("modalAddResult");
        if (!name) { result.innerHTML = '<span class="banner-warn">请输入名称</span>'; return; }
        result.innerHTML = "添加中...";
        try {
          await App.api("/api/v1/providers", {
            method: "POST",
            body: { name, type, api_key, base_url, chat_model: model, embedding_model: model },
          });
          closeModal();
          loadSettings();
          App.toast("提供商「" + name + "」已添加", "success");
        } catch (e) {
          result.innerHTML = '<span class="banner-err">失败: ' + App.escapeHtml(e.message) + '</span>';
        }
      });
    }
  };
})();
