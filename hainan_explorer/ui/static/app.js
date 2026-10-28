/* Hainan Explorer UI: vanilla JS, hash routing, keyboard-first review. */
(() => {
  "use strict";
  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));
  const LABELS = { undecided: "未决定", want_to_visit: "想去", maybe: "也许", skip: "跳过", needs_research: "待研究" };
  const PERM = { local_copy_allowed: "许可允许本地保存", link_only: "仅链接（许可不允许保存）", api_display_only: "仅 API 展示", unknown: "许可未知（不保存）", blocked: "禁止" };
  const state = {
    meta: null, page: "review", filters: loadFilters(), offset: 0, limit: 60, items: [], total: 0, focusIndex: -1,
    selectMode: false, selected: new Set(), currentPlace: null, map: null, cluster: null, corridorLayer: null, miniMap: null, jobsTimer: null,
  };

  // ------------------------------------------------------------ utilities
  async function api(path, opts = {}) {
    const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts, body: opts.body ? JSON.stringify(opts.body) : undefined });
    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try { const j = await res.json(); detail = j.detail || JSON.stringify(j); } catch (_) {}
      throw new Error(detail);
    }
    return res.json();
  }
  function toast(msg, ms = 2200) {
    const t = $("#toast"); t.textContent = msg; t.hidden = false;
    clearTimeout(toast._t); toast._t = setTimeout(() => { t.hidden = true; }, ms);
  }
  function esc(s) { return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
  function el(html) { const t = document.createElement("template"); t.innerHTML = html.trim(); return t.content.firstElementChild; }
  function loadFilters() { try { const f = JSON.parse(localStorage.getItem("hx.filters.v2") || "{}"); if (!f.sort) f.sort = "region"; return f; } catch (_) { return { sort: "region" }; } }
  function saveFilters() { try { localStorage.setItem("hx.filters.v2", JSON.stringify(state.filters)); } catch (_) {} }
  function commonsThumb(url, width) { if (!url) return null; const m = /^(https:\/\/upload\.wikimedia\.org\/wikipedia\/commons\/thumb\/.+\/)(\d+)px-([^/?]+)(\?.*)?$/.exec(url); return m ? `${m[1]}${width}px-${m[3]}` : url; }
  function fmtKm(v) { return v == null ? "—" : `${Number(v).toFixed(1)} km`; }

  // ------------------------------------------------------------ routing
  function route() {
    const m = /^#\/([a-z]+)(?:\/(\d+))?/.exec(location.hash);
    const page = m && $$(".page").some((p) => p.dataset.page === m[1]) ? m[1] : "review";
    state.page = page;
    $$(".page").forEach((p) => { p.hidden = p.dataset.page !== page; });
    $$("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.page === page));
    if (page === "review") loadGrid();
    if (page === "map") initMap();
    if (page === "duplicates") loadDuplicates();
    if (page === "leads") loadLeads();
    if (page === "jobs") { loadJobs(); startJobsPolling(); } else { stopJobsPolling(); }
    if (page === "data") loadData();
    if (m && m[2]) openPlace(Number(m[2]));
  }

  // ------------------------------------------------------------ meta + sidebar
  async function loadMeta() {
    state.meta = await api("/api/meta");
    const regionOpts = state.meta.regions.map((r) => `<option value="${r.key}">${esc(r.name)}</option>`).join("");
    const catOpts = state.meta.categories.map((c) => `<option value="${c.key}">${esc(c.label)}</option>`).join("");
    for (const id of ["#f-region", "#m-region"]) $(id).insertAdjacentHTML("beforeend", regionOpts);
    for (const id of ["#f-category", "#m-category"]) $(id).insertAdjacentHTML("beforeend", catOpts);
    applyFiltersToControls();
  }
  async function refreshSummary() {
    try {
      const s = await api("/api/summary");
      $("#side-stats").innerHTML = `
        <div>地点 <b>${s.total}</b></div><div>种子 <b>${s.seeds}</b></div>
        <div>有坐标 <b>${s.with_coords}</b></div><div>待核实 <b>${s.needs_geo}</b></div>
        <div>有图 <b>${s.with_images}</b></div><div>本地图 <b>${s.with_local_images}</b></div>
        <div>想去 <b>${s.by_interest.want_to_visit || 0}</b></div><div>也许 <b>${s.by_interest.maybe || 0}</b></div>
        <div>图片 <b>${s.images_total}</b></div><div>本地文件 <b>${s.images_local}</b></div>`;
      $("#badge-undecided").textContent = s.by_interest.undecided || "";
      $("#badge-dups").textContent = s.pending_duplicates || "";
      const active = (s.jobs.running || 0) + (s.jobs.queued || 0) + (s.jobs.retry_wait || 0);
      $("#badge-jobs").textContent = active || "";
    } catch (e) { console.warn(e); }
  }

  // ------------------------------------------------------------ filters
  const FILTER_IDS = { q: "#f-q", region: "#f-region", category: "#f-category", interest: "#f-interest", image_state: "#f-image", sort: "#f-sort", max_route_km: "#f-route", min_sources: "#f-sources" };
  const FILTER_CHECKS = { undecided_only: "#f-undecided", coastal: "#f-coastal", has_coords: "#f-coords", include_seeds: "#f-seeds" };
  function applyFiltersToControls() {
    for (const [k, id] of Object.entries(FILTER_IDS)) $(id).value = state.filters[k] ?? "";
    for (const [k, id] of Object.entries(FILTER_CHECKS)) $(id).checked = !!state.filters[k];
  }
  function readFilters() {
    for (const [k, id] of Object.entries(FILTER_IDS)) { const v = $(id).value; if (v === "") delete state.filters[k]; else state.filters[k] = v; }
    for (const [k, id] of Object.entries(FILTER_CHECKS)) { if ($(id).checked) state.filters[k] = true; else delete state.filters[k]; }
    saveFilters();
  }
  function filterQuery() {
    const p = new URLSearchParams();
    for (const [k, v] of Object.entries(state.filters)) if (v !== "" && v != null) p.set(k, v);
    p.set("limit", state.limit); p.set("offset", state.offset);
    return p.toString();
  }

  // ------------------------------------------------------------ grid
  let gridTimer = null;
  function scheduleGrid() { clearTimeout(gridTimer); gridTimer = setTimeout(() => { state.offset = 0; readFilters(); loadGrid(); }, 200); }
  async function loadGrid() {
    const grid = $("#grid");
    try {
      const data = await api(`/api/places?${filterQuery()}`);
      state.items = data.items; state.total = data.total;
      $("#result-count").textContent = `${data.total} 个地点`;
      $("#result-note").textContent = data.total === 0 ? "没有匹配的地点。试试放宽筛选，或在“任务”页运行发现任务。" : "";
      grid.replaceChildren(...data.items.map(renderCard));
      $("#pg-info").textContent = `${state.offset + 1}–${Math.min(state.offset + state.limit, data.total)} / ${data.total}`;
      $("#pg-prev").disabled = state.offset === 0; $("#pg-next").disabled = state.offset + state.limit >= data.total;
      if (state.focusIndex >= data.items.length) state.focusIndex = data.items.length - 1;
      highlightFocus();
    } catch (e) { grid.innerHTML = `<div class="empty">加载失败：${esc(e.message)}</div>`; }
  }
  function imageBlock(p) {
    if (p.card_image_url) return `<img src="${esc(p.card_image_url)}" alt="" loading="lazy" referrerpolicy="no-referrer" onerror="this.parentElement.innerHTML='<div class=ph><div class=ph-icon>🔗</div><div>远程图片加载失败<br>在详情中打开来源页</div></div>'">`;
    if (p.image_state === "remote") return `<div class="ph"><div class="ph-icon">🔗</div><div>有图片记录但无法在卡片中显示<br>（在详情中打开来源页）</div></div>`;
    return `<div class="ph"><div class="ph-icon">◌</div><div>暂无图片</div></div>`;
  }
  function renderCard(p, idx) {
    const tags = [];
    if (p.image_count) tags.push(`<span class="tag ${p.any_image_verified ? "tag-ok" : (p.best_image_score >= 5 ? "" : "tag-warn")}">${esc(p.image_badge)}</span>`);
    if (p.local_image_count) tags.push(`<span class="tag tag-local">本地 ${p.local_image_count}</span>`);
    if (p.needs_geographic_verification) tags.push(`<span class="tag tag-warn">坐标待核实</span>`);
    if (p.pending_duplicates) tags.push(`<span class="tag tag-warn">疑似重复</span>`);
    const status = p.interest_status !== "undecided" ? `<span class="card-status st-${p.interest_status}">${LABELS[p.interest_status]}</span>` : "";
    const card = el(`<article class="card ${state.selected.has(p.id) ? "selected" : ""}" data-id="${p.id}" tabindex="0">
      <div class="card-img">${imageBlock(p)}<div class="card-tags">${tags.join("")}</div>${status}</div>
      <div class="card-body">
        <div class="card-name">${esc(p.canonical_name)}</div>
        <div class="card-meta"><span>${esc(p.county || "市县未知")}</span><span>· ${esc(p.category_label)}</span><span>· 来源 ${p.source_count}</span>${p.route_distance_km != null ? `<span>· 走廊 ${fmtKm(p.route_distance_km)}</span>` : ""}</div>
        ${p.description ? `<div class="card-desc">${esc(p.description)}</div>` : `<div class="card-desc muted">尚无描述（${esc(p.discovery_reason)}）</div>`}
      </div>
      <div class="card-foot">
        <button class="btn btn-want ${p.interest_status === "want_to_visit" ? "active-want" : ""}" data-decide="want_to_visit">想去</button>
        <button class="btn btn-maybe ${p.interest_status === "maybe" ? "active-maybe" : ""}" data-decide="maybe">也许</button>
        <button class="btn btn-skip ${p.interest_status === "skip" ? "active-skip" : ""}" data-decide="skip">跳过</button>
        <button class="btn btn-research ${p.interest_status === "needs_research" ? "active-needs_research" : ""}" data-decide="needs_research">研究</button>
      </div></article>`);
    card.addEventListener("click", (ev) => {
      const btn = ev.target.closest("[data-decide]");
      if (btn) { ev.stopPropagation(); decide(p.id, btn.dataset.decide); return; }
      if (state.selectMode) { toggleSelect(p.id, card); return; }
      state.focusIndex = state.items.findIndex((x) => x.id === p.id); highlightFocus();
      openPlace(p.id);
    });
    card.addEventListener("focus", () => { state.focusIndex = state.items.findIndex((x) => x.id === p.id); highlightFocus(false); });
    return card;
  }
  function highlightFocus(scroll = true) {
    $$("#grid .card").forEach((c, i) => c.classList.toggle("focused", i === state.focusIndex));
    const c = $$("#grid .card")[state.focusIndex];
    if (c && scroll) c.scrollIntoView({ block: "nearest" });
  }
  function toggleSelect(id, card) {
    if (state.selected.has(id)) state.selected.delete(id); else state.selected.add(id);
    card.classList.toggle("selected", state.selected.has(id));
    $("#bulk-count").textContent = `${state.selected.size} 项`;
  }
  async function decide(id, decision) {
    try {
      const p = await api(`/api/places/${id}/decision`, { method: "POST", body: { decision } });
      patchItem(p); toast(`「${p.canonical_name}」→ ${LABELS[decision]}（U 撤销）`);
      if (state.currentPlace && state.currentPlace.id === id) renderDrawer(p);
      refreshSummary();
      if (state.filters.undecided_only && decision !== "undecided") setTimeout(loadGrid, 350);
    } catch (e) { toast(`操作失败：${e.message}`); }
  }
  function patchItem(p) {
    const i = state.items.findIndex((x) => x.id === p.id);
    if (i >= 0) { state.items[i] = { ...state.items[i], ...p }; const old = $$("#grid .card")[i]; if (old) old.replaceWith(renderCard(state.items[i], i)); highlightFocus(false); }
  }
  async function undo() {
    try { const p = await api(`/api/places/undo`, { method: "POST" }); patchItem(p); toast(`已撤销：「${p.canonical_name}」恢复为 ${LABELS[p.interest_status]}`); refreshSummary(); if (state.currentPlace && state.currentPlace.id === p.id) renderDrawer(p); }
    catch (e) { toast(`无法撤销：${e.message}`); }
  }

  // ------------------------------------------------------------ drawer
  async function openPlace(id) {
    try {
      const p = await api(`/api/places/${id}`);
      state.currentPlace = p; renderDrawer(p); $("#drawer").hidden = false;
    } catch (e) { toast(`加载失败：${e.message}`); }
  }
  function closeDrawer() { $("#drawer").hidden = true; state.currentPlace = null; if (state.miniMap) { state.miniMap.remove(); state.miniMap = null; } if (location.hash.match(/^#\/review\/\d+/)) history.replaceState(null, "", "#/review"); }
  function renderDrawer(p) {
    state.currentPlace = p;
    $("#d-title").innerHTML = `${esc(p.canonical_name)} <span class="muted small">${esc(p.code)}</span>`;
    $$("#drawer [data-decide]").forEach((b) => b.className = `btn btn-${b.dataset.decide === "needs_research" ? "research" : b.dataset.decide.split("_")[0]} ${p.interest_status === b.dataset.decide ? "active-" + b.dataset.decide : ""}`);
    const gallery = p.images.length ? p.images.map(renderGalleryImage).join("") : `<div class="muted small">尚无图片记录。可在下方“为此地点找图”。</div>`;
    const sourced = p.facts.sourced.map((f) => `<li><b>${esc(f.label)}</b>：${esc(f.value)}${f.source ? ` <span class="muted">（${esc(f.source)}）</span>` : ""}</li>`).join("");
    const derived = p.facts.derived.map((f) => `<li><b>${esc(f.label)}</b>：${esc(f.value)}${f.note ? ` <span class="muted">（${esc(f.note)}）</span>` : ""}</li>`).join("");
    const unknown = p.facts.unknown.map((f) => `<li><b>${esc(f.label)}</b>：${esc(f.value)}</li>`).join("");
    const sources = p.sources.map((s) => `<li><a href="${esc(s.url)}" target="_blank" rel="noreferrer">${esc(s.title || s.url)}</a> <span class="badge">${esc(s.provider)}</span> <span class="badge ${s.access_status === "fetched" ? "ok" : "warn"}">${esc(s.access_status)}</span>${s.publisher ? ` <span class="muted">${esc(s.publisher)}</span>` : ""}${s.evidence_excerpt ? `<span class="ex">“${esc(s.evidence_excerpt.slice(0, 220))}${s.evidence_excerpt.length > 220 ? "…" : ""}”</span>` : ""}${s.license_notes ? `<span class="ex muted">${esc(s.license_notes)}</span>` : ""}</li>`).join("");
    const rels = p.relations.map((r) => {
      const otherId = r.place_id_a === p.id ? r.place_id_b : r.place_id_a;
      const otherName = r.place_id_a === p.id ? r.name_b : r.name_a;
      return `<li>${esc(r.relation_type)} → <a data-open="${otherId}">${esc(otherName)}</a> <span class="badge ${r.review_status === "pending" ? "warn" : ""}">${esc(r.review_status)}</span> <span class="muted">${esc((r.reasons || []).join(", "))}</span>
        ${r.review_status === "pending" && r.relation_type === "duplicate_of" ? `<button class="btn" data-merge="${r.place_id_a}:${r.place_id_b}">合并（可撤销）</button> <button class="btn" data-rel="${r.id}:rejected">不是重复</button>` : ""}
        ${r.review_status === "merged" && r.place_id_a !== p.id ? `<button class="btn" data-unmerge="${r.place_id_a}">撤销合并 ${esc(r.name_a)}</button>` : ""}</li>`;
    }).join("");
    const nearby = p.nearby.map((n) => `<div><a data-open="${n.id}">${esc(n.canonical_name)}</a> <span class="muted">${esc(n.category_label)} · ${n.distance_km} km${n.image_count ? " · 有图" : ""}</span></div>`).join("");
    const reviews = p.reviews.slice(0, 8).map((r) => `<li>${esc(r.reviewed_at.slice(0, 16).replace("T", " "))} ${esc(r.decision)}${r.previous_decision ? ` (原 ${esc(r.previous_decision)})` : ""}${r.reason ? ` · ${esc(r.reason)}` : ""}${r.undone ? " · 已撤销" : ""}</li>`).join("");
    $("#d-body").innerHTML = `
      <div><div class="sect-title">图片 <span class="badge ${p.any_image_verified ? "ok" : (p.image_count ? "warn" : "")}">${esc(p.image_badge)}</span>
        <button class="btn" data-job="images_for_place" data-payload='{"place_id":${p.id}}'>为此地点找图</button></div>
        <div class="gallery">${gallery}</div></div>
      <div class="facts">
        <div><h4>有来源的事实</h4><ul>${sourced || "<li class='muted'>暂无</li>"}</ul></div>
        <div><h4>推断 / 估算</h4><ul>${derived || "<li class='muted'>暂无</li>"}</ul></div>
        <div><h4>未知</h4><ul>${unknown}</ul></div>
      </div>
      <div><div class="sect-title">名称与分类</div>
        <div class="small">别名：${p.aliases.length ? p.aliases.map(esc).join("、") : "<span class='muted'>无</span>"}${p.name_en ? ` · EN: ${esc(p.name_en)}` : ""}</div>
        <div class="small">类别：${esc(p.category_label)}${p.subcategory ? ` <span class="muted">(${esc(p.subcategory)})</span>` : ""} · 发现原因：${esc(p.discovery_reason)} · 置信度 ${Number(p.confidence_score).toFixed(2)} · 小众分 ${Number(p.novelty_score).toFixed(2)} · 发现分 ${Number(p.discovery_score).toFixed(2)} · 研究状态 ${esc(p.research_status)}</div>
        <div class="small">核实状态：<select id="d-verify" class="input">${["unverified", "partially_verified", "verified", "disputed"].map((v) => `<option value="${v}" ${p.verification_status === v ? "selected" : ""}>${v}</option>`).join("")}</select>
          <button class="btn" data-job="research_place" data-payload='{"place_id":${p.id}}'>重新研究此地点</button>
          <button class="btn" data-job="nearby_expansion" data-payload='{"place_id":${p.id}}' ${p.latitude == null ? "disabled" : ""}>扩展周边地物</button>
          <button class="btn" id="d-report">报告问题</button></div>
      </div>
      ${p.latitude != null ? `<div><div class="sect-title">位置 <span class="muted small">${p.latitude.toFixed(5)}, ${p.longitude.toFixed(5)} · ${esc(p.coordinate_precision || "")} · ${esc(p.coordinate_source || "")}</span></div><div id="mini-map" class="mini-map"></div></div>` : `<div><div class="sect-title">位置</div><div class="small muted">没有坐标。可以手动输入：<input id="d-lat" class="input input-xs" placeholder="纬度" style="width:90px"> <input id="d-lon" class="input input-xs" placeholder="经度" style="width:90px"> <button class="btn" id="d-setcoords">保存坐标</button></div></div>`}
      <div><div class="sect-title">来源证据（${p.sources.length}）</div><ul class="sources">${sources || "<li class='muted'>无</li>"}</ul></div>
      <div><div class="sect-title">关系与重复候选</div><ul class="sources">${rels || "<li class='muted'>无</li>"}</ul></div>
      <div><div class="sect-title">附近 3 km 内的候选</div><div class="nearby">${nearby || "<span class='muted small'>无（或没有坐标）</span>"}</div></div>
      <div class="notes"><div class="sect-title">我的笔记</div><textarea id="d-notes">${esc(p.personal_notes || "")}</textarea><div class="row" style="margin-top:6px"><button class="btn btn-primary" id="d-save-notes">保存笔记</button><span class="muted small">提供方 ID：${p.provider_ids.map((x) => `${esc(x.provider)}:${esc(x.external_id)}`).join("，") || "无"}</span></div></div>
      <div><div class="sect-title">审核历史</div><ul class="sources">${reviews || "<li class='muted'>无</li>"}</ul></div>`;
    $("#d-save-notes").onclick = async () => { const r = await api(`/api/places/${p.id}`, { method: "PATCH", body: { personal_notes: $("#d-notes").value } }); toast("笔记已保存"); state.currentPlace = r; };
    $("#d-verify").onchange = async (e) => { const r = await api(`/api/places/${p.id}`, { method: "PATCH", body: { verification_status: e.target.value } }); toast("核实状态已更新"); renderDrawer(r); };
    $("#d-report").onclick = async () => { const r = await api(`/api/places/${p.id}`, { method: "PATCH", body: { verification_status: "disputed", personal_notes: (p.personal_notes || "") + "\n[报告] 地点信息有误，待复核" } }); toast("已标记为有争议"); renderDrawer(r); };
    const sc = $("#d-setcoords"); if (sc) sc.onclick = async () => { const lat = parseFloat($("#d-lat").value), lon = parseFloat($("#d-lon").value); if (isNaN(lat) || isNaN(lon)) return toast("请输入有效坐标"); const r = await api(`/api/places/${p.id}`, { method: "PATCH", body: { latitude: lat, longitude: lon } }); toast("坐标已保存（来源：用户）"); renderDrawer(r); loadGrid(); };
    $$("#d-body [data-open]").forEach((a) => a.onclick = () => openPlace(Number(a.dataset.open)));
    $$("#d-body [data-merge]").forEach((b) => b.onclick = async () => { const [a, t] = b.dataset.merge.split(":").map(Number); try { await api("/api/places/merge", { method: "POST", body: { source_id: a, target_id: t, reason: "user confirmed duplicate" } }); toast("已合并（可在目标地点撤销）"); openPlace(t); loadGrid(); refreshSummary(); } catch (e) { toast(e.message); } });
    $$("#d-body [data-rel]").forEach((b) => b.onclick = async () => { const [id, st] = b.dataset.rel.split(":"); await api(`/api/relations/${id}/status`, { method: "POST", body: { status: st } }); toast("已标记"); openPlace(p.id); refreshSummary(); });
    $$("#d-body [data-unmerge]").forEach((b) => b.onclick = async () => { try { await api(`/api/places/${b.dataset.unmerge}/unmerge`, { method: "POST" }); toast("已撤销合并"); openPlace(p.id); loadGrid(); } catch (e) { toast(e.message); } });
    $$("#d-body [data-job]").forEach(bindJobButton);
    $$("#d-body [data-assoc]").forEach((b) => b.onclick = async () => { const [imageId, status, primary] = b.dataset.assoc.split(":"); const r = await api(`/api/places/${p.id}/images/${imageId}/association`, { method: "POST", body: { status, make_primary: primary === "1" } }); toast("图片关联已更新"); renderDrawer(r); patchItem(r); });
    $$("#d-body [data-rm-local]").forEach((b) => b.onclick = async () => { await api(`/api/images/${b.dataset.rmLocal}/local`, { method: "DELETE" }); toast("本地副本已删除，记录保留"); openPlace(p.id); });
    $$("#d-body [data-report-img]").forEach((b) => b.onclick = async () => { await api(`/api/images/${b.dataset.reportImg}/report`, { method: "POST", body: { issue: "user report: wrong image / wrong place / rights issue" } }); await api(`/api/places/${p.id}/images/${b.dataset.reportImg}/association`, { method: "POST", body: { status: "rejected", notes: "reported by user" } }); toast("已报告并取消关联"); openPlace(p.id); });
    $$("#d-body .gimg img").forEach((img) => img.onclick = () => lightbox(img.dataset.full || img.src, img.dataset.cap));
    if (p.latitude != null && window.L) {
      if (state.miniMap) { state.miniMap.remove(); }
      state.miniMap = L.map("mini-map", { scrollWheelZoom: false }).setView([p.latitude, p.longitude], 13);
      L.tileLayer(state.meta.map_tiles.url, { attribution: state.meta.map_tiles.attribution, maxZoom: state.meta.map_tiles.max_zoom || 19 }).addTo(state.miniMap);
      L.circleMarker([p.latitude, p.longitude], { radius: 8, color: "#0e6b74", fillOpacity: p.coordinate_precision === "exact" ? 0.9 : 0.2 }).addTo(state.miniMap);
      for (const n of p.nearby) L.circleMarker([n.latitude, n.longitude], { radius: 4, color: "#888" }).addTo(state.miniMap).bindTooltip(n.canonical_name);
      // Leaflet measures its container once at creation; the drawer is still laying out (images, fonts)
      // at that moment, so re-measure after paint, whenever the container resizes, and after gallery images load.
      const mm = state.miniMap;
      const fix = () => { if (state.miniMap === mm) mm.invalidateSize(); };
      requestAnimationFrame(fix); setTimeout(fix, 250); setTimeout(fix, 1000);
      if (window.ResizeObserver) { const ro = new ResizeObserver(fix); ro.observe($("#mini-map")); mm.once("remove", () => ro.disconnect()); }
      $$("#d-body .gimg img").forEach((img) => img.addEventListener("load", fix, { once: true }));
      $("#d-body").addEventListener("scroll", fix, { passive: true });
    }
  }
  function renderGalleryImage(i) {
    const src = i.thumbnail_url || ((i.permission_status === "link_only" || i.permission_status === "local_copy_allowed") && i.provider === "commons" ? commonsThumb(i.display_url, 480) : null);
    const full = i.local_url || i.display_url || i.original_url;
    const img = src ? `<img src="${esc(src)}" data-full="${esc(full || src)}" data-cap="${esc((i.title || "") + " · " + (i.attribution_text || ""))}" alt="${esc(i.title || "")}" loading="lazy">` : `<div class="ph">无法在应用内展示<br><a href="${esc(i.source_page_url)}" target="_blank" rel="noreferrer">打开来源页</a></div>`;
    const reasons = (i.match_reasons || []).join(", ");
    return `<div class="gimg ${i.association_status}">${img}<div class="meta">
      <div><span class="badge ${i.verified_by_user ? "ok" : (i.match_score >= 5 ? "" : "warn")}">${i.verified_by_user ? "已人工核实" : `匹配 ${Number(i.match_score).toFixed(1)}（未核实）`}</span> ${i.is_primary ? '<span class="badge">主图</span>' : ""} ${i.local_path ? '<span class="badge">本地</span>' : `<span class="badge warn">${esc(PERM[i.permission_status] || i.permission_status)}</span>`}</div>
      <div class="muted" title="${esc(reasons)}">${esc(reasons)}</div>
      <div>${esc(i.attribution_text || "")} · <a href="${esc(i.source_page_url)}" target="_blank" rel="noreferrer">来源页</a>${i.license_url ? ` · <a href="${esc(i.license_url)}" target="_blank" rel="noreferrer">${esc(i.license_short || i.license_id)}</a>` : ` · ${esc(i.license_short || i.license_id || "许可未知")}`}</div>
      <div class="acts">
        <button class="btn" data-assoc="${i.id}:user_verified:1">确认是此地 + 设主图</button>
        <button class="btn" data-assoc="${i.id}:rejected:0">不是此地</button>
        <button class="btn" data-report-img="${i.id}">报告问题</button>
        ${i.local_path ? `<button class="btn" data-rm-local="${i.id}">删除本地副本</button>` : ""}
      </div></div></div>`;
  }
  function lightbox(src, cap) {
    const box = el(`<div class="lightbox"><img src="${esc(src)}" alt=""><div class="cap">${esc(cap || "")}</div></div>`);
    box.onclick = () => box.remove(); document.body.appendChild(box);
  }

  // ------------------------------------------------------------ map
  function initMap() {
    if (!window.L) { $("#map").innerHTML = "<div class='empty'>Leaflet 未加载</div>"; return; }
    if (!state.map) {
      state.map = L.map("map").setView([19.2, 109.8], 8);
      L.tileLayer(state.meta.map_tiles.url, { attribution: state.meta.map_tiles.attribution, maxZoom: state.meta.map_tiles.max_zoom || 19 }).addTo(state.map);
      state.cluster = L.markerClusterGroup({ maxClusterRadius: 40, disableClusteringAtZoom: 13 });
      state.map.addLayer(state.cluster);
    }
    setTimeout(() => state.map.invalidateSize(), 50);
    loadMapData();
  }
  async function loadMapData() {
    const p = new URLSearchParams();
    if ($("#m-interest").value) p.set("interest", $("#m-interest").value);
    if ($("#m-category").value) p.set("category", $("#m-category").value);
    if ($("#m-region").value) p.set("region", $("#m-region").value);
    if ($("#m-seeds").checked) p.set("include_seeds", "true");
    const [geo, corridor] = await Promise.all([api(`/api/map/places?${p}`), api("/api/corridor")]);
    state.cluster.clearLayers();
    for (const f of geo.features) {
      const pr = f.properties; const [lon, lat] = f.geometry.coordinates;
      const icon = L.divIcon({ className: "", html: `<div class="pin ${pr.interest_status} ${pr.coordinate_precision === "exact" ? "" : "approx"}"></div>`, iconSize: [12, 12] });
      const m = L.marker([lat, lon], { icon });
      m.bindPopup(`<div class="popup-name">${esc(pr.canonical_name)}</div><div>${esc(pr.county || "")} · ${esc(pr.category_label)} · ${LABELS[pr.interest_status]}</div><div>图片 ${pr.image_count}（本地 ${pr.local_image_count}）${pr.route_distance_km != null ? ` · 走廊直线 ${fmtKm(pr.route_distance_km)}` : ""}</div><div><a href="#/review/${pr.id}">查看详情</a></div>`);
      state.cluster.addLayer(m);
    }
    $("#m-count").textContent = `${geo.features.length} 个有坐标的地点`;
    if (state.corridorLayer) { state.map.removeLayer(state.corridorLayer); state.corridorLayer = null; }
    if ($("#m-corridor").checked && corridor && corridor.geometry) {
      state.corridorLayer = L.geoJSON(corridor.geometry, { style: { color: "#b9684b", weight: 3, dashArray: "6 6", opacity: 0.7 } }).bindTooltip(`${corridor.name}（估算）`).addTo(state.map);
    }
  }

  // ------------------------------------------------------------ duplicates
  async function loadDuplicates() {
    const rows = await api("/api/relations?status=pending&limit=200");
    const box = $("#dups");
    if (!rows.length) { box.innerHTML = "<div class='empty'>没有待审核的重复候选。</div>"; return; }
    box.replaceChildren(...rows.map((r) => {
      const dist = (r.lat_a != null && r.lat_b != null) ? `${(haversine(r.lat_a, r.lon_a, r.lat_b, r.lon_b) * 1000).toFixed(0)} m` : "至少一方无坐标";
      const d = el(`<div class="dup">
        <div class="dup-side"><b><a data-open="${r.place_id_a}">${esc(r.name_a)}</a></b><span>${esc(r.county_a || "市县未知")} · ${esc(r.category_a)} · 图 ${r.images_a}</span><span class="muted">${r.lat_a != null ? `${r.lat_a.toFixed(4)}, ${r.lon_a.toFixed(4)}` : "无坐标"}</span></div>
        <div class="dup-mid"><span class="badge warn">${esc(r.relation_type)} · ${Number(r.confidence_score).toFixed(2)}</span><span>${dist}</span><span>${esc((r.reasons || []).join(", "))}</span>
          <button class="btn" data-merge="${r.place_id_a}:${r.place_id_b}">合并 A → B</button><button class="btn" data-merge="${r.place_id_b}:${r.place_id_a}">合并 B → A</button>
          <button class="btn" data-rel="${r.id}:confirmed">相关但分开保留</button><button class="btn" data-rel="${r.id}:rejected">无关</button></div>
        <div class="dup-side"><b><a data-open="${r.place_id_b}">${esc(r.name_b)}</a></b><span>${esc(r.county_b || "市县未知")} · ${esc(r.category_b)} · 图 ${r.images_b}</span><span class="muted">${r.lat_b != null ? `${r.lat_b.toFixed(4)}, ${r.lon_b.toFixed(4)}` : "无坐标"}</span></div></div>`);
      $$("[data-open]", d).forEach((a) => a.onclick = () => openPlace(Number(a.dataset.open)));
      $$("[data-merge]", d).forEach((b) => b.onclick = async () => { const [a, t] = b.dataset.merge.split(":").map(Number); try { await api("/api/places/merge", { method: "POST", body: { source_id: a, target_id: t, reason: "duplicate review" } }); toast("已合并（可撤销）"); loadDuplicates(); refreshSummary(); } catch (e) { toast(e.message); } });
      $$("[data-rel]", d).forEach((b) => b.onclick = async () => { const [id, st] = b.dataset.rel.split(":"); await api(`/api/relations/${id}/status`, { method: "POST", body: { status: st } }); loadDuplicates(); refreshSummary(); });
      return d;
    }));
  }
  function haversine(a, b, c, d) { const R = 6371, t = Math.PI / 180, dl = (c - a) * t, dn = (d - b) * t; const h = Math.sin(dl / 2) ** 2 + Math.cos(a * t) * Math.cos(c * t) * Math.sin(dn / 2) ** 2; return 2 * R * Math.asin(Math.sqrt(h)); }

  // ------------------------------------------------------------ leads
  async function loadLeads() {
    const rows = await api("/api/images/leads/unassigned?limit=300");
    const box = $("#leads");
    if (!rows.length) { box.innerHTML = "<div class='empty'>没有未匹配的带坐标图片。运行“Commons 坐标扫描”任务后会出现线索。</div>"; return; }
    box.replaceChildren(...rows.map((i) => {
      const d = el(`<div class="lead">${i.display_url ? `<img src="${esc(i.thumbnail_url ? "/media/thumbnails/" + i.thumbnail_path : i.display_url)}" alt="" loading="lazy">` : ""}<div class="p">
        <b>${esc(i.title || "")}</b><span class="muted">${i.latitude.toFixed(4)}, ${i.longitude.toFixed(4)} · ${esc(i.license_short || i.license_id || "许可未知")}</span>
        <span class="muted">${esc(i.attribution_text || "")}</span>
        <span><a href="${esc(i.source_page_url)}" target="_blank" rel="noreferrer">来源页</a> · <a href="https://www.openstreetmap.org/?mlat=${i.latitude}&mlon=${i.longitude}#map=16/${i.latitude}/${i.longitude}" target="_blank" rel="noreferrer">在 OSM 查看位置</a></span></div></div>`);
      return d;
    }));
  }

  // ------------------------------------------------------------ jobs
  function bindJobButton(b) {
    b.onclick = async () => {
      try {
        const payload = b.dataset.payload ? JSON.parse(b.dataset.payload) : {};
        const r = await api("/api/jobs", { method: "POST", body: { job_type: b.dataset.job, payload } });
        toast(`任务已加入队列 #${r.job_id}`); refreshSummary(); if (state.page === "jobs") loadJobs();
      } catch (e) { toast(`无法创建任务：${e.message}`); }
    };
  }
  async function loadJobs() {
    try {
      const [jobs, cov] = await Promise.all([api("/api/jobs?limit=60"), api("/api/coverage")]);
      $("#jobs-list").replaceChildren(...jobs.items.map((j) => {
        const pr = j.progress || {}; const pct = pr.total ? Math.round(100 * (pr.done || 0) / pr.total) : null;
        const d = el(`<div class="job"><div class="job-head"><b>#${j.id} ${esc(j.job_type)}</b><span class="pill ${j.status}">${esc(j.status)}</span>
          ${["queued", "running", "retry_wait"].includes(j.status) ? `<button class="btn" data-cancel="${j.id}">取消</button>` : ""}${["failed", "cancelled"].includes(j.status) ? `<button class="btn" data-retry="${j.id}">重试</button>` : ""}</div>
          <div class="muted">${esc(JSON.stringify(j.payload))} · 尝试 ${j.attempt_count}/${j.max_attempts} · ${esc((j.started_at || j.created_at || "").slice(0, 16).replace("T", " "))}</div>
          ${pct != null ? `<div class="bar"><span style="width:${pct}%"></span></div>` : ""}
          <div class="muted">${esc(pr.stage || "")} ${Object.entries(pr).filter(([k]) => !["stage", "updated_at", "result"].includes(k)).map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`).join(" · ")}</div>
          ${pr.result ? `<div class="muted">结果：${esc(JSON.stringify(pr.result)).slice(0, 400)}</div>` : ""}
          ${j.last_error ? `<div style="color:var(--skip)">${esc(j.last_error)}</div>` : ""}</div>`);
        $$("[data-cancel]", d).forEach((b) => b.onclick = async () => { await api(`/api/jobs/${b.dataset.cancel}/cancel`, { method: "POST" }); loadJobs(); });
        $$("[data-retry]", d).forEach((b) => b.onclick = async () => { await api(`/api/jobs/${b.dataset.retry}/retry`, { method: "POST" }); loadJobs(); });
        return d;
      }));
      const provState = Object.fromEntries(cov.providers.map((p) => [p.provider, p]));
      $("#providers").innerHTML = state.meta.providers.map((p) => {
        const s = provState[p.name] || provState[{ overpass: "osm" }[p.name]] || {};
        return `<div class="provider"><span><b>${esc(p.name)}</b> <span class="pill">${p.enabled ? (p.configured ? "启用" : "需要 API key") : "已禁用"}</span></span><span class="muted">间隔 ≥ ${p.min_interval_seconds}s${s.last_success_at ? ` · 上次成功 ${esc(s.last_success_at.slice(0, 16).replace("T", " "))}` : ""}${s.last_error ? ` · 错误：${esc(s.last_error).slice(0, 80)}` : ""}</span></div>`;
      }).join("") + `<div class="muted small">HTTP 统计：${Object.entries(state.meta.http_stats || {}).map(([h, s]) => `${esc(h)} ${s.requests}（429: ${s.rate_limited}）`).join("，") || "本会话尚无请求"}</div>` + (cov.osm_categories_not_run.length ? `<div class="muted small">尚未运行的 OSM 类别组：${cov.osm_categories_not_run.map(esc).join(", ")}</div>` : "") + (cov.recent_failures.length ? `<div class="muted small">最近失败：${cov.recent_failures.slice(0, 5).map((f) => `${esc(f.provider)} ${esc(f.query || "")}: ${esc((f.error_summary || "").slice(0, 80))}`).join("；")}</div>` : "");
      $("#coverage").innerHTML = `<table class="cov-table"><tr><th>市县</th><th>地点</th><th>有图</th><th>未决定</th><th>已研究</th></tr>${Object.values(cov.by_region).map((r) => `<tr><td>${esc(r.name)}</td><td>${r.places}</td><td>${r.with_images}</td><td>${r.undecided}</td><td>${r.researched}</td></tr>`).join("")}</table>`;
    } catch (e) { $("#jobs-list").innerHTML = `<div class="empty">${esc(e.message)}</div>`; }
  }
  function startJobsPolling() { stopJobsPolling(); state.jobsTimer = setInterval(() => { loadJobs(); refreshSummary(); }, 5000); }
  function stopJobsPolling() { if (state.jobsTimer) { clearInterval(state.jobsTimer); state.jobsTimer = null; } }

  // ------------------------------------------------------------ data page
  async function loadData() {
    const [exports, backups, files] = await Promise.all([api("/api/export/files"), api("/api/backups"), api("/api/import/files")]);
    $("#exports").innerHTML = exports.map((f) => `<div class="list-item"><a href="${esc(f.download_url)}">${esc(f.name)}</a><span class="muted">${(f.bytes / 1024).toFixed(0)} KB</span></div>`).join("") || "<div class='muted small'>尚无导出</div>";
    $("#backups").innerHTML = backups.map((b) => `<div class="list-item"><span>${esc(b.name)}</span><span class="muted">${(b.bytes / 1024).toFixed(0)} KB · ${esc(b.modified_at)}</span><button class="btn" data-restore="${esc(b.name)}">恢复</button></div>`).join("") || "<div class='muted small'>尚无备份</div>";
    $$("#backups [data-restore]").forEach((b) => b.onclick = async () => { if (!window.confirm(`恢复 ${b.dataset.restore}？当前数据库会先自动备份。`)) return; const r = await api("/api/restore", { method: "POST", body: { backup_name: b.dataset.restore } }); toast(`已恢复，恢复前备份：${r.pre_restore_backup}`); refreshSummary(); });
    $("#im-file").innerHTML = files.map((f) => `<option>${esc(f)}</option>`).join("") || "<option value=''>（data/imports 为空）</option>";
  }

  // ------------------------------------------------------------ keyboard
  document.addEventListener("keydown", (ev) => {
    if (["INPUT", "TEXTAREA", "SELECT"].includes(ev.target.tagName)) { if (ev.key === "Escape") ev.target.blur(); return; }
    const drawerOpen = !$("#drawer").hidden;
    const target = drawerOpen && state.currentPlace ? state.currentPlace.id : (state.items[state.focusIndex] || {}).id;
    const map = { "1": "want_to_visit", "2": "maybe", "3": "skip", "4": "needs_research", w: "want_to_visit", m: "maybe", s: "skip", r: "needs_research" };
    const k = ev.key.toLowerCase();
    if (map[k] && target) { ev.preventDefault(); decide(target, map[k]); if (!drawerOpen && state.focusIndex < state.items.length - 1) { state.focusIndex++; highlightFocus(); } return; }
    if (k === "u") { ev.preventDefault(); undo(); return; }
    if (k === "escape") { closeDrawer(); return; }
    if (state.page !== "review") return;
    if (k === "j" || k === "arrowright") { ev.preventDefault(); state.focusIndex = Math.min(state.items.length - 1, state.focusIndex + 1); highlightFocus(); if (drawerOpen) openPlace(state.items[state.focusIndex].id); }
    if (k === "k" || k === "arrowleft") { ev.preventDefault(); state.focusIndex = Math.max(0, state.focusIndex - 1); highlightFocus(); if (drawerOpen) openPlace(state.items[state.focusIndex].id); }
    if (k === "enter" && state.items[state.focusIndex]) { ev.preventDefault(); openPlace(state.items[state.focusIndex].id); }
  });

  // ------------------------------------------------------------ wiring
  function wire() {
    for (const id of Object.values(FILTER_IDS)) $(id).addEventListener("input", scheduleGrid);
    for (const id of Object.values(FILTER_CHECKS)) $(id).addEventListener("change", scheduleGrid);
    $("#pg-prev").onclick = () => { state.offset = Math.max(0, state.offset - state.limit); loadGrid(); };
    $("#pg-next").onclick = () => { state.offset += state.limit; loadGrid(); };
    $("#btn-undo").onclick = undo;
    $("#btn-select-mode").onclick = () => { state.selectMode = !state.selectMode; $("#bulk-bar").classList.toggle("hidden", !state.selectMode); $("#btn-select-mode").textContent = state.selectMode ? "退出批量" : "批量选择"; if (!state.selectMode) { state.selected.clear(); $$("#grid .card.selected").forEach((c) => c.classList.remove("selected")); } };
    $$("#bulk-bar [data-bulk]").forEach((b) => b.onclick = async () => { if (!state.selected.size) return toast("先点选卡片"); const r = await api("/api/places/bulk-decision", { method: "POST", body: { place_ids: [...state.selected], decision: b.dataset.bulk } }); toast(`已更新 ${r.updated} 项（可逐条 U 撤销）`); state.selected.clear(); $("#bulk-count").textContent = "0 项"; loadGrid(); refreshSummary(); });
    $("#bulk-clear").onclick = () => { state.selected.clear(); $("#bulk-count").textContent = "0 项"; $$("#grid .card.selected").forEach((c) => c.classList.remove("selected")); };
    $("#drawer-close").onclick = closeDrawer;
    $$("#drawer [data-decide]").forEach((b) => b.onclick = () => state.currentPlace && decide(state.currentPlace.id, b.dataset.decide));
    for (const id of ["#m-interest", "#m-category", "#m-region", "#m-corridor", "#m-seeds"]) $(id).addEventListener("change", loadMapData);
    $$("[data-page='jobs'] [data-job]").forEach(bindJobButton);
    $("#btn-retry-failed").onclick = async () => { const r = await api("/api/jobs/retry-failed", { method: "POST" }); toast(`已重新排队 ${r.requeued} 个任务`); loadJobs(); };
    $("#btn-url").onclick = async () => { const url = $("#url-input").value.trim(); if (!url) return; try { const r = await api("/api/leads/url", { method: "POST", body: { url } }); toast(`已加入抓取任务 #${r.job_id}`); $("#url-input").value = ""; loadJobs(); } catch (e) { toast(e.message); } };
    $("#btn-export").onclick = async () => { const interest = $("#ex-interest").value ? $("#ex-interest").value.split(",") : null; const r = await api("/api/export", { method: "POST", body: { format: $("#ex-format").value, interest } }); toast(`已导出 ${r.name}`); loadData(); };
    $("#btn-backup").onclick = async () => { const r = await api("/api/backup", { method: "POST" }); toast(`已备份 ${r.name}`); loadData(); };
    $("#btn-im-preview").onclick = async () => { const name = $("#im-file").value; if (!name) return; try { $("#im-result").textContent = JSON.stringify(await api(`/api/import/csv?name=${encodeURIComponent(name)}&dry_run=true`, { method: "POST" }), null, 2); } catch (e) { $("#im-result").textContent = e.message; } };
    $("#btn-im-apply").onclick = async () => { const name = $("#im-file").value; if (!name) return; try { $("#im-result").textContent = JSON.stringify(await api(`/api/import/csv?name=${encodeURIComponent(name)}&dry_run=false`, { method: "POST" }), null, 2); refreshSummary(); } catch (e) { $("#im-result").textContent = e.message; } };
    $("#btn-im-corridor").onclick = async () => { const name = $("#im-file").value; if (!name) return; try { $("#im-result").textContent = JSON.stringify(await api(`/api/import/corridor?name=${encodeURIComponent(name)}`, { method: "POST" }), null, 2); } catch (e) { $("#im-result").textContent = e.message; } };
    window.addEventListener("hashchange", route);
  }

  (async () => {
    await loadMeta();
    wire();
    if (!location.hash) location.replace("#/review");
    route();
    refreshSummary();
    setInterval(refreshSummary, 15000);
  })();
})();
