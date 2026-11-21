/* Renderizador de mapa em Canvas 60 FPS para o Purah Pad (3 camadas, multi-LOD, marcadores e Caminho do Herói). */
window.PurahMap = (function () {
  "use strict";

  const WORLD_X_MIN = -6000;
  const WORLD_X_MAX = 6000;
  const WORLD_Z_MIN = -5000;
  const WORLD_Z_MAX = 5000;
  const TILE_WORLD = 1000;
  const COLS = 12;
  const ROWS = 10;

  const CATEGORY_META = [
    { key: "skyview_towers", label: "Torres Panorâmicas", icon: "tower", color: "#37e0c2", defaultOn: true, noHideCompleted: true },
    { key: "shrines", label: "Santuários", icon: "shrine", color: "#3fe0c5", defaultOn: true },
    { key: "lightroots", label: "Raízes Luminosas", icon: "lightroot", color: "#ff9b42", defaultOn: true },
    { key: "shops", label: "Lojas e Serviços", icon: "shop_armor", color: "#f5c242", defaultOn: true, noDim: true, noHideCompleted: true },
    { key: "stables", label: "Estábulos", icon: "stable", color: "#e5a657", defaultOn: true, noDim: true, noHideCompleted: true },
    { key: "caves", label: "Cavernas", icon: "cave", color: "#c2a878", defaultOn: true },
    { key: "bubbuls", label: "Sapos Bubbul", icon: "bubbul", color: "#7be3f5", defaultOn: false },
    { key: "wells", label: "Poços", icon: "cave", color: "#68b5e8", defaultOn: false },
    { key: "chasms", label: "Abismos", icon: "depths", color: "#d44d6e", defaultOn: true, noHideCompleted: true },
    { key: "dispensers", label: "Dispensadores Zonai", icon: "dispenser", color: "#79e29b", defaultOn: true, noHideCompleted: true },
    { key: "locations", label: "Locais e Cidades", icon: "sky", color: "#b6c5d4", defaultOn: false, noHideCompleted: true },
    { key: "dragon_tears", label: "Lágrimas do Dragão", icon: "dragon_tear", color: "#8ae8c8", defaultOn: true },
    { key: "great_fairies", label: "Grandes Fadas", icon: "great_fairy", color: "#f59ae0", defaultOn: true, noHideCompleted: true },
    { key: "hidden_koroks", label: "Koroks Escondidos", icon: "korok", color: "#90e05a", defaultOn: false },
    { key: "carry_koroks", label: "Duplas de Koroks", icon: "carry_korok", color: "#b8ed66", defaultOn: false },
    { key: "sages_wills", label: "Vontades dos Sábios", icon: "sages_will", color: "#f0d473", defaultOn: false },
    { key: "old_maps", label: "Mapas Antigos", icon: "old_map", color: "#dcb86a", defaultOn: false },
    { key: "schema_stones", label: "Pedras Esquema", icon: "schema_stone", color: "#60d7c4", defaultOn: false },
    { key: "yiga_schematics", label: "Esquemas Yiga", icon: "yiga_schematic", color: "#e85858", defaultOn: false },
    { key: "addison_signposts", label: "Placas do Addison", icon: "stamp_Human", color: "#f2c15c", defaultOn: false },
    { key: "armor_chests", label: "Baús de Armadura", icon: "armor_chest", color: "#f5c242", defaultOn: false },
    { key: "treasure_chests", label: "Baús de Tesouro", icon: "treasure_chest", color: "#c99f49", defaultOn: false },
    { key: "hinoxes", label: "Hinoxes", icon: "hinox", color: "#ea7359", defaultOn: false },
    { key: "taluses", label: "Tálus", icon: "talus", color: "#d68d5c", defaultOn: false },
    { key: "moldugas", label: "Moldugas", icon: "molduga", color: "#d4aa62", defaultOn: false },
    { key: "flux_constructs", label: "Gólens Cúbicos", icon: "flux_construct", color: "#6ad1ab", defaultOn: false },
    { key: "froxes", label: "Froxes", icon: "frox", color: "#9e7ae0", defaultOn: false },
    { key: "gleeoks", label: "Gleeoks", icon: "gleeok", color: "#f05a5a", defaultOn: false },
    { key: "lynels", label: "Centaleões", icon: "lynel", color: "#e36c49", defaultOn: false },
  ];

  const ENTITY_META = [
    { key: "npcs", label: "NPCs", singular: "NPC", icon: "entity_npc", color: "#5ec8ff" },
    { key: "animals", label: "Animais", singular: "Animal", icon: "entity_animal", color: "#f2b950" },
    { key: "plants", label: "Plantas", singular: "Planta", icon: "entity_plant", color: "#5ee07b" },
    { key: "monsters", label: "Monstros", singular: "Monstro", icon: "entity_monster", color: "#ff5e6c" },
  ];

  const tr = (k, vars) => (window.PurahI18n ? window.PurahI18n.t(k, vars) : k);
  const LAYER_LABELS = {
    get sky() { return tr("layer.sky"); },
    get surface() { return tr("layer.surface"); },
    get depths() { return tr("layer.depths"); },
  };
  const LAYER_INDEX = { surface: 0, sky: 1, depths: 2 };

  class MapController {
    constructor(canvas, callbacks) {
      this.canvas = canvas;
      this.ctx = canvas.getContext("2d");
      this.cb = callbacks || {};

      this.layer = "surface";
      this.camX = -250;
      this.camZ = -100;
      this.zoom = 0.14; // pixels por unidade do mundo
      this.minZoom = 0.06;
      this.maxZoom = 2.6;

      this.spoilerFree = true;
      this.mapMode = "spoiler_free"; // spoiler_free | assist | full
      this.assistRadius = 200;
      this.fogOfWar = true;
      this.hideCompleted = false;
      this.autoLayer = true;
      this.followLink = true;
      this.showHeroPath = true;
      this.showPins = true;
      this.showQuests = true;
      this.showCustom = true;

      this.enabledCats = new Set(CATEGORY_META.filter((c) => c.defaultOn).map((c) => c.key));
      this.enabledEntities = new Set();
      this.entityNameFilter = null; // { cat, names: Set, label, showAll?: boolean }

      this.mapData = null;
      this.entitiesData = null;
      this.questsData = null;
      this._questMap = null;
      this._questMapSrc = null;
      this.snapshot = null;
      this.live = null;
      this.footprint = null;
      this.userMarkers = [];

      // Posição interpolada do Link
      this.linkSmooth = null;
      this.selected = null;
      this.hovered = null;
      this.hitItems = [];

      this.tileCache = new Map();
      this.iconCache = new Map();
      this.maskCache = new Map();
      this._revealCanvas = document.createElement("canvas");
      this._revealCtx = this._revealCanvas.getContext("2d");
      this._maskCanvas = document.createElement("canvas");
      this._maskCtx = this._maskCanvas.getContext("2d");
      this.dirty = true;

      this._dragging = false;
      this._moved = false;
      this._lastPt = { x: 0, y: 0 };

      this._bindEvents();
      this._startLoop();
    }

    getCategoryMeta() {
      return CATEGORY_META.map((c) => ({ ...c, label: tr("cat." + c.key) }));
    }

    getEntityMeta() {
      return ENTITY_META.map((e) => ({
        ...e,
        label: tr("ent." + e.key),
        singular: tr("ent." + e.key + ".singular"),
      }));
    }

    _bindEvents() {
      const ro = new ResizeObserver(() => this._resize());
      ro.observe(this.canvas.parentElement);
      this._resize();

      this.canvas.addEventListener("mousedown", (e) => {
        if (e.button === 0) {
          this._dragging = true;
          this._moved = false;
          this._lastPt = { x: e.clientX, y: e.clientY };
        }
      });

      window.addEventListener("mousemove", (e) => {
        const rect = this.canvas.getBoundingClientRect();
        if (this._dragging) {
          const dx = e.clientX - this._lastPt.x;
          const dy = e.clientY - this._lastPt.y;
          if (Math.abs(dx) > 3 || Math.abs(dy) > 3) {
            this._moved = true;
            if (this.followLink && this.cb.onStopFollow) {
              this.followLink = false;
              this.cb.onStopFollow();
            }
          }
          this.camX -= dx / this.zoom;
          this.camZ -= dy / this.zoom;
          this._lastPt = { x: e.clientX, y: e.clientY };
          this.dirty = true;
        }
        if (e.target === this.canvas) {
          const sx = e.clientX - rect.left;
          const sy = e.clientY - rect.top;
          const w = this.screenToWorld(sx, sy);
          if (this.cb.onCursorMove) this.cb.onCursorMove(w.x, w.z);
          this._updateHover(sx, sy);
        }
      });

      window.addEventListener("mouseup", (e) => {
        if (this._dragging && e.button === 0 && !this._moved && e.target === this.canvas) {
          const rect = this.canvas.getBoundingClientRect();
          this._handleClick(e.clientX - rect.left, e.clientY - rect.top);
        }
        this._dragging = false;
      });

      this.canvas.addEventListener(
        "wheel",
        (e) => {
          e.preventDefault();
          const rect = this.canvas.getBoundingClientRect();
          const sx = e.clientX - rect.left;
          const sy = e.clientY - rect.top;
          const factor = e.deltaY < 0 ? 1.18 : 1 / 1.18;
          this.zoomAt(sx, sy, this.zoom * factor);
        },
        { passive: false }
      );

      this.canvas.addEventListener("contextmenu", (e) => {
        e.preventDefault();
        const rect = this.canvas.getBoundingClientRect();
        const w = this.screenToWorld(e.clientX - rect.left, e.clientY - rect.top);
        if (this.cb.onContextMarker) {
          this.cb.onContextMarker(w.x, w.z, this.layer);
        }
      });

      // Suporte touch básico para celular/tablet (--lan)
      let lastTouch = null;
      this.canvas.addEventListener("touchstart", (e) => {
        if (e.touches.length === 1) {
          lastTouch = { x: e.touches[0].clientX, y: e.touches[0].clientY, moved: false };
        }
      });
      this.canvas.addEventListener(
        "touchmove",
        (e) => {
          if (e.touches.length === 1 && lastTouch) {
            e.preventDefault();
            const dx = e.touches[0].clientX - lastTouch.x;
            const dy = e.touches[0].clientY - lastTouch.y;
            if (Math.abs(dx) > 4 || Math.abs(dy) > 4) {
              lastTouch.moved = true;
              if (this.followLink && this.cb.onStopFollow) {
                this.followLink = false;
                this.cb.onStopFollow();
              }
            }
            this.camX -= dx / this.zoom;
            this.camZ -= dy / this.zoom;
            lastTouch.x = e.touches[0].clientX;
            lastTouch.y = e.touches[0].clientY;
            this.dirty = true;
          }
        },
        { passive: false }
      );
      this.canvas.addEventListener("touchend", (e) => {
        if (lastTouch && !lastTouch.moved && e.changedTouches.length) {
          const rect = this.canvas.getBoundingClientRect();
          this._handleClick(e.changedTouches[0].clientX - rect.left, e.changedTouches[0].clientY - rect.top);
        }
        lastTouch = null;
      });
    }

    _resize() {
      const parent = this.canvas.parentElement;
      if (!parent) return;
      const dpr = window.devicePixelRatio || 1;
      const w = parent.clientWidth || 800;
      const h = parent.clientHeight || 600;
      this.w = w;
      this.h = h;
      this.dpr = dpr;
      this.canvas.width = Math.round(w * dpr);
      this.canvas.height = Math.round(h * dpr);
      if (this._revealCanvas) {
        this._revealCanvas.width = this.canvas.width;
        this._revealCanvas.height = this.canvas.height;
      }
      if (this._maskCanvas) {
        this._maskCanvas.width = this.canvas.width;
        this._maskCanvas.height = this.canvas.height;
      }
      this.dirty = true;
    }

    worldToScreen(wx, wz) {
      return {
        x: this.w / 2 + (wx - this.camX) * this.zoom,
        y: this.h / 2 + (wz - this.camZ) * this.zoom,
      };
    }

    screenToWorld(sx, sy) {
      return {
        x: this.camX + (sx - this.w / 2) / this.zoom,
        z: this.camZ + (sy - this.h / 2) / this.zoom,
      };
    }

    zoomAt(sx, sy, nextZoom) {
      const z = Math.max(this.minZoom, Math.min(this.maxZoom, nextZoom));
      const before = this.screenToWorld(sx, sy);
      this.zoom = z;
      this.camX = before.x - (sx - this.w / 2) / this.zoom;
      this.camZ = before.z - (sy - this.h / 2) / this.zoom;
      this.dirty = true;
    }

    zoomCenter(factor) {
      this.zoomAt(this.w / 2, this.h / 2, this.zoom * factor);
    }

    setLayer(layer) {
      if (layer && layer !== this.layer) {
        this.layer = layer;
        this.dirty = true;
      }
    }

    focusPoint(x, z, layer, zoomLevel) {
      if (layer) this.layer = layer;
      this.camX = x;
      this.camZ = z;
      if (zoomLevel) this.zoom = zoomLevel;
      this.dirty = true;
    }

    recenterOnLink() {
      const p = (this.live && this.live.player && this.live.player.pos) ||
                (this.snapshot && this.snapshot.player && this.snapshot.player.pos);
      const lyr = (this.live && this.live.player && this.live.player.layer) ||
                  (this.snapshot && this.snapshot.player && this.snapshot.player.layer);
      if (p) {
        this.camX = p[0];
        this.camZ = p[2];
        if (lyr) this.layer = lyr;
        if (this.zoom < 0.25) this.zoom = 0.35;
        this.dirty = true;
      }
    }

    setData({ mapData, entitiesData, questsData, snapshot, live, footprint, userMarkers }) {
      if (mapData !== undefined) this.mapData = mapData;
      if (entitiesData !== undefined) this.entitiesData = entitiesData;
      if (questsData !== undefined) this.questsData = questsData;
      if (snapshot !== undefined) this.snapshot = snapshot;
      if (live !== undefined) {
        this.live = live;
        const p = live && live.player && live.player.pos;
        const lyr = live && live.player && live.player.layer;
        if (p) {
          if (this.autoLayer && lyr && lyr !== this.layer) {
            this.layer = lyr;
            if (this.cb.onLayerChange) this.cb.onLayerChange(lyr);
          }
          if (this.followLink && !this._dragging) {
            this.camX = p[0];
            this.camZ = p[2];
          }
          if (this.mapMode === "assist") {
            this.dirty = true;
          }
        }
      }
      if (footprint !== undefined) this.footprint = footprint;
      if (userMarkers !== undefined) this.userMarkers = userMarkers;
      this.dirty = true;
    }

    _getLinkRef() {
      const p = (this.live && this.live.player && this.live.player.pos) ||
                (this.snapshot && this.snapshot.player && this.snapshot.player.pos);
      if (!p) return null;
      const lyr = (this.live && this.live.player && this.live.player.layer) ||
                  (this.snapshot && this.snapshot.player && this.snapshot.player.layer) ||
                  "surface";
      const pos = this.linkSmooth && (this.live && this.live.player && this.live.player.pos)
        ? this.linkSmooth
        : { x: p[0], z: p[2] };
      return { x: pos.x, z: pos.z, layer: lyr };
    }

    isInAssistRadius(x, z, layer) {
      if (this.mapMode !== "assist") return false;
      const lp = this._getLinkRef();
      if (!lp || lp.layer !== layer) return false;
      const dx = x - lp.x;
      const dz = z - lp.z;
      return dx * dx + dz * dz <= this.assistRadius * this.assistRadius;
    }

    _getUnlockedTowerNums() {
      const nums = new Set();
      const ids = new Set();
      const towers = (this.mapData && this.mapData.skyview_towers) || [];
      const doneArr = (this.snapshot && this.snapshot.progress && this.snapshot.progress.done && this.snapshot.progress.done.skyview_towers) || [];
      for (let i = 0; i < towers.length; i++) {
        if (doneArr[i]) {
          const id = towers[i].internal_name || "";
          ids.add(id);
          const n = parseInt(id.replace("Tower", ""), 10);
          if (Number.isFinite(n)) nums.add(n);
        }
      }
      return { nums, ids };
    }

    _isBeginningIslandVisited() {
      const locs = (this.mapData && this.mapData.locations) || [];
      const doneArr = (this.snapshot && this.snapshot.progress && this.snapshot.progress.done && this.snapshot.progress.done.locations) || [];
      for (let i = 0; i < locs.length; i++) {
        if (locs[i].internal_name === "BeginningIsland") return Boolean(doneArr[i]);
      }
      return false;
    }

    setEntityNameFilter(filter) {
      this.entityNameFilter = filter;
      this.dirty = true;
    }

    getAvailableNpcQuests(npcIndex) {
      const qids = this.entitiesData && this.entitiesData.npc_quests && this.entitiesData.npc_quests[String(npcIndex)];
      if (!qids || !qids.length || !this.questsData || !this.snapshot || !this.snapshot.quests) return null;
      if (this._questMapSrc !== this.questsData) {
        this._questMap = new Map((this.questsData.quests || []).map((q) => [q.id, q]));
        this._questMapSrc = this.questsData;
      }
      const states = this.snapshot.quests;
      const out = [];
      for (const qid of qids) {
        const st = states[qid];
        const q = this._questMap.get(qid);
        if (q && q.category !== "main_quest" && st && st.status === "available") {
          out.push(q);
        }
      }
      return out.length ? out : null;
    }

    isEntityVisible(ent, layerStr, unlockedTowerNums, unlockedLightroots, beginningOpen) {
      if (this.mapMode === "full") return true;
      const x = ent[0];
      const z = ent[1];
      if (this.mapMode === "assist") {
        return this.isInAssistRadius(x, z, layerStr);
      }
      const lyrIdx = ent[3];
      const regIdx = ent[6];
      if (lyrIdx === 2) {
        return regIdx >= 0 && Boolean(unlockedLightroots[regIdx]);
      }
      if (regIdx > 0 && unlockedTowerNums.has(regIdx)) return true;
      if (lyrIdx === 1 && beginningOpen && x >= -150 && x <= 1100 && z >= 700 && z <= 2050) return true;
      return false;
    }

    _getTile(layer, lod, col, row) {
      const key = `${layer}/${lod}/${col}/${row}`;
      let entry = this.tileCache.get(key);
      if (!entry) {
        const img = new Image();
        entry = { img, state: "loading" };
        img.onload = () => {
          entry.state = "ok";
          this.dirty = true;
        };
        img.onerror = () => {
          entry.state = "err";
        };
        img.src = `/api/tile/${layer}/${lod}/${col}/${row}.png`;
        this.tileCache.set(key, entry);
      }
      return entry;
    }

    _getIcon(name) {
      let entry = this.iconCache.get(name);
      if (!entry) {
        const img = new Image();
        entry = { img, state: "loading" };
        img.onload = () => {
          entry.state = "ok";
          this.dirty = true;
        };
        img.onerror = () => {
          entry.state = "err";
        };
        img.src = `/api/icon/map/${encodeURIComponent(name)}.png?v=5`;
        this.iconCache.set(name, entry);
      }
      return entry;
    }

    _getMask(name) {
      let entry = this.maskCache.get(name);
      if (!entry) {
        const img = new Image();
        entry = { img, state: "loading" };
        img.onload = () => {
          entry.state = "ok";
          this.dirty = true;
        };
        img.onerror = () => {
          entry.state = "err";
        };
        img.src = `/api/mask/${encodeURIComponent(name)}.png`;
        this.maskCache.set(name, entry);
      }
      return entry;
    }

    _updateHover(sx, sy) {
      let best = null;
      let bestD = 18;
      for (let i = this.hitItems.length - 1; i >= 0; i--) {
        const it = this.hitItems[i];
        const d = Math.hypot(sx - it.sx, sy - it.sy);
        if (d < bestD) {
          bestD = d;
          best = it;
        }
      }
      this.canvas.style.cursor = best ? "pointer" : this._dragging ? "grabbing" : "grab";
      if (best !== this.hovered) {
        this.hovered = best;
        this.dirty = true;
      }
    }

    _handleClick(sx, sy) {
      let best = null;
      let bestD = 20;
      for (let i = this.hitItems.length - 1; i >= 0; i--) {
        const it = this.hitItems[i];
        const d = Math.hypot(sx - it.sx, sy - it.sy);
        if (d < bestD) {
          bestD = d;
          best = it;
        }
      }
      this.selected = best ? best.item : null;
      this.dirty = true;
      if (this.cb.onSelect) this.cb.onSelect(this.selected);
    }

    _startLoop() {
      const frame = () => {
        // Suaviza movimento do Link ao vivo
        const lp = this.live && this.live.player && this.live.player.pos;
        if (lp) {
          if (!this.linkSmooth) {
            this.linkSmooth = { x: lp[0], z: lp[2], heading: this.live.player.heading || 0 };
            this.dirty = true;
          } else {
            const dx = lp[0] - this.linkSmooth.x;
            const dz = lp[2] - this.linkSmooth.z;
            if (Math.abs(dx) > 0.05 || Math.abs(dz) > 0.05) {
              this.linkSmooth.x += dx * 0.35;
              this.linkSmooth.z += dz * 0.35;
              this.dirty = true;
            }
            const h = this.live.player.heading;
            if (typeof h === "number" && Math.abs(h - this.linkSmooth.heading) > 0.2) {
              this.linkSmooth.heading = h;
              this.dirty = true;
            }
          }
        }
        if (this.dirty) {
          this.dirty = false;
          this.render();
        }
        requestAnimationFrame(frame);
      };
      requestAnimationFrame(frame);
    }

    render() {
      const ctx = this.ctx;
      const w = this.w;
      const h = this.h;
      if (!w || !h) return;

      ctx.save();
      ctx.scale(this.dpr, this.dpr);

      // Fundo base por camada
      ctx.fillStyle = this.layer === "depths" ? "#08060d" : this.layer === "sky" ? "#0b141c" : "#070b0f";
      ctx.fillRect(0, 0, w, h);

      const topLeft = this.screenToWorld(0, 0);
      const botRight = this.screenToWorld(w, h);

      const minCol = Math.max(0, Math.floor((topLeft.x - WORLD_X_MIN) / TILE_WORLD));
      const maxCol = Math.min(COLS - 1, Math.floor((botRight.x - WORLD_X_MIN) / TILE_WORLD));
      const minRow = Math.max(0, Math.floor((topLeft.z - WORLD_Z_MIN) / TILE_WORLD));
      const maxRow = Math.min(ROWS - 1, Math.floor((botRight.z - WORLD_Z_MIN) / TILE_WORLD));

      const wantHighLod = this.zoom * TILE_WORLD > 360;
      ctx.imageSmoothingEnabled = true;
      ctx.imageSmoothingQuality = "high";

      this._drawMapTiles(ctx, topLeft, botRight, minCol, maxCol, minRow, maxRow, wantHighLod);

      // Anel do radar no Modo Auxílio (embaixo da trilha e dos marcadores)
      if (this.mapMode === "assist") {
        this._drawAssistRing(ctx);
      }

      // Caminho do Herói (footprint.sav + trilha da sessão atual)
      if (this.showHeroPath && this.footprint) {
        this._drawHeroPath(ctx, topLeft, botRight);
      }

      this.hitItems = [];

      // Rota do item selecionado (Korok trilha de flores / dupla)
      if (this.selected && this.selected.raw && this.selected.raw.path) {
        this._drawSelectedPath(ctx, this.selected.raw.path);
      }

      // Entidades vivas (NPCs, Animais, Plantas, Monstros) e NPCs com missão secundária disponível
      if (this.entitiesData && (this.enabledEntities.size || (this.showQuests && this.questsData && this.snapshot) || this.entityNameFilter)) {
        this._drawEntities(ctx, topLeft, botRight);
      }

      // Objetos do mapa
      if (this.mapData) {
        this._drawWorldMarkers(ctx, topLeft, botRight);
      }

      // Destinos das missões ativas
      if (this.showQuests && this.questsData && this.snapshot && this.snapshot.quests) {
        this._drawQuestMarkers(ctx, topLeft, botRight);
      }

      // Pinos e Carimbos do próprio jogo
      if (this.showPins) {
        this._drawGamePinsAndStamps(ctx);
      }

      // Marcadores personalizados do usuário
      if (this.showCustom && this.userMarkers.length) {
        this._drawUserMarkers(ctx);
      }

      // Seta do Link (sempre por cima)
      this._drawPlayer(ctx);

      ctx.restore();
    }

    _drawTileRange(targetCtx, layerName, minCol, maxCol, minRow, maxRow, wantHighLod) {
      for (let r = minRow; r <= maxRow; r++) {
        for (let c = minCol; c <= maxCol; c++) {
          const wx0 = WORLD_X_MIN + c * TILE_WORLD;
          const wz0 = WORLD_Z_MIN + r * TILE_WORLD;
          const p0 = this.worldToScreen(wx0, wz0);
          const p1 = this.worldToScreen(wx0 + TILE_WORLD, wz0 + TILE_WORLD);
          const dx = p0.x;
          const dy = p0.y;
          const dw = p1.x - p0.x + 0.6;
          const dh = p1.y - p0.y + 0.6;

          const baseTile = this._getTile(layerName, 2, c, r);
          if (baseTile.state === "ok") {
            targetCtx.drawImage(baseTile.img, dx, dy, dw, dh);
          }
          if (wantHighLod) {
            const hiTile = this._getTile(layerName, 1, c, r);
            if (hiTile.state === "ok") {
              targetCtx.drawImage(hiTile.img, dx, dy, dw, dh);
            }
          }
        }
      }
    }

    _drawDepthsGrid(ctx, tl, br) {
      ctx.save();
      const xStart = Math.max(WORLD_X_MIN, Math.floor(tl.x / 250) * 250);
      const xEnd = Math.min(WORLD_X_MAX, br.x);
      const zStart = Math.max(WORLD_Z_MIN, Math.floor(tl.z / 250) * 250);
      const zEnd = Math.min(WORLD_Z_MAX, br.z);
      const pMin = this.worldToScreen(xStart, zStart);
      const pMax = this.worldToScreen(xEnd, zEnd);

      for (let x = xStart; x <= xEnd; x += 250) {
        const sx = this.worldToScreen(x, 0).x;
        ctx.strokeStyle = x % 1000 === 0 ? "rgba(42, 74, 96, 0.38)" : "rgba(28, 48, 66, 0.22)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(sx, pMin.y);
        ctx.lineTo(sx, pMax.y);
        ctx.stroke();
      }
      for (let z = zStart; z <= zEnd; z += 250) {
        const sy = this.worldToScreen(0, z).y;
        ctx.strokeStyle = z % 1000 === 0 ? "rgba(42, 74, 96, 0.38)" : "rgba(28, 48, 66, 0.22)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(pMin.x, sy);
        ctx.lineTo(pMax.x, sy);
        ctx.stroke();
      }
      ctx.restore();
    }

    _drawMapTiles(ctx, tl, br, minCol, maxCol, minRow, maxRow, wantHighLod) {
      if (!this.fogOfWar) {
        this._drawTileRange(ctx, this.layer, minCol, maxCol, minRow, maxRow, wantHighLod);
        return;
      }

      const rctx = this._revealCtx;
      const mctx = this._maskCtx;
      if (!rctx || !mctx) return;

      if (this.layer === "depths") {
        this._drawDepthsGrid(ctx, tl, br);
        const lightroots = (this.mapData && this.mapData.lightroots) || [];
        const doneArr = (this.snapshot && this.snapshot.progress && this.snapshot.progress.done && this.snapshot.progress.done.lightroots) || [];
        let hasMask = false;

        mctx.save();
        mctx.setTransform(1, 0, 0, 1, 0, 0);
        mctx.clearRect(0, 0, this._maskCanvas.width, this._maskCanvas.height);
        mctx.scale(this.dpr, this.dpr);

        for (let i = 0; i < lightroots.length; i++) {
          if (!doneArr[i]) continue;
          const lr = lightroots[i];
          const p = lr.position;
          const rad = lr.reveal_radius || 560;
          if (p.x + rad < tl.x || p.x - rad > br.x || p.z + rad < tl.z || p.z - rad > br.z) continue;
          const s = this.worldToScreen(p.x, p.z);
          const radPx = rad * this.zoom;
          const grad = mctx.createRadialGradient(s.x, s.y, radPx * 0.8, s.x, s.y, radPx);
          grad.addColorStop(0, "rgba(255,255,255,1)");
          grad.addColorStop(1, "rgba(255,255,255,0)");
          mctx.fillStyle = grad;
          mctx.beginPath();
          mctx.arc(s.x, s.y, radPx, 0, Math.PI * 2);
          mctx.fill();
          hasMask = true;
        }
        mctx.restore();

        if (hasMask) {
          rctx.save();
          rctx.setTransform(1, 0, 0, 1, 0, 0);
          rctx.clearRect(0, 0, this._revealCanvas.width, this._revealCanvas.height);
          rctx.scale(this.dpr, this.dpr);
          rctx.imageSmoothingEnabled = true;
          rctx.imageSmoothingQuality = "high";
          this._drawTileRange(rctx, "depths", minCol, maxCol, minRow, maxRow, wantHighLod);
          rctx.setTransform(1, 0, 0, 1, 0, 0);
          rctx.globalCompositeOperation = "destination-in";
          rctx.drawImage(this._maskCanvas, 0, 0);
          rctx.globalCompositeOperation = "source-over";
          rctx.restore();

          ctx.save();
          ctx.setTransform(1, 0, 0, 1, 0, 0);
          ctx.drawImage(this._revealCanvas, 0, 0);
          ctx.restore();
        }
        return;
      }

      // Superfície e Céu: tiles de névoa oficiais + máscara por Torre Panorâmica ativa
      this._drawTileRange(ctx, `${this.layer}_fog`, minCol, maxCol, minRow, maxRow, wantHighLod);
      const { ids: unlockedIds } = this._getUnlockedTowerNums();
      const regions = (this.mapData && this.mapData.region_masks) || [];
      const beginningOpen = this.layer === "sky" && this._isBeginningIslandVisited();

      if (!unlockedIds.size && !beginningOpen) return;

      mctx.save();
      mctx.setTransform(1, 0, 0, 1, 0, 0);
      mctx.clearRect(0, 0, this._maskCanvas.width, this._maskCanvas.height);
      mctx.scale(this.dpr, this.dpr);

      let drewMask = false;
      const borderDraws = [];
      for (const rm of regions) {
        if (!unlockedIds.has(rm.id)) continue;
        if (rm.x0 + rm.w < tl.x || rm.x0 > br.x || rm.z0 + rm.h < tl.z || rm.z0 > br.z) continue;
        const p0 = this.worldToScreen(rm.x0, rm.z0);
        const p1 = this.worldToScreen(rm.x0 + rm.w, rm.z0 + rm.h);
        const mw = p1.x - p0.x;
        const mh = p1.y - p0.y;
        const mEntry = this._getMask(`region_${rm.id}`);
        if (mEntry.state === "ok") {
          mctx.drawImage(mEntry.img, p0.x, p0.y, mw, mh);
          drewMask = true;
        }
        const bEntry = this._getMask(`border_${rm.id}`);
        if (bEntry.state === "ok") {
          borderDraws.push({ img: bEntry.img, x: p0.x, y: p0.y, w: mw, h: mh });
        }
      }

      if (beginningOpen) {
        const s = this.worldToScreen(440, 1380);
        const radPx = 760 * this.zoom;
        const grad = mctx.createRadialGradient(s.x, s.y, radPx * 0.78, s.x, s.y, radPx);
        grad.addColorStop(0, "rgba(255,255,255,1)");
        grad.addColorStop(1, "rgba(255,255,255,0)");
        mctx.fillStyle = grad;
        mctx.beginPath();
        mctx.arc(s.x, s.y, radPx, 0, Math.PI * 2);
        mctx.fill();
        drewMask = true;
      }
      mctx.restore();

      if (drewMask) {
        rctx.save();
        rctx.setTransform(1, 0, 0, 1, 0, 0);
        rctx.clearRect(0, 0, this._revealCanvas.width, this._revealCanvas.height);
        rctx.scale(this.dpr, this.dpr);
        rctx.imageSmoothingEnabled = true;
        rctx.imageSmoothingQuality = "high";
        this._drawTileRange(rctx, this.layer, minCol, maxCol, minRow, maxRow, wantHighLod);
        rctx.setTransform(1, 0, 0, 1, 0, 0);
        rctx.globalCompositeOperation = "destination-in";
        rctx.drawImage(this._maskCanvas, 0, 0);
        rctx.globalCompositeOperation = "source-over";
        rctx.restore();

        ctx.save();
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        ctx.drawImage(this._revealCanvas, 0, 0);
        ctx.restore();
      }

      if (borderDraws.length) {
        ctx.save();
        ctx.globalAlpha = 0.78;
        for (const bd of borderDraws) {
          ctx.drawImage(bd.img, bd.x, bd.y, bd.w, bd.h);
        }
        ctx.restore();
      }
    }

    _drawAssistRing(ctx) {
      const lp = this._getLinkRef();
      if (!lp) return;
      const s = this.worldToScreen(lp.x, lp.z);
      const radPx = this.assistRadius * this.zoom;
      const sameLayer = lp.layer === this.layer;

      ctx.save();
      ctx.beginPath();
      ctx.arc(s.x, s.y, radPx, 0, Math.PI * 2);
      if (sameLayer) {
        ctx.fillStyle = "rgba(55, 224, 194, 0.065)";
        ctx.fill();
        ctx.strokeStyle = "rgba(55, 224, 194, 0.72)";
        ctx.lineWidth = 2;
        ctx.setLineDash([8, 6]);
        ctx.stroke();

        ctx.setLineDash([]);
        ctx.font = "700 11px Consolas, monospace";
        ctx.textAlign = "center";
        ctx.fillStyle = "#0b1116";
        const label = `Radar ${this.assistRadius} m`;
        const tw = ctx.measureText(label).width + 10;
        const ty = s.y - radPx;
        ctx.fillRect(s.x - tw / 2, ty - 16, tw, 15);
        ctx.strokeStyle = "rgba(55, 224, 194, 0.5)";
        ctx.lineWidth = 1;
        ctx.strokeRect(s.x - tw / 2, ty - 16, tw, 15);
        ctx.fillStyle = "#37e0c2";
        ctx.fillText(label, s.x, ty - 5);
      } else {
        ctx.strokeStyle = "rgba(55, 224, 194, 0.25)";
        ctx.lineWidth = 1.5;
        ctx.setLineDash([4, 6]);
        ctx.stroke();
      }
      ctx.restore();
    }

    _drawHeroPath(ctx, tl, br) {
      const lines = (this.footprint.paths && this.footprint.paths[this.layer]) || [];
      ctx.save();
      ctx.lineWidth = Math.max(2, Math.min(4, this.zoom * 14));
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      ctx.strokeStyle = "rgba(74, 240, 150, 0.72)";
      ctx.shadowColor = "rgba(55, 224, 194, 0.45)";
      ctx.shadowBlur = 6;

      for (const poly of lines) {
        if (poly.length < 2) continue;
        ctx.beginPath();
        let started = false;
        for (const pt of poly) {
          const s = this.worldToScreen(pt[0], pt[1]);
          if (!started) {
            ctx.moveTo(s.x, s.y);
            started = true;
          } else {
            ctx.lineTo(s.x, s.y);
          }
        }
        ctx.stroke();
      }

      // Trilha ao vivo desta sessão
      const sess = (this.footprint.session_trail || []).filter((p) => p.layer === this.layer);
      if (sess.length >= 2) {
        ctx.strokeStyle = "rgba(55, 224, 194, 0.92)";
        ctx.beginPath();
        sess.forEach((p, idx) => {
          const s = this.worldToScreen(p.x, p.z);
          if (idx === 0) ctx.moveTo(s.x, s.y);
          else ctx.lineTo(s.x, s.y);
        });
        ctx.stroke();
      }
      ctx.restore();

      // Mortes
      const deaths = (this.footprint.deaths || []).filter((d) => d.layer === this.layer);
      const deadIcon = this._getIcon("death");
      for (const d of deaths) {
        if (d.x < tl.x - 100 || d.x > br.x + 100 || d.z < tl.z - 100 || d.z > br.z + 100) continue;
        const s = this.worldToScreen(d.x, d.z);
        if (deadIcon.state === "ok") {
          ctx.drawImage(deadIcon.img, s.x - 10, s.y - 10, 20, 20);
        } else {
          ctx.fillStyle = "#e85858";
          ctx.beginPath();
          ctx.arc(s.x, s.y, 4, 0, Math.PI * 2);
          ctx.fill();
        }
      }
    }

    _drawSelectedPath(ctx, pathObj) {
      ctx.save();
      ctx.strokeStyle = "#f2d16b";
      ctx.lineWidth = 3;
      ctx.setLineDash([7, 5]);
      if (pathObj.trail && pathObj.trail.length >= 2) {
        ctx.beginPath();
        pathObj.trail.forEach((pt, idx) => {
          const s = this.worldToScreen(pt.x, pt.z);
          if (idx === 0) ctx.moveTo(s.x, s.y);
          else ctx.lineTo(s.x, s.y);
        });
        ctx.stroke();
      } else if (pathObj.start && pathObj.end) {
        const a = this.worldToScreen(pathObj.start.x, pathObj.start.z);
        const b = this.worldToScreen(pathObj.end.x, pathObj.end.z);
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(b.x, b.y);
        ctx.stroke();
        ctx.fillStyle = "#37e0c2";
        ctx.beginPath();
        ctx.arc(a.x, a.y, 5, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();
    }

    _drawWorldMarkers(ctx, tl, br) {
      const doneMap = (this.snapshot && this.snapshot.progress && this.snapshot.progress.done) || {};
      const foundMap = (this.snapshot && this.snapshot.progress && this.snapshot.progress.found) || {};
      const pad = 120 / this.zoom;

      for (const meta of CATEGORY_META) {
        if (!this.enabledCats.has(meta.key)) continue;
        const list = this.mapData[meta.key] || [];
        const doneArr = doneMap[meta.key] || [];
        const foundArr = foundMap[meta.key] || [];
        const defaultIcon = this._getIcon(meta.icon);

        for (let i = 0; i < list.length; i++) {
          const obj = list[i];
          const objLayer = obj.layer || "surface";
          if (objLayer !== this.layer) continue;

          const p = obj.position;
          if (!p) continue;

          const isDone = Boolean(doneArr[i]);
          const isFound = Boolean(foundArr[i]);

          if (this.hideCompleted && isDone && !meta.noHideCompleted) continue;
          if (this.mapMode === "spoiler_free" && !isDone && !isFound) continue;
          if (this.mapMode === "assist" && !isDone && !isFound && !this.isInAssistRadius(p.x, p.z, objLayer)) continue;

          if (p.x < tl.x - pad || p.x > br.x + pad || p.z < tl.z - pad || p.z > br.z + pad) continue;

          // Oculta locais menores quando muito afastado
          if (meta.key === "locations" && this.zoom < 0.22) continue;

          const s = this.worldToScreen(p.x, p.z);
          const isSel = this.selected && this.selected.kind === "world" && this.selected.cat === meta.key && this.selected.index === i;

          if (meta.key === "locations") {
            ctx.save();
            ctx.font = "600 12px 'Segoe UI', sans-serif";
            ctx.textAlign = "center";
            ctx.lineWidth = 3;
            ctx.strokeStyle = "rgba(8, 12, 16, 0.9)";
            ctx.strokeText(obj.display_name, s.x, s.y);
            ctx.fillStyle = isDone ? "#e6eef4" : "#95aab9";
            ctx.fillText(obj.display_name, s.x, s.y);
            ctx.restore();
            this.hitItems.push({
              sx: s.x,
              sy: s.y,
              item: { kind: "world", cat: meta.key, catLabel: meta.label, index: i, raw: obj, done: isDone, found: isFound },
            });
            continue;
          }

          const iconEntry = obj.icon ? this._getIcon(obj.icon) : defaultIcon;
          const sz = isSel ? 28 : this.zoom > 0.35 ? 24 : 19;
          ctx.save();
          if (isDone && !this.spoilerFree && !meta.noDim) ctx.globalAlpha = 0.48;
          if (isSel) {
            ctx.strokeStyle = "#f0c850";
            ctx.lineWidth = 2.5;
            ctx.beginPath();
            ctx.arc(s.x, s.y, sz * 0.65, 0, Math.PI * 2);
            ctx.stroke();
          }

          if (iconEntry.state === "ok") {
            ctx.drawImage(iconEntry.img, s.x - sz / 2, s.y - sz / 2, sz, sz);
          } else {
            ctx.fillStyle = meta.color;
            ctx.beginPath();
            ctx.arc(s.x, s.y, sz * 0.35, 0, Math.PI * 2);
            ctx.fill();
            ctx.strokeStyle = "#0b1116";
            ctx.lineWidth = 1.5;
            ctx.stroke();
          }

          // Indicador de santuário aberto mas ainda não concluído
          if (meta.key === "shrines" && isFound && !isDone) {
            ctx.fillStyle = "#f2a93b";
            ctx.beginPath();
            ctx.arc(s.x + sz * 0.35, s.y - sz * 0.35, 4, 0, Math.PI * 2);
            ctx.fill();
          }
          ctx.restore();

          this.hitItems.push({
            sx: s.x,
            sy: s.y,
            item: { kind: "world", cat: meta.key, catLabel: meta.label, index: i, raw: obj, done: isDone, found: isFound },
          });
        }
      }
    }

    _drawEntities(ctx, tl, br) {
      const layerIdx = LAYER_INDEX[this.layer] ?? 0;
      const names = this.entitiesData.names || [];
      const npcQuestsMap = this.entitiesData.npc_quests || {};
      const pad = 90 / this.zoom;
      const { nums: unlockedTowers } = this._getUnlockedTowerNums();
      const unlockedLightroots = (this.snapshot && this.snapshot.progress && this.snapshot.progress.done && this.snapshot.progress.done.lightroots) || [];
      const beginningOpen = this._isBeginningIslandVisited();
      const useIcons = this.zoom >= 0.16 || this.mapMode === "assist";
      const questNpcIcon = this._getIcon("entity_npc_quest");
      const nameFilter = this.entityNameFilter;

      for (const meta of ENTITY_META) {
        const hasCatOn = this.enabledEntities.has(meta.key);
        const onlyQuestNpcs = meta.key === "npcs" && !hasCatOn && this.showQuests && this.questsData && this.snapshot;
        const hasWikiFilter = nameFilter && nameFilter.cat === meta.key && nameFilter.names && nameFilter.names.size > 0;
        if (!hasCatOn && !onlyQuestNpcs && !hasWikiFilter) continue;

        const arr = this.entitiesData[meta.key] || [];
        const iconEntry = useIcons || hasWikiFilter || meta.key === "npcs" ? this._getIcon(meta.icon) : null;

        const visibleIndices = [];
        if (onlyQuestNpcs && !hasWikiFilter) {
          for (const keyIdx of Object.keys(npcQuestsMap)) {
            const i = parseInt(keyIdx, 10);
            const ent = arr[i];
            if (!ent || ent[3] !== layerIdx) continue;
            const x = ent[0];
            const z = ent[1];
            if (x < tl.x - pad || x > br.x + pad || z < tl.z - pad || z > br.z + pad) continue;
            if (!this.isEntityVisible(ent, this.layer, unlockedTowers, unlockedLightroots, beginningOpen)) continue;
            const avail = this.getAvailableNpcQuests(i);
            if (avail) visibleIndices.push(i);
          }
        } else {
          for (let i = 0; i < arr.length; i++) {
            const ent = arr[i];
            if (ent[3] !== layerIdx) continue;
            const nm = names[ent[4]] || "";
            if (hasWikiFilter && !nameFilter.names.has(nm)) continue;
            const x = ent[0];
            const z = ent[1];
            if (x < tl.x - pad || x > br.x + pad || z < tl.z - pad || z > br.z + pad) continue;
            if (!(hasWikiFilter && nameFilter.showAll) && !this.isEntityVisible(ent, this.layer, unlockedTowers, unlockedLightroots, beginningOpen)) continue;
            visibleIndices.push(i);
          }
        }

        const step = !useIcons && !onlyQuestNpcs && !hasWikiFilter && visibleIndices.length > 2200 ? Math.ceil(visibleIndices.length / 2200) : 1;
        for (let k = 0; k < visibleIndices.length; k += step) {
          const i = visibleIndices[k];
          const ent = arr[i];
          const x = ent[0];
          const z = ent[1];
          const y = ent[2];
          const name = names[ent[4]] || meta.singular;
          const count = ent[5] || 1;
          const s = this.worldToScreen(x, z);
          const availQuests = meta.key === "npcs" && this.showQuests ? this.getAvailableNpcQuests(i) : null;
          const isQuestNpc = Boolean(availQuests && availQuests.length);
          const isWikiMatch = Boolean(hasWikiFilter && nameFilter.names.has(name));
          const isSel = this.selected && this.selected.kind === "entity" && this.selected.cat === meta.key && this.selected.index === i;

          if (!useIcons && !isSel && !isQuestNpc && !isWikiMatch) {
            ctx.fillStyle = meta.color;
            ctx.beginPath();
            ctx.arc(s.x, s.y, 3, 0, Math.PI * 2);
            ctx.fill();
            continue;
          }

          const baseSz = isSel ? 24 : this.zoom > 0.35 ? 20 : 17;
          const sz = isQuestNpc || isWikiMatch ? baseSz + 4 : baseSz;
          const chosenIcon = isQuestNpc ? questNpcIcon : iconEntry;
          ctx.save();
          if (isWikiMatch) {
            ctx.fillStyle = "rgba(229, 195, 101, 0.24)";
            ctx.beginPath();
            ctx.arc(s.x, s.y, sz * 0.85, 0, Math.PI * 2);
            ctx.fill();
            ctx.strokeStyle = "#e5c365";
            ctx.lineWidth = 2;
            ctx.stroke();
          }
          if (isSel) {
            ctx.strokeStyle = "#f0c850";
            ctx.lineWidth = 2.5;
            ctx.beginPath();
            ctx.arc(s.x, s.y, sz * 0.65, 0, Math.PI * 2);
            ctx.stroke();
          }
          if (chosenIcon && chosenIcon.state === "ok") {
            ctx.drawImage(chosenIcon.img, s.x - sz / 2, s.y - sz / 2, sz, sz);
          } else {
            ctx.fillStyle = isQuestNpc ? "#ffd240" : meta.color;
            ctx.beginPath();
            ctx.arc(s.x, s.y, isQuestNpc ? 6.5 : 4.5, 0, Math.PI * 2);
            ctx.fill();
            ctx.strokeStyle = "#0b1116";
            ctx.lineWidth = 1.5;
            ctx.stroke();
          }
          if (count > 1 && this.zoom >= 0.25 && !isQuestNpc) {
            ctx.font = "700 9px Consolas, monospace";
            ctx.textAlign = "center";
            const badgeText = `x${count}`;
            ctx.fillStyle = "rgba(11, 17, 22, 0.9)";
            ctx.fillRect(s.x + 3, s.y + 1, badgeText.length * 6 + 4, 11);
            ctx.fillStyle = "#e6eef4";
            ctx.fillText(badgeText, s.x + 5 + badgeText.length * 3, s.y + 9);
          }
          ctx.restore();

          this.hitItems.push({
            sx: s.x,
            sy: s.y,
            item: {
              kind: "entity",
              cat: meta.key,
              catLabel: isQuestNpc ? tr("ent.questNpcCat") : tr("ent." + meta.key),
              singular: isQuestNpc ? tr("ent.questNpcSingular") : tr("ent." + meta.key + ".singular"),
              index: i,
              display_name: name,
              count,
              quests: availQuests,
              layer: this.layer,
              position: { x, y, z },
            },
          });
        }
      }
    }

    _drawQuestMarkers(ctx, tl, br) {
      const quests = this.questsData.quests || [];
      const states = this.snapshot.quests || {};
      for (const q of quests) {
        const st = states[q.id];
        if (!st || st.status !== "active") continue;
        const pts = st.points || [];
        for (const pt of pts) {
          const lyr = pt[1] < -400 ? "depths" : pt[1] > 680 ? "sky" : "surface";
          if (lyr !== this.layer) continue;
          const s = this.worldToScreen(pt[0], pt[2]);
          ctx.save();
          ctx.fillStyle = "#e5c365";
          ctx.strokeStyle = "#111a21";
          ctx.lineWidth = 2;
          ctx.beginPath();
          ctx.arc(s.x, s.y, 9, 0, Math.PI * 2);
          ctx.fill();
          ctx.stroke();
          ctx.fillStyle = "#111a21";
          ctx.font = "bold 11px sans-serif";
          ctx.textAlign = "center";
          ctx.textBaseline = "middle";
          ctx.fillText("!", s.x, s.y + 0.5);
          ctx.restore();

          this.hitItems.push({
            sx: s.x,
            sy: s.y,
            item: {
              kind: "quest",
              raw: q,
              state: st,
              position: { x: pt[0], y: pt[1], z: pt[2] },
              layer: lyr,
            },
          });
        }
      }
    }

    _drawGamePinsAndStamps(ctx) {
      const m = (this.live && this.live.map) || (this.snapshot && this.snapshot.map);
      if (!m) return;

      for (const p of m.pins || []) {
        if ((p.layer || "surface") !== this.layer) continue;
        const s = this.worldToScreen(p.x, p.z);
        const icon = this._getIcon(`pin_${p.type}`);
        ctx.save();
        if (icon.state === "ok") {
          ctx.shadowColor = "rgba(0, 0, 0, 0.7)";
          ctx.shadowBlur = 6;
          ctx.drawImage(icon.img, s.x - 16, s.y - 30, 32, 32);
        } else {
          ctx.fillStyle = "#37e0c2";
          ctx.beginPath();
          ctx.arc(s.x, s.y, 7, 0, Math.PI * 2);
          ctx.fill();
        }
        ctx.restore();
        this.hitItems.push({
          sx: s.x,
          sy: s.y - 10,
          item: { kind: "pin", raw: p, position: { x: p.x, y: p.y, z: p.z }, layer: p.layer },
        });
      }

      for (const st of m.stamps || []) {
        if ((st.layer || "surface") !== this.layer) continue;
        const s = this.worldToScreen(st.x, st.z);
        const icon = this._getIcon(`stamp_${st.type}`);
        if (icon.state === "ok") {
          ctx.drawImage(icon.img, s.x - 11, s.y - 11, 22, 22);
        } else {
          ctx.fillStyle = "#e5c365";
          ctx.fillRect(s.x - 5, s.y - 5, 10, 10);
        }
        this.hitItems.push({
          sx: s.x,
          sy: s.y,
          item: { kind: "stamp", raw: st, position: { x: st.x, y: 0, z: st.z }, layer: st.layer },
        });
      }
    }

    _drawUserMarkers(ctx) {
      for (const mk of this.userMarkers) {
        if ((mk.layer || "surface") !== this.layer) continue;
        const s = this.worldToScreen(mk.x, mk.z);
        ctx.save();
        ctx.fillStyle = mk.color || "#f0c850";
        ctx.strokeStyle = "#0b1116";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.arc(s.x, s.y, 9, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();

        ctx.font = "600 11px 'Segoe UI', sans-serif";
        ctx.textAlign = "center";
        ctx.lineWidth = 3;
        ctx.strokeStyle = "rgba(8, 12, 16, 0.92)";
        ctx.strokeText(mk.title, s.x, s.y - 14);
        ctx.fillStyle = "#fff";
        ctx.fillText(mk.title, s.x, s.y - 14);
        ctx.restore();

        this.hitItems.push({
          sx: s.x,
          sy: s.y,
          item: { kind: "custom", raw: mk, position: { x: mk.x, y: 0, z: mk.z }, layer: mk.layer },
        });
      }
    }

    _drawPlayer(ctx) {
      const player = (this.live && this.live.player) || (this.snapshot && this.snapshot.player);
      if (!player || !player.pos) return;
      const pos = this.linkSmooth || { x: player.pos[0], z: player.pos[2], heading: player.heading || 0 };
      const s = this.worldToScreen(pos.x, pos.z);
      const sameLayer = (player.layer || "surface") === this.layer;

      ctx.save();
      ctx.translate(s.x, s.y);
      if (!sameLayer) ctx.globalAlpha = 0.4;

      // Halo
      ctx.fillStyle = "rgba(55, 224, 194, 0.25)";
      ctx.beginPath();
      ctx.arc(0, 0, 16, 0, Math.PI * 2);
      ctx.fill();

      // Rotação: heading 0° = Norte (-Z, para cima na tela), sentido horário
      const ang = ((pos.heading || 0) * Math.PI) / 180;
      ctx.rotate(ang);

      ctx.fillStyle = "#ffd640";
      ctx.strokeStyle = "#0b1116";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(0, -12);
      ctx.lineTo(9, 10);
      ctx.lineTo(0, 5);
      ctx.lineTo(-9, 10);
      ctx.closePath();
      ctx.fill();
      ctx.stroke();

      ctx.restore();
    }
  }

  return { MapController, CATEGORY_META, ENTITY_META, LAYER_LABELS, LAYER_INDEX };
})();
