"""Leitor de save local (progress.sav, footprint.sav, album) e avaliador compartilhado de progresso."""
from __future__ import annotations

import math
import struct
from pathlib import Path
from typing import Any

from totk_formats import mmh3

HEADER_MAGIC = 0x01020304
TABLE_START = 0x28
SAVE_TYPE_HASH = 0xA3DB7114  # Fim da tabela; valor aponta para array u64 GUID terminado em 0
PLAYTIME_HASH = 0xE573F564
FOOTPRINT_COUNT_HASH = 0x08E8C243

STATUS_CLEAR = 1654019904  # mmh3("Clear")
STATUS_OPEN = 404286466    # mmh3("Open")
STATUS_ENTER = 2121473774  # mmh3("Enter")
STEP_NOT_READY = mmh3("NotReady")
STEP_READY = mmh3("Ready")
STEP_COMPLETE = mmh3("Complete")

PICTUREBOOK_UNOPENED = mmh3("Unopened")
PICTUREBOOK_PHOTO = mmh3("TakePhoto")
PICTUREBOOK_BUY = mmh3("Buy")

MAP_CATEGORY_RULES: dict[str, str] = {
    "shrines": "clear",
    "lightroots": "open",
    "shops": "nonzero",
    "stables": "nonzero",
    "hidden_koroks": "nonzero",
    "carry_koroks": "clear",
    "bubbuls": "nonzero",
    "locations": "nonzero",
    "caves": "nonzero",
    "wells": "nonzero",
    "chasms": "nonzero",
    "skyview_towers": "nonzero",
    "great_fairies": "nonzero",
    "hinoxes": "nonzero",
    "taluses": "nonzero",
    "moldugas": "nonzero",
    "flux_constructs": "nonzero",
    "froxes": "nonzero",
    "gleeoks": "nonzero",
    "lynels": "none",
    "sages_wills": "guid",
    "old_maps": "nonzero",
    "addison_signposts": "guid",
    "schema_stones": "nonzero",
    "yiga_schematics": "nonzero",
    "dragon_tears": "nonzero",
    "armor_chests": "guid",
    "treasure_chests": "guid",
    "dispensers": "nonzero",
}

# Enum hashes idênticos aos de companion_snapshot.c
EFFECTS = [
    "None", "AttackUp", "AttackUpPlus", "DurabilityUp", "DurabilityUpPlus", "FinishBlow",
    "LongThrow", "RapidFire", "ThreeWayZoom", "FiveWay", "GuardUp", "GuardUpPlus",
]
FOOD_EFFECTS = [
    "None", "ResistHot", "ResistBurn", "ResistCold", "ResistElectric", "ResitLightning", "ResistFreeze",
    "ResistAncient", "SwimSpeedUp", "DecreaseSwimStamina", "SpinAttack", "ClimbWaterfall", "ClimbSpeedUp",
    "ClimbSpeedUpOnlyHorizontaly", "AttackUp", "AttackUpCold", "AttackUpHot", "AttackUpThunderstorm",
    "AttackUpDark", "AttackUpBone", "QuietnessUp", "SandMoveUp", "SnowMoveUp", "WakeWind", "TwiceJump",
    "EmergencyAvoid", "DefenseUp", "AllSpeed", "MiasmaGuard", "MaskBokoblin", "MaskMoriblin",
    "MaskLizalfos", "MaskLynel", "YigaDisguise", "StalDisguise", "LifeRecover", "LifeMaxUp",
    "StaminaRecover", "ExStaminaMaxUp", "LifeRepair", "DivingMobilityUp", "NotSlippy", "Moisturizing",
    "LightEmission", "RupeeGuard", "FallResist", "SwordBeamUp", "VisualizeLife", "NightMoveSpeedUp",
    "NightGlow", "DecreaseWallJumpStamina", "DecreaseChargeAttackStamina", "EmitTerror", "NoBurning",
    "NoFallDamage", "NoSlip", "RupeeGuardRate", "MaskAll", "DecreaseZonauEnergy", "ZonauEnergyHealUp",
    "MaskHorablin", "MiasmaDefenseUp", "ChargePowerUpCold", "ChargePowerUpHot",
    "ChargePowerUpThunderstorm", "LightFootprint", "SoulPowerUpLightning", "SoulPowerUpWater",
    "SoulPowerUpWind", "SoulPowerUpFire", "SoulPowerUpSpirit", "EnableUseSwordBeam",
]
COLORS = [
    "None", "Blue", "Red", "Yellow", "White", "Black", "Purple", "Green", "LightBlue",
    "Navy", "Orange", "Pink", "Crimson", "LightYellow", "Brown", "Gray",
]
POWERS = [
    "None", "UltraHand", "OneTouchBond", "CeilingClipper", "ReverseRecorder",
    "AutoBuilder", "SheikahCamera", "Map", "Amiibo",
]
LAYERS = ["Ground", "Sky", "UnderGround", "Underground"]
PINS = ["Invalid", "Red", "Blue", "Yellow", "Green", "Purple", "LightBlue"]
STAMPS = ["Invalid", "Sword", "Pot", "Human", "Rhombus", "Heart", "Star", "TreasureBox", "Skull", "Leaf", "Ore"]
JOINING = ["Joining", "BreakawayNotice", "Breakaway"]

