const esc = (v) => String(v ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
const date = (v) => { if (!v) return "Unknown"; const d = new Date(v); return Number.isNaN(d.valueOf()) ? v : d.toLocaleDateString(undefined, {year:"numeric",month:"short",day:"numeric"}); };
const decks = (data) => data.identities.flatMap((i) => i.decks);
const key = (d) => `${d.color_identity}/${d.slug}`;

function stats(data) {
  const tracked = data.tracked_identity_count, total = data.identity_count;
  const queue = decks(data).filter((d) => d.analysis_status === "Unreviewed").length;
  document.querySelector("#coverage").textContent = `${tracked} / ${total}`;
  document.querySelector("#coverage-detail").textContent = `${Math.round(tracked / total * 100)}% of colour identities tracked`;
  document.querySelector("#coverage-bar").style.width = `${tracked / total * 100}%`;
  document.querySelector("#deck-count").textContent = data.deck_count;
  document.querySelector("#analysis-count").textContent = queue;
  document.querySelector("#generated-at").textContent = `Generated ${date(data.generated_at)} from the deck directories.`;
}

function grid(data) {
  const target = document.querySelector("#identity-grid");
  target.innerHTML = data.identities.map((i) => `<article class="identity ${i.decks.length ? "tracked" : ""}"><h3>${esc(i.name)}</h3><div class="meta"><span class="colors">${esc(i.colors || "—")}</span><span class="status">${esc(i.status)}</span></div>${i.decks.length ? `<div class="chips">${i.decks.map((d) => `<a class="chip" href="#deck=${encodeURIComponent(key(d))}">${esc(d.display_name)}</a>`).join("")}</div>` : ""}</article>`).join("");
  target.querySelectorAll("a[href^=\"#deck=\"]").forEach((link) => link.addEventListener("click", () => show(data, decodeURIComponent(link.hash.slice(6)))));
}

function cardSections(cards) {
  const sections = new Map();
  cards.forEach((card) => { if (!sections.has(card.section)) sections.set(card.section, []); sections.get(card.section).push(card); });
  return [...sections].map(([name, sectionCards]) => `<section class="card-section"><h3>${esc(name)}</h3>${sectionCards.map((c) => `<div class="card-row"><strong>${esc(c.name)}</strong><span>${c.quantity}</span></div>`).join("")}</section>`).join("");
}

function show(data, deckKey) {
  const deck = decks(data).find((d) => key(d) === deckKey); if (!deck) return;
  document.querySelector("#deck-heading").textContent = deck.display_name;
  document.querySelector("#deck-details").innerHTML = `<div class="deck-summary"><span>Identity: <strong>${esc(deck.color_identity.replaceAll("-", " "))}</strong></span><span>Commander: <strong>${esc(deck.commander.join(" · ") || "Not recorded")}</strong></span><span>Cards: <strong>${deck.card_count}</strong></span><span>Analysis: <strong>${esc(deck.analysis_status)}</strong></span><span>Synced: <strong>${date(deck.retrieved_at)}</strong></span></div><div class="actions"><a class="primary" href="${esc(deck.current_path)}">Current decklist ↗</a><a href="${esc(deck.source_url)}">Open ${esc(deck.source)} ↗</a>${deck.notes.map((n) => `<a href="${esc(n.path)}">${esc(n.name)} ↗</a>`).join("")}</div><div class="cards">${cardSections(deck.cards)}</div>`;
  const panel = document.querySelector("#deck-panel"); panel.hidden = false; panel.scrollIntoView({behavior:"smooth",block:"start"});
}

async function start() {
  const response = await fetch("data.json"); if (!response.ok) throw new Error(`Could not load deck data (${response.status})`);
  const data = await response.json(); stats(data); grid(data);
  document.querySelector("#close-deck").addEventListener("click", () => { document.querySelector("#deck-panel").hidden = true; history.replaceState(null, "", "#"); });
  if (location.hash.startsWith("#deck=")) show(data, decodeURIComponent(location.hash.slice(6)));
}
start().catch((error) => { document.querySelector("#identity-grid").innerHTML = `<p>Unable to load dashboard data: ${esc(error.message)}</p>`; });
