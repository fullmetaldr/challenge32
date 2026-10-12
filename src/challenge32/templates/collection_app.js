const number = (value) => value === null || value === undefined ? "—" : value.toLocaleString();
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[character]));
const rarityLabels = { common: "C", uncommon: "U", rare: "R", mythic: "M" };

function locationBreakdown(item) {
  const rows = [
    ...item.decks.map((deck) => ({ name: deck.name, quantity: deck.quantity })),
    ...item.locations.map((location) => ({ name: location.label || location.name, quantity: location.quantity })),
  ];
  const warning = item.status === "location-unknown"
    ? `${item.free_known} owned copy/copies have no recorded location.`
    : item.status === "conflict"
      ? `Recorded allocations exceed owned copies by ${Math.abs(item.free_known)}.`
      : item.status === "ownership-unknown"
        ? "This card has a recorded allocation but no ownership entry."
        : "";
  return `<div class="location-breakdown">
    ${rows.length ? `<table><thead><tr><th>Location</th><th>Count</th></tr></thead><tbody>${rows.map((row) =>
      `<tr><td>${escapeHtml(row.name)}</td><td>${number(row.quantity)}</td></tr>`
    ).join("")}</tbody></table>` : `<p class="muted">No placements recorded.</p>`}
    ${warning ? `<p class="placement-warning">${escapeHtml(warning)}</p>` : ""}
  </div>`;
}

let payload;
const INVENTORY_PAGE_SIZE = 50;
let inventoryPage = 1;

function setupPanelToggles() {
  document.querySelectorAll(".panel-toggle").forEach((button) => {
    button.addEventListener("click", () => {
      const content = document.getElementById(button.getAttribute("aria-controls"));
      const collapsing = button.getAttribute("aria-expanded") === "true";
      button.setAttribute("aria-expanded", String(!collapsing));
      content.hidden = collapsing;
      button.closest(".panel").classList.toggle("collapsed", collapsing);
      if (collapsing) hidePreview();
    });
  });
}

function renderSummary() {
  const summary = payload.summary;
  const metrics = [
    ["Deck-allocated cards", summary.deck_allocated, ""],
    ["In Staging", summary.in_staging, ""],
    ["In Reserve", summary.in_reserve, ""],
    ["Location unknown", summary.location_unknown, summary.location_unknown ? "warning" : ""],
    ["Conflicts", summary.conflicts, summary.conflicts ? "danger" : ""],
  ];
  const inventory = `<div class="metric metric-inventory"><span class="muted">Inventory</span>
    <dl class="metric-lines">
      <div><dt>No. different cards</dt><dd>${number(summary.different_cards)}</dd></div>
      <div><dt>No. total cards</dt><dd>${number(summary.known_owned)}</dd></div>
    </dl></div>`;
  document.querySelector("#summary").innerHTML = inventory + metrics.map(([label, value, klass]) =>
    `<div class="metric ${klass}"><span class="muted">${label}</span><strong>${number(value)}</strong></div>`
  ).join("");
}

function renderWarnings() {
  const warnings = payload.inventory.filter((item) => item.status !== "accounted");
  const panel = document.querySelector("#warnings");
  panel.classList.toggle("hidden", warnings.length === 0);
  document.querySelector("#warning-list").innerHTML = warnings.slice(0, 100).map((item) => {
    const detail = item.status === "conflict"
      ? `${Math.abs(item.free_known)} more allocated/placed than known owned`
      : item.status === "location-unknown"
        ? `${item.free_known} known copy/copies have no recorded location`
        : "Allocated or placed, but ownership is not recorded";
    return `<div class="warning"><strong>${escapeHtml(item.name)}</strong> <span class="subline">${escapeHtml(item.printing || "printing unknown")} · ${detail}</span></div>`;
  }).join("") + (warnings.length > 100 ? `<p class="muted">Showing the first 100 warnings.</p>` : "");
}