ENUM_HASH_MAPS: dict[str, dict[int, str]] = {
    name: {mmh3(v): v for v in vals}
    for name, vals in {
        "effect": EFFECTS,
        "food": FOOD_EFFECTS,
        "color": COLORS,
        "power": POWERS,
        "layer": LAYERS,
        "pin": PINS,
        "stamp": STAMPS,
        "joining": JOINING,
    }.items()
}

POUCH_CATEGORIES = [
    ("weapons", "Weapon", 20, True, True, False, True, "EquipIndex"),
    ("bows", "Bow", 14, True, False, False, True, "EquipIndex"),
    ("shields", "Shield", 20, True, True, False, True, "EquipIndex"),
    ("arrows", "Arrow", 1, False, False, True, False, "EquipIndex"),
    ("armor", "Armor", 150, False, False, False, False, None),
    ("materials", "Material", 255, False, False, True, False, None),
    ("food", "Food", 60, False, False, True, False, None),
    ("zonai", "SpecialParts", 30, False, False, True, False, None),
    ("keyItems", "KeyItem", 100, False, False, True, False, None),
]

SAGES_LIST = ["Wind", "Fire", "Water", "Electric", "Soul"]


def normalize_layer_name(raw_layer: str | None, y: float | None = None) -> str:
    """Converte camada pelo valor de altitude Y (autoritativo) ou enum MapData.CurrentLayer."""
    if y is not None and math.isfinite(y):
        if y < -220.0:
            return "depths"
        if y > 680.0:
            return "sky"
        return "surface"
    if raw_layer == "Sky":
        return "sky"
    if raw_layer in ("UnderGround", "Underground"):
        return "depths"
    return "surface"


def _and(a: bool | None, b: bool | None) -> bool | None:
    if a is False or b is False:
        return False
    if a is None or b is None:
        return None
    return True


def _or(a: bool | None, b: bool | None) -> bool | None:
    if a is True or b is True:
        return True
    if a is None or b is None:
        return None
    return False


