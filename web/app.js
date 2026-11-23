/* Lógica principal do Purah Pad (SSE ao vivo, abas, inventário, missões, arquivos e marcadores). */
(function () {
  "use strict";

  const tr = (key, vars) => (window.PurahI18n ? window.PurahI18n.t(key, vars) : key);

  const INV_CATS = ["weapons", "bows", "shields", "armor", "materials", "food", "zonai", "keyItems", "arrows"];
  const QUEST_CATS = ["all", "main_quest", "side_adventure", "shrine_quest", "side_quest"];
  const QUEST_STATUSES = ["active", "available", "complete", "locked", "all"];
  const PIN_COLOR_HEX = [
    ["Red", "#ff4d5a"],
    ["Blue", "#3c9dff"],
    ["Yellow", "#ffd638"],
    ["Green", "#4ce67c"],
    ["Purple", "#c46eff"],
    ["LightBlue", "#48ebff"],
  ];
  const STAMP_KEYS = ["Sword", "Pot", "Human", "Rhombus", "Heart", "Star", "TreasureBox", "Skull", "Leaf", "Ore"];

  const PREFS_KEY = "purahpad_prefs_v2";
  const LEGACY_PREFS_KEY = "purahpad_map_prefs_v1";

  const WIKI_CATS = ["all", "Weapon", "Bow", "Shield", "Armor", "Material", "Food", "SpecialParts", "KeyItem"];
  const ARCHIVE_SUBS = ["compendium", "profiles", "recipes", "memories", "album"];
  const ARCHIVE_CATS = ["all", "Animal", "Enemy", "Material", "Weapon", "Treasure"];
  const VALID_TABS = ["map", "inventory", "quests", "archives", "wiki"];
  const VALID_ENTITY_KEYS = ["npcs", "animals", "plants", "monsters"];

  function formatShopPrice(g) {
    if (!g) return "";
    const cur = g.currency === "Rupees" ? tr("detail.currencyRupees") : g.currency || tr("detail.currencyRupees");
    return `${g.price ?? 0} ${cur}`;
  }

  const state = {
    activeTab: "map",
    activeLang: null,
    i18nApplied: false,
    streamStarted: false,
    pollTimersStarted: false,
    serverPrefsLoaded: false,
    bootComplete: false,
    status: null,
    live: null,
    snapshot: null,
    mapData: null,
    entitiesData: null,
    entitiesPromise: null,
    questsData: null,
    catalogData: null,
    footprint: null,
    userMarkers: [],
    invCat: "weapons",
    invSelected: null,
    questCat: "all",
    questStatus: "active",
    questSelected: null,
    archiveSub: "compendium",
    archiveCat: "all",
    archiveSpoiler: true,
    spoilerFree: true,
    mapMode: "spoiler_free",
    assistRadius: 200,
    fogOfWar: true,
    hideCompleted: false,
    sidebarCollapsed: false,
    nearbyOpen: false,
    nearbyManuallyClosed: false,
    nearbyFilter: "all",
    lastNearbyPos: null,
    lastNearbyAt: 0,
    wikiCat: "all",
    wikiShopsOnly: false,
    wikiAllRanks: false,
    wikiSelected: null,
    wikiFilter: null,
    archiveSelected: null,
    staticLoaded: false,
  };

  let prefsSaveTimer = null;
  let prefsDirty = false;
  let viewSaveTimer = null;

  const $ = (id) => document.getElementById(id);
  const esc = (s) =>
    String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  async function apiJson(url, opts) {
    const res = await fetch(url, opts);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  function scheduleViewSave() {
    clearTimeout(viewSaveTimer);
    viewSaveTimer = setTimeout(() => saveAllPrefs(false), 350);
  }

  // ---------------- Mapa ----------------
  const mapCtrl = new window.PurahMap.MapController($("map-canvas"), {
    onCursorMove: (x, z) => {
      $("map-cursor-coords").textContent = `X: ${Math.round(x)} · Z: ${Math.round(z)}`;
    },
    onLayerChange: (layer) => syncLayerButtons(layer),
    onStopFollow: () => {
      $("chk-follow").checked = false;
      saveAllPrefs(false);
    },
    onViewChange: () => scheduleViewSave(),
    onSelect: (item) => renderMapDetail(item),
    onContextMarker: (x, z, layer) => openMarkerEditor({ x, z, layer }),
  });

  function collectAllPrefs() {
    return {
      mapMode: state.mapMode,
      assistRadius: state.assistRadius,
      fogOfWar: state.fogOfWar,
      hideCompleted: state.hideCompleted,
      layer: mapCtrl.layer,
      autoLayer: mapCtrl.autoLayer,
      followLink: mapCtrl.followLink,
      showHeroPath: mapCtrl.showHeroPath,
      showPins: mapCtrl.showPins,
      showQuests: mapCtrl.showQuests,
      showCustom: mapCtrl.showCustom,
      zoom: Number(mapCtrl.zoom.toFixed(4)),
      camX: Math.round(mapCtrl.camX * 100) / 100,
      camZ: Math.round(mapCtrl.camZ * 100) / 100,
      enabledCats: Array.from(mapCtrl.enabledCats),
      enabledEntities: Array.from(mapCtrl.enabledEntities),
      sidebarCollapsed: state.sidebarCollapsed,
      nearbyOpen: state.nearbyOpen,
      nearbyManuallyClosed: state.nearbyManuallyClosed,
      nearbyFilter: state.nearbyFilter,
      activeTab: state.activeTab,
      invCat: state.invCat,
      questCat: state.questCat,
      questStatus: state.questStatus,
      archiveSub: state.archiveSub,
      archiveCat: state.archiveCat,
      archiveSpoiler: state.archiveSpoiler,
      wikiCat: state.wikiCat,
      wikiShopsOnly: state.wikiShopsOnly,
      wikiAllRanks: state.wikiAllRanks,
    };
  }

  function applyAllPrefs(p) {
    if (!p || typeof p !== "object") return false;
    if (p.mapMode && ["spoiler_free", "assist", "full"].includes(p.mapMode)) {
      state.mapMode = p.mapMode;
      state.spoilerFree = p.mapMode === "spoiler_free";
      mapCtrl.mapMode = state.mapMode;
      mapCtrl.spoilerFree = state.spoilerFree;
    }
    if (typeof p.assistRadius === "number" && Number.isFinite(p.assistRadius) && p.assistRadius >= 50 && p.assistRadius <= 1000) {
      state.assistRadius = Math.round(p.assistRadius);
      mapCtrl.assistRadius = state.assistRadius;
    }
    if (typeof p.fogOfWar === "boolean") {
      state.fogOfWar = p.fogOfWar;
      mapCtrl.fogOfWar = p.fogOfWar;
    }
    if (typeof p.hideCompleted === "boolean") {
      state.hideCompleted = p.hideCompleted;
      mapCtrl.hideCompleted = p.hideCompleted;
    }
    if (p.layer && ["sky", "surface", "depths"].includes(p.layer)) mapCtrl.layer = p.layer;
    if (typeof p.autoLayer === "boolean") mapCtrl.autoLayer = p.autoLayer;
    if (typeof p.followLink === "boolean") mapCtrl.followLink = p.followLink;
    if (typeof p.showHeroPath === "boolean") mapCtrl.showHeroPath = p.showHeroPath;
    if (typeof p.showPins === "boolean") mapCtrl.showPins = p.showPins;
    if (typeof p.showQuests === "boolean") mapCtrl.showQuests = p.showQuests;
    if (typeof p.showCustom === "boolean") mapCtrl.showCustom = p.showCustom;
    if (typeof p.zoom === "number" && Number.isFinite(p.zoom)) {
      mapCtrl.zoom = Math.max(mapCtrl.minZoom, Math.min(mapCtrl.maxZoom, p.zoom));
    }
    if (typeof p.camX === "number" && Number.isFinite(p.camX)) {
      mapCtrl.camX = Math.max(-6500, Math.min(6500, p.camX));
    }
    if (typeof p.camZ === "number" && Number.isFinite(p.camZ)) {
      mapCtrl.camZ = Math.max(-5500, Math.min(5500, p.camZ));
    }
    if (Array.isArray(p.enabledCats)) {
      mapCtrl.enabledCats = new Set(p.enabledCats.filter((x) => typeof x === "string" && x));
    }
    if (Array.isArray(p.enabledEntities)) {
      mapCtrl.enabledEntities = new Set(p.enabledEntities.filter((x) => VALID_ENTITY_KEYS.includes(x)));
    }
    if (typeof p.sidebarCollapsed === "boolean") state.sidebarCollapsed = p.sidebarCollapsed;
    if (typeof p.nearbyManuallyClosed === "boolean") state.nearbyManuallyClosed = p.nearbyManuallyClosed;
    if (typeof p.nearbyOpen === "boolean") {
      state.nearbyOpen = p.nearbyOpen;
    } else if (state.mapMode === "assist" && !state.nearbyManuallyClosed) {
      state.nearbyOpen = true;
    }
    if (p.nearbyFilter && ["all", "poi", "npcs", "enemies", "resources"].includes(p.nearbyFilter)) {
      state.nearbyFilter = p.nearbyFilter;
    }
    if (p.activeTab && VALID_TABS.includes(p.activeTab)) state.activeTab = p.activeTab;
    if (p.invCat && INV_CATS.includes(p.invCat)) state.invCat = p.invCat;
    if (p.questCat && QUEST_CATS.includes(p.questCat)) state.questCat = p.questCat;
    if (p.questStatus && QUEST_STATUSES.includes(p.questStatus)) state.questStatus = p.questStatus;
    if (p.archiveSub && ARCHIVE_SUBS.includes(p.archiveSub)) state.archiveSub = p.archiveSub;
    if (p.archiveCat && ARCHIVE_CATS.includes(p.archiveCat)) state.archiveCat = p.archiveCat;
    if (typeof p.archiveSpoiler === "boolean") state.archiveSpoiler = p.archiveSpoiler;
    if (p.wikiCat && WIKI_CATS.includes(p.wikiCat)) state.wikiCat = p.wikiCat;
    if (typeof p.wikiShopsOnly === "boolean") state.wikiShopsOnly = p.wikiShopsOnly;
    if (typeof p.wikiAllRanks === "boolean") state.wikiAllRanks = p.wikiAllRanks;
    mapCtrl.dirty = true;
    return true;
  }

  function applyModeUI() {
    document.querySelectorAll("#map-mode-seg .mode-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.mode === state.mapMode);
    });
    const desc = $("map-mode-desc");
    if (desc) desc.textContent = tr("map.modeDesc." + state.mapMode);
    const box = $("assist-controls");
    if (box) box.classList.toggle("hidden", state.mapMode !== "assist");
    const rng = $("rng-assist-radius");
    if (rng) rng.value = String(state.assistRadius);
    const val = $("assist-radius-val");
    if (val) val.textContent = `${state.assistRadius} m`;
    const chkFog = $("chk-fog");
    if (chkFog) chkFog.checked = state.fogOfWar;
    const chkHide = $("chk-hide-done");
    if (chkHide) chkHide.checked = state.hideCompleted;
    const btnNearby = $("btn-nearby");
    if (btnNearby) btnNearby.classList.toggle("active", Boolean(state.nearbyOpen));
    const drawerNearby = $("map-nearby");
    if (drawerNearby) drawerNearby.classList.toggle("hidden", !state.nearbyOpen);
  }

  function syncAllControlUI() {
    applyModeUI();
    const chkAuto = $("chk-autolayer");
    if (chkAuto) chkAuto.checked = Boolean(mapCtrl.autoLayer);
    const chkFollow = $("chk-follow");
    if (chkFollow) chkFollow.checked = Boolean(mapCtrl.followLink);
    const chkHero = $("chk-heropath");
    if (chkHero) chkHero.checked = Boolean(mapCtrl.showHeroPath);
    const chkPins = $("chk-pins");
    if (chkPins) chkPins.checked = Boolean(mapCtrl.showPins);
    const chkQuests = $("chk-quests-map");
    if (chkQuests) chkQuests.checked = Boolean(mapCtrl.showQuests);
    const chkCustom = $("chk-custom-map");
    if (chkCustom) chkCustom.checked = Boolean(mapCtrl.showCustom);
    const sb = $("map-sidebar");
    if (sb) sb.classList.toggle("collapsed", Boolean(state.sidebarCollapsed));
    const chkArchSp = $("chk-archive-spoiler");
    if (chkArchSp) chkArchSp.checked = Boolean(state.archiveSpoiler);
    const chkWikiShops = $("chk-wiki-shops-only");
    if (chkWikiShops) chkWikiShops.checked = Boolean(state.wikiShopsOnly);
    const chkWikiRanks = $("chk-wiki-all-ranks");
    if (chkWikiRanks) chkWikiRanks.checked = Boolean(state.wikiAllRanks);
    syncLayerButtons(mapCtrl.layer);
  }

  function readLocalPrefs() {
    try {
      const raw = localStorage.getItem(PREFS_KEY) || localStorage.getItem(LEGACY_PREFS_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : null;
    } catch (_) {
      return null;
    }
  }

  function writeLocalPrefs(prefs) {
    try {
      localStorage.setItem(PREFS_KEY, JSON.stringify(prefs));
    } catch (_) {}
  }

  function flushPrefsToServer() {
    clearTimeout(prefsSaveTimer);
    prefsSaveTimer = null;
    if (!prefsDirty) return;
    prefsDirty = false;
    fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ui_prefs: collectAllPrefs() }),
      keepalive: true,
    }).catch(() => {});
  }

  function saveAllPrefs(immediate = false) {
    writeLocalPrefs(collectAllPrefs());
    prefsDirty = true;
    clearTimeout(prefsSaveTimer);
    if (immediate) {
      flushPrefsToServer();
    } else {
      prefsSaveTimer = setTimeout(flushPrefsToServer, 300);
    }
  }

  function flushPrefsBeacon() {
    clearTimeout(viewSaveTimer);
    clearTimeout(prefsSaveTimer);
    if (!prefsDirty) return;
    prefsDirty = false;
    const body = JSON.stringify({ ui_prefs: collectAllPrefs() });
    if (navigator.sendBeacon) {
      navigator.sendBeacon("/api/settings", new Blob([body], { type: "application/json" }));
    } else {
      fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body, keepalive: true }).catch(() => {});
    }
  }

  async function loadServerPrefs() {
    try {
      const res = await apiJson("/api/settings");
      state.serverPrefsLoaded = true;
      const serverPrefs = res && res.ui_prefs;
      if (serverPrefs && Object.keys(serverPrefs).length > 0) {
        applyAllPrefs(serverPrefs);
        writeLocalPrefs(collectAllPrefs());
        syncAllControlUI();
        if (state.staticLoaded && mapCtrl.enabledEntities.size > 0) {
          ensureEntitiesLoaded().catch(() => {});
        }
      } else {
        const localPrefs = readLocalPrefs();
        if (localPrefs && Object.keys(localPrefs).length > 0) {
          saveAllPrefs(true);
        }
      }
    } catch (_) {
      state.serverPrefsLoaded = true;
    }
  }

  const initialLocalPrefs = readLocalPrefs();
  if (initialLocalPrefs) {
    applyAllPrefs(initialLocalPrefs);
  }

  async function ensureEntitiesLoaded() {
    if (state.entitiesData) return state.entitiesData;
    if (state.entitiesPromise) return state.entitiesPromise;
    state.entitiesPromise = apiJson("/api/static/entities")
      .then((data) => {
        state.entitiesData = data;
        mapCtrl.setData({ entitiesData: data });
        renderCategoryList();
        if (state.nearbyOpen) renderNearbyPanel(true);
        return data;
      })
      .catch((err) => {
        state.entitiesPromise = null;
        throw err;
      });
    return state.entitiesPromise;
  }

  function syncLayerButtons(layer) {
    document.querySelectorAll(".layer-btn").forEach((b) => {
      b.classList.toggle("active", b.dataset.layer === layer);
    });
    $("map-zoom-label").textContent = window.PurahMap.LAYER_LABELS[layer] || layer;
    if (state.nearbyOpen) renderNearbyPanel(true);
  }

  function renderCategoryList() {
    const container = $("map-categories");
    const doneMap = (state.snapshot && state.snapshot.progress && state.snapshot.progress.done) || {};
    const foundMap = (state.snapshot && state.snapshot.progress && state.snapshot.progress.found) || {};

    container.innerHTML = "";
    for (const meta of mapCtrl.getCategoryMeta()) {
      const list = (state.mapData && state.mapData[meta.key]) || [];
      const doneArr = doneMap[meta.key] || [];
      const doneCount = doneArr.reduce((a, b) => a + (b ? 1 : 0), 0);
      const foundArr = foundMap[meta.key] || [];

      const hideDone = state.hideCompleted && !meta.noHideCompleted;
      let countText;
      if (hideDone) {
        if (state.mapMode === "spoiler_free") {
          const rem = foundArr.reduce((a, b, idx) => a + (b && !doneArr[idx] ? 1 : 0), 0);
          countText = tr("count.pending", { n: rem });
        } else if (state.mapMode === "assist") {
          let vis = 0;
          for (let i = 0; i < list.length; i++) {
            if (doneArr[i]) continue;
            if (foundArr[i]) {
              vis++;
            } else {
              const p = list[i].position;
              if (p && mapCtrl.isInAssistRadius(p.x, p.z, list[i].layer || "surface")) vis++;
            }
          }
          countText = tr("count.remaining", { n: vis });
        } else {
          countText = tr("count.remaining", { n: list.length - doneCount });
        }
      } else if (state.mapMode === "spoiler_free") {
        const discovered = doneCount + foundArr.reduce((a, b, idx) => a + (b && !doneArr[idx] ? 1 : 0), 0);
        countText = tr("count.found", { n: discovered });
      } else if (state.mapMode === "assist") {
        let vis = 0;
        for (let i = 0; i < list.length; i++) {
          if (doneArr[i] || foundArr[i]) {
            vis++;
          } else {
            const p = list[i].position;
            if (p && mapCtrl.isInAssistRadius(p.x, p.z, list[i].layer || "surface")) vis++;
          }
        }
        countText = tr("count.visible", { n: vis });
      } else {
        countText = `${doneCount}/${list.length}`;
      }

      const el = document.createElement("div");
      el.className = "cat-item" + (mapCtrl.enabledCats.has(meta.key) ? " on" : "");
      el.innerHTML = `
        <div class="cat-left">
          <img src="/api/icon/map/${meta.icon}.png?v=5" alt="" onerror="this.style.display='none'" />
          <span class="cat-name">${esc(meta.label)}</span>
        </div>
        <span class="cat-count">${countText}</span>
      `;
      el.addEventListener("click", () => {
        if (mapCtrl.enabledCats.has(meta.key)) mapCtrl.enabledCats.delete(meta.key);
        else mapCtrl.enabledCats.add(meta.key);
        mapCtrl.dirty = true;
        saveAllPrefs();
        renderCategoryList();
      });
      container.appendChild(el);
    }

    const groupHdr = document.createElement("div");
    groupHdr.className = "cat-group-label";
    groupHdr.textContent = tr("map.livingWorld");
    container.appendChild(groupHdr);

    const layerMap = ["surface", "sky", "depths"];
    const { nums: unlockedTowers } = mapCtrl._getUnlockedTowerNums();
    const unlockedLightroots = doneMap.lightroots || [];
    const beginningOpen = mapCtrl._isBeginningIslandVisited();

    for (const meta of mapCtrl.getEntityMeta()) {
      const arr = state.entitiesData ? state.entitiesData[meta.key] || [] : null;
      let countText = tr("count.load");
      if (arr) {
        if (state.mapMode === "full") {
          countText = `${arr.length}`;
        } else {
          let vis = 0;
          for (let i = 0; i < arr.length; i++) {
            const ent = arr[i];
            if (mapCtrl.isEntityVisible(ent, layerMap[ent[3]] || "surface", unlockedTowers, unlockedLightroots, beginningOpen)) {
              vis++;
            }
          }
          countText = state.mapMode === "assist" ? tr("count.visible", { n: vis }) : tr("count.inArea", { n: vis });
        }
      } else if (mapCtrl.enabledEntities.has(meta.key)) {
        countText = "...";
      }

      const el = document.createElement("div");
      el.className = "cat-item" + (mapCtrl.enabledEntities.has(meta.key) ? " on" : "");
      el.innerHTML = `
        <div class="cat-left">
          <img src="/api/icon/map/${meta.icon}.png?v=5" alt="" onerror="this.style.display='none'" />
          <span class="cat-name">${esc(meta.label)}</span>
        </div>
        <span class="cat-count">${countText}</span>
      `;
      el.addEventListener("click", async () => {
        if (mapCtrl.enabledEntities.has(meta.key)) {
          mapCtrl.enabledEntities.delete(meta.key);
          mapCtrl.dirty = true;
          saveAllPrefs();
          renderCategoryList();
        } else {
          mapCtrl.enabledEntities.add(meta.key);
          saveAllPrefs();
          renderCategoryList();
          try {
            await ensureEntitiesLoaded();
            mapCtrl.dirty = true;
          } catch (_) {
            mapCtrl.enabledEntities.delete(meta.key);
            saveAllPrefs();
            renderCategoryList();
          }
        }
      });
      container.appendChild(el);
    }
  }

  function selectWorldOnMap(meta, index, o, done, found, zoomLevel = 0.55) {
    $("chk-follow").checked = false;
    mapCtrl.followLink = false;
    mapCtrl.enabledCats.add(meta.key);
    renderCategoryList();
    mapCtrl.selected = {
      kind: "world",
      cat: meta.key,
      catLabel: meta.label,
      index,
      raw: o,
      done: Boolean(done),
      found: Boolean(found),
    };
    const lyr = o.layer || "surface";
    mapCtrl.focusPoint(o.position.x, o.position.z, lyr, zoomLevel);
    syncLayerButtons(lyr);
    renderMapDetail(mapCtrl.selected);
  }

  function selectEntityOnMap(meta, index, ent, layer, zoomLevel = 0.55) {
    const names = (state.entitiesData && state.entitiesData.names) || [];
    const name = names[ent[4]] || meta.singular;
    const availQuests = meta.key === "npcs" ? mapCtrl.getAvailableNpcQuests(index) : null;
    const hasQuest = Boolean(availQuests && availQuests.length);
    $("chk-follow").checked = false;
    mapCtrl.followLink = false;
    mapCtrl.enabledEntities.add(meta.key);
    renderCategoryList();
    mapCtrl.selected = {
      kind: "entity",
      cat: meta.key,
      catLabel: hasQuest ? tr("ent.questNpcCat") : tr("ent." + meta.key),
      singular: hasQuest ? tr("ent.questNpcSingular") : tr("ent." + meta.key + ".singular"),
      index,
      display_name: name,
      count: ent[5] || 1,
      quests: availQuests,
      layer,
      position: { x: ent[0], y: ent[2], z: ent[1] },
    };
    mapCtrl.focusPoint(ent[0], ent[1], layer, zoomLevel);
    syncLayerButtons(layer);
    renderMapDetail(mapCtrl.selected);
  }

  function openItemInWiki(itemId) {
    const items = (state.catalogData && state.catalogData.items) || {};
    const entry = items[itemId];
    if (!entry) return;
    state.wikiCat = "all";
    state.wikiShopsOnly = false;
    if (entry.category === "" || (entry.category === "Armor" && (entry.rank > 1 || entry.id.endsWith("_B")))) {
      state.wikiAllRanks = true;
    }
    const srch = $("wiki-search");
    if (srch) srch.value = "";
    state.wikiSelected = itemId;
    switchTab("wiki");
  }

  function renderMapDetail(item) {
    const panel = $("map-detail");
    if (!item) {
      panel.classList.add("hidden");
      return;
    }
    panel.classList.remove("hidden");
    const linkPos = (state.live && state.live.player && state.live.player.pos) ||
                    (state.snapshot && state.snapshot.player && state.snapshot.player.pos);
    const pos = item.position || (item.raw && item.raw.position);
    const dist = linkPos && pos ? `${Math.round(Math.hypot(pos.x - linkPos[0], pos.z - linkPos[2]))} m` : "—";

    if (item.kind === "world") {
      const o = item.raw;
      const statusBadge = item.done
        ? `<span class="status-tag complete">${esc(tr("detail.done"))}</span>`
        : item.found
        ? `<span class="status-tag active">${esc(tr("detail.found"))}</span>`
        : `<span class="status-tag queued">${esc(tr("detail.unfound"))}</span>`;
      const catLbl = item.cat ? tr("cat." + item.cat) : item.catLabel;
      const catSubtitle = o.sub_label ? `${catLbl} · ${o.sub_label}` : catLbl;
      const goods = Array.isArray(o.goods) ? o.goods : [];
      const goodsHtml = goods.length
        ? `<div class="shop-goods-box">
            <h4>${esc(tr("detail.shopGoods", { n: goods.length }))}</h4>
            <div class="shop-goods-list">
              ${goods
                .map(
                  (g) => `
                <div class="shop-good-row" data-wiki-id="${esc(g.id)}">
                  <img src="/api/icon/item/${esc(g.icon || g.id)}.png" alt="" onerror="this.style.opacity='0.25'" />
                  <div class="shop-good-name">${esc(g.name)}${g.bundle > 1 ? ` ×${g.bundle}` : ""}</div>
                  <div class="shop-good-price">${esc(formatShopPrice(g))}</div>
                </div>`
                )
                .join("")}
            </div>
          </div>`
        : "";
      panel.innerHTML = `
        <div class="detail-head">
          <div>
            <div class="muted" style="font-size:11px;margin-bottom:3px">${esc(catSubtitle)}</div>
            <h3>${esc(o.display_name)}</h3>
          </div>
          <button class="icon-btn" id="btn-close-map-detail">✕</button>
        </div>
        <div style="margin-bottom:10px">${statusBadge}</div>
        <div class="kv-list">
          <div class="kv-row"><span>${esc(tr("detail.layer"))}</span><strong>${esc(window.PurahMap.LAYER_LABELS[o.layer] || o.layer)}</strong></div>
          <div class="kv-row"><span>${esc(tr("detail.coords"))}</span><strong>${Math.round(o.position.x)}, ${Math.round(o.position.z)}, ${Math.round(o.position.y)}</strong></div>
          <div class="kv-row"><span>${esc(tr("detail.distLink"))}</span><strong>${dist}</strong></div>
          ${o.puzzle_type ? `<div class="kv-row"><span>${esc(tr("detail.puzzleType"))}</span><strong>${esc(o.puzzle_type)}</strong></div>` : ""}
        </div>
        ${
          o.contents && o.contents.length
            ? `<div class="step-box"><h4>${esc(tr("detail.dispenserContains"))}</h4><div>${o.contents.map(esc).join(" · ")}</div></div>`
            : ""
        }
        ${goodsHtml}
      `;
      panel.querySelectorAll("[data-wiki-id]").forEach((row) => {
        row.onclick = () => openItemInWiki(row.dataset.wikiId);
      });
    } else if (item.kind === "entity") {
      const entMeta = mapCtrl.getEntityMeta().find((m) => m.key === item.cat);
      const quests = Array.isArray(item.quests) ? item.quests : [];
      const iconName = quests.length ? "entity_npc_quest" : (entMeta && entMeta.icon) || "entity_npc";
      const questsHtml = quests.length
        ? `<div class="npc-quests-box">
            <h4>${esc(tr("detail.npcQuests"))}</h4>
            ${quests
              .map(
                (q) => `
              <div class="npc-quest-card">
                <div class="npc-quest-title">${esc(q.name)}</div>
                <div class="npc-quest-meta">${esc(q.region || "Hyrule")}</div>
                <button class="btn btn-gold" data-open-quest="${esc(q.id)}" style="width:100%;padding:5px 10px;font-size:12px">${esc(tr("detail.openInJournal"))}</button>
              </div>`
              )
              .join("")}
          </div>`
        : "";
      panel.innerHTML = `
        <div class="detail-head">
          <div style="display:flex;align-items:center;gap:10px">
            <img src="/api/icon/map/${esc(iconName)}.png?v=5" onerror="this.style.display='none'" alt="" style="width:34px;height:34px;object-fit:contain" />
            <div>
              <div class="muted" style="font-size:11px;margin-bottom:2px">${esc(quests.length ? tr("ent.questNpcSingular") : (entMeta && entMeta.singular) || item.singular || item.catLabel)}</div>
              <h3>${esc(item.display_name)}</h3>
            </div>
          </div>
          <button class="icon-btn" id="btn-close-map-detail">✕</button>
        </div>
        <div class="kv-list">
          ${item.count > 1 ? `<div class="kv-row"><span>${esc(tr("detail.countHere"))}</span><strong>${item.count}×</strong></div>` : ""}
          <div class="kv-row"><span>${esc(tr("detail.layer"))}</span><strong>${esc(window.PurahMap.LAYER_LABELS[item.layer] || item.layer)}</strong></div>
          <div class="kv-row"><span>${esc(tr("detail.coords"))}</span><strong>${Math.round(item.position.x)}, ${Math.round(item.position.z)}, ${Math.round(item.position.y)}</strong></div>
          <div class="kv-row"><span>${esc(tr("detail.distLink"))}</span><strong>${dist}</strong></div>
        </div>
        ${questsHtml}
      `;
      panel.querySelectorAll("[data-open-quest]").forEach((btn) => {
        btn.onclick = () => {
          const qid = btn.dataset.openQuest;
          const st = (state.snapshot && state.snapshot.quests && state.snapshot.quests[qid]) || {};
          state.questCat = "all";
          state.questStatus = st.status || "available";
          state.questSelected = qid;
          switchTab("quests");
          renderQuests();
        };
      });
    } else if (item.kind === "quest") {
      const q = item.raw;
      const st = item.state;
      panel.innerHTML = `
        <div class="detail-head">
          <div>
            <div class="muted" style="font-size:11px;margin-bottom:3px">${esc(tr("detail.activeQuest"))}</div>
            <h3>${esc(q.name)}</h3>
          </div>
          <button class="icon-btn" id="btn-close-map-detail">✕</button>
        </div>
        <div class="detail-desc">${esc(st.stepText || "")}</div>
        <div class="kv-list">
          <div class="kv-row"><span>${esc(tr("detail.region"))}</span><strong>${esc(q.region || "—")}</strong></div>
          <div class="kv-row"><span>${esc(tr("detail.dist"))}</span><strong>${dist}</strong></div>
        </div>
        <button class="btn btn-gold" id="btn-open-in-quests" style="width:100%;margin-top:8px">${esc(tr("detail.openInJournal"))}</button>
      `;
      setTimeout(() => {
        const b = $("btn-open-in-quests");
        if (b) {
          b.onclick = () => {
            state.questSelected = q.id;
            switchTab("quests");
            renderQuests();
          };
        }
      }, 0);
    } else if (item.kind === "pin" || item.kind === "stamp") {
      const isPin = item.kind === "pin";
      const isLive = state.live && state.live.mode === "live" && state.live.status === "ready";
      const iconName = isPin ? `pin_${item.raw.type}` : `stamp_${item.raw.type}`;
      const title = isPin ? tr("pin." + item.raw.type) || tr("detail.pinDefault") : tr("detail.stampPrefix", { name: tr("stamp." + item.raw.type) || item.raw.type });
      const hasSlot = typeof item.raw.slot === "number";
      panel.innerHTML = `
        <div class="detail-head">
          <div style="display:flex;align-items:center;gap:10px">
            <img src="/api/icon/map/${esc(iconName)}.png?v=5" alt="" style="width:36px;height:36px;object-fit:contain" />
            <div>
              <div class="muted" style="font-size:11px;margin-bottom:2px">${esc(tr("detail.gameMark"))}</div>
              <h3>${esc(title)}</h3>
            </div>
          </div>
          <button class="icon-btn" id="btn-close-map-detail">✕</button>
        </div>
        <div class="kv-list">
          <div class="kv-row"><span>${esc(tr("detail.layer"))}</span><strong>${esc(window.PurahMap.LAYER_LABELS[item.layer] || item.layer)}</strong></div>
          <div class="kv-row"><span>${esc(tr("detail.coords"))}</span><strong>${Math.round(pos.x)}, ${Math.round(pos.z)}${isPin && typeof pos.y === "number" ? `, ${Math.round(pos.y)}` : ""}</strong></div>
          <div class="kv-row"><span>${esc(tr("detail.dist"))}</span><strong>${dist}</strong></div>
        </div>
        ${
          hasSlot && isLive
            ? `<button id="btn-del-game-mark" class="btn btn-danger" style="width:100%;margin-top:10px">${esc(tr("detail.removeFromGame"))}</button>
               <div class="muted" style="font-size:11px;margin-top:6px;line-height:1.35">${esc(tr("detail.removeFromGameHint"))}</div>`
            : `<div class="muted" style="font-size:11px;margin-top:8px">${esc(tr("detail.needLiveMark"))}</div>`
        }
        <div id="game-mark-err" class="muted" style="color:var(--danger);font-size:12px;margin-top:6px"></div>
      `;
      setTimeout(() => {
        const delBtn = $("btn-del-game-mark");
        if (delBtn) {
          delBtn.onclick = async () => {
            delBtn.disabled = true;
            try {
              const url = isPin ? `/api/game/pins/${item.raw.slot}` : `/api/game/stamps/${item.raw.slot}`;
              const res = await fetch(url, { method: "DELETE" });
              if (!res.ok) {
                const err = await res.json().catch(() => ({}));
                throw new Error(err.error || `HTTP ${res.status}`);
              }
              const live = await apiJson("/api/live");
              state.live = live;
              mapCtrl.selected = null;
              mapCtrl.setData({ live });
              renderMapDetail(null);
            } catch (err) {
              $("game-mark-err").textContent = err.message;
              delBtn.disabled = false;
            }
          };
        }
      }, 0);
    } else if (item.kind === "custom") {
      const mk = item.raw;
      panel.innerHTML = `
        <div class="detail-head">
          <div>
            <div class="muted" style="font-size:11px;margin-bottom:3px">${esc(tr("detail.customMarker"))}</div>
            <h3>${esc(mk.title)}</h3>
          </div>
          <button class="icon-btn" id="btn-close-map-detail">✕</button>
        </div>
        <div class="detail-desc">${esc(mk.note || tr("detail.noNotes"))}</div>
        <div class="kv-list">
          <div class="kv-row"><span>${esc(tr("detail.layer"))}</span><strong>${esc(window.PurahMap.LAYER_LABELS[mk.layer] || mk.layer)}</strong></div>
          <div class="kv-row"><span>${esc(tr("detail.coords"))}</span><strong>${Math.round(mk.x)}, ${Math.round(mk.z)}</strong></div>
          <div class="kv-row"><span>${esc(tr("detail.dist"))}</span><strong>${dist}</strong></div>
        </div>
        <div style="display:flex;gap:8px;margin-top:10px">
          <button class="btn btn-gold" id="btn-edit-mk" style="flex:1">${esc(tr("detail.edit"))}</button>
          <button class="btn btn-danger" id="btn-del-mk" style="flex:1">${esc(tr("detail.delete"))}</button>
        </div>
      `;
      setTimeout(() => {
        $("btn-edit-mk").onclick = () => openMarkerEditor(mk);
        $("btn-del-mk").onclick = async () => {
          await apiJson(`/api/markers/${mk.id}`, { method: "DELETE" });
          state.userMarkers = state.userMarkers.filter((m) => m.id !== mk.id);
          mapCtrl.selected = null;
          mapCtrl.setData({ userMarkers: state.userMarkers });
          renderMapDetail(null);
        };
      }, 0);
    }

    const closeBtn = $("btn-close-map-detail");
    if (closeBtn) {
      closeBtn.onclick = () => {
        mapCtrl.selected = null;
        mapCtrl.dirty = true;
        renderMapDetail(null);
      };
    }
  }

  function openMarkerEditor(init) {
    const panel = $("map-detail");
    panel.classList.remove("hidden");
    const isEdit = Boolean(init.id);
    const isLive = state.live && state.live.mode === "live" && state.live.status === "ready";
    const activePins = new Set((((state.live && state.live.map) || (state.snapshot && state.snapshot.map) || {}).pins || []).map((p) => p.type));
    let mode = isEdit ? "note" : isLive ? "pin" : "note";

    const renderBody = () => {
      const layerLbl = window.PurahMap.LAYER_LABELS[init.layer || mapCtrl.layer] || mapCtrl.layer;
      panel.innerHTML = `
        <div class="detail-head">
          <h3>${esc(isEdit ? tr("mk.editNote") : tr("mk.addTitle"))}</h3>
          <button class="icon-btn" id="btn-close-mk-form">✕</button>
        </div>
        ${
          !isEdit
            ? `<div class="pill-bar" style="margin-bottom:12px">
                <button class="pill ${mode === "pin" ? "active" : ""}" data-mkmode="pin">${esc(tr("mk.tabPin"))}</button>
                <button class="pill ${mode === "stamp" ? "active" : ""}" data-mkmode="stamp">${esc(tr("mk.tabStamp"))}</button>
                <button class="pill ${mode === "note" ? "active" : ""}" data-mkmode="note">${esc(tr("mk.tabNote"))}</button>
              </div>`
            : ""
        }
        <div class="kv-list" style="margin-bottom:12px">
          <div class="kv-row"><span>${esc(tr("mk.location"))}</span><strong>${Math.round(init.x)}, ${Math.round(init.z)} (${esc(layerLbl)})</strong></div>
        </div>
        <div id="mk-mode-body"></div>
        <div id="mk-err" class="muted" style="color:var(--danger);font-size:12px;margin-top:8px"></div>
      `;

      $("btn-close-mk-form").onclick = () => panel.classList.add("hidden");
      panel.querySelectorAll("[data-mkmode]").forEach((b) => {
        b.onclick = () => {
          mode = b.dataset.mkmode;
          renderBody();
        };
      });

      const body = $("mk-mode-body");
      if (mode === "pin") {
        if (!isLive) {
          body.innerHTML = `<div class="empty-hint" style="padding:12px 0">${esc(tr("mk.needLivePin"))}</div>`;
          return;
        }
        body.innerHTML = `
          <div class="muted" style="font-size:12px;margin-bottom:8px">${esc(tr("mk.pickPin"))}</div>
          <div class="picker-grid pins">
            ${PIN_COLOR_HEX
              .map(
                ([k, hex]) => `
                <button class="picker-btn" data-pin="${k}">
                  <img src="/api/icon/map/pin_${k}.png?v=5" alt="" />
                  <span>${esc(tr("color." + k))}</span>
                  ${activePins.has(k) ? `<small style="color:${hex}">${esc(tr("mk.move"))}</small>` : `<small class="muted">${esc(tr("mk.new"))}</small>`}
                </button>`
              )
              .join("")}
          </div>
        `;
        body.querySelectorAll("[data-pin]").forEach((btn) => {
          btn.onclick = async () => {
            btn.disabled = true;
            try {
              const res = await fetch("/api/game/pins", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  color: btn.dataset.pin,
                  x: init.x,
                  z: init.z,
                  layer: init.layer || mapCtrl.layer,
                }),
              });
              const data = await res.json();
              if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
              const live = await apiJson("/api/live");
              state.live = live;
              mapCtrl.setData({ live });
              const placed = (live.map && live.map.pins || []).find((p) => p.slot === data.slot) || data;
              mapCtrl.selected = { kind: "pin", raw: placed, position: { x: placed.x, y: placed.y, z: placed.z }, layer: placed.layer };
              renderMapDetail(mapCtrl.selected);
            } catch (err) {
              $("mk-err").textContent = err.message;
              btn.disabled = false;
            }
          };
        });
      } else if (mode === "stamp") {
        if (!isLive) {
          body.innerHTML = `<div class="empty-hint" style="padding:12px 0">${esc(tr("mk.needLiveStamp"))}</div>`;
          return;
        }
        body.innerHTML = `
          <div class="muted" style="font-size:12px;margin-bottom:8px">${esc(tr("mk.pickStamp"))}</div>
          <div class="picker-grid stamps">
            ${STAMP_KEYS
              .map(
                (k) => `
                <button class="picker-btn" data-stamp="${k}">
                  <img src="/api/icon/map/stamp_${k}.png?v=5" alt="" />
                  <span>${esc(tr("stamp." + k))}</span>
                </button>`
              )
              .join("")}
          </div>
        `;
        body.querySelectorAll("[data-stamp]").forEach((btn) => {
          btn.onclick = async () => {
            btn.disabled = true;
            try {
              const res = await fetch("/api/game/stamps", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  type: btn.dataset.stamp,
                  x: init.x,
                  z: init.z,
                  layer: init.layer || mapCtrl.layer,
                }),
              });
              const data = await res.json();
              if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);
              const live = await apiJson("/api/live");
              state.live = live;
              mapCtrl.setData({ live });
              const placed = (live.map && live.map.stamps || []).find((s) => s.slot === data.slot) || data;
              mapCtrl.selected = { kind: "stamp", raw: placed, position: { x: placed.x, y: 0, z: placed.z }, layer: placed.layer };
              renderMapDetail(mapCtrl.selected);
            } catch (err) {
              $("mk-err").textContent = err.message;
              btn.disabled = false;
            }
          };
        });
      } else {
        body.innerHTML = `
          <div class="form-group">
            <label>${esc(tr("mk.titleLabel"))}</label>
            <input id="mk-title" class="form-control" value="${esc(init.title || "")}" placeholder="${esc(tr("mk.titlePlaceholder"))}" />
          </div>
          <div class="form-group">
            <label>${esc(tr("mk.colorLabel"))}</label>
            <input id="mk-color" type="color" class="form-control" style="height:36px;padding:3px" value="${esc(init.color || "#f0c850")}" />
          </div>
          <div class="form-group">
            <label>${esc(tr("mk.notesLabel"))}</label>
            <textarea id="mk-note" class="form-control" placeholder="${esc(tr("mk.notesPlaceholder"))}">${esc(init.note || "")}</textarea>
          </div>
          <button id="btn-save-mk" class="btn btn-gold" style="width:100%;margin-top:8px">${esc(tr("mk.saveNote"))}</button>
        `;
        $("btn-save-mk").onclick = async () => {
          const payload = {
            title: $("mk-title").value.trim() || tr("mk.defaultName"),
            note: $("mk-note").value.trim(),
            color: $("mk-color").value,
            layer: init.layer || mapCtrl.layer,
            x: init.x,
            z: init.z,
          };
          if (isEdit) {
            const updated = await apiJson(`/api/markers/${init.id}`, {
              method: "PUT",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(payload),
            });
            state.userMarkers = state.userMarkers.map((m) => (m.id === init.id ? updated : m));
            mapCtrl.selected = { kind: "custom", raw: updated, position: { x: updated.x, y: 0, z: updated.z }, layer: updated.layer };
            renderMapDetail(mapCtrl.selected);
          } else {
            const created = await apiJson("/api/markers", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(payload),
            });
            state.userMarkers.push(created);
            mapCtrl.selected = { kind: "custom", raw: created, position: { x: created.x, y: 0, z: created.z }, layer: created.layer };
            renderMapDetail(mapCtrl.selected);
          }
          mapCtrl.setData({ userMarkers: state.userMarkers });
        };
      }
    };

    renderBody();
  }

  function setupMapSearch() {
    const input = $("map-search");
    const box = $("map-search-results");
    const LAYER_NAMES = ["surface", "sky", "depths"];

    const runSearch = () => {
      const q = input.value.trim().toLowerCase();
      if (q.length < 2 || !state.mapData) {
        box.classList.add("hidden");
        return;
      }
      if (!state.entitiesData) {
        ensureEntitiesLoaded().then(() => {
          if (input.value.trim().toLowerCase() === q) runSearch();
        }).catch(() => {});
      }

      const doneMap = (state.snapshot && state.snapshot.progress && state.snapshot.progress.done) || {};
      const foundMap = (state.snapshot && state.snapshot.progress && state.snapshot.progress.found) || {};
      const hits = [];

      for (const meta of mapCtrl.getCategoryMeta()) {
        const list = state.mapData[meta.key] || [];
        const dArr = doneMap[meta.key] || [];
        const fArr = foundMap[meta.key] || [];
        for (let i = 0; i < list.length; i++) {
          const o = list[i];
          const isDone = Boolean(dArr[i]);
          const isFound = Boolean(fArr[i]);
          const lyr = o.layer || "surface";
          if (state.hideCompleted && isDone && !meta.noHideCompleted) continue;
          if (state.mapMode === "spoiler_free" && !isDone && !isFound) continue;
          if (state.mapMode === "assist" && !isDone && !isFound && (!o.position || !mapCtrl.isInAssistRadius(o.position.x, o.position.z, lyr))) continue;
          const hay = ((o.display_name || "") + " " + (o.sub_label || "")).toLowerCase();
          if (hay.includes(q)) {
            hits.push({ kind: "world", meta, i, o, done: isDone, found: isFound });
            if (hits.length >= 25) break;
          }
        }
        if (hits.length >= 25) break;
      }

      if (state.entitiesData && hits.length < 35) {
        const names = state.entitiesData.names || [];
        const { nums: unlockedTowers } = mapCtrl._getUnlockedTowerNums();
        const unlockedLightroots = doneMap.lightroots || [];
        const beginningOpen = mapCtrl._isBeginningIslandVisited();
        for (const meta of mapCtrl.getEntityMeta()) {
          const arr = state.entitiesData[meta.key] || [];
          for (let i = 0; i < arr.length; i++) {
            const ent = arr[i];
            const nm = names[ent[4]] || "";
            if (!nm.toLowerCase().includes(q)) continue;
            const lyr = LAYER_NAMES[ent[3]] || "surface";
            if (!mapCtrl.isEntityVisible(ent, lyr, unlockedTowers, unlockedLightroots, beginningOpen)) continue;
            hits.push({ kind: "entity", meta, i, ent, name: nm, layer: lyr });
            if (hits.length >= 35) break;
          }
          if (hits.length >= 35) break;
        }
      }

      if (!hits.length) {
        box.innerHTML = `<div class="search-row"><span class="muted">${esc(tr("search.noResults"))}</span></div>`;
      } else {
        box.innerHTML = "";
        for (const h of hits) {
          const row = document.createElement("div");
          row.className = "search-row";
          if (h.kind === "world") {
            const sub = h.o.sub_label ? `${h.meta.label} · ${h.o.sub_label}` : h.meta.label;
            row.innerHTML = `<span>${esc(h.o.display_name)}</span><small>${esc(sub)}</small>`;
            row.onclick = () => {
              box.classList.add("hidden");
              selectWorldOnMap(h.meta, h.i, h.o, h.done, h.found, 0.55);
            };
          } else {
            const cnt = h.ent[5] > 1 ? ` (×${h.ent[5]})` : "";
            row.innerHTML = `<span>${esc(h.name + cnt)}</span><small>${esc(h.meta.singular)}</small>`;
            row.onclick = () => {
              box.classList.add("hidden");
              selectEntityOnMap(h.meta, h.i, h.ent, h.layer, 0.55);
            };
          }
          box.appendChild(row);
        }
      }
      box.classList.remove("hidden");
    };

    input.addEventListener("input", runSearch);
  }

  // ---------------- HUD & Status ----------------
  function renderHearts(p) {
    const box = $("hud-hearts");
    if (!p) {
      box.innerHTML = "";
      return;
    }
    const maxQ = p.maxLife || 12;
    const curQ = Math.max(0, p.life || 0);
    const extraQ = Math.max(0, p.extraLife || 0);
    const totalHearts = Math.ceil((maxQ + extraQ) / 4);
    let html = "";
    for (let i = 0; i < Math.min(totalHearts, 40); i++) {
      const qStart = i * 4;
      const isExtra = qStart >= maxQ;
      const filled = isExtra ? Math.min(4, Math.max(0, extraQ - (qStart - maxQ))) : Math.min(4, Math.max(0, curQ - qStart));
      const color = isExtra ? "#f5d442" : filled > 0 ? "#ef4455" : "#2c3a44";
      const op = filled === 0 ? "0.35" : String(0.35 + filled * 0.1625);
      html += `<svg class="heart-svg" viewBox="0 0 24 24"><path fill="${color}" fill-opacity="${op}" stroke="#0b1116" stroke-width="1.4" d="M12 21.35l-1.45-1.32C5.4 15.36 2 12.28 2 8.5 2 5.42 4.42 3 7.5 3c1.74 0 3.41.81 4.5 2.09C13.09 3.81 14.76 3 16.5 3 19.58 3 22 5.42 22 8.5c0 3.78-3.4 6.86-8.55 11.54L12 21.35z"/></svg>`;
    }
    box.innerHTML = html;
  }

  function renderHud(data) {
    const pill = $("conn-pill");
    const mode = (data && data.mode) || "offline";
    if (mode === "live") {
      pill.textContent = tr("conn.live");
      pill.className = "conn-pill live";
    } else if (mode === "title") {
      pill.textContent = tr("conn.title");
      pill.className = "conn-pill title";
    } else if (mode === "save") {
      pill.textContent = tr("conn.save");
      pill.className = "conn-pill save";
    } else {
      pill.textContent = tr("conn.offline");
      pill.className = "conn-pill offline";
    }

    const p = data && data.player;
    renderHearts(p);
    if (!p) {
      $("hud-stamina").textContent = "⚡ —";
      $("hud-battery").textContent = "🔋 —";
      $("hud-rupees").textContent = "◆ —";
      $("hud-coords").textContent = "X: — Z: —";
      return;
    }

    const wheels = ((p.maxStamina || 1000) / 1000).toFixed(1).replace(/\.0$/, "");
    $("hud-stamina").textContent = `⚡ ${wheels}x`;
    const cells = Math.round((p.maxEnergy || 100) / 100);
    $("hud-battery").textContent = `🔋 ${cells}`;
    $("hud-rupees").textContent = `◆ ${p.rupees ?? 0}`;

    if ((p.poes || 0) > 0) {
      $("hud-poes").style.display = "";
      $("hud-poes").textContent = `👻 ${p.poes}`;
    } else {
      $("hud-poes").style.display = "none";
    }

    if (p.cookBuff && p.cookBuff.time > 0) {
      const m = Math.floor(p.cookBuff.time / 60);
      const s = Math.floor(p.cookBuff.time % 60);
      $("hud-buff").style.display = "";
      $("hud-buff").textContent = `🍲 Lv.${p.cookBuff.level} ${m}:${String(s).padStart(2, "0")}`;
    } else {
      $("hud-buff").style.display = "none";
    }

    if (p.pos) {
      $("hud-coords").textContent = `X:${Math.round(p.pos[0])} Z:${Math.round(p.pos[2])} Y:${Math.round(p.pos[1])}`;
    }
  }

  // ---------------- Inventário ----------------
  function itemInfo(actorId) {
    return (state.catalogData && state.catalogData.items && state.catalogData.items[actorId]) || {
      id: actorId,
      name: actorId,
      caption: "",
      icon: actorId,
    };
  }

  function renderInventory() {
    const sagesBox = $("sages-strip");
    const sages = (state.snapshot && state.snapshot.sages) || [];
    sagesBox.innerHTML = sages
      .map((s) => {
        const cls = !s.joined ? "locked" : s.summoned ? "active" : "";
        const stTxt = !s.joined ? tr("inv.sage.locked") : s.summoned ? tr("inv.sage.summoned") : tr("inv.sage.dismissed");
        return `<div class="sage-badge ${cls}"><strong>${esc(tr("inv.sage." + s.id))}</strong><span>${esc(stTxt)}</span></div>`;
      })
      .join("");

    const catsBox = $("inv-cats");
    const pouch = (state.snapshot && state.snapshot.pouch) || {};
    catsBox.innerHTML = "";
    for (const cKey of INV_CATS) {
      const arr = pouch[cKey] || [];
      const btn = document.createElement("button");
      btn.className = "pill" + (state.invCat === cKey ? " active" : "");
      btn.textContent = `${tr("inv.cat." + cKey)} (${arr.length})`;
      btn.onclick = () => {
        state.invCat = cKey;
        state.invSelected = null;
        saveAllPrefs();
        renderInventory();
      };
      catsBox.appendChild(btn);
    }

    const q = $("inv-search").value.trim().toLowerCase();
    const list = (pouch[state.invCat] || []).filter((it) => {
      if (!q) return true;
      const meta = itemInfo(it.name);
      const fuseMeta = it.fuse ? itemInfo(it.fuse) : null;
      return (
        meta.name.toLowerCase().includes(q) ||
        it.name.toLowerCase().includes(q) ||
        (fuseMeta && fuseMeta.name.toLowerCase().includes(q))
      );
    });

    const grid = $("inv-grid");
    grid.innerHTML = "";
    if (!list.length) {
      grid.innerHTML = `<div class="empty-hint" style="grid-column:1/-1;padding:24px">${esc(tr("inv.emptyCat"))}</div>`;
    } else {
      for (const it of list) {
        const meta = itemInfo(it.name);
        const fuseMeta = it.fuse ? itemInfo(it.fuse) : null;
        const card = document.createElement("div");
        const isSel = state.invSelected && state.invSelected.slot === it.slot && state.invSelected.name === it.name;
        card.className = "inv-card" + (it.equipped ? " equipped" : "") + (isSel ? " selected" : "");
        const topBadge = it.equipped ? "E" : it.effect && it.effect.type ? (tr("effect." + it.effect.type) || it.effect.type) : "";
        const bottomBadge = typeof it.count === "number" ? `x${it.count}` : typeof it.life === "number" ? `🛡 ${it.life}` : "";
        card.innerHTML = `
          ${topBadge ? `<span class="inv-badge-tl">${esc(topBadge)}</span>` : ""}
          ${fuseMeta ? `<span class="inv-fuse-dot" title="${esc(tr("inv.stat.fused"))}: ${esc(fuseMeta.name)}"><img src="/api/icon/item/${esc(fuseMeta.icon)}.png" alt="" onerror="this.style.display='none'"/></span>` : ""}
          <img src="/api/icon/item/${esc(meta.icon)}.png" alt="" onerror="this.style.opacity='0.25'" />
          ${bottomBadge ? `<span class="inv-badge-br">${esc(bottomBadge)}</span>` : ""}
          <div class="inv-card-name">${esc(meta.name)}</div>
        `;
        card.onclick = () => {
          state.invSelected = it;
          renderInventory();
        };
        grid.appendChild(card);
      }
    }

    renderInvDetail();
  }

  function renderInvDetail() {
    const panel = $("inv-detail");
    const it = state.invSelected;
    if (!it) {
      panel.className = "detail-panel empty";
      panel.innerHTML = `<div class="empty-hint">${esc(tr("inv.emptyHint"))}</div>`;
      return;
    }
    panel.className = "detail-panel";
    const meta = itemInfo(it.name);
    const fuseMeta = it.fuse ? itemInfo(it.fuse) : null;
    const rows = [];
    if (it.equipped) rows.push([tr("inv.stat.state"), tr("inv.stat.equipped")]);
    if (typeof it.life === "number") rows.push([tr("inv.stat.life"), it.life]);
    if (typeof it.count === "number") rows.push([tr("inv.stat.qty"), it.count]);
    if (fuseMeta) rows.push([tr("inv.stat.fused"), `${fuseMeta.name}${it.fuseLife ? ` (+${it.fuseLife})` : ""}`]);
    if (it.effect && it.effect.type) rows.push([tr("inv.stat.bonus"), `${tr("effect." + it.effect.type) || it.effect.type} (${it.effect.value})`]);
    if (typeof it.heal === "number" && it.heal > 0) rows.push([tr("wiki.stat.heal"), tr("wiki.stat.heartsUnit", { n: (it.heal / 4).toFixed(2).replace(/\.00$/, "") })]);
    if (typeof it.effect === "string") rows.push([tr("inv.stat.effect"), tr("inv.stat.effectLv", { eff: it.effect, lv: it.level || 1 })]);
    if (it.color) rows.push([tr("inv.stat.dye"), it.color]);
    if (it.materials && it.materials.length) rows.push([tr("inv.stat.ingredients"), it.materials.map((m) => itemInfo(m).name).join(", ")]);
    if (meta.sell) rows.push([tr("wiki.stat.sell"), `${meta.sell} ${tr("detail.currencyRupees")}`]);

    panel.innerHTML = `
      <div class="detail-head">
        <h3>${esc(meta.name)}</h3>
      </div>
      <div class="detail-hero">
        <img src="/api/icon/item/${esc(meta.icon)}.png" alt="" />
      </div>
      <div class="detail-desc">${esc(meta.caption || tr("inv.stat.noDesc"))}</div>
      <div class="kv-list">
        ${rows.map(([k, v]) => `<div class="kv-row"><span>${esc(k)}</span><strong>${esc(v)}</strong></div>`).join("")}
      </div>
    `;
  }

  // ---------------- Missões ----------------
  function renderQuests() {
    const catBar = $("quest-cat-pills");
    catBar.innerHTML = "";
    for (const cKey of QUEST_CATS) {
      const btn = document.createElement("button");
      btn.className = "pill" + (state.questCat === cKey ? " active" : "");
      btn.textContent = tr("quest.cat." + cKey);
      btn.onclick = () => {
        state.questCat = cKey;
        saveAllPrefs();
        renderQuests();
      };
      catBar.appendChild(btn);
    }

    const stBar = $("quest-status-pills");
    stBar.innerHTML = "";
    for (const sKey of QUEST_STATUSES) {
      const btn = document.createElement("button");
      btn.className = "pill" + (state.questStatus === sKey ? " active" : "");
      btn.textContent = tr("quest.st." + sKey);
      btn.onclick = () => {
        state.questStatus = sKey;
        saveAllPrefs();
        renderQuests();
      };
      stBar.appendChild(btn);
    }

    const quests = (state.questsData && state.questsData.quests) || [];
    const states = (state.snapshot && state.snapshot.quests) || {};
    const qStr = $("quest-search").value.trim().toLowerCase();

    const filtered = quests.filter((q) => {
      if (state.questCat !== "all" && q.category !== state.questCat) return false;
      const st = states[q.id] || { status: "locked" };
      if (state.questStatus !== "all") {
        if (state.questStatus === "locked") {
          if (st.status !== "locked" && st.status !== "queued") return false;
        } else if (st.status !== state.questStatus) {
          return false;
        }
      }
      if (qStr) {
        return (
          q.name.toLowerCase().includes(qStr) ||
          (q.giver || "").toLowerCase().includes(qStr) ||
          (q.region || "").toLowerCase().includes(qStr)
        );
      }
      return true;
    });

    const listEl = $("quest-list");
    listEl.innerHTML = "";
    if (!filtered.length) {
      listEl.innerHTML = `<div class="empty-hint" style="padding:24px">${esc(tr("quest.none"))}</div>`;
    } else {
      for (const q of filtered) {
        const st = states[q.id] || { status: "locked" };
        const row = document.createElement("div");
        row.className = "quest-row" + (state.questSelected === q.id ? " selected" : "");
        row.innerHTML = `
          <div>
            <div class="quest-title">${esc(q.name)}</div>
            <div class="quest-meta">${esc(q.region || "Hyrule")}${q.giver ? ` · ${esc(q.giver)}` : ""}</div>
          </div>
          <span class="status-tag ${esc(st.status)}">${esc(tr("quest.st." + st.status) || st.status)}</span>
        `;
        row.onclick = () => {
          state.questSelected = q.id;
          renderQuests();
        };
        listEl.appendChild(row);
      }
    }

    renderQuestDetail();
  }

  function renderQuestDetail() {
    const panel = $("quest-detail");
    const quests = (state.questsData && state.questsData.quests) || [];
    const q = quests.find((x) => x.id === state.questSelected);
    if (!q) {
      panel.className = "detail-panel empty";
      panel.innerHTML = `<div class="empty-hint">${esc(tr("quest.emptyHint"))}</div>`;
      return;
    }
    panel.className = "detail-panel";
    const st = (state.snapshot && state.snapshot.quests && state.snapshot.quests[q.id]) || { status: "locked", points: [] };
    const pts = (st.points && st.points.length ? st.points : (q.start && q.start.points) || []);
    const targetPt = pts[0];

    panel.innerHTML = `
      <div class="detail-head">
        <div>
          <div class="muted" style="font-size:11px;margin-bottom:4px">${esc(q.region || "Hyrule")}${q.giver ? ` · ${esc(q.giver)}` : ""}</div>
          <h3>${esc(q.name)}</h3>
        </div>
        <span class="status-tag ${esc(st.status)}">${esc(tr("quest.st." + st.status) || st.status)}</span>
      </div>
      ${targetPt ? `<button id="btn-quest-map" class="btn btn-gold" style="width:100%;margin-bottom:10px">${esc(tr("wiki.viewOnMap"))}</button>` : ""}
      <div class="step-list">
        ${(q.steps || [])
          .filter((s) => s.text)
          .map((s, idx) => {
            const isCur = s.name === st.stepName;
            return `<div class="step-box ${isCur ? "current" : ""}">
              <h4>${esc(isCur ? tr("quest.currentStep") : tr("quest.stepNum", { n: idx + 1 }))}</h4>
              <div class="detail-desc" style="margin:0">${esc(s.text)}</div>
            </div>`;
          })
          .join("")}
      </div>
    `;
    const mapBtn = $("btn-quest-map");
    if (mapBtn && targetPt) {
      mapBtn.onclick = () => {
        const lyr = targetPt[1] < -400 ? "depths" : targetPt[1] > 680 ? "sky" : "surface";
        $("chk-follow").checked = false;
        mapCtrl.followLink = false;
        switchTab("map");
        mapCtrl.focusPoint(targetPt[0], targetPt[2], lyr, 0.45);
        syncLayerButtons(lyr);
      };
    }
  }

  // ---------------- Arquivos ----------------
  function renderArchives() {
    document.querySelectorAll("#archive-subtabs .pill").forEach((b) => {
      b.classList.toggle("active", b.dataset.sub === state.archiveSub);
    });

    const extra = $("archive-extra-filters");
    extra.innerHTML = "";
    if (state.archiveSub === "compendium") {
      for (const k of ["all", "Animal", "Enemy", "Material", "Weapon", "Treasure"]) {
        const b = document.createElement("button");
        b.className = "pill" + (state.archiveCat === k ? " active" : "");
        b.textContent = tr("arch.cat." + k);
        b.onclick = () => {
          state.archiveCat = k;
          saveAllPrefs();
          renderArchives();
        };
        extra.appendChild(b);
      }
    }

    const cat = state.catalogData || {};
    const prog = (state.snapshot && state.snapshot.archives) || {};
    const q = $("archive-search").value.trim().toLowerCase();
    const grid = $("archive-grid");
    grid.innerHTML = "";

    if (state.archiveSub === "compendium") {
      const states = prog.compendium || {};
      const rows = (cat.compendium || []).filter((e) => {
        if (state.archiveCat !== "all" && e.category !== state.archiveCat) return false;
        const unlocked = states[e.id] && states[e.id] !== "unopened";
        if (state.archiveSpoiler && !unlocked) return false;
        if (q) return e.name.toLowerCase().includes(q) || e.category_label.toLowerCase().includes(q);
        return true;
      });
      for (const e of rows) {
        const st = states[e.id] || "unopened";
        const unlocked = st !== "unopened";
        const card = document.createElement("div");
        card.className = "arch-card" + (!unlocked ? " locked" : "") + (state.archiveSelected === `pb:${e.id}` ? " selected" : "");
        card.innerHTML = `
          ${e.has_icon ? `<img src="/api/icon/picturebook/${esc(e.id)}.png" alt="" loading="lazy" />` : `<div style="height:96px"></div>`}
          <div class="arch-title">#${e.index} ${esc(unlocked ? e.name : "???")}</div>
          <div class="arch-sub">${esc(e.category_label)}</div>
        `;
        card.onclick = () => {
          state.archiveSelected = `pb:${e.id}`;
          renderArchiveDetail({ type: "compendium", entry: e, unlocked, st });
          renderArchives();
        };
        grid.appendChild(card);
      }
    } else if (state.archiveSub === "profiles") {
      const states = prog.profiles || {};
      const rows = (cat.profiles || []).filter((e) => {
        const unlocked = Boolean(states[e.id]);
        if (state.archiveSpoiler && !unlocked) return false;
        if (q) return e.name.toLowerCase().includes(q) || (e.alias || "").toLowerCase().includes(q);
        return true;
      });
      for (const e of rows) {
        const unlocked = Boolean(states[e.id]);
        const card = document.createElement("div");
        card.className = "arch-card" + (!unlocked ? " locked" : "") + (state.archiveSelected === `cd:${e.id}` ? " selected" : "");
        card.innerHTML = `
          ${e.has_icon ? `<img src="/api/icon/chara/${esc(e.id)}.png" alt="" loading="lazy" />` : `<div style="height:96px"></div>`}
          <div class="arch-title">${esc(unlocked ? e.name : "???")}</div>
          <div class="arch-sub">${esc(unlocked ? e.alias || e.race : tr("arch.profileLocked"))}</div>
        `;
        card.onclick = () => {
          state.archiveSelected = `cd:${e.id}`;
          renderArchiveDetail({ type: "profile", entry: e, unlocked });
          renderArchives();
        };
        grid.appendChild(card);
      }
    } else if (state.archiveSub === "recipes") {
      const states = prog.recipes || {};
      const rows = (cat.recipes || []).filter((e) => {
        const unlocked = Boolean(states[e.id]);
        if (state.archiveSpoiler && !unlocked) return false;
        if (q) return e.name.toLowerCase().includes(q);
        return true;
      });
      for (const e of rows) {
        const unlocked = Boolean(states[e.id]);
        const card = document.createElement("div");
        card.className = "arch-card" + (!unlocked ? " locked" : "") + (state.archiveSelected === `rc:${e.id}` ? " selected" : "");
        card.innerHTML = `
          <img src="/api/icon/item/${esc(e.icon)}.png" alt="" loading="lazy" />
          <div class="arch-title">#${e.index} ${esc(unlocked ? e.name : tr("arch.recipeUnknown"))}</div>
        `;
        card.onclick = () => {
          state.archiveSelected = `rc:${e.id}`;
          renderArchiveDetail({ type: "recipe", entry: e, unlocked });
          renderArchives();
        };
        grid.appendChild(card);
      }
    } else if (state.archiveSub === "memories") {
      const states = prog.memories || {};
      const rows = (cat.memories || []).filter((e) => {
        const unlocked = Boolean(states[e.id]);
        if (state.archiveSpoiler && !unlocked) return false;
        if (q) return e.title.toLowerCase().includes(q);
        return true;
      });
      for (const e of rows) {
        const unlocked = Boolean(states[e.id]);
        const card = document.createElement("div");
        card.className = "arch-card" + (!unlocked ? " locked" : "") + (state.archiveSelected === `mm:${e.id}` ? " selected" : "");
        card.innerHTML = `
          <div class="arch-sub">${esc(tr("arch.memorySub", { n: e.index }))}</div>
          <div class="arch-title">${esc(unlocked ? e.title : tr("arch.memoryLockedSub"))}</div>
        `;
        card.onclick = () => {
          state.archiveSelected = `mm:${e.id}`;
          renderArchiveDetail({ type: "memory", entry: e, unlocked });
          renderArchives();
        };
        grid.appendChild(card);
      }
    } else if (state.archiveSub === "album") {
      const photos = (state.snapshot && state.snapshot.album) || [];
      for (const ph of photos) {
        if (q && !(ph.location || "").toLowerCase().includes(q) && !(ph.actor || "").toLowerCase().includes(q)) continue;
        const card = document.createElement("div");
        card.className = "arch-card album-card";
        card.innerHTML = `
          <img src="/api/album/${esc(ph.thumb || ph.filename)}" alt="" loading="lazy" />
          <div class="arch-title">${esc(tr("arch.photoTitle", { n: ph.index + 1 }))}</div>
          <div class="arch-sub">${esc(ph.location || "")}</div>
        `;
        card.onclick = () => {
          $("lightbox-img").src = `/api/album/${esc(ph.filename)}`;
          $("lightbox-caption").textContent = `${tr("arch.photoTitle", { n: ph.index + 1 })}${ph.location ? ` · ${ph.location}` : ""}`;
          $("photo-lightbox").classList.remove("hidden");
        };
        grid.appendChild(card);
      }
    }

    if (!grid.children.length) {
      grid.innerHTML = `<div class="empty-hint" style="grid-column:1/-1;padding:24px">${esc(tr("arch.none"))}</div>`;
    }
  }

  function renderArchiveDetail(sel) {
    const panel = $("archive-detail");
    if (!sel) {
      panel.className = "detail-panel empty";
      panel.innerHTML = `<div class="empty-hint">${esc(tr("arch.emptyHint"))}</div>`;
      return;
    }
    panel.className = "detail-panel";
    const e = sel.entry;
    if (sel.type === "compendium") {
      panel.innerHTML = `
        <div class="detail-head"><h3>#${e.index} ${esc(sel.unlocked ? e.name : "???")}</h3></div>
        ${e.has_icon ? `<div class="detail-hero"><img src="/api/icon/picturebook_detail/${esc(e.id)}.png" onerror="this.src='/api/icon/picturebook/${esc(e.id)}.png'" alt=""/></div>` : ""}
        <div class="detail-desc">${esc(sel.unlocked ? e.caption : tr("arch.pbLockedDesc"))}</div>
        ${sel.unlocked && e.locations && e.locations.length ? `<div class="kv-list"><div class="kv-row"><span>${esc(tr("arch.locations"))}</span><strong>${esc(e.locations.join(", "))}</strong></div></div>` : ""}
      `;
    } else if (sel.type === "profile") {
      panel.innerHTML = `
        <div class="detail-head"><div><div class="muted" style="font-size:11px">${esc(e.alias || e.race)}</div><h3>${esc(sel.unlocked ? e.name : "???")}</h3></div></div>
        ${e.has_icon ? `<div class="detail-hero"><img src="/api/icon/chara_pic/${esc(e.id)}.png" onerror="this.src='/api/icon/chara/${esc(e.id)}.png'" alt=""/></div>` : ""}
        <div class="detail-desc">${esc(sel.unlocked ? e.caption : tr("arch.profileLockedDesc"))}</div>
      `;
    } else if (sel.type === "recipe") {
      panel.innerHTML = `
        <div class="detail-head"><h3>#${e.index} ${esc(sel.unlocked ? e.name : tr("arch.recipeUnknown"))}</h3></div>
        <div class="detail-hero"><img src="/api/icon/item/${esc(e.icon)}.png" alt=""/></div>
        <div class="detail-desc">${esc(sel.unlocked ? e.caption : tr("arch.recipeLockedDesc"))}</div>
      `;
    } else if (sel.type === "memory") {
      panel.innerHTML = `
        <div class="detail-head"><h3>${esc(tr("arch.memoryTitle", { n: e.index, title: sel.unlocked ? e.title : tr("arch.memoryLocked") }))}</h3></div>
        <div class="detail-desc">${esc(sel.unlocked ? e.caption : tr("arch.memoryLockedDesc"))}</div>
      `;
    }
  }

  // ---------------- Por Perto (Radar) & Filtro Wiki ----------------
  const POI_WEIGHTS = {
    skyview_towers: 120,
    shrines: 115,
    lightroots: 115,
    great_fairies: 110,
    dragon_tears: 110,
    hinoxes: 102,
    taluses: 102,
    moldugas: 102,
    flux_constructs: 102,
    froxes: 102,
    gleeoks: 102,
    lynels: 102,
    armor_chests: 98,
    sages_wills: 98,
    old_maps: 96,
    schema_stones: 96,
    yiga_schematics: 96,
    stables: 92,
    shops: 92,
    dispensers: 92,
    chasms: 90,
    caves: 86,
    bubbuls: 86,
    wells: 84,
    hidden_koroks: 78,
    carry_koroks: 78,
    addison_signposts: 78,
    treasure_chests: 70,
    locations: 62,
  };
  const ENTITY_WEIGHTS = {
    npcs: 48,
    monsters: 58,
    animals: 34,
    plants: 24,
  };
  const NEARBY_CHIP_KEYS = ["all", "poi", "npcs", "enemies", "resources"];

  function applyWikiMapFilter(filter) {
    state.wikiFilter = filter || null;
    mapCtrl.setEntityNameFilter(filter || null);
    const banner = $("wiki-filter-banner");
    if (!banner) return;
    if (!filter) {
      banner.classList.add("hidden");
      banner.innerHTML = "";
      return;
    }
    banner.innerHTML = `<span>${esc(tr("wiki.highlightBanner"))} <strong>${esc(filter.label)}</strong></span><button id="btn-clear-wiki-filter" title="${esc(tr("wiki.clearHighlightTitle"))}">✕</button>`;
    banner.classList.remove("hidden");
    const clr = $("btn-clear-wiki-filter");
    if (clr) {
      clr.onclick = () => applyWikiMapFilter(null);
    }
  }

  function scheduleNearbyRefresh(force = false) {
    if (!state.nearbyOpen || !state.mapData) return;
    const linkRef = mapCtrl._getLinkRef();
    const ref = linkRef || { x: mapCtrl.camX, z: mapCtrl.camZ, layer: mapCtrl.layer };
    const prev = state.lastNearbyPos;
    const moved = prev ? Math.hypot(ref.x - prev.x, ref.z - prev.z) : 9999;
    const layerChanged = !prev || prev.layer !== ref.layer;
    const elapsed = Date.now() - state.lastNearbyAt;
    if (force || layerChanged || moved >= 3 || elapsed >= 1500) {
      renderNearbyPanel();
    }
  }

  function renderNearbyPanel() {
    const panel = $("map-nearby");
    if (!panel) return;
    if (!state.nearbyOpen) {
      panel.classList.add("hidden");
      return;
    }
    panel.classList.remove("hidden");

    const linkRef = mapCtrl._getLinkRef();
    const ref = linkRef
      ? { x: linkRef.x, z: linkRef.z, layer: linkRef.layer, isLink: true }
      : { x: mapCtrl.camX, z: mapCtrl.camZ, layer: mapCtrl.layer, isLink: false };
    state.lastNearbyPos = { x: ref.x, z: ref.z, layer: ref.layer };
    state.lastNearbyAt = Date.now();

    const radius = state.assistRadius || 200;
    const layerNames = ["surface", "sky", "depths"];
    const layerLabel = window.PurahMap.LAYER_LABELS[ref.layer] || ref.layer;
    const doneMap = (state.snapshot && state.snapshot.progress && state.snapshot.progress.done) || {};
    const foundMap = (state.snapshot && state.snapshot.progress && state.snapshot.progress.found) || {};
    const items = [];

    // 1) Missões ativas próximas
    const quests = (state.questsData && state.questsData.quests) || [];
    const qStates = (state.snapshot && state.snapshot.quests) || {};
    for (const q of quests) {
      const st = qStates[q.id];
      if (!st || st.status !== "active") continue;
      for (const pt of st.points || []) {
        const lyr = pt[1] < -400 ? "depths" : pt[1] > 680 ? "sky" : "surface";
        if (lyr !== ref.layer) continue;
        const d = Math.hypot(pt[0] - ref.x, pt[2] - ref.z);
        if (d <= radius) {
          items.push({
            group: "poi",
            dist: d,
            score: 140 / (d + 35),
            title: q.name,
            sub: tr("detail.activeQuest"),
            icon: "quest",
            done: false,
            onClick: () => {
              $("chk-follow").checked = false;
              mapCtrl.followLink = false;
              mapCtrl.selected = { kind: "quest", raw: q, state: st, position: { x: pt[0], y: pt[1], z: pt[2] }, layer: lyr };
              mapCtrl.focusPoint(pt[0], pt[2], lyr, 0.55);
              syncLayerButtons(lyr);
              renderMapDetail(mapCtrl.selected);
            },
          });
        }
      }
    }

    // 2) POIs do mundo (torres, santuários, lojas, estábulos, koroks, chefes, baús...)
    if (state.mapData) {
      for (const meta of mapCtrl.getCategoryMeta()) {
        const list = state.mapData[meta.key] || [];
        const dArr = doneMap[meta.key] || [];
        const fArr = foundMap[meta.key] || [];
        const w = POI_WEIGHTS[meta.key] || 65;
        const isEnemyPoi = ["hinoxes", "taluses", "moldugas", "flux_constructs", "froxes", "gleeoks", "lynels"].includes(meta.key);
        for (let i = 0; i < list.length; i++) {
          const o = list[i];
          const p = o.position;
          if (!p) continue;
          const lyr = o.layer || "surface";
          if (lyr !== ref.layer) continue;
          const isDone = Boolean(dArr[i]);
          const isFound = Boolean(fArr[i]);
          if (state.hideCompleted && isDone && !meta.noHideCompleted) continue;
          if (state.mapMode === "spoiler_free" && !isDone && !isFound && meta.key !== "shops" && meta.key !== "stables") continue;
          const d = Math.hypot(p.x - ref.x, p.z - ref.z);
          if (d > radius) continue;
          const effW = isDone ? w * 0.35 : w;
          items.push({
            group: isEnemyPoi ? "enemies" : "poi",
            dist: d,
            score: effW / (d + 35),
            title: o.display_name,
            sub: o.sub_label ? `${meta.label} · ${o.sub_label}` : meta.label,
            icon: meta.icon,
            done: isDone,
            onClick: () => selectWorldOnMap(meta, i, o, isDone, isFound, 0.6),
          });
        }
      }
    }

    // 3) Mundo Vivo (NPCs c/ missão destacada, NPCs, monstros, animais, plantas)
    if (state.entitiesData) {
      const names = state.entitiesData.names || [];
      for (const meta of mapCtrl.getEntityMeta()) {
        const arr = state.entitiesData[meta.key] || [];
        const baseW = ENTITY_WEIGHTS[meta.key] || 40;
        for (let i = 0; i < arr.length; i++) {
          const ent = arr[i];
          const lyr = layerNames[ent[3]] || "surface";
          if (lyr !== ref.layer) continue;
          const d = Math.hypot(ent[0] - ref.x, ent[1] - ref.z);
          if (d > radius) continue;
          const nm = names[ent[4]] || meta.singular;
          const availQuests = meta.key === "npcs" ? mapCtrl.getAvailableNpcQuests(i) : null;
          const hasQ = Boolean(availQuests && availQuests.length);
          const effW = hasQ ? 135 : baseW;
          const group = meta.key === "npcs" ? "npcs" : meta.key === "monsters" ? "enemies" : "resources";
          items.push({
            group,
            dist: d,
            score: effW / (d + 35),
            title: ent[5] > 1 && !hasQ ? `${nm} (×${ent[5]})` : nm,
            sub: hasQ ? tr("nearby.questSub", { name: availQuests[0].name }) : meta.singular,
            icon: hasQ ? "entity_npc_quest" : meta.icon,
            done: false,
            onClick: () => selectEntityOnMap(meta, i, ent, lyr, 0.65),
          });
        }
      }
    }

    const filtered = items
      .filter((it) => state.nearbyFilter === "all" || it.group === state.nearbyFilter)
      .sort((a, b) => b.score - a.score || a.dist - b.dist)
      .slice(0, 80);

    const prevList = panel.querySelector(".nearby-list");
    const prevScroll = prevList ? prevList.scrollTop : 0;

    panel.innerHTML = `
      <div class="detail-head" style="margin-bottom:4px">
        <div>
          <div class="muted" style="font-size:11px;margin-bottom:2px">${esc(tr("nearby.header", { r: radius, layer: layerLabel }))}</div>
          <h3>${esc(tr("nearby.title", { n: filtered.length }))}</h3>
        </div>
        <button class="icon-btn" id="btn-close-nearby" title="${esc(tr("nearby.closeTitle"))}">✕</button>
      </div>
      <div class="nearby-sub">${esc(ref.isLink ? tr("nearby.subLink") : tr("nearby.subCam"))}</div>
      <div class="nearby-chips">
        ${NEARBY_CHIP_KEYS.map((ck) => `<button class="nearby-chip${state.nearbyFilter === ck ? " active" : ""}" data-nchip="${ck}">${esc(tr("nearby.chip." + ck))}</button>`).join("")}
      </div>
      <div class="nearby-list"></div>
    `;

    const closeBtn = $("btn-close-nearby");
    if (closeBtn) {
      closeBtn.onclick = () => {
        state.nearbyOpen = false;
        state.nearbyManuallyClosed = true;
        saveAllPrefs();
        applyModeUI();
      };
    }

    panel.querySelectorAll("[data-nchip]").forEach((btn) => {
      btn.onclick = () => {
        state.nearbyFilter = btn.dataset.nchip;
        saveAllPrefs();
        renderNearbyPanel();
      };
    });

    const listEl = panel.querySelector(".nearby-list");
    if (!filtered.length) {
      listEl.innerHTML = `<div class="empty-hint" style="padding:24px 8px">${esc(tr("nearby.empty", { r: radius }))}</div>`;
    } else {
      for (const it of filtered) {
        const row = document.createElement("div");
        row.className = "nearby-row" + (it.done ? " done" : "");
        const iconHtml =
          it.icon === "quest"
            ? `<span style="width:24px;height:24px;border-radius:50%;background:#e5c365;color:#111a21;display:inline-flex;align-items:center;justify-content:center;font-weight:900;font-size:13px;flex-shrink:0">!</span>`
            : `<img src="/api/icon/map/${esc(it.icon)}.png?v=5" alt="" onerror="this.style.opacity='0.25'" />`;
        row.innerHTML = `
          ${iconHtml}
          <div class="nearby-row-main">
            <div class="nearby-row-title">${esc(it.title)}</div>
            <div class="nearby-row-sub">${esc(it.sub)}</div>
          </div>
          <span class="nearby-dist">${Math.round(it.dist)} m</span>
        `;
        row.onclick = it.onClick;
        listEl.appendChild(row);
      }
      listEl.scrollTop = prevScroll;
    }
  }

  // ---------------- Catálogo / Wiki de Itens ----------------
  function findClosestWorldMatch(catKey, x, z, layer) {
    if (!state.mapData) return null;
    const list = state.mapData[catKey] || [];
    let bestIdx = -1;
    let bestDist = Infinity;
    for (let i = 0; i < list.length; i++) {
      const p = list[i].position;
      if (!p) continue;
      const d = Math.hypot(p.x - x, p.z - z) + ((list[i].layer || "surface") === layer ? 0 : 100000);
      if (d < bestDist) {
        bestDist = d;
        bestIdx = i;
      }
    }
    if (bestIdx < 0) return null;
    const meta = mapCtrl.getCategoryMeta().find((m) => m.key === catKey);
    const doneArr = (state.snapshot && state.snapshot.progress && state.snapshot.progress.done && state.snapshot.progress.done[catKey]) || [];
    const foundArr = (state.snapshot && state.snapshot.progress && state.snapshot.progress.found && state.snapshot.progress.found[catKey]) || [];
    return { meta, index: bestIdx, obj: list[bestIdx], done: Boolean(doneArr[bestIdx]), found: Boolean(foundArr[bestIdx]) };
  }

  function focusEntityCategoryFilter(cat, namesArr, label) {
    ensureEntitiesLoaded()
      .then((entData) => {
        applyWikiMapFilter({ cat, names: new Set(namesArr), label, showAll: true });
        switchTab("map");
        const arr = entData[cat] || [];
        const names = entData.names || [];
        const targetSet = new Set(namesArr);
        const linkRef = mapCtrl._getLinkRef();
        const refX = linkRef ? linkRef.x : 0;
        const refZ = linkRef ? linkRef.z : 0;
        const layerNames = ["surface", "sky", "depths"];
        let best = null;
        let bestD = Infinity;
        for (let i = 0; i < arr.length; i++) {
          const ent = arr[i];
          if (!targetSet.has(names[ent[4]] || "")) continue;
          const d = Math.hypot(ent[0] - refX, ent[1] - refZ);
          if (d < bestD) {
            bestD = d;
            best = { x: ent[0], z: ent[1], layer: layerNames[ent[3]] || "surface" };
          }
        }
        $("chk-follow").checked = false;
        mapCtrl.followLink = false;
        if (best) {
          mapCtrl.focusPoint(best.x, best.z, best.layer, 0.28);
          syncLayerButtons(best.layer);
        }
      })
      .catch(() => {});
  }

  function renderWiki() {
    const catsBox = $("wiki-cats");
    if (!catsBox) return;
    const chkShops = $("chk-wiki-shops-only");
    if (chkShops) chkShops.checked = Boolean(state.wikiShopsOnly);
    const chkRanks = $("chk-wiki-all-ranks");
    if (chkRanks) chkRanks.checked = Boolean(state.wikiAllRanks);
    catsBox.innerHTML = "";
    for (const cKey of WIKI_CATS) {
      const btn = document.createElement("button");
      btn.className = "pill" + (state.wikiCat === cKey ? " active" : "");
      btn.textContent = tr("wiki.cat." + cKey);
      btn.onclick = () => {
        state.wikiCat = cKey;
        saveAllPrefs();
        renderWiki();
      };
      catsBox.appendChild(btn);
    }

    const itemsMap = (state.catalogData && state.catalogData.items) || {};
    const q = ($("wiki-search") ? $("wiki-search").value : "").trim().toLowerCase();
    const list = Object.values(itemsMap).filter((it) => {
      if (!it || !it.id) return false;
      if (!state.wikiAllRanks) {
        if (!it.category) return false;
        if (it.name === it.id && !it.sources) return false;
        if (it.category === "Armor" && ((it.rank || 0) > 1 || it.id.endsWith("_B"))) return false;
      }
      if (state.wikiCat !== "all") {
        if (state.wikiCat === "Bow") {
          if (it.category !== "Bow" && it.category !== "Arrow") return false;
        } else if (state.wikiCat === "KeyItem") {
          if (it.category !== "KeyItem" && it.category !== "SpecialPower" && it.category !== "Rupee") return false;
        } else if (it.category !== state.wikiCat) {
          return false;
        }
      }
      if (state.wikiShopsOnly && !(it.sources && it.sources.shops && it.sources.shops.length)) return false;
      if (q) {
        const nm = (it.name || "").toLowerCase();
        const cap = (it.caption || "").toLowerCase();
        if (!nm.includes(q) && !cap.includes(q) && !it.id.toLowerCase().includes(q)) return false;
      }
      return true;
    });

    list.sort((a, b) => (a.category || "").localeCompare(b.category || "") || (a.sort_key || 0) - (b.sort_key || 0) || (a.name || "").localeCompare(b.name || ""));

    const grid = $("wiki-grid");
    grid.innerHTML = "";
    const MAX_CARDS = 240;
    const shown = list.slice(0, MAX_CARDS);

    if (!shown.length) {
      grid.innerHTML = `<div class="empty-hint" style="grid-column:1/-1;padding:24px">${esc(tr("wiki.none"))}</div>`;
    } else {
      for (const it of shown) {
        const card = document.createElement("div");
        card.className = "wiki-card" + (state.wikiSelected === it.id ? " selected" : "");
        const srcCount =
          (it.sources && it.sources.shops ? it.sources.shops.length : 0) +
          (it.sources && it.sources.chests ? it.sources.chests.length : 0) +
          (it.sources && it.sources.dispensers ? it.sources.dispensers.length : 0) +
          (it.sources && it.sources.drops ? it.sources.drops.length : 0) +
          (it.sources && it.sources.world ? 1 : 0);
        const badgeText = it.power > 0 ? `⚡ ${it.power}` : it.heal > 0 ? `♥ ${(it.heal / 4).toFixed(1).replace(/\.0$/, "")}` : "";
        card.innerHTML = `
          ${badgeText ? `<span class="wiki-badge-power">${esc(badgeText)}</span>` : ""}
          <img src="/api/icon/item/${esc(it.icon || it.id)}.png" alt="" loading="lazy" onerror="this.style.opacity='0.25'" />
          <div class="wiki-card-name">${esc(it.name || it.id)}</div>
          <div class="wiki-card-sub">${srcCount > 0 ? esc(tr("wiki.sourcesCount", { n: srcCount })) : esc(it.category || "Item")}</div>
        `;
        card.onclick = () => {
          state.wikiSelected = it.id;
          renderWiki();
        };
        grid.appendChild(card);
      }
      if (list.length > MAX_CARDS) {
        const note = document.createElement("div");
        note.className = "empty-hint";
        note.style.cssText = "grid-column:1/-1;padding:12px;font-size:12px";
        note.textContent = tr("wiki.truncated", { shown: MAX_CARDS, total: list.length });
        grid.appendChild(note);
      }
    }

    const selEntry = state.wikiSelected ? itemsMap[state.wikiSelected] : null;
    renderWikiDetail(selEntry || null);
  }

  function renderWikiDetail(entry) {
    const panel = $("wiki-detail");
    if (!panel) return;
    if (!entry) {
      panel.className = "detail-panel empty";
      panel.innerHTML = `<div class="empty-hint">${esc(tr("wiki.emptyHint"))}</div>`;
      return;
    }
    panel.className = "detail-panel";

    const rows = [];
    if (entry.category) rows.push([tr("wiki.stat.cat"), entry.category]);
    if (entry.power > 0) rows.push([entry.category === "Armor" ? tr("wiki.stat.def") : tr("wiki.stat.pwr"), entry.power]);
    if (entry.heal > 0) rows.push([tr("wiki.stat.heal"), tr("wiki.stat.heartsUnit", { n: (entry.heal / 4).toFixed(2).replace(/\.00$/, "") })]);
    if (entry.buy > 0) rows.push([tr("wiki.stat.buy"), `${entry.buy} ${tr("detail.currencyRupees")}`]);
    if (entry.sell > 0) rows.push([tr("wiki.stat.sell"), `${entry.sell} ${tr("detail.currencyRupees")}`]);
    if (entry.rank > 1) rows.push([tr("wiki.stat.rank"), `★${entry.rank - 1}`]);

    const src = entry.sources || {};
    let sourcesHtml = "";

    if (src.shops && src.shops.length) {
      sourcesHtml += `<div class="source-section"><h4>${esc(tr("wiki.src.shops", { n: src.shops.length }))}</h4>`;
      src.shops.forEach((s, idx) => {
        sourcesHtml += `
          <div class="source-row">
            <div class="source-row-main">
              <div class="source-row-title">${esc(s.name)}${s.sub ? ` · ${esc(s.sub)}` : ""}</div>
              <div class="source-row-sub">${esc(formatShopPrice(s))}${s.bundle > 1 ? esc(tr("wiki.src.bundle", { n: s.bundle })) : ""}</div>
            </div>
            <button class="mini-map-btn" data-src-shop="${idx}">${esc(tr("wiki.viewOnMap"))}</button>
          </div>`;
      });
      sourcesHtml += `</div>`;
    }

    if (src.chests && src.chests.length) {
      const totalLbl = src.chest_total && src.chest_total > src.chests.length ? tr("wiki.src.chestsPartial", { shown: src.chests.length, total: src.chest_total }) : `${src.chests.length}`;
      sourcesHtml += `<div class="source-section"><h4>${esc(tr("wiki.src.chests", { label: totalLbl }))}</h4>`;
      src.chests.forEach((c, idx) => {
        sourcesHtml += `
          <div class="source-row">
            <div class="source-row-main">
              <div class="source-row-title">${esc(c.kind || tr("wiki.src.chestDefault"))}</div>
              <div class="source-row-sub">${esc(window.PurahMap.LAYER_LABELS[c.layer] || c.layer)} · X:${c.x}, Z:${c.z}</div>
            </div>
            <button class="mini-map-btn" data-src-chest="${idx}">${esc(tr("wiki.viewOnMap"))}</button>
          </div>`;
      });
      sourcesHtml += `</div>`;
    }

    if (src.dispensers && src.dispensers.length) {
      sourcesHtml += `<div class="source-section"><h4>${esc(tr("wiki.src.dispensers", { n: src.dispensers.length }))}</h4>`;
      src.dispensers.forEach((d, idx) => {
        sourcesHtml += `
          <div class="source-row">
            <div class="source-row-main">
              <div class="source-row-title">${esc(tr("wiki.src.dispenserName"))}</div>
              <div class="source-row-sub">${esc(window.PurahMap.LAYER_LABELS[d.layer] || d.layer)} · X:${d.x}, Z:${d.z}</div>
            </div>
            <button class="mini-map-btn" data-src-disp="${idx}">${esc(tr("wiki.viewOnMap"))}</button>
          </div>`;
      });
      sourcesHtml += `</div>`;
    }

    if (src.world && src.world.count > 0) {
      sourcesHtml += `
        <div class="source-section">
          <h4>${esc(tr("wiki.src.world"))}</h4>
          <div class="source-row">
            <div class="source-row-main">
              <div class="source-row-title">${esc(src.world.name)}</div>
              <div class="source-row-sub">${esc(tr("wiki.src.worldCount", { n: src.world.count }))}</div>
            </div>
            <button class="mini-map-btn" id="btn-wiki-world-map">${esc(tr("wiki.viewOnMap"))}</button>
          </div>
        </div>`;
    }

    if (src.drops && src.drops.length) {
      sourcesHtml += `
        <div class="source-section">
          <h4>${esc(tr("wiki.src.drops"))}</h4>
          <div class="detail-desc" style="margin-bottom:8px">${src.drops.map(esc).join(" · ")}</div>
          <button class="btn btn-gold" id="btn-wiki-drops-map" style="width:100%">${esc(tr("wiki.src.viewMonsters"))}</button>
        </div>`;
    }

    if (src.regions && src.regions.length) {
      sourcesHtml += `
        <div class="source-section">
          <h4>${esc(tr("wiki.src.regions"))}</h4>
          <div class="detail-desc" style="margin-bottom:0">${src.regions.map(esc).join(" · ")}</div>
        </div>`;
    }

    if (!sourcesHtml) {
      sourcesHtml = `<div class="source-section"><div class="muted" style="font-size:12px">${esc(tr("wiki.src.none"))}</div></div>`;
    }

    panel.innerHTML = `
      <div class="detail-head">
        <div>
          <div class="muted" style="font-size:11px;margin-bottom:2px">${esc(entry.id)}</div>
          <h3>${esc(entry.name)}</h3>
        </div>
      </div>
      <div class="detail-hero">
        <img src="/api/icon/item/${esc(entry.icon || entry.id)}.png" alt="" onerror="this.style.opacity='0.25'" />
      </div>
      <div class="detail-desc">${esc(entry.caption || tr("inv.stat.noDesc"))}</div>
      ${
        rows.length
          ? `<div class="kv-list">${rows.map(([k, v]) => `<div class="kv-row"><span>${esc(k)}</span><strong>${esc(v)}</strong></div>`).join("")}</div>`
          : ""
      }
      ${sourcesHtml}
    `;

    panel.querySelectorAll("[data-src-shop]").forEach((btn) => {
      btn.onclick = () => {
        const s = src.shops[parseInt(btn.dataset.srcShop, 10)];
        if (!s) return;
        const m = findClosestWorldMatch("shops", s.x, s.z, s.layer);
        switchTab("map");
        if (m) selectWorldOnMap(m.meta, m.index, m.obj, m.done, m.found, 0.65);
        else mapCtrl.focusPoint(s.x, s.z, s.layer, 0.65);
      };
    });

    panel.querySelectorAll("[data-src-chest]").forEach((btn) => {
      btn.onclick = () => {
        const c = src.chests[parseInt(btn.dataset.srcChest, 10)];
        if (!c) return;
        const mArmor = findClosestWorldMatch("armor_chests", c.x, c.z, c.layer);
        const mTreas = findClosestWorldMatch("treasure_chests", c.x, c.z, c.layer);
        let chosen = null;
        if (mArmor && Math.hypot(mArmor.obj.position.x - c.x, mArmor.obj.position.z - c.z) < 8) chosen = mArmor;
        else if (mTreas && Math.hypot(mTreas.obj.position.x - c.x, mTreas.obj.position.z - c.z) < 8) chosen = mTreas;
        switchTab("map");
        if (chosen) selectWorldOnMap(chosen.meta, chosen.index, chosen.obj, chosen.done, chosen.found, 0.65);
        else {
          mapCtrl.focusPoint(c.x, c.z, c.layer, 0.65);
          syncLayerButtons(c.layer);
        }
      };
    });

    panel.querySelectorAll("[data-src-disp]").forEach((btn) => {
      btn.onclick = () => {
        const d = src.dispensers[parseInt(btn.dataset.srcDisp, 10)];
        if (!d) return;
        const m = findClosestWorldMatch("dispensers", d.x, d.z, d.layer);
        switchTab("map");
        if (m) selectWorldOnMap(m.meta, m.index, m.obj, m.done, m.found, 0.65);
        else mapCtrl.focusPoint(d.x, d.z, d.layer, 0.65);
      };
    });

    const wBtn = $("btn-wiki-world-map");
    if (wBtn && src.world) {
      wBtn.onclick = () => focusEntityCategoryFilter(src.world.cat, [src.world.name], entry.name);
    }
    const dBtn = $("btn-wiki-drops-map");
    if (dBtn && src.drops && src.drops.length) {
      dBtn.onclick = () => focusEntityCategoryFilter("monsters", src.drops, `Drop: ${entry.name}`);
    }
  }

  // ---------------- Navegação & Setup ----------------
  function switchTab(tab) {
    state.activeTab = tab;
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
    document.querySelectorAll(".tab-view").forEach((v) => v.classList.toggle("active", v.id === `view-${tab}`));
    if (state.bootComplete) saveAllPrefs();
    if (tab === "map") mapCtrl._resize();
    else if (tab === "inventory") renderInventory();
    else if (tab === "quests") renderQuests();
    else if (tab === "archives") renderArchives();
    else if (tab === "wiki") renderWiki();
  }

  async function loadStaticData() {
    if (state.staticLoaded) return;
    const [mapData, questsData, catalogData, footprint, markersRes] = await Promise.all([
      apiJson("/api/static/map_data"),
      apiJson("/api/static/quests"),
      apiJson("/api/static/catalog"),
      apiJson("/api/footprint"),
      apiJson("/api/markers"),
    ]);
    state.mapData = mapData;
    state.questsData = questsData;
    state.catalogData = catalogData;
    state.footprint = footprint;
    state.userMarkers = markersRes.markers || [];
    state.staticLoaded = true;
    mapCtrl.setData({
      mapData,
      questsData,
      footprint,
      userMarkers: state.userMarkers,
    });
    renderCategoryList();
    ensureEntitiesLoaded().catch(() => {});
    if (state.nearbyOpen) renderNearbyPanel();
  }

  async function refreshSnapshot() {
    try {
      const snap = await apiJson("/api/snapshot");
      state.snapshot = snap;
      mapCtrl.setData({ snapshot: snap });
      renderHud(state.live || snap);
      if (state.staticLoaded) renderCategoryList();
      if (state.activeTab === "map" && state.nearbyOpen) scheduleNearbyRefresh();
      if (state.activeTab === "inventory") renderInventory();
      else if (state.activeTab === "quests") renderQuests();
      else if (state.activeTab === "archives") renderArchives();
    } catch (_) {}
  }

  function applyLanguageFromStatus(st) {
    if (!window.PurahI18n || !st || !st.lang) return;
    const changed = state.activeLang !== st.lang;
    state.activeLang = st.lang;
    window.PurahI18n.setLang(st.lang);
    if (changed || !state.i18nApplied) {
      state.i18nApplied = true;
      window.PurahI18n.applyDom();
      syncAllControlUI();
      renderHud(state.live || state.snapshot);
      if (state.staticLoaded) renderCategoryList();
      mapCtrl.dirty = true;
    }
  }

  async function checkSetupAndBoot() {
    const st = await apiJson("/api/status");
    state.status = st;
    applyLanguageFromStatus(st);
    const b = st.build || {};
    if (b.state === "ready") {
      $("setup-overlay").classList.add("hidden");
      if (!state.serverPrefsLoaded) {
        await loadServerPrefs();
      }
      await loadStaticData();
      await refreshSnapshot();
      switchTab(state.activeTab);
      state.bootComplete = true;
      try {
        state.footprint = await apiJson("/api/footprint");
        mapCtrl.setData({ footprint: state.footprint });
      } catch (_) {}
      if (!state.streamStarted) {
        state.streamStarted = true;
        connectStream();
      }
      if (!state.pollTimersStarted) {
        state.pollTimersStarted = true;
        setInterval(refreshSnapshot, 1800);
        setInterval(async () => {
          try {
            const st2 = await apiJson("/api/status");
            const b2 = st2.build || {};
            if ((b2.state === "building" || (st2.lang && state.activeLang && st2.lang !== state.activeLang)) && !state.reloadingLang) {
              state.reloadingLang = true;
              state.staticLoaded = false;
              state.entitiesData = null;
              state.entitiesPromise = null;
              checkSetupAndBoot().finally(() => { state.reloadingLang = false; });
              return;
            }
            applyLanguageFromStatus(st2);
            state.footprint = await apiJson("/api/footprint");
            mapCtrl.setData({ footprint: state.footprint });
          } catch (_) {}
        }, 10000);
      }
      return;
    }

    $("setup-overlay").classList.remove("hidden");
    const pct = b.total > 0 ? Math.round((b.progress / b.total) * 100) : 10;
    $("setup-bar").style.width = `${pct}%`;
    $("setup-message").textContent = b.message || tr("setup.preparing");
    if (b.state === "error") {
      $("setup-detail").textContent = b.error || tr("setup.unknownError");
      $("setup-retry").classList.remove("hidden");
    } else {
      $("setup-detail").textContent = `${pct}%`;
      $("setup-retry").classList.add("hidden");
      setTimeout(checkSetupAndBoot, 800);
    }
  }

  function connectStream() {
    const es = new EventSource("/api/stream");
    es.onmessage = (ev) => {
      try {
        const live = JSON.parse(ev.data);
        state.live = live;
        mapCtrl.setData({ live });
        renderHud(live);
        if (state.activeTab === "map" && state.nearbyOpen) scheduleNearbyRefresh();
      } catch (_) {}
    };
    es.onerror = () => {
      es.close();
      setTimeout(connectStream, 1500);
    };
  }

  // Bindings iniciais
  document.querySelectorAll(".tab-btn").forEach((b) => {
    b.addEventListener("click", () => switchTab(b.dataset.tab));
  });

  document.querySelectorAll(".layer-btn").forEach((b) => {
    b.addEventListener("click", () => {
      $("chk-autolayer").checked = false;
      mapCtrl.autoLayer = false;
      mapCtrl.setLayer(b.dataset.layer);
      syncLayerButtons(b.dataset.layer);
      saveAllPrefs();
    });
  });

  document.querySelectorAll("#map-mode-seg .mode-btn").forEach((b) => {
    b.addEventListener("click", () => {
      const mode = b.dataset.mode;
      if (!["spoiler_free", "assist", "full"].includes(mode)) return;
      state.mapMode = mode;
      state.spoilerFree = mode === "spoiler_free";
      mapCtrl.mapMode = mode;
      mapCtrl.spoilerFree = state.spoilerFree;
      if (mode === "assist" && !state.nearbyManuallyClosed) {
        state.nearbyOpen = true;
      }
      mapCtrl.dirty = true;
      applyModeUI();
      saveAllPrefs();
      renderCategoryList();
      if (state.nearbyOpen) renderNearbyPanel();
    });
  });

  $("rng-assist-radius").addEventListener("input", (e) => {
    const r = Math.max(50, Math.min(1000, parseInt(e.target.value, 10) || 200));
    state.assistRadius = r;
    mapCtrl.assistRadius = r;
    mapCtrl.dirty = true;
    $("assist-radius-val").textContent = `${r} m`;
    saveAllPrefs();
    renderCategoryList();
    if (state.nearbyOpen) renderNearbyPanel();
  });

  $("chk-fog").addEventListener("change", (e) => {
    state.fogOfWar = e.target.checked;
    mapCtrl.fogOfWar = e.target.checked;
    mapCtrl.dirty = true;
    saveAllPrefs();
  });

  $("chk-hide-done").addEventListener("change", (e) => {
    state.hideCompleted = e.target.checked;
    mapCtrl.hideCompleted = e.target.checked;
    mapCtrl.dirty = true;
    saveAllPrefs();
    renderCategoryList();
    if (state.nearbyOpen) renderNearbyPanel();
  });

  $("chk-autolayer").addEventListener("change", (e) => {
    mapCtrl.autoLayer = e.target.checked;
    saveAllPrefs();
  });
  $("chk-follow").addEventListener("change", (e) => {
    mapCtrl.followLink = e.target.checked;
    if (e.target.checked) mapCtrl.recenterOnLink();
    saveAllPrefs();
  });
  $("chk-heropath").addEventListener("change", (e) => {
    mapCtrl.showHeroPath = e.target.checked;
    mapCtrl.dirty = true;
    saveAllPrefs();
  });
  $("chk-pins").addEventListener("change", (e) => {
    mapCtrl.showPins = e.target.checked;
    mapCtrl.dirty = true;
    saveAllPrefs();
  });
  $("chk-quests-map").addEventListener("change", (e) => {
    mapCtrl.showQuests = e.target.checked;
    mapCtrl.dirty = true;
    saveAllPrefs();
  });
  $("chk-custom-map").addEventListener("change", (e) => {
    mapCtrl.showCustom = e.target.checked;
    mapCtrl.dirty = true;
    saveAllPrefs();
  });

  $("btn-cat-all").onclick = () => {
    mapCtrl.getCategoryMeta().forEach((c) => mapCtrl.enabledCats.add(c.key));
    mapCtrl.dirty = true;
    saveAllPrefs();
    renderCategoryList();
  };
  $("btn-cat-none").onclick = () => {
    mapCtrl.enabledCats.clear();
    mapCtrl.enabledEntities.clear();
    mapCtrl.dirty = true;
    saveAllPrefs();
    renderCategoryList();
  };

  $("btn-toggle-sidebar").onclick = () => {
    state.sidebarCollapsed = $("map-sidebar").classList.toggle("collapsed");
    saveAllPrefs();
    mapCtrl._resize();
  };
  $("btn-recenter").onclick = () => mapCtrl.recenterOnLink();
  $("btn-zoom-in").onclick = () => mapCtrl.zoomCenter(1.3);
  $("btn-zoom-out").onclick = () => mapCtrl.zoomCenter(1 / 1.3);
  $("btn-new-marker").onclick = () => openMarkerEditor({ x: mapCtrl.camX, z: mapCtrl.camZ, layer: mapCtrl.layer });
  $("btn-nearby").onclick = () => {
    state.nearbyOpen = !state.nearbyOpen;
    state.nearbyManuallyClosed = !state.nearbyOpen;
    saveAllPrefs();
    applyModeUI();
    if (state.nearbyOpen) {
      ensureEntitiesLoaded().catch(() => {});
      renderNearbyPanel();
    }
  };

  window.addEventListener("keydown", (e) => {
    if (e.code === "Space" && state.activeTab === "map" && !["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) {
      e.preventDefault();
      mapCtrl.recenterOnLink();
    }
  });
  window.addEventListener("pagehide", flushPrefsBeacon);
  window.addEventListener("beforeunload", flushPrefsBeacon);

  $("inv-search").addEventListener("input", renderInventory);
  $("quest-search").addEventListener("input", renderQuests);
  $("archive-search").addEventListener("input", renderArchives);
  $("wiki-search").addEventListener("input", renderWiki);
  $("chk-wiki-shops-only").addEventListener("change", (e) => {
    state.wikiShopsOnly = e.target.checked;
    saveAllPrefs();
    renderWiki();
  });
  $("chk-wiki-all-ranks").addEventListener("change", (e) => {
    state.wikiAllRanks = e.target.checked;
    saveAllPrefs();
    renderWiki();
  });
  $("chk-archive-spoiler").addEventListener("change", (e) => {
    state.archiveSpoiler = e.target.checked;
    saveAllPrefs();
    renderArchives();
  });
  document.querySelectorAll("#archive-subtabs .pill").forEach((b) => {
    b.addEventListener("click", () => {
      state.archiveSub = b.dataset.sub;
      state.archiveSelected = null;
      saveAllPrefs();
      renderArchiveDetail(null);
      renderArchives();
    });
  });

  $("btn-settings").onclick = async () => {
    const st = await apiJson("/api/status");
    const selLang = $("sel-lang");
    if (selLang) {
      const langs = st.supported_languages || [];
      selLang.innerHTML = `<option value="auto">${esc(tr("settings.langAuto"))}</option>` +
        langs.map((l) => `<option value="${esc(l.code)}">${esc(l.code)} — ${esc(l.label)}</option>`).join("");
      selLang.value = st.lang_setting || "auto";
      selLang.onchange = async () => {
        selLang.disabled = true;
        $("settings-modal").classList.add("hidden");
        try {
          await apiJson("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ lang: selLang.value }),
          });
          state.staticLoaded = false;
          state.entitiesData = null;
          state.entitiesPromise = null;
          state.i18nApplied = false;
          state.activeLang = null;
          checkSetupAndBoot();
        } finally {
          selLang.disabled = false;
        }
      };
    }
    const hint = $("settings-lang-hint");
    if (hint) {
      const srcKey = "settings.src." + (st.lang_source || "default");
      hint.textContent = tr("settings.langHint", { code: st.lang || "USen", src: tr(srcKey) });
    }
    $("settings-info").innerHTML = `
      <div class="kv-row"><span>${esc(tr("settings.gameDir"))}</span><strong>${esc(st.game_dir)}</strong></div>
      <div class="kv-row"><span>${esc(tr("settings.saveSlot"))}</span><strong>${esc(st.save_slot || tr("settings.saveNone"))}</strong></div>
      <div class="kv-row"><span>${esc(tr("settings.connMode"))}</span><strong>${esc(st.connection_mode)}</strong></div>
      ${st.lan_url ? `<div class="kv-row"><span>${esc(tr("settings.lanUrl"))}</span><strong>${esc(st.lan_url)}</strong></div>` : ""}
    `;
    $("settings-modal").classList.remove("hidden");
  };
  $("btn-close-settings").onclick = $("btn-close-settings-2").onclick = () => $("settings-modal").classList.add("hidden");
  $("btn-rebuild-cache").onclick = async () => {
    $("settings-modal").classList.add("hidden");
    state.staticLoaded = false;
    await apiJson("/api/rebuild", { method: "POST" });
    checkSetupAndBoot();
  };
  $("setup-retry").onclick = async () => {
    await apiJson("/api/rebuild", { method: "POST" });
    checkSetupAndBoot();
  };
  $("btn-close-lightbox").onclick = () => $("photo-lightbox").classList.add("hidden");

  syncAllControlUI();
  setupMapSearch();
  checkSetupAndBoot();
})();