function renderLocations() {
  document.querySelector("#locations").innerHTML = `<div class="compact-list">${payload.locations.map((item) =>
    `<div class="compact-row"><span>${escapeHtml(item.label || item.name)}</span><strong>${number(item.quantity)} <span class="subline">${number(item.card_versions)} versions</span></strong></div>`
  ).join("") || `<p class="muted">No non-deck placements recorded.</p>`}</div>`;
}

function renderDecks() {
  document.querySelector("#decks").innerHTML = `<div class="compact-list">${payload.decks.map((item) =>
    `<div class="compact-row"><span>${escapeHtml(item.display_name)}</span><strong>${number(item.quantity)} <span class="subline">${number(item.card_versions)} versions</span></strong></div>`
  ).join("")}</div>`;
}

function renderInventory() {
  const query = document.querySelector("#search").value.trim().toLocaleLowerCase();
  const status = document.querySelector("#status-filter").value;
  const rows = payload.inventory.filter((item) => {
    const haystack = `${item.name} ${item.printing} ${item.set_name} ${item.card_number} ${item.rarity || ""} ${item.foil}`.toLocaleLowerCase();
    return (!query || haystack.includes(query)) && (status === "all" || item.status === status);
  });
  const pageCount = Math.max(1, Math.ceil(rows.length / INVENTORY_PAGE_SIZE));
  inventoryPage = Math.max(1, Math.min(inventoryPage, pageCount));
  const first = (inventoryPage - 1) * INVENTORY_PAGE_SIZE;
  const visibleRows = rows.slice(first, first + INVENTORY_PAGE_SIZE);
  const range = rows.length ? `${number(first + 1)}–${number(first + visibleRows.length)}` : "0";
  const overall = rows.length === payload.inventory.length ? "" : ` (${number(payload.inventory.length)} total)`;
  document.querySelector("#inventory-count").textContent = `Showing ${range} of ${number(rows.length)} card versions${overall}`;
  const pagination = document.querySelector("#inventory-pagination");
  pagination.hidden = pageCount === 1;
  const selector = document.querySelector("#inventory-page");
  selector.innerHTML = Array.from({ length: pageCount }, (_, index) =>
    `<option value="${index + 1}">${index + 1}</option>`
  ).join("");
  selector.value = String(inventoryPage);
  document.querySelector("#page-count").textContent = `of ${number(pageCount)}`;
  document.querySelector("#previous-page").disabled = inventoryPage === 1;
  document.querySelector("#next-page").disabled = inventoryPage === pageCount;
  hidePreview();
  document.querySelector("#inventory-body").innerHTML = visibleRows.map((item) => `
    <tr class="inventory-row ${item.status}" data-card-id="${item.id}">
      <td><button class="inventory-expand" type="button" aria-expanded="false" aria-controls="inventory-details-${item.id}" aria-label="Show locations for ${escapeHtml(item.name)}"><span class="chevron" aria-hidden="true">▸</span><strong>${escapeHtml(item.name)}</strong></button>${item.status === "accounted" ? "" : ` <span class="badge ${item.status}">${escapeHtml(item.status.replaceAll("-", " "))}</span>`}</td>
      <td>${item.card_number ? `<button class="preview-button" type="button" data-set="${escapeHtml(item.set_code)}" data-number="${escapeHtml(item.card_number)}" aria-label="Preview ${escapeHtml(item.name)}" aria-describedby="card-preview">▧</button>` : "—"}</td>
      <td>${escapeHtml(item.set_name) || "—"}</td>
      <td>${escapeHtml(item.card_number) || "—"}</td>
      <td title="${escapeHtml(item.rarity || "Rarity unknown")}">${escapeHtml(rarityLabels[item.rarity] || item.rarity || "—")}</td>
      <td>${escapeHtml(item.foil)}</td>
      <td>${number(item.known_owned)}</td>
      <td>${number(item.deck_allocated)}</td>
    </tr>
    <tr class="inventory-details" id="inventory-details-${item.id}" hidden><td colspan="8">${locationBreakdown(item)}</td></tr>`).join("") || `<tr><td colspan="8" class="muted">No matching card versions.</td></tr>`;
}