def evaluate_boolexp(
    h: int,
    bool_table: dict[int, int],
    enum_table: dict[int, int],
    logic: dict[str, Any],
    cache: dict[str, bool | None],
) -> bool | None:
    """Executa expressão pós-fixa BoolExp contra tabelas ao vivo ou do save."""
    key = str(h)
    if key in cache:
        return cache[key]
    prog = logic.get("exprs", {}).get(key)
    if prog is None:
        return None
    cache[key] = None
    stack: list[bool | None] = []
    pending: tuple[int, int] | None = None
    for ins in prog:
        op = ins[0]
        arg = ins[1] if len(ins) > 1 else None
        if op == 0 and arg is not None:
            if arg in bool_table:
                stack.append(bool(bool_table[arg]))
            else:
                d = logic.get("bools", {}).get(str(arg))
                stack.append(None if d is None else bool(d))
        elif op == 10 and arg is not None:
            stack.append(evaluate_boolexp(arg, bool_table, enum_table, logic, cache))
        elif op in (1, 12) and arg is not None:
            pending = (op, arg)
        elif op == 2 and pending is not None and arg is not None:
            kind, enum_hash = pending
            pending = None
            info = logic.get("enums", {}).get(str(enum_hash))
            cur = enum_table.get(enum_hash)
            if cur is None and info is not None:
                default_val = info.get("default")
                cur = mmh3(default_val) if isinstance(default_val, str) else default_val
            if cur is None:
                stack.append(None)
            elif kind == 1:
                stack.append(cur == arg)
            elif info:
                order = info.get("order") or []
                order_hashes = [mmh3(v) if isinstance(v, str) else v for v in order]
                if cur in order_hashes and arg in order_hashes:
                    stack.append(order_hashes.index(cur) > order_hashes.index(arg))
                else:
                    stack.append(None)
            else:
                stack.append(None)
        elif op == 3 and len(stack) >= 2:
            b = stack.pop()
            a = stack.pop()
            stack.append(_and(a, b))
        elif op == 4 and len(stack) >= 2:
            b = stack.pop()
            a = stack.pop()
            stack.append(_or(a, b))
        elif op == 5 and stack:
            a = stack.pop()
            stack.append(None if a is None else not a)
        else:
            stack.append(None)
    res = stack[-1] if stack else None
    cache[key] = res
    return res


def evaluate_world_progress(
    map_data: dict[str, Any],
    all_flags: dict[int, int],
    guids: set[str],
) -> tuple[dict[str, list[bool]], dict[str, list[bool]]]:
    """Calcula flags `done` e `found` para todas as categorias de map_data."""
    done: dict[str, list[bool]] = {}
    for cat, rule in MAP_CATEGORY_RULES.items():
        items = map_data.get(cat) or []
        flags: list[bool] = []
        if rule == "none":
            flags = [False] * len(items)
        elif rule == "guid":
            for o in items:
                flags.append(o.get("guid") in guids)
        elif rule == "clear":
            for o in items:
                flags.append(all_flags.get(o.get("completion_hash", 0)) == STATUS_CLEAR)
        elif rule == "open":
            for o in items:
                flags.append(all_flags.get(o.get("completion_hash", 0)) == STATUS_OPEN)
        else:
            for o in items:
                flags.append(bool(all_flags.get(o.get("completion_hash", 0), 0)))
        done[cat] = flags

    found = {
        "shrines": [
            all_flags.get(o.get("completion_hash", 0)) in (STATUS_OPEN, STATUS_ENTER)
            for o in (map_data.get("shrines") or [])
        ]
    }
    return done, found


def evaluate_quests_progress(
    quests_data: dict[str, Any],
    bool_table: dict[int, int],
    enum_table: dict[int, int],
) -> dict[str, dict[str, Any]]:
    """Retorna {quest_id: {status, stepName, stepIndex, stepText, points}}."""
    quests = quests_data.get("quests") or []
    logic = quests_data.get("logic") or {}
    cache: dict[str, bool | None] = {}
    out: dict[str, dict[str, Any]] = {}
    done_ids: set[str] = set()

    # Primeira passada para saber quais missões já foram concluídas (para séries)
    raw_steps: dict[str, int] = {}
    for q in quests:
        step_val = enum_table.get(q["flag"], STEP_NOT_READY)
        raw_steps[q["id"]] = step_val
        if step_val == STEP_COMPLETE:
            done_ids.add(q["id"])

    for q in quests:
        qid = q["id"]
        step_val = raw_steps[qid]
        steps = q.get("steps") or []
        step_idx = -1
        step_name = ""
        step_text = ""
        points: list[list[float]] = []

        for idx, s in enumerate(steps):
            if s["hash"] == step_val:
                step_idx = idx
                step_name = s["name"]
                step_text = s.get("text") or ""
                points = s.get("points") or []
                break

        if step_val == STEP_COMPLETE:
            status = "complete"
        elif step_val not in (STEP_NOT_READY, STEP_READY):
            status = "active"
        else:
            # Avalia pré-requisito
            req = q.get("requires")
            unlocked = True
            if req:
                if req["kind"] == "bool":
                    unlocked = bool(bool_table.get(req["hash"], logic.get("bools", {}).get(str(req["hash"]), 0)))
                elif req["kind"] == "exp":
                    res = evaluate_boolexp(req["hash"], bool_table, enum_table, logic, cache)
                    if res is False:
                        unlocked = False
            after = q.get("after")
            if unlocked and after and after not in done_ids:
                status = "queued"
            elif unlocked:
                status = "available"
            else:
                status = "locked"
            if not points:
                points = (q.get("start") or {}).get("points") or []

        out[qid] = {
            "status": status,
            "stepName": step_name,
            "stepIndex": step_idx,
            "stepText": step_text,
            "points": points,
        }
    return out


