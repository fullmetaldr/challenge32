const number = (value) => value === null || value === undefined ? "—" : value.toLocaleString();
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (character) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[character]));
const quantityList = (items) => items.length ? items.map((item) => `${item.quantity} × ${escapeHtml(item.name)}`).join(", ") : "—";

let payload;

function renderSummary() {
  const summary = payload.summary;
  const metrics = [
    ["Known card versions", summary.known_card_versions, ""],
    ["Known owned cards", summary.known_owned, ""],
    ["Deck-allocated cards", summary.deck_allocated, ""],
    ["Non-deck placements", summary.non_deck_placed, ""],
    ["Location unknown", summary.location_unknown, summary.location_unknown ? "warning" : ""],
    ["Conflicts", summary.conflicts, summary.conflicts ? "danger" : ""],
  ];
  document.querySelector("#summary").innerHTML = metrics.map(([label, value, klass]) =>
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
    `<div class="compact-row"><span>${escapeHtml(item.name)}</span><strong>${number(item.quantity)} <span class="subline">${number(item.card_versions)} versions</span></strong></div>`
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
    const haystack = `${item.name} ${item.printing} ${item.set_name} ${item.card_number} ${item.foil}`.toLocaleLowerCase();
    return (!query || haystack.includes(query)) && (status === "all" || item.status === status);
  });
  document.querySelector("#inventory-count").textContent = `${number(rows.length)} of ${number(payload.inventory.length)} card versions`;
  hidePreview();
  document.querySelector("#inventory-body").innerHTML = rows.map((item) => `
    <tr>
      <td><strong>${escapeHtml(item.name)}</strong></td>
      <td>${item.card_number ? `<button class="preview-button" type="button" data-set="${escapeHtml(item.set_code)}" data-number="${escapeHtml(item.card_number)}" aria-label="Preview ${escapeHtml(item.name)}" aria-describedby="card-preview">▧</button>` : "—"}</td>
      <td>${escapeHtml(item.set_name) || "—"}</td>
      <td>${escapeHtml(item.card_number) || "—"}</td>
      <td>${escapeHtml(item.foil)}</td>
      <td>${number(item.known_owned)}</td>
      <td>${number(item.deck_allocated)}<span class="subline">${quantityList(item.decks)}</span></td>
      <td>${number(item.non_deck_placed)}<span class="subline">${quantityList(item.locations)}</span></td>
      <td>${number(item.free_known)}</td>
      <td><span class="badge ${item.status}">${item.status.replaceAll("-", " ")}</span></td>
    </tr>`).join("") || `<tr><td colspan="10" class="muted">No matching card versions.</td></tr>`;
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
    document.querySelector("#search").addEventListener("input", renderInventory);
    document.querySelector("#status-filter").addEventListener("change", renderInventory);
  })
  .catch((error) => {
    document.querySelector("main").insertAdjacentHTML("afterbegin", `<div class="panel warning">Could not load dashboard data: ${error}</div>`);
  });