function resetInventoryPage() {
  inventoryPage = 1;
  renderInventory();
}

let previewTimer;
let previewTarget;

function hidePreview() {
  clearTimeout(previewTimer);
  previewTarget = null;
  document.querySelector("#card-preview").classList.add("hidden");
}

function showPreview(button) {
  clearTimeout(previewTimer);
  previewTarget = button;
  previewTimer = setTimeout(() => {
    if (previewTarget !== button || !button.isConnected) return;
    const tooltip = document.querySelector("#card-preview");
    tooltip.innerHTML = `<span class="muted">Loading card image…</span>`;
    tooltip.classList.remove("hidden");
    const rect = button.getBoundingClientRect();
    tooltip.style.left = `${Math.min(rect.right + 10, window.innerWidth - 300)}px`;
    tooltip.style.top = `${Math.max(8, Math.min(rect.top, window.innerHeight - 420))}px`;
    const image = new Image();
    image.alt = button.getAttribute("aria-label");
    image.onload = () => { if (previewTarget === button) tooltip.replaceChildren(image); };
    image.onerror = () => {
      if (previewTarget === button) tooltip.innerHTML = `<span class="muted">Image unavailable. Check the local server and connection.</span>`;
    };
    image.src = `/api/card-image?set=${encodeURIComponent(button.dataset.set)}&number=${encodeURIComponent(button.dataset.number)}`;
  }, 180);
}

document.querySelector("#inventory-body").addEventListener("pointerover", (event) => {
  const button = event.target.closest(".preview-button");
  if (button && button !== previewTarget) showPreview(button);
});
document.querySelector("#inventory-body").addEventListener("pointerout", (event) => {
  const button = event.target.closest(".preview-button");
  if (button && !button.contains(event.relatedTarget)) hidePreview();
});
document.querySelector("#inventory-body").addEventListener("focusin", (event) => {
  if (event.target.matches(".preview-button")) showPreview(event.target);
});
document.querySelector("#inventory-body").addEventListener("focusout", hidePreview);
document.querySelector("#inventory-body").addEventListener("click", (event) => {
  const row = event.target.closest(".inventory-row");
  if (!row || event.target.closest(".preview-button")) return;
  const button = row.querySelector(".inventory-expand");
  const details = document.getElementById(button.getAttribute("aria-controls"));
  const expanded = button.getAttribute("aria-expanded") === "true";
  button.setAttribute("aria-expanded", String(!expanded));
  button.setAttribute("aria-label", `${expanded ? "Show" : "Hide"} locations for ${button.querySelector("strong").textContent}`);
  details.hidden = expanded;
});
document.addEventListener("keydown", (event) => { if (event.key === "Escape") hidePreview(); });

fetch("data.json")
  .then((response) => response.json())
  .then((data) => {
    payload = data;
    document.querySelector("#generated-at").textContent = `Generated ${new Date(data.generated_at).toLocaleString()}`;
    renderSummary();
    renderWarnings();
    renderLocations();
    renderDecks();
    renderInventory();
    setupPanelToggles();
    document.querySelector("#search").addEventListener("input", resetInventoryPage);
    document.querySelector("#status-filter").addEventListener("change", resetInventoryPage);
    document.querySelector("#inventory-page").addEventListener("change", (event) => {
      inventoryPage = Number(event.target.value);
      renderInventory();
    });
    document.querySelector("#previous-page").addEventListener("click", () => {
      inventoryPage -= 1;
      renderInventory();
    });
    document.querySelector("#next-page").addEventListener("click", () => {
      inventoryPage += 1;
      renderInventory();
    });
  })
  .catch((error) => {
    document.querySelector("main").insertAdjacentHTML("afterbegin", `<div class="panel warning">Could not load dashboard data: ${error}</div>`);
  });