def evaluate_archives_progress(
    catalog: dict[str, Any],
    bool_table: dict[int, int],
    enum_table: dict[int, int],
) -> dict[str, Any]:
    """Avalia estado da Enciclopédia, Perfis, Receitas e Memórias."""
    compendium: dict[str, str] = {}
    for entry in catalog.get("compendium") or []:
        val = enum_table.get(entry["state_hash"], PICTUREBOOK_UNOPENED)
        if val == PICTUREBOOK_PHOTO:
            compendium[entry["id"]] = "photo"
        elif val == PICTUREBOOK_BUY:
            compendium[entry["id"]] = "buy"
        else:
            compendium[entry["id"]] = "unopened"

    profiles: dict[str, bool] = {}
    for entry in catalog.get("profiles") or []:
        tips_ok = bool(bool_table.get(entry["tips_hash"], 0))
        use_ok = bool(bool_table.get(entry["use_hash"], 0)) if entry.get("use_hash") else False
        talk_ok = bool(bool_table.get(entry["have_talked_hash"], 0))
        profiles[entry["id"]] = tips_ok or use_ok or talk_ok

    recipes: dict[str, bool] = {}
    for entry in catalog.get("recipes") or []:
        recipes[entry["id"]] = bool(bool_table.get(entry["flag_hash"], 0))

    memories: dict[str, bool] = {}
    for entry in catalog.get("memories") or []:
        got = bool(bool_table.get(entry["flag_hash"], 0))
        cond = bool(bool_table.get(entry["cond_hash"], 0)) if entry.get("cond_hash") else False
        memories[entry["id"]] = got or cond

    return {
        "compendium": compendium,
        "profiles": profiles,
        "recipes": recipes,
        "memories": memories,
    }


