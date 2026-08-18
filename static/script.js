let leads = [];
let currentFilter = "no";

async function loadLeads() {
  const qs = currentFilter ? `?website=${currentFilter}` : "";
  const res = await fetch(`/api/leads${qs}`);
  leads = await res.json();
  renderLeads();
  renderStats();
}

function renderStats() {
  const withEmail = leads.filter(l => l.email).length;
  document.getElementById("stats").textContent =
    `${leads.length} leads shown · ${withEmail} with email`;
}

document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    tab.classList.add("active");
    currentFilter = tab.dataset.filter;
    loadLeads();
  });
});

function renderLeads() {
  const body = document.getElementById("leads-body");
  body.innerHTML = "";

  for (const lead of leads) {
    const tr = document.createElement("tr");

    const searchQuery = encodeURIComponent(`${lead.name} ${lead.address} email contact`);
    const links = [
      `<a href="${lead.google_maps_url}" target="_blank" rel="noopener">Google Maps</a>`,
      lead.possible_social_url
        ? `<a href="${lead.possible_social_url}" target="_blank" rel="noopener">Social page</a>`
        : "",
      `<a href="https://www.google.com/search?q=${searchQuery}" target="_blank" rel="noopener">Find email &rarr;</a>`,
    ].filter(Boolean).join("");

    const websiteCell = lead.has_website
      ? `<a href="${lead.website_url}" target="_blank" rel="noopener">${escapeHtml(lead.website_url || "")}</a>`
      : `<span class="badge">none</span>`;

    tr.innerHTML = `
      <td><input type="checkbox" class="lead-check" data-id="${lead.id}"></td>
      <td>${escapeHtml(lead.name || "")}</td>
      <td>${escapeHtml(lead.address || "")}</td>
      <td>${escapeHtml(lead.phone || "")}</td>
      <td>${websiteCell}</td>
      <td class="links">${links}</td>
      <td><input type="text" class="email-input" data-id="${lead.id}"
            value="${escapeHtml(lead.email || "")}" placeholder="add email"></td>
    `;
    body.appendChild(tr);
  }

  document.querySelectorAll(".email-input").forEach(input => {
    input.addEventListener("change", async (e) => {
      const id = e.target.dataset.id;
      await fetch(`/api/leads/${id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: e.target.value, email_source: "manual" }),
      });
      loadLeads();
    });
  });
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

document.getElementById("select-all").addEventListener("change", (e) => {
  document.querySelectorAll(".lead-check").forEach(c => c.checked = e.target.checked);
});

document.getElementById("search-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const location = document.getElementById("location").value;
  const category = document.getElementById("category").value;
  const statusEl = document.getElementById("search-status");
  statusEl.textContent = "Searching...";
  statusEl.className = "status";

  const res = await fetch("/api/search", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ location, category }),
  });
  const data = await res.json();

  if (!res.ok) {
    statusEl.textContent = data.error || "Search failed.";
    statusEl.className = "status error";
    return;
  }

  statusEl.textContent =
    `Found ${data.found_no_website} without a website and ${data.found_has_website} with one.`;
  statusEl.className = "status ok";
  loadLeads();
});

document.getElementById("campaign-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const subject = document.getElementById("subject").value;
  const body = document.getElementById("body").value;
  const lead_ids = Array.from(document.querySelectorAll(".lead-check:checked"))
    .map(c => parseInt(c.dataset.id, 10));

  const statusEl = document.getElementById("campaign-status");
  if (lead_ids.length === 0) {
    statusEl.textContent = "Select at least one lead first.";
    statusEl.className = "status error";
    return;
  }

  const btn = document.getElementById("send-btn");
  btn.disabled = true;
  statusEl.textContent = "Sending...";
  statusEl.className = "status";

  const res = await fetch("/api/campaign/send", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ subject, body, lead_ids }),
  });
  const data = await res.json();
  btn.disabled = false;

  if (!res.ok) {
    statusEl.textContent = data.error || "Send failed.";
    statusEl.className = "status error";
    return;
  }

  statusEl.textContent =
    `Sent ${data.sent}, failed ${data.failed}, skipped ${data.skipped_no_email} (no email), ` +
    `skipped ${data.skipped_suppressed} (unsubscribed).`;
  statusEl.className = "status ok";
});

loadLeads();