class SaveProgressReader:
    """Lê progress.sav e extrai snapshot completo compatível com o leitor de memória ao vivo."""

    def __init__(self, save_path: Path) -> None:
        self.path = Path(save_path)
        self.buf = self.path.read_bytes()
        if len(self.buf) < TABLE_START or struct.unpack_from("<I", self.buf, 0)[0] != HEADER_MAGIC:
            raise ValueError(f"Save inválido: {self.path}")
        self.table: dict[int, int] = {}
        self.guids: set[str] = set()
        pos = TABLE_START
        n = len(self.buf)
        while pos + 8 <= n:
            h, v = struct.unpack_from("<II", self.buf, pos)
            pos += 8
            if h == SAVE_TYPE_HASH:
                self._read_guids(v)
                break
            self.table[h] = v

    def _read_guids(self, off: int) -> None:
        n = len(self.buf)
        while off + 8 <= n:
            g = struct.unpack_from("<Q", self.buf, off)[0]
            if g == 0:
                break
            self.guids.add(str(g))
            off += 8

    def get_int(self, name: str, default: int | None = None) -> int | None:
        raw = self.table.get(mmh3(name))
        if raw is None:
            return default
        return struct.unpack("<i", struct.pack("<I", raw))[0]

    def get_float(self, name: str, default: float | None = None) -> float | None:
        raw = self.table.get(mmh3(name))
        if raw is None:
            return default
        val = struct.unpack("<f", struct.pack("<I", raw))[0]
        return val if math.isfinite(val) else default

    def get_bool(self, name: str) -> bool:
        return bool(self.table.get(mmh3(name), 0))

    def get_enum(self, name: str, kind: str) -> str | None:
        raw = self.table.get(mmh3(name))
        if raw is None:
            return None
        return ENUM_HASH_MAPS[kind].get(raw)

    def get_vec3(self, name: str) -> list[float] | None:
        off = self.table.get(mmh3(name))
        if not off or off + 12 > len(self.buf):
            return None
        v = list(struct.unpack_from("<3f", self.buf, off))
        if not all(math.isfinite(x) for x in v):
            return None
        return v

    def get_int_array(self, name: str) -> list[int]:
        off = self.table.get(mmh3(name))
        if not off or off + 4 > len(self.buf):
            return []
        cnt = struct.unpack_from("<I", self.buf, off)[0]
        if cnt > 4096 or off + 4 + 4 * cnt > len(self.buf):
            return []
        return list(struct.unpack_from(f"<{cnt}i", self.buf, off + 4))

    def get_uint_array(self, name: str) -> list[int]:
        off = self.table.get(mmh3(name))
        if not off or off + 4 > len(self.buf):
            return []
        cnt = struct.unpack_from("<I", self.buf, off)[0]
        if cnt > 4096 or off + 4 + 4 * cnt > len(self.buf):
            return []
        return list(struct.unpack_from(f"<{cnt}I", self.buf, off + 4))

    def get_vec2_array(self, name: str) -> list[tuple[float, float]]:
        off = self.table.get(mmh3(name))
        if not off or off + 4 > len(self.buf):
            return []
        cnt = struct.unpack_from("<I", self.buf, off)[0]
        if cnt > 4096 or off + 4 + 8 * cnt > len(self.buf):
            return []
        vals = struct.unpack_from(f"<{cnt * 2}f", self.buf, off + 4)
        return [(vals[i * 2], vals[i * 2 + 1]) for i in range(cnt)]

    def get_vec3_array(self, name: str) -> list[tuple[float, float, float]]:
        off = self.table.get(mmh3(name))
        if not off or off + 4 > len(self.buf):
            return []
        cnt = struct.unpack_from("<I", self.buf, off)[0]
        if cnt > 4096 or off + 4 + 12 * cnt > len(self.buf):
            return []
        vals = struct.unpack_from(f"<{cnt * 3}f", self.buf, off + 4)
        return [(vals[i * 3], vals[i * 3 + 1], vals[i * 3 + 2]) for i in range(cnt)]

    def get_str64_array(self, name: str) -> list[str]:
        off = self.table.get(mmh3(name))
        if not off or off + 4 > len(self.buf):
            return []
        cnt = struct.unpack_from("<I", self.buf, off)[0]
        if cnt > 4096 or off + 4 + 64 * cnt > len(self.buf):
            return []
        out: list[str] = []
        base = off + 4
        for i in range(cnt):
            chunk = self.buf[base + i * 64 : base + (i + 1) * 64]
            nul = chunk.find(b"\0")
            raw = chunk[:nul] if nul >= 0 else chunk
            s = raw.decode("ascii", "ignore")
            out.append(s)
        return out

    def build_live_pose(self) -> dict[str, Any]:
        pos = self.get_vec3("PlayerStatus.SavePos")
        raw_layer = self.get_enum("MapData.CurrentLayer", "layer")
        y = pos[1] if pos else None
        layer = normalize_layer_name(raw_layer, y)

        buff_id = self.get_int("PlayerStatus.CookBuff", 0) or 0
        cook_buff = None
        if buff_id > 0:
            cook_buff = {
                "id": buff_id,
                "level": self.get_int("PlayerStatus.CookBuffLv", 0) or 0,
                "time": self.get_float("PlayerStatus.CookBuffTime", 0.0) or 0.0,
            }

        player = {
            "life": self.get_int("PlayerStatus.Life", 12),
            "maxLife": self.get_int("PlayerStatus.MaxLife", 12),
            "extraLife": self.get_int("PlayerStatus.ExtraLife", 0),
            "breakLife": self.get_int("PlayerStatus.BreakLife", 0),
            "temporaryLife": self.get_int("PlayerStatus.TemporaryLife", 0),
            "rupees": self.get_int("PlayerStatus.CurrentRupee", 0),
            "poes": self.get_int("PlayerStatus.CurrentMamo", 0),
            "maxStamina": self.get_float("PlayerStatus.MaxStamina", 1000.0),
            "extraStamina": self.get_float("PlayerStatus.ExtraStamina", 0.0),
            "maxEnergy": self.get_float("PlayerStatus.MaxEnergy", 100.0),
            "extraEnergy": self.get_float("PlayerStatus.ExtraEnergy", 0.0),
            "ability": self.get_enum("PlayerStatus.CurrentSpecialPower", "power") or "None",
            "cookBuff": cook_buff,
            "pos": [round(x, 2) for x in pos] if pos else None,
            "heading": None,
            "layer": layer,
        }

        pins = []
        pin_pos = self.get_vec3_array("MapData.IconData.MapPinData.Pos")
        pin_type = self.get_uint_array("MapData.IconData.MapPinData.Type")
        for idx, ((px, py, pz), pt) in enumerate(zip(pin_pos, pin_type)):
            ty = ENUM_HASH_MAPS["pin"].get(pt)
            if ty and ty != "Invalid" and all(math.isfinite(v) for v in (px, py, pz)):
                pins.append({"slot": idx, "x": round(px, 2), "y": round(py, 2), "z": round(pz, 2), "type": ty, "layer": normalize_layer_name(None, py)})

        stamps = []
        st_pos = self.get_vec2_array("MapData.IconData.StampData.Pos")
        st_type = self.get_uint_array("MapData.IconData.StampData.Type")
        st_layer = self.get_uint_array("MapData.IconData.StampData.Layer")
        for idx, ((sx, sz), st, sl) in enumerate(zip(st_pos, st_type, st_layer)):
            ty = ENUM_HASH_MAPS["stamp"].get(st)
            ly = ENUM_HASH_MAPS["layer"].get(sl)
            if ty and ty != "Invalid" and math.isfinite(sx) and math.isfinite(sz):
                stamps.append({"slot": idx, "x": round(sx, 2), "z": round(sz, 2), "type": ty, "layer": normalize_layer_name(ly)})

        return {
            "mode": "save",
            "status": "ready",
            "player": player,
            "map": {"pins": pins, "stamps": stamps},
            "pauseMenu": False,
            "playtime": self.table.get(PLAYTIME_HASH, 0),
        }

    def build_full_snapshot(
        self,
        map_data: dict[str, Any] | None,
        quests_data: dict[str, Any] | None,
        catalog_data: dict[str, Any] | None,
        album_dir: Path | None,
    ) -> dict[str, Any]:
        live = self.build_live_pose()

        # Inventário (partição 0 no save)
        part = 0
        armor_head = (self.get_int_array("Pouch.Armor.EquipIndexes.Head") + [-1, -1])[part]
        armor_upper = (self.get_int_array("Pouch.Armor.EquipIndexes.Upper") + [-1, -1])[part]
        armor_bottom = (self.get_int_array("Pouch.Armor.EquipIndexes.Bottom") + [-1, -1])[part]

        pouch: dict[str, list[dict[str, Any]]] = {}
        for key, cat, slots, has_life, has_fuse, has_stock, has_effect, equip_field in POUCH_CATEGORIES:
            names = self.get_str64_array(f"Pouch.{cat}.Content.Name")
            if len(names) < slots:
                pouch[key] = []
                continue
            off = part * slots
            life_arr = self.get_int_array(f"Pouch.{cat}.Content.Life") if has_life else []
            stock_arr = self.get_int_array(f"Pouch.{cat}.Content.StockNum") if has_stock else []
            et_arr = self.get_uint_array(f"Pouch.{cat}.Content.Effect.Type") if has_effect else []
            ev_arr = self.get_int_array(f"Pouch.{cat}.Content.Effect.Value") if has_effect else []
            fuse_arr = self.get_str64_array(f"Pouch.{cat}.Content.Combined.Name") if has_fuse else []
            fl_arr = self.get_int_array(f"Pouch.{cat}.Content.Combined.Life") if has_fuse else []
            col_arr = self.get_uint_array(f"Pouch.Armor.Content.ColorVariation") if key == "armor" else []

            is_food = key == "food"
            heal_arr = self.get_int_array("Pouch.Food.Content.LifeRecover") if is_food else []
            fe_arr = self.get_uint_array("Pouch.Food.Content.Effect.Type") if is_food else []
            flv_arr = self.get_int_array("Pouch.Food.Content.Effect.Level") if is_food else []
            ft_arr = self.get_int_array("Pouch.Food.Content.Effect.Time") if is_food else []
            pr_arr = self.get_int_array("Pouch.Food.Content.Price") if is_food else []
            fm_arr = self.get_str64_array("Pouch.Food.Content.MaterialName") if is_food else []

            equipped_idx = -1
            if equip_field:
                eq_list = self.get_int_array(f"Pouch.{cat}.{equip_field}")
                if part < len(eq_list):
                    equipped_idx = eq_list[part]

            items_out: list[dict[str, Any]] = []
            for s in range(slots):
                idx = off + s
                nm = names[idx] if idx < len(names) else ""
                if not nm:
                    continue
                entry: dict[str, Any] = {"name": nm, "slot": s}
                if idx < len(life_arr):
                    entry["life"] = life_arr[idx]
                if idx < len(stock_arr):
                    entry["count"] = stock_arr[idx]
                if idx < len(et_arr):
                    ef = ENUM_HASH_MAPS["effect"].get(et_arr[idx])
                    if ef and ef != "None":
                        entry["effect"] = {"type": ef, "value": ev_arr[idx] if idx < len(ev_arr) else 0}
                if idx < len(fuse_arr) and fuse_arr[idx]:
                    entry["fuse"] = fuse_arr[idx]
                    if idx < len(fl_arr):
                        entry["fuseLife"] = fl_arr[idx]
                if idx < len(col_arr):
                    cv = ENUM_HASH_MAPS["color"].get(col_arr[idx])
                    if cv and cv != "None":
                        entry["color"] = cv
                if is_food:
                    if idx < len(heal_arr):
                        entry["heal"] = heal_arr[idx]
                    if idx < len(fe_arr):
                        fe_name = ENUM_HASH_MAPS["food"].get(fe_arr[idx])
                        if fe_name and fe_name != "None":
                            entry["effect"] = fe_name
                            if idx < len(flv_arr):
                                entry["level"] = flv_arr[idx]
                            if idx < len(ft_arr):
                                entry["time"] = ft_arr[idx]
                    if idx < len(pr_arr):
                        entry["price"] = pr_arr[idx]
                    if fm_arr:
                        mats = [fm_arr[idx * 5 + m] for m in range(5) if idx * 5 + m < len(fm_arr) and fm_arr[idx * 5 + m]]
                        if mats:
                            entry["materials"] = mats
                if equip_field:
                    entry["equipped"] = s == equipped_idx
                elif key == "armor":
                    entry["equipped"] = s in (armor_head, armor_upper, armor_bottom)
                else:
                    entry["equipped"] = False
                items_out.append(entry)
            pouch[key] = items_out

        slots_valid = {}
        for key, cat in (("weapons", "Weapon"), ("bows", "Bow"), ("shields", "Shield")):
            arr = self.get_int_array(f"Pouch.{cat}.ValidNum")
            if arr:
                slots_valid[key] = arr[0]

        abilities = [
            nm
            for nm in self.get_str64_array("Pouch.SpecialPower.Content.Name")[:10]
            if nm
        ]

        sages = []
        for sname in SAGES_LIST:
            joined = self.get_bool(f"PlayerStatus.Companion.{sname}.IsGet")
            summoned = self.get_bool(f"PlayerStatus.Companion.{sname}.IsSummon")
            cond = self.get_enum(f"PlayerStatus.Companion.{sname}.JoiningCondition", "joining")
            sages.append({"id": sname, "joined": joined, "summoned": summoned, "condition": cond})

        done, found = evaluate_world_progress(map_data, self.table, self.guids) if map_data else ({}, {})
        quests = evaluate_quests_progress(quests_data, self.table, self.table) if quests_data else {}
        archives = evaluate_archives_progress(catalog_data, self.table, self.table) if catalog_data else {}
        album = read_album_photos(album_dir, self)

        return {
            **live,
            "pouch": pouch,
            "slots": slots_valid,
            "abilities": abilities,
            "sages": sages,
            "progress": {"done": done, "found": found},
            "quests": quests,
            "archives": archives,
            "album": album,
        }


def read_footprint_sav(fp_path: Path) -> dict[str, Any]:
    """Decodifica footprint.sav (Caminho do Herói) em polilinhas por camada e pontos de morte."""
    if not fp_path.is_file():
        return {"paths": {"surface": [], "sky": [], "depths": []}, "deaths": [], "count": 0}
    buf = fp_path.read_bytes()
    if len(buf) < 360 or struct.unpack_from("<I", buf, 0)[0] != HEADER_MAGIC:
        return {"paths": {"surface": [], "sky": [], "depths": []}, "deaths": [], "count": 0}

    count = 0
    pos = TABLE_START
    while pos + 8 <= 344:
        h, v = struct.unpack_from("<II", buf, pos)
        pos += 8
        if h == SAVE_TYPE_HASH:
            break
        if h == FOOTPRINT_COUNT_HASH:
            count = v
            break

    cap = struct.unpack_from("<I", buf, 356)[0]
    if cap > 200000 or 360 + cap * 4 > len(buf):
        cap = (len(buf) - 360) // 4
    limit = min(count, cap) if count > 0 else cap

    paths: dict[str, list[list[list[float]]]] = {"surface": [], "sky": [], "depths": []}
    deaths: list[dict[str, Any]] = []
    cur_layer: str | None = None
    cur_line: list[list[float]] = []
    total_pts = 0

    for i in range(limit):
        v = struct.unpack_from("<I", buf, 360 + i * 4)[0]
        if v == 0:
            if count == 0:
                break
            continue
        total_pts += 1
        z_mag = (v >> 20) & 0xFFF
        z_neg = (v >> 19) & 1  # 1 = negativo, 0 = positivo
        z = float(-z_mag if z_neg else z_mag)

        x_mag = (v >> 6) & 0x1FFF
        x_neg = (v >> 5) & 1  # 1 = negativo, 0 = positivo
        x = float(-x_mag if x_neg else x_mag)

        layer = {0: "sky", 1: "surface", 2: "depths"}.get((v >> 3) & 3, "surface")
        is_warp = bool((v >> 2) & 1)
        is_death = bool((v >> 1) & 1)

        if is_death:
            deaths.append({"x": x, "z": z, "layer": layer})

        if is_warp or layer != cur_layer or (
            cur_line and (abs(x - cur_line[-1][0]) > 250.0 or abs(z - cur_line[-1][1]) > 250.0)
        ):
            if len(cur_line) >= 2 and cur_layer is not None:
                paths[cur_layer].append(cur_line)
            cur_layer = layer
            cur_line = [[x, z]]
        else:
            if not cur_line or abs(x - cur_line[-1][0]) >= 4.0 or abs(z - cur_line[-1][1]) >= 4.0:
                cur_line.append([x, z])

    if len(cur_line) >= 2 and cur_layer is not None:
        paths[cur_layer].append(cur_line)

    return {"paths": paths, "deaths": deaths, "count": total_pts}


def read_album_photos(album_dir: Path | None, sav: SaveProgressReader | None = None) -> list[dict[str, Any]]:
    """Lista fotos salvas em profile/save/<uid>/album/ pareando metadados do progress.sav."""
    if not album_dir or not album_dir.is_dir():
        return []
    indices = sav.get_int_array("AlbumData.Photograph.Index") if sav else []
    actors = sav.get_str64_array("AlbumData.Photograph.ActorName") if sav else []
    locs = sav.get_str64_array("AlbumData.Photograph.Location") if sav else []

    by_idx: dict[int, dict[str, str]] = {}
    for pos_i, slot_idx in enumerate(indices):
        if slot_idx >= 0:
            by_idx[slot_idx] = {
                "actor": actors[pos_i] if pos_i < len(actors) else "",
                "location": locs[pos_i] if pos_i < len(locs) else "",
            }

    photos: list[dict[str, Any]] = []
    for p in sorted(album_dir.glob("*_Photo.jpg")):
        prefix = p.name.split("_", 1)[0]
        try:
            idx = int(prefix)
        except ValueError:
            idx = -1
        meta = by_idx.get(idx, {})
        thumb = p.with_name(f"{prefix}_Thumb.jpg")
        photos.append(
            {
                "index": idx,
                "filename": p.name,
                "thumb": thumb.name if thumb.is_file() else p.name,
                "actor": meta.get("actor", ""),
                "location": meta.get("location", ""),
            }
        )
    return photos
