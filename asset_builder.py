"""Extrator de assets e bancos de dados (map tiles, ícones, mapa, missões, catálogo) do RomFS do TotK."""
from __future__ import annotations

import json
import math
import re
import struct
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageChops, ImageDraw, ImageFilter

from config import (
    CACHE_DIR,
    CACHE_VERSION,
    CATALOG_PATH,
    ENTITIES_PATH,
    ICONS_CACHE_DIR,
    MAP_DATA_PATH,
    MASKS_CACHE_DIR,
    META_PATH,
    QUESTS_PATH,
    TILES_CACHE_DIR,
    ensure_dirs,
)
from totk_formats import (
    Romfs,
    decode_bntx_image,
    list_bntx_textures,
    mmh3,
    parse_byml,
    parse_msbt,
    parse_sarc,
)

LAYERS_MAP = {"surface": "G", "sky": "S", "depths": "U", "surface_fog": "G", "sky_fog": "S"}
LAYER_FROM_CODE = {"G": "surface", "S": "sky", "U": "depths"}
TILE_RE = re.compile(r"UI/Map/MainField/([GSU])_(\d\d)-(\d\d)_(\d\d)((?:_[TFAB]+)*)\.bntx\.zs$")
BANC_RE = re.compile(
    r"Banc/(MainField|MinusField)/([A-J]-\d_(Static|Dynamic)|Sky/.*|Cave/.*|DeepHole/.*|LargeDungeon/.*|Castle/.*)\.bcett\.byml\.zs$"
)

BOSS_PREFIXES = {
    "Giant": "hinoxes",
    "Golem": "taluses",
    "Sandworm": "moldugas",
    "Zonau": "flux_constructs",
    "Mogurudo": "froxes",
    "Drake": "gleeoks",
}
KOROK_ACTORS = ("Npc_HiddenKorokFly", "Npc_HiddenKorokGround")
HIDE_TYPES_PT: dict[int | None, str] = {
    None: "Levantar a pedra",
    1: "Luz brilhante",
    2: "Mergulhar na luz",
    3: "Trilha de flores",
    4: "Corrida até o alvo",
    5: "Luz em movimento",
    6: "Completar padrão de pedras",
    7: "Prato de oferenda",
    8: "Catavento e balões",
    9: "Acertar o balão",
    10: "Bolota pendurada",
    11: "Pousar no alvo",
    12: "Construir abrigo",
    13: "Consertar o telhado",
    15: "Quebra-cabeça de blocos",
    17: "Alcançar a luz",
    18: "Tocar o alvo",
    19: "Pegar a semente",
    20: "Puxar a rolha",
    23: "Atravessar o teto",
    24: "Pedestal de pedra",
    25: "Tocar o sino",
}
HIDE_TYPES_EN: dict[int | None, str] = {
    None: "Lift rock",
    1: "Sparkling leaves",
    2: "Dive into ring",
    3: "Flower trail",
    4: "Race to target",
    5: "Moving sparkle",
    6: "Rock pattern",
    7: "Offering plate",
    8: "Pinwheel & balloons",
    9: "Shoot balloon",
    10: "Hanging acorn",
    11: "Land on target",
    12: "Build shelter",
    13: "Fix roof",
    15: "Block puzzle",
    17: "Reach the light",
    18: "Touch target",
    19: "Grab seed",
    20: "Pull cork",
    23: "Ascend ceiling",
    24: "Stone pedestal",
    25: "Ring bell",
}


def _ltxt(lang: str, en: str, pt: str) -> str:
    return pt if lang == "USpt" else en
SCHEMA_SITES = {
    "Obj_AutoBuilderDraft_00": "SmeltShopGolem_10",
    "Obj_AutoBuilderDraft_01": "MinusField_Rito",
    "Obj_AutoBuilderDraft_02": "SmeltShopGolem_01",
    "Obj_AutoBuilderDraft_03": "SmeltShopGolem_03",
    "Obj_AutoBuilderDraft_04": "MinusField_Hateno",
    "Obj_AutoBuilderDraft_05": "SmeltShopGolem_09",
    "Obj_AutoBuilderDraft_06": "SmeltShopGolem_06",
    "Obj_AutoBuilderDraft_07": "SmeltShopGolem_02",
    "Obj_AutoBuilderDraft_08": "SmeltShopGolem_07",
    "Obj_AutoBuilderDraft_09": "MinusField_Goron",
    "Obj_AutoBuilderDraft_10": "MinusField_StartPoint",
    "Obj_AutoBuilderDraft_11": "MinusField_StartPoint",
}
MARKER_PLACES = re.compile(r"^(DemonStatue_\d+|SmallDemonStatue|SmeltShopGolem_\d+|ForgeShopGolem)$")
PLACE_CATEGORIES = re.compile(r"^(City|Dungeon|SkyArchipelago|SpotBig.*|SpotMiddle\w+)$")
SHOP_CATEGORY_ICONS: dict[str, str] = {
    "ShopArmor": "shop_armor",
    "ShopGeneral": "shop_general",
    "ShopInn": "shop_inn",
    "ShopDye": "shop_dye",
    "ShopJewelry": "shop_jewelry",
}
SPECIAL_SHOP_ICONS: dict[str, str] = {
    "Bar": "shop_bar",
    "CookingShop": "shop_cook",
    "ScrapShop": "shop_etc",
    "TreasureBoxShop": "shop_treasure",
    "RentalZarashiShop": "shop_etc",
    "BatteryExchangeShop": "shop_energy",
    "ForgeShop": "shop_weapon",
    "SmeltShop": "shop_energy",
    "HorseStableBranchOffice": "shop_horse",
    "EvilStatue": "shop_evil",
    "SmallEvilStatue": "shop_evil",
    "Farm": "shop_milk",
    "School": "shop_school",
    "FigureGallery": "shop_monster",
}
OPEN_MASK_BOUNDS: dict[str, tuple[int, int, int, int]] = {
    "Tower01": (4, 3, 3, 3),
    "Tower02": (1, 2, 5, 4),
    "Tower03": (2, 0, 5, 4),
    "Tower04": (6, 0, 5, 5),
    "Tower05": (8, 0, 4, 4),
    "Tower06": (6, 3, 4, 5),
    "Tower07": (7, 2, 5, 4),
    "Tower08": (3, 5, 4, 3),
    "Tower09": (0, 6, 6, 4),
    "Tower10": (0, 4, 5, 4),
    "Tower11": (7, 6, 5, 4),
    "Tower12": (4, 0, 4, 4),
    "Tower13": (4, 5, 5, 5),
    "Tower14": (8, 5, 4, 4),
    "Tower15": (0, 0, 4, 5),
}
GATHER_FRUITS = {
    "BombFruit",
    "FireFruit",
    "IceFruit",
    "ElectricalFruit",
    "WaterFruit",
    "LightFruit",
    "ConfusionFruit",
    "ConfusionFruit_Static",
}
QUEST_CATEGORY_MAP = {
    "Main": "main_quest",
    "ImportantMini": "side_adventure",
    "Sub": "shrine_quest",
    None: "side_quest",
    "": "side_quest",
}

MAP_ICON_RECIPES: dict[str, tuple[str, str, tuple[int, int, int] | None]] = {
    "shrine": ("mask", "MapIconDungeon_L_Icon^s", (62, 232, 200)),
    "lightroot": ("mask", "MapIconArrivalPoint_L_FrameIcon^s", (255, 168, 66)),
    "tower": ("mask", "MapIconTower_00^s", (72, 206, 255)),
    "cave": ("ui", "MapIconCaveL_72x72^w", None),
    "dispenser": ("ui", "MapIconRecycleBox_00^w", None),
    "dragon_tear": ("mask", "MapIconDragonTears_00^s", (130, 235, 195)),
    "great_fairy": ("ui", "MapIconFairy_72x72^w", None),
    "korok": ("ui", "MapIconKorok^w", None),
    "carry_korok": ("ui", "MapIconKorok_x2^w", None),
    "armor_chest": ("ui", "MapIconShopArmor_58x58^w", None),
    "treasure_chest": ("ui", "MapIconTreasureBox_72x72^w", None),
    "shop_armor": ("ui", "MapIconShopArmor_58x58^w", None),
    "shop_general": ("ui", "MapIconShopGeneral_58x58^w", None),
    "shop_inn": ("ui", "MapIconShopInn_58x58^w", None),
    "shop_dye": ("ui", "MapIconShopDyeing_58x58^w", None),
    "shop_jewelry": ("ui", "MapIconShopJewelery_58x58^w", None),
    "shop_bar": ("ui", "MapIconShopBar_58x58^w", None),
    "shop_cook": ("ui", "MapIconShopCook_58x58^w", None),
    "shop_etc": ("ui", "MapIconShopEtc_58x58^w", None),
    "shop_treasure": ("ui", "MapIconShopTreasure_58x58^w", None),
    "shop_energy": ("ui", "MapIconImportantShopEnergy_58x58^w", None),
    "shop_weapon": ("ui", "MapIconImportantShopWeapon_58x58^w", None),
    "shop_horse": ("ui", "MapIconShopHorse_58x58^w", None),
    "shop_evil": ("ui", "MapIconShopEvil_58x58^w", None),
    "shop_milk": ("ui", "MapIconShopMilk_58x58^w", None),
    "shop_school": ("ui", "MapIconShopSchool_58x58^w", None),
    "shop_monster": ("ui", "MapIconShopMonster_58x58^w", None),
    "stable": ("ui", "MapIconBuildingStableInn_58x58^w", None),
    "entity_npc": ("badge", "MapIconHuman_72x72^w", (94, 200, 255)),
    "entity_npc_quest": ("quest_npc", "MapIconHuman_72x72^w", (255, 210, 64)),
    "entity_animal": ("badge", "MapIconHorse_66x66^w", (242, 185, 80)),
    "entity_plant": ("badge", "MapIconLeaf_72x72^w", (94, 224, 123)),
    "entity_monster": ("badge", "MapIconSkull_72x72^w", (255, 94, 108)),
    "player": ("mask", "Nt_MapPlayerIconNew_00^s", (255, 214, 64)),
    "death": ("ui", "MapIconDead_64x64^w", None),
    "sky": ("mask", "MapTabIcon_Sky^s", (240, 240, 240)),
    "surface": ("mask", "MapTabIcon_Ground^s", (240, 240, 240)),
    "depths": ("mask", "MapTabIcon_Cave^s", (240, 240, 240)),
    "pin_Red": ("pin", "MapPinIconSmall0_00^s", (255, 77, 90)),
    "pin_Blue": ("pin", "MapPinIconSmall1_00^s", (60, 157, 255)),
    "pin_Yellow": ("pin", "MapPinIconSmall2_00^s", (255, 214, 56)),
    "pin_Green": ("pin", "MapPinIconSmall3_00^s", (76, 230, 124)),
    "pin_Purple": ("pin", "MapPinIconSmall4_00^s", (196, 110, 255)),
    "pin_LightBlue": ("pin", "MapPinIconSmall5_00^s", (72, 235, 255)),
    "stamp_Sword": ("ui", "MapIconWeapon_72x72^w", None),
    "stamp_Pot": ("ui", "MapIconCuisine_72x72^w", None),
    "stamp_Human": ("ui", "MapIconHuman_72x72^w", None),
    "stamp_Rhombus": ("ui", "MapIconSquare_72x72^w", None),
    "stamp_Heart": ("ui", "MapIconHeart_72x72^w", None),
    "stamp_Star": ("ui", "MapIconStar_72x72^w", None),
    "stamp_TreasureBox": ("ui", "MapIconTreasureBox_72x72^w", None),
    "stamp_Skull": ("ui", "MapIconSkull_72x72^w", None),
    "stamp_Leaf": ("ui", "MapIconLeaf_72x72^w", None),
    "stamp_Ore": ("ui", "MapIconOre_72x72^w", None),
    "bubbul": ("item", "Item_Enemy_115", None),
    "sages_will": ("item", "Item_SageSoul", None),
    "old_map": ("item", "Obj_TreasureMap_00", None),
    "schema_stone": ("item", "Obj_AutoBuilderDraft_00", None),
    "yiga_schematic": ("item", "Obj_AutoBuilderDraftAssassin_00", None),
    "hinox": ("pb", "Enemy_Giant_Junior", None),
    "talus": ("pb", "Enemy_Golem_Junior", None),
    "molduga": ("pb", "Enemy_Sandworm", None),
    "flux_construct": ("pb", "Enemy_Zonau_BlockMaster_Junior", None),
    "frox": ("pb", "Enemy_Mogurudo_Junior", None),
    "gleeok": ("pb", "Enemy_Drake_Fire", None),
    "lynel": ("pb", "Enemy_Lynel_Junior", None),
}


@dataclass
class BuildStatus:
    state: str = "idle"  # idle | building | ready | error
    step: str = ""
    progress: int = 0
    total: int = 0
    message: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_STATUS_LOCK = threading.Lock()
_STATUS = BuildStatus()
_TILE_INDEX_LOCK = threading.Lock()
_TILE_INDEX_CACHE: dict[tuple[str, int, int, int], str] | None = None
_FOG_TILE_INDEX_CACHE: dict[tuple[str, int, int, int], str] | None = None
_ROMFS_LOCK = threading.Lock()
_ROMFS_SINGLETON: Romfs | None = None
_ROMFS_DIR: str | None = None


def get_build_status() -> dict[str, Any]:
    with _STATUS_LOCK:
        return _STATUS.to_dict()


def _set_status(**kwargs: Any) -> None:
    with _STATUS_LOCK:
        for k, v in kwargs.items():
            setattr(_STATUS, k, v)


def get_romfs(game_dir: Path | str) -> Romfs:
    global _ROMFS_SINGLETON, _ROMFS_DIR
    romfs_dir = str(Path(game_dir) / "romfs")
    with _ROMFS_LOCK:
        if _ROMFS_SINGLETON is None or _ROMFS_DIR != romfs_dir:
            if _ROMFS_SINGLETON is not None:
                _ROMFS_SINGLETON.close()
            _ROMFS_SINGLETON = Romfs(romfs_dir)
            _ROMFS_DIR = romfs_dir
        return _ROMFS_SINGLETON


def _basename(path: str | None) -> str:
    return path.rsplit("/", 1)[-1].split(".", 1)[0] if path else ""


def _pos(t: list[float] | tuple[float, float, float]) -> dict[str, float]:
    return {"x": round(float(t[0]), 2), "y": round(float(t[1]), 2), "z": round(float(t[2]), 2)}


def _dist(a: list[float] | tuple[float, ...], b: list[float] | tuple[float, ...]) -> float:
    return sum((a[i] - b[i]) ** 2 for i in range(3)) ** 0.5


def _nearest(points: list[list[float]], t: list[float], within: float | None = None) -> list[float] | None:
    best = min(points, key=lambda p: _dist(p, t), default=None)
    return best if best is not None and (within is None or _dist(best, t) <= within) else None


def _write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".part")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def _product_version_key(path: str, prefix: str, suffix: str) -> tuple[int, str]:
    mid = path[len(prefix) : len(path) - len(suffix)] if path.startswith(prefix) and path.endswith(suffix) else ""
    digits = "".join(ch for ch in mid.split(".", 1)[0] if ch.isdigit())
    return (int(digits) if digits else -1, path)


def _pick_latest_product(romfs: Romfs, prefix: str, suffix: str) -> str | None:
    """Escolhe o arquivo RomFS com o maior número de versão `Product.<N>` (100, 110, 121, 143...)."""
    candidates = romfs.find(prefix, suffix)
    if not candidates:
        return None
    return max(candidates, key=lambda p: _product_version_key(p, prefix, suffix))


def detect_romfs_version(romfs: Romfs) -> str:
    """Infere a versão do jogo (ex.: '1.2.1', '1.4.3') a partir dos arquivos `Product.<N>` do RomFS."""
    probes = (
        ("GameData/GameDataList.Product.", ".byml.zs"),
        ("RSDB/PouchActorInfo.Product.", ".rstbl.byml.zs"),
        ("RSDB/Challenge.Product.", ".rstbl.byml.zs"),
        ("RSDB/Location.Product.", ".byml.zs"),
    )
    best_num = -1
    for prefix, suffix in probes:
        picked = _pick_latest_product(romfs, prefix, suffix)
        if picked:
            num, _ = _product_version_key(picked, prefix, suffix)
            if num > best_num:
                best_num = num
    if best_num >= 100:
        s = str(best_num)
        if len(s) == 3:
            return f"{s[0]}.{s[1]}.{s[2]}"
        return s
    return "unknown"


def is_cache_ready(game_dir: Path, lang: str, game_version: str | None = None) -> bool:
    if not META_PATH.is_file():
        return False
    try:
        meta = json.loads(META_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if game_version is not None and meta.get("game_version") != game_version:
        return False
    return (
        meta.get("cache_version") == CACHE_VERSION
        and meta.get("lang") == lang
        and meta.get("game_dir") == str(game_dir)
        and MAP_DATA_PATH.is_file()
        and ENTITIES_PATH.is_file()
        and QUESTS_PATH.is_file()
        and CATALOG_PATH.is_file()
        and (MASKS_CACHE_DIR / "region_Tower01.png").is_file()
        and (MASKS_CACHE_DIR / "border_Tower01.png").is_file()
        and (ICONS_CACHE_DIR / "map" / "entity_npc_quest.png").is_file()
        and (TILES_CACHE_DIR / "surface_fog" / "2" / "5_4.png").is_file()
    )


def pick_tile_variants(romfs: Romfs) -> dict[tuple[str, int, int, int], str]:
    """Mapeia (layer, lod, col, row) -> caminho RomFS escolhendo a variante completa revelada."""
    best: dict[tuple[str, int, int, int], tuple[tuple[int, int, int, str], str]] = {}
    for path in romfs.find("UI/Map/MainField/", ".bntx.zs"):
        m = TILE_RE.match(path)
        if not m:
            continue
        l_code, col_s, row_s, lod_s, suffix = m.groups()
        layer = LAYER_FROM_CODE[l_code]
        lod = int(lod_s)
        col = int(col_s)
        row = int(row_s)
        parts = [x for x in suffix.split("_") if x]
        letters = "".join(parts)
        score = (len(parts), letters.count("T") - letters.count("F"), letters.count("A"), suffix)
        key = (layer, lod, col, row)
        if key not in best or score > best[key][0]:
            best[key] = (score, path)
    return {k: v[1] for k, v in best.items()}


def pick_fog_tile_variants(romfs: Romfs) -> dict[tuple[str, int, int, int], str]:
    """Mapeia (layer_fog, lod, col, row) -> caminho RomFS escolhendo a variante totalmente não revelada (_F/_FF/...)."""
    best: dict[tuple[str, int, int, int], tuple[tuple[int, int, str], str]] = {}
    for path in romfs.find("UI/Map/MainField/", ".bntx.zs"):
        m = TILE_RE.match(path)
        if not m:
            continue
        l_code, col_s, row_s, lod_s, suffix = m.groups()
        if l_code not in ("G", "S"):
            continue
        parts = [x for x in suffix.split("_") if x]
        if not parts or any(ch != "F" for ch in parts[0]):
            continue
        layer = f"{LAYER_FROM_CODE[l_code]}_fog"
        lod = int(lod_s)
        col = int(col_s)
        row = int(row_s)
        sub_variant = "".join(parts[1:])
        score = (1 if sub_variant.startswith("A") else 0, len(parts[0]), suffix)
        key = (layer, lod, col, row)
        if key not in best or score > best[key][0]:
            best[key] = (score, path)
    return {k: v[1] for k, v in best.items()}


def _get_tile_index(romfs: Romfs, fog: bool = False) -> dict[tuple[str, int, int, int], str]:
    global _TILE_INDEX_CACHE, _FOG_TILE_INDEX_CACHE
    with _TILE_INDEX_LOCK:
        if fog:
            if _FOG_TILE_INDEX_CACHE is None:
                _FOG_TILE_INDEX_CACHE = pick_fog_tile_variants(romfs)
            return _FOG_TILE_INDEX_CACHE
        if _TILE_INDEX_CACHE is None:
            _TILE_INDEX_CACHE = pick_tile_variants(romfs)
        return _TILE_INDEX_CACHE


def get_or_decode_tile(game_dir: Path, layer: str, lod: int, col: int, row: int) -> Path | None:
    """Retorna o caminho do tile PNG em cache, decodificando sob demanda se necessário."""
    if layer not in LAYERS_MAP or lod not in (0, 1, 2, 3, 4) or not (0 <= col <= 11 and 0 <= row <= 9):
        return None
    out_path = TILES_CACHE_DIR / layer / str(lod) / f"{col}_{row}.png"
    if out_path.is_file():
        return out_path
    romfs = get_romfs(game_dir)
    is_fog = layer.endswith("_fog")
    idx = _get_tile_index(romfs, fog=is_fog)
    rpath = idx.get((layer, lod, col, row))
    if not rpath:
        return None
    data = romfs.read(rpath)
    img = decode_bntx_image(data)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".part.png")
    img.save(tmp, format="PNG")
    tmp.replace(out_path)
    return out_path


def _build_overview_tiles(romfs: Romfs) -> None:
    """Pré-decodifica todos os 360 tiles revelados e 240 tiles de névoa LOD 2 (300x300 px) em paralelo."""
    combined: list[tuple[tuple[str, int, int, int], str]] = [
        *list(_get_tile_index(romfs, fog=False).items()),
        *list(_get_tile_index(romfs, fog=True).items()),
    ]
    tasks: list[tuple[str, int, int, str, Path]] = []
    for (layer, lod, col, row), rpath in combined:
        if lod != 2:
            continue
        out_path = TILES_CACHE_DIR / layer / "2" / f"{col}_{row}.png"
        if not out_path.is_file():
            tasks.append((layer, col, row, rpath, out_path))

    total = max(len(tasks), 1)
    _set_status(step="tiles", progress=0, total=len(tasks), message=f"Gerando tiles do mapa (0/{len(tasks)})...")
    if not tasks:
        return

    def worker(item: tuple[str, int, int, str, Path]) -> None:
        _, _, _, rpath, out_path = item
        out_path.parent.mkdir(parents=True, exist_ok=True)
        img = decode_bntx_image(romfs.read(rpath))
        tmp = out_path.with_suffix(".part.png")
        img.save(tmp, format="PNG")
        tmp.replace(out_path)

    done = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(worker, t) for t in tasks]
        for f in as_completed(futs):
            f.result()
            done += 1
            if done % 25 == 0 or done == total:
                _set_status(progress=done, message=f"Gerando tiles do mapa ({done}/{len(tasks)})...")


def _fit_icon(img: Image.Image, size: int, box: int) -> Image.Image:
    visible = img.getchannel("A").point(lambda v: 255 if v > 80 else 0).getbbox()
    if visible:
        l, t, r, b = visible
        visible = (max(l - 2, 0), max(t - 2, 0), min(r + 2, img.width), min(b + 2, img.height))
    cropped = img.crop(visible or (0, 0, *img.size))
    scale = box / max(cropped.size)
    resized = cropped.resize((max(1, round(cropped.width * scale)), max(1, round(cropped.height * scale))), Image.LANCZOS)
    out = Image.new("RGBA", (size, size))
    out.alpha_composite(resized, ((size - resized.width) // 2, (size - resized.height) // 2))
    return out


def _with_outline(img: Image.Image, width: int = 5, opacity: float = 0.85) -> Image.Image:
    alpha = img.getchannel("A")
    edge = alpha.filter(ImageFilter.MaxFilter(width)).filter(ImageFilter.GaussianBlur(1.4))
    edge = edge.point(lambda v: int(v * opacity))
    out = Image.new("RGBA", img.size, (14, 16, 20, 0))
    out.putalpha(edge)
    out.alpha_composite(img)
    return out


def _tint_mask(mask: Image.Image, colour: tuple[int, int, int]) -> Image.Image:
    out = Image.new("RGBA", mask.size, (*colour, 0))
    out.putalpha(mask.getchannel("A"))
    return out


def _photo_badge(img: Image.Image, size: int = 64) -> Image.Image:
    side = min(img.size)
    left, top = (img.width - side) // 2, (img.height - side) // 2
    cropped = img.crop((left, top, left + side, top + side)).resize((size - 8, size - 8), Image.LANCZOS)
    mask = Image.new("L", cropped.size, 0)
    ImageDraw.Draw(mask).ellipse((0, 0, cropped.width - 1, cropped.height - 1), fill=255)
    out = Image.new("RGBA", (size, size))
    ImageDraw.Draw(out).ellipse((0, 0, size - 1, size - 1), fill=(16, 18, 22, 255))
    ImageDraw.Draw(out).ellipse((2, 2, size - 3, size - 3), fill=(215, 191, 130, 255))
    cropped.putalpha(ImageChops.multiply(cropped.getchannel("A"), mask))
    out.alpha_composite(cropped, (4, 4))
    return out


def _pin_badge(glyph_mask: Image.Image, colour: tuple[int, int, int], size: int = 64) -> Image.Image:
    """Desenha um pino em forma de gota do Purah Pad preenchido com `colour` e glifo interno claro."""
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(out)
    cx = size // 2
    cy = int(size * 0.38)
    r = int(size * 0.30)
    tip_y = int(size * 0.94)
    ang = math.radians(32)
    dx = int(r * math.cos(ang))
    dy = int(r * math.sin(ang))

    # Borda escura + corpo colorido da gota
    draw.polygon([(cx - dx - 2, cy + dy), (cx + dx + 2, cy + dy), (cx, tip_y + 2)], fill=(12, 16, 22, 240))
    draw.ellipse((cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2), fill=(12, 16, 22, 240))
    draw.polygon([(cx - dx, cy + dy - 1), (cx + dx, cy + dy - 1), (cx, tip_y - 2)], fill=(*colour, 255))
    draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(*colour, 255))
    # Brilho interno sutil
    draw.ellipse((cx - r + 2, cy - r + 2, cx + r - 2, cy + r - 2), outline=(255, 255, 255, 110), width=2)

    glyph = _fit_icon(_tint_mask(glyph_mask, (18, 22, 28)), size, int(size * 0.42))
    glyph_w = _fit_icon(_tint_mask(glyph_mask, (255, 255, 255)), size, int(size * 0.42))
    shift_y = cy - size // 2
    out.alpha_composite(glyph, (0, shift_y + 1))
    out.alpha_composite(glyph_w, (0, shift_y))
    return out


def _entity_badge(img: Image.Image, border_colour: tuple[int, int, int], size: int = 64) -> Image.Image:
    """Desenha um emblema circular escuro com aro colorido e ícone oficial centralizado."""
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(out)
    draw.ellipse((2, 2, size - 3, size - 3), fill=(14, 20, 26, 238), outline=(*border_colour, 255), width=4)
    glyph = _fit_icon(img, size, size - 20)
    out.alpha_composite(glyph, (0, 0))
    return out


def _quest_npc_badge(img: Image.Image, border_colour: tuple[int, int, int], size: int = 64) -> Image.Image:
    """Desenha o emblema dourado de NPC com selo de missão secundária (!)."""
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(out)
    draw.ellipse((3, 5, size - 5, size - 3), fill=(26, 20, 10, 245), outline=(*border_colour, 255), width=4)
    glyph = _fit_icon(img, size, size - 22)
    out.alpha_composite(glyph, (-1, 1))
    # Selo '!' dourado no canto superior direito
    bx, by, br = size - 14, 13, 11
    draw.ellipse((bx - br, by - br, bx + br, by + br), fill=(255, 210, 64, 255), outline=(14, 18, 22, 255), width=2)
    draw.rectangle((bx - 2, by - 6, bx + 2, by + 1), fill=(18, 22, 28, 255))
    draw.rectangle((bx - 2, by + 3, bx + 2, by + 6), fill=(18, 22, 28, 255))
    return out


def _build_open_masks(romfs: Romfs, force: bool = False) -> None:
    """Extrai as máscaras oficiais das 15 Torres Panorâmicas e gera seus contornos ciano."""
    _set_status(step="masks", progress=0, total=len(OPEN_MASK_BOUNDS), message="Extraindo máscaras das regiões...")
    MASKS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    for idx, tname in enumerate(sorted(OPEN_MASK_BOUNDS), 1):
        num = tname.replace("Tower", "")
        reg_path = MASKS_CACHE_DIR / f"region_{tname}.png"
        brd_path = MASKS_CACHE_DIR / f"border_{tname}.png"
        if not force and reg_path.is_file() and brd_path.is_file():
            continue
        rpath = f"UI/Map/MainFieldOpenMask/G_OpenMask_{num}.bntx.zs"
        if not romfs.exists(rpath):
            continue
        img = decode_bntx_image(romfs.read(rpath))
        tmp_r = reg_path.with_suffix(".part.png")
        img.save(tmp_r, format="PNG")
        tmp_r.replace(reg_path)

        alpha = img.getchannel("A")
        outer = alpha.filter(ImageFilter.MaxFilter(5))
        inner = alpha.filter(ImageFilter.MinFilter(3))
        edge = ImageChops.subtract(outer, inner).filter(ImageFilter.GaussianBlur(0.8))
        brd = Image.new("RGBA", img.size, (56, 206, 255, 0))
        brd.putalpha(edge)
        tmp_b = brd_path.with_suffix(".part.png")
        brd.save(tmp_b, format="PNG")
        tmp_b.replace(brd_path)
        _set_status(progress=idx)


def get_mask_path(name: str) -> Path | None:
    """Retorna o caminho seguro de uma máscara ou contorno em MASKS_CACHE_DIR."""
    safe = Path(name).name
    if not safe or safe != name or ".." in safe:
        return None
    p = MASKS_CACHE_DIR / f"{safe}.png"
    return p if p.is_file() else None


def _load_region_masks_lookup(romfs: Romfs) -> list[tuple[int, float, float, float, float, int, int, bytes]]:
    """Carrega os canais alfa das 15 máscaras em memória para classificação rápida (x, z) -> regionIdx."""
    entries: list[tuple[int, float, float, float, float, int, int, bytes]] = []
    for i in range(1, 16):
        tname = f"Tower{i:02d}"
        bounds = OPEN_MASK_BOUNDS.get(tname)
        if not bounds:
            continue
        c0, r0, tw, th = bounds
        x0 = -6000.0 + c0 * 1000.0
        z0 = -5000.0 + r0 * 1000.0
        w_m = tw * 1000.0
        h_m = th * 1000.0
        reg_path = MASKS_CACHE_DIR / f"region_{tname}.png"
        if reg_path.is_file():
            alpha = Image.open(reg_path).getchannel("A")
        else:
            rpath = f"UI/Map/MainFieldOpenMask/G_OpenMask_{i:02d}.bntx.zs"
            if not romfs.exists(rpath):
                continue
            alpha = decode_bntx_image(romfs.read(rpath)).getchannel("A")
        entries.append((i, x0, z0, w_m, h_m, alpha.width, alpha.height, alpha.tobytes()))
    return entries


def _build_map_icons(romfs: Romfs, force: bool = False) -> None:
    _set_status(step="icons", progress=0, total=len(MAP_ICON_RECIPES), message="Extraindo ícones do mapa...")
    out_dir = ICONS_CACHE_DIR / "map"
    out_dir.mkdir(parents=True, exist_ok=True)
    common_path = _pick_latest_product(romfs, "UI/LayoutArchive/Common.", ".blarc.zs")
    ui_data: bytes | None = None
    ui_index: dict[str, int] = {}
    if common_path:
        ui_data = parse_sarc(romfs.read(common_path)).get("timg/__Combined.bntx")
        if ui_data:
            ui_index = dict(list_bntx_textures(ui_data))

    size = 64
    for idx, (name, (kind, src, colour)) in enumerate(MAP_ICON_RECIPES.items(), 1):
        out_path = out_dir / f"{name}.png"
        if not force and out_path.is_file():
            continue
        try:
            if kind in ("ui", "mask"):
                if not ui_data or src not in ui_index:
                    continue
                img = decode_bntx_image(ui_data, ui_index[src])
                if kind == "mask" and colour is not None:
                    img = _tint_mask(img, colour)
                img = _with_outline(_fit_icon(img, size, size - 12))
            elif kind == "badge":
                if not ui_data or src not in ui_index or colour is None:
                    continue
                img = _entity_badge(decode_bntx_image(ui_data, ui_index[src]), colour, size=size)
            elif kind == "quest_npc":
                if not ui_data or src not in ui_index or colour is None:
                    continue
                img = _quest_npc_badge(decode_bntx_image(ui_data, ui_index[src]), colour, size=size)
            elif kind == "pin":
                if not ui_data or src not in ui_index or colour is None:
                    continue
                img = _pin_badge(decode_bntx_image(ui_data, ui_index[src]), colour, size=size)
            elif kind == "item":
                rpath = f"UI/Tex/Icon/{src}.bntx.zs"
                if not romfs.exists(rpath):
                    continue
                img = _with_outline(_fit_icon(decode_bntx_image(romfs.read(rpath)), size, size - 8), width=3, opacity=0.65)
            elif kind == "pb":
                rpath = f"UI/Tex/PictureBook/{src}_Icon.bntx.zs"
                if not romfs.exists(rpath):
                    continue
                img = _photo_badge(decode_bntx_image(romfs.read(rpath)), size=size)
            else:
                continue
            tmp = out_path.with_suffix(".part.png")
            img.save(tmp, format="PNG")
            tmp.replace(out_path)
        except Exception:
            continue
        if idx % 10 == 0:
            _set_status(progress=idx)


def _resolve_item_icon_name(actor_id: str, icon_set: set[str]) -> str:
    """Resolve o arquivo de ícone real em UI/Tex/Icon para um PouchActorInfo.__RowId."""
    if actor_id in icon_set:
        return actor_id
    # Mapeamentos comuns do TotK (peixes/insetos/armaduras variantes/mapas/esquemas)
    replacements = [
        ("Animal_Fish_", "Item_FishGet_"),
        ("Animal_Insect_", "Item_InsectGet_"),
        ("Item_Plant_", "Item_PlantGet_"),
    ]
    for old, new in replacements:
        if actor_id.startswith(old):
            cand = new + actor_id[len(old) :]
            if cand in icon_set:
                return cand
    for suffix in ("_B", "_Broken", "_Static", "_Bundle", "_Capsule"):
        if actor_id.endswith(suffix):
            cand = actor_id[: -len(suffix)]
            if cand in icon_set:
                return cand
            if suffix == "_Capsule":
                cand2 = f"{cand}_Capsule_A_01"
                if cand2 in icon_set:
                    return cand2
                cand3 = f"{cand}_A_01"
                if cand3 in icon_set:
                    return cand3
    if actor_id.startswith("Obj_TreasureMap"):
        return "Obj_TreasureMap_00"
    if actor_id.startswith("Obj_AutoBuilderDraftAssassin"):
        return "Obj_AutoBuilderDraftAssassin_00"
    if actor_id.startswith("Obj_AutoBuilderDraft"):
        return "Obj_AutoBuilderDraft_00"
    if actor_id.startswith("Armor_") and actor_id.count("_") >= 2:
        parts = actor_id.split("_")
        cand = "_".join(parts[:3])
        if cand in icon_set:
            return cand
        cand2 = "_".join(parts[:2]) + "_Head"
        if cand2 in icon_set:
            return cand2
    return actor_id


def get_or_decode_icon(game_dir: Path, kind: str, name: str) -> Path | None:
    """Retorna ou decodifica sob demanda um ícone (map, item, picturebook, picturebook_detail, chara, chara_pic)."""
    safe_name = Path(name).name
    if not safe_name or safe_name != name or ".." in safe_name:
        return None
    out_path = ICONS_CACHE_DIR / kind / f"{safe_name}.png"
    if out_path.is_file():
        return out_path
    if kind == "map":
        return None

    romfs = get_romfs(game_dir)
    rpath: str | None = None
    if kind == "item":
        cand = f"UI/Tex/Icon/{safe_name}.bntx.zs"
        if romfs.exists(cand):
            rpath = cand
    elif kind == "picturebook":
        cand = f"UI/Tex/PictureBook/{safe_name}_Icon.bntx.zs"
        if romfs.exists(cand):
            rpath = cand
    elif kind == "picturebook_detail":
        cand = f"UI/Tex/PictureBook/{safe_name}_Detail.bntx.zs"
        if romfs.exists(cand):
            rpath = cand
    elif kind == "chara":
        cand = f"UI/Tex/CharaDirectory/{safe_name}_Icon.bntx.zs"
        if romfs.exists(cand):
            rpath = cand
    elif kind == "chara_pic":
        cand = f"UI/Tex/CharaDirectory/{safe_name}_Picture.bntx.zs"
        if romfs.exists(cand):
            rpath = cand

    if not rpath:
        return None
    img = decode_bntx_image(romfs.read(rpath))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".part.png")
    img.save(tmp, format="PNG")
    tmp.replace(out_path)
    return out_path


def _flower_trails(flowers: list[tuple[list[float], int | None]], link: float = 60.0) -> list[list[list[float]]]:
    n = len(flowers)
    if n == 0:
        return []
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if _dist(flowers[i][0], flowers[j][0]) < link:
                parent[find(i)] = find(j)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    trails: list[list[list[float]]] = []
    for idx in groups.values():
        first = [i for i in idx if flowers[i][1] == 1]
        cur = first[0] if first else idx[0]
        order = [cur]
        rest = set(idx) - {cur}
        while rest:
            cur = min(rest, key=lambda i: _dist(flowers[i][0], flowers[cur][0]))
            order.append(cur)
            rest.remove(cur)
        trails.append([flowers[i][0] for i in order])
    return trails


def _carry_routes(carry: dict[int, tuple[str, list[float], list[int]]]) -> list[tuple[list[float], list[float]]]:
    out: list[tuple[list[float], list[float]]] = []
    for g, t, links in carry.values():
        if g != "KorokCarryPassenger_Pair":
            continue
        for d in links:
            dest = carry.get(d)
            if dest and dest[0] == "KorokCarry_Destination":
                out.append((t, dest[1]))
                break
    return out


def _infer_banc_layer(path: str, y: float) -> str:
    if path.startswith("Banc/MinusField/"):
        return "depths"
    if "/Sky/" in path or y > 680.0:
        return "sky"
    return "surface"


_MONSTER_TOKEN_STRIPS = (
    "_AllDay",
    "_AlwaysRespawn",
    "_NoOrder",
    "_Ambush",
    "_Cliff",
    "_Golem_Fort",
    "_TreeHouseTop",
    "_Army",
    "_RagdollShort",
    "_GerudoCanyon",
    "_PopUp",
    "_Popup",
    "_LongVisibility",
    "_LongSight",
    "_Lookout_Cliff",
    "_Lookout_Mile",
    "_Lookout",
    "_Beginning",
    "_Sky",
    "_Defense",
    "_GateKeeper",
    "_Gatekeeper",
    "_Rider_Bow",
    "_Rider",
    "_Swarm_Cave",
)


def _resolve_npc_name(g: str, npc_msg: dict[str, str]) -> str:
    if g.startswith(("Npc_HiddenKorok", "Npc_DressFairy_")) or g == "Npc_CraftSignboard001":
        return ""
    if "Dummy" in g or "_Test" in g:
        return ""
    if f"{g}_Name" in npc_msg:
        return npc_msg[f"{g}_Name"]
    parts = g.split("_")
    while len(parts) >= 2:
        cand = "_".join(parts) + "_Name"
        if cand in npc_msg:
            return npc_msg[cand]
        parts.pop()
    return ""


def _resolve_animal_name(g: str, pb_msg: dict[str, str], pouch_msg: dict[str, str]) -> str:
    if "Dummy" in g or g == "Animal_Insect_EP":
        return ""
    if g.startswith("Animal_Fish_"):
        key = "Item_FishGet_" + g[len("Animal_Fish_") :] + "_Name"
        return pouch_msg.get(key) or pb_msg.get(key) or ""
    if g.startswith("Animal_Insect_"):
        key = "Item_InsectGet_" + g[len("Animal_Insect_") :] + "_Name"
        return pouch_msg.get(key) or pb_msg.get(key) or ""
    if g == "GameRomHorseNushi":
        return "Senhor da Montanha"
    if g == "Animal_Horse_A_Gold":
        return "Cavalo dourado"
    if g.startswith(("Animal_Horse_", "GameRomHorse")):
        return pb_msg.get(f"{g}_Name") or pb_msg.get("GameRomHorse_Name") or "Cavalo"
    if g.startswith("Animal_Dog_"):
        return pb_msg.get(f"{g}_Name") or pb_msg.get("Animal_Dog_A_Name") or ""
    if g.startswith("Animal_Donkey_"):
        return pb_msg.get(f"{g}_Name") or "Burro"
    if g.startswith("Animal_Kokko_"):
        return pb_msg.get(f"{g}_Name") or pb_msg.get("Animal_Kokko_A_Name") or ""
    if g.startswith("Animal_Sheep_"):
        return pb_msg.get(f"{g}_Name") or pb_msg.get("Animal_Sheep_A_Name") or ""
    if g.startswith("Animal_Sunazarashi"):
        return pb_msg.get(f"{g}_Name") or pb_msg.get("Animal_Sunazarashi_A_Name") or ""
    if g.startswith("Animal_RupeeRabbit"):
        return pb_msg.get(f"{g}_Name") or pb_msg.get("Animal_RupeeRabbit_A_Name") or ""

    base = re.sub(r"_(Swarm|NoMove|MOTD)$", "", g)
    for cand in (f"{base}_Name", f"{base}_A_Name"):
        if cand in pb_msg:
            return pb_msg[cand]
        if cand in pouch_msg:
            return pouch_msg[cand]
    parts = base.split("_")
    while len(parts) >= 2:
        prefix = "_".join(parts)
        for cand in (f"{prefix}_Name", f"{prefix}_A_Name"):
            if cand in pb_msg:
                return pb_msg[cand]
            if cand in pouch_msg:
                return pouch_msg[cand]
        parts.pop()
    return ""


def _resolve_plant_name(g: str, pouch_msg: dict[str, str], pb_msg: dict[str, str]) -> str:
    if g.endswith(("_OwnedByNpc", "_TemporaryOwnedByNpc")) or g.startswith("Obj_Plant_"):
        return ""
    if not (g.startswith(("Item_Plant_", "Item_Fruit_", "Item_Mushroom_")) or g in GATHER_FRUITS):
        return ""
    base = re.sub(r"_Static$", "", g)
    cands = [base]
    if base.count("_") >= 2:
        cands.append("_".join(base.split("_")[:3]))
    for c in cands:
        alt = c
        if c.startswith("Item_Plant_"):
            alt = "Item_PlantGet_" + c[len("Item_Plant_") :]
        elif c.startswith("Item_Mushroom_"):
            alt = "Item_MushroomGet_" + c[len("Item_Mushroom_") :]
        elif c.startswith("Item_Fruit_"):
            alt = "Item_FruitGet_" + c[len("Item_Fruit_") :]
        for key in (f"{c}_Name", f"{alt}_Name"):
            nm = pouch_msg.get(key) or pb_msg.get(key)
            if nm:
                return nm
    return ""


def _resolve_monster_name(g: str, monster_msg: dict[str, str]) -> str:
    if (
        g.startswith(("Enemy_Army_Manager", "Enemy_CaveMaster", "Enemy_Dragon_Light", "Enemy_DungeonBoss_", "Enemy_Lynel"))
        or "Dummy" in g
        or "Part" in g
    ):
        return ""
    base = g
    for tok in _MONSTER_TOKEN_STRIPS:
        base = base.replace(tok, "")
    for mid in ("_Guard_", "_Armor_", "_NoSleep_", "_Sniper_", "_Shooter_"):
        base = base.replace(mid, "_")
    while "__" in base:
        base = base.replace("__", "_")
    base = base.rstrip("_")
    if base.startswith("Enemy_Chuchu_") and base.endswith(("_Middle", "_Senior")):
        base = re.sub(r"_(Middle|Senior)$", "_Junior", base)
    elif base in ("Enemy_Chuchu_Middle", "Enemy_Chuchu_Senior"):
        base = "Enemy_Chuchu_Junior"

    if f"{base}_Name" in monster_msg:
        return monster_msg[f"{base}_Name"]
    parts = base.split("_")
    while len(parts) >= 2:
        cand = "_".join(parts) + "_Name"
        if cand in monster_msg:
            return monster_msg[cand]
        parts.pop()
    return ""


def _canonical_item_id(actor_id: str, pouch_ids: set[str]) -> tuple[str, int]:
    """Normaliza IDs de display/pacote do mundo para o __RowId canônico em PouchActorInfo."""
    if not actor_id:
        return "", 1
    if actor_id == "Obj_ArrowBundle_A_01":
        return "NormalArrow", 5
    if actor_id == "Obj_ArrowBundle_A_02":
        return "NormalArrow", 10
    if actor_id == "Obj_ArrowNormal_A_01":
        return "NormalArrow", 1

    clean = actor_id.removesuffix("_forDisplay").removesuffix("_Static")
    for src_pref, dst_pref in (
        ("Item_FishGet_", "Animal_Fish_"),
        ("Item_InsectGet_", "Animal_Insect_"),
        ("Item_PlantGet_", "Item_Plant_"),
        ("Item_MushroomGet_", "Item_Mushroom_"),
        ("Item_FruitGet_", "Item_Fruit_"),
    ):
        if clean.startswith(src_pref):
            cand = dst_pref + clean[len(src_pref) :]
            if cand in pouch_ids:
                return cand, 1
    if clean in pouch_ids:
        return clean, 1
    for suf in ("_B", "_Broken"):
        if clean.endswith(suf):
            base = clean[: -len(suf)]
            if base in pouch_ids:
                return base, 1
    return clean, 1


def _resolve_item_name_caption(
    rid: str,
    pouch_msg: dict[str, str],
    pb_msg: dict[str, str],
    attach_msg: dict[str, str],
    lang: str = "USen",
) -> tuple[str, str]:
    """Resolve nome e descrição oficiais (no idioma do jogo) de um PouchActorInfo.__RowId."""
    if rid == "Energy_Material_02" and "Energy_Material_02_Name" not in pouch_msg:
        nm = pouch_msg.get("Energy_Material_01_Name") or _ltxt(lang, "Crystallized Charge", "Cristal energético")
        return nm, pouch_msg.get("Energy_Material_02_Caption") or ""
    cands = [rid]
    for src_pref, alt_pref in (
        ("Animal_Fish_", "Item_FishGet_"),
        ("Animal_Insect_", "Item_InsectGet_"),
        ("Item_Plant_", "Item_PlantGet_"),
        ("Item_Mushroom_", "Item_MushroomGet_"),
        ("Item_Fruit_", "Item_FruitGet_"),
    ):
        if rid.startswith(src_pref):
            cands.append(alt_pref + rid[len(src_pref) :])

    name = ""
    caption = ""
    for c in cands:
        if not name:
            name = pouch_msg.get(f"{c}_Name") or pb_msg.get(f"{c}_Name") or attach_msg.get(f"{c}_Name") or ""
        if not caption:
            caption = pouch_msg.get(f"{c}_Caption") or pb_msg.get(f"{c}_Caption") or attach_msg.get(f"{c}_Caption") or ""
        if name and caption:
            break
    return (name or rid), caption


def _cluster_entities(
    raw_points: list[tuple[Any, ...]],
    cell_size: float,
    region_lookup: Any,
    lightroots: list[dict[str, Any]],
    collect_tags: bool = False,
) -> Any:
    """Agrupa entidades com mesmo (layerIdx, nameIdx) próximas espacialmente e anota regionIdx."""
    if not raw_points:
        return ([], []) if collect_tags else []
    buckets: dict[tuple[int, int, int, int], list[int]] = {}
    r2 = cell_size * cell_size
    out: list[list[int]] = []
    tags_out: list[set[str]] = []

    for pt in raw_points:
        x, z, y, lyr, nidx = int(pt[0]), int(pt[1]), int(pt[2]), int(pt[3]), int(pt[4])
        tag = str(pt[5]) if len(pt) > 5 and pt[5] else ""
        gx = int(math.floor(x / cell_size))
        gz = int(math.floor(z / cell_size))
        placed = False
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                for idx in buckets.get((lyr, nidx, gx + dx, gz + dz), ()):
                    ent = out[idx]
                    ex = ent[0]
                    ez = ent[1]
                    if (x - ex) * (x - ex) + (z - ez) * (z - ez) <= r2:
                        c = ent[5]
                        ent[0] = round((ex * c + x) / (c + 1))
                        ent[1] = round((ez * c + z) / (c + 1))
                        ent[2] = round((ent[2] * c + y) / (c + 1))
                        ent[5] = c + 1
                        if collect_tags and tag:
                            tags_out[idx].add(tag)
                        placed = True
                        break
                if placed:
                    break
            if placed:
                break
        if not placed:
            new_idx = len(out)
            ent = [x, z, y, lyr, nidx, 1, 0]
            out.append(ent)
            if collect_tags:
                tags_out.append({tag} if tag else set())
            buckets.setdefault((lyr, nidx, gx, gz), []).append(new_idx)

    # Pré-calcula índices para lookup de região nas Profundezas
    lr_coords = [
        (idx, lr["position"]["x"], lr["position"]["z"], float(lr.get("reveal_radius", 560)) ** 2)
        for idx, lr in enumerate(lightroots)
    ]
    for ent in out:
        x, z, _, lyr, _, _, _ = ent
        if lyr == 2:
            best_idx = -1
            best_d2 = float("inf")
            for idx, lx, lz, rad2 in lr_coords:
                d2 = (x - lx) ** 2 + (z - lz) ** 2
                if d2 <= rad2 and d2 < best_d2:
                    best_d2 = d2
                    best_idx = idx
            ent[6] = best_idx
        else:
            ent[6] = region_lookup(x, z)
    return (out, tags_out) if collect_tags else out


def _build_map_data(
    romfs: Romfs,
    mals: dict[str, bytes],
    gd: dict[str, Any],
    pouch_rows: list[dict[str, Any]],
    quests_data: dict[str, Any] | None = None,
    lang: str = "USen",
) -> tuple[dict[str, Any], dict[str, Any], dict[str, list[dict[str, Any]]]]:
    _set_status(step="map", progress=0, total=100, message="Extraindo locais, lojas, santuários, koroks e baús...")

    def msgs(name: str) -> dict[str, str]:
        f = f"{name}.msbt"
        return parse_msbt(mals[f]) if f in mals else {}

    names = {**msgs("LocationMsg/Location"), **msgs("LocationMsg/Dungeon")}
    npcs = msgs("ActorMsg/Npc")
    items_msg = msgs("ActorMsg/PouchContent")
    attach_msg = msgs("ActorMsg/Attachment")
    drafts = msgs("ActorMsg/AutoBuilderDraft")
    pb_msg = msgs("ActorMsg/PictureBook")
    bosses_msg = {**pb_msg, **msgs("ActorMsg/Boss")}
    bool_flags = {x["Hash"] for x in (gd.get("Bool") or [])}

    pouch_by_id = {r["__RowId"]: r for r in pouch_rows if r.get("__RowId")}
    pouch_ids = set(pouch_by_id.keys())
    icon_set = {p.rsplit("/", 1)[-1].split(".")[0] for p in romfs.find("UI/Tex/Icon/", ".bntx.zs")}

    non_main_givers: dict[str, list[dict[str, Any]]] = {}
    giver_fallback_name: dict[str, str] = {}
    for q in ((quests_data or {}).get("quests") or []):
        ga = q.get("giver_actor") or ""
        if not ga:
            continue
        if q.get("giver") and ga not in giver_fallback_name:
            giver_fallback_name[ga] = q["giver"]
        if q.get("category") != "main_quest":
            non_main_givers.setdefault(ga, []).append(
                {"id": q["id"], "pts": (q.get("start") or {}).get("points") or []}
            )

    loc_rsdb_path = _pick_latest_product(romfs, "RSDB/Location.Product.", ".byml.zs")
    loc_rsdb_rows = parse_byml(romfs.read(loc_rsdb_path)) or [] if loc_rsdb_path else []
    loc_rsdb_map: dict[str, dict[str, Any]] = {}
    dep_hash_to_base: dict[int, str] = {}
    for row in loc_rsdb_rows:
        rid = row.get("__RowId") or ""
        base = _basename(rid)
        if base:
            loc_rsdb_map[base] = row
            dep_hash_to_base[mmh3(base)] = base

    def resolve_shop_flag(loc_name: str, row: dict[str, Any]) -> tuple[int, str]:
        dep = dep_hash_to_base.get(row.get("DependenceLocationHash") or 0, "")
        beg_island = names.get("BeginningIsland") or names.get("HyruleSkyIsland") or _ltxt(lang, "Great Sky Island", "Grande Ilha Celeste")
        sub_label = names.get(dep, "") if dep else (beg_island if loc_name.endswith("_00") else "")
        ov_hash = row.get("OverrideIconFlagHash")
        if ov_hash and ov_hash in bool_flags:
            return int(ov_hash), sub_label
        if loc_name.startswith("DemonStatue_"):
            return mmh3(f"IsVisitLocation.{loc_name}"), sub_label
        if dep and not dep.startswith("Tower"):
            dep_visit = mmh3(f"IsVisitLocation.{dep}")
            if dep_visit in bool_flags:
                return dep_visit, sub_label
        visit_self = mmh3(f"IsVisitLocation.{loc_name}")
        if visit_self in bool_flags:
            return visit_self, sub_label
        if dep.startswith("Tower"):
            return mmh3(f"IsOpenCannon.{dep}"), sub_label
        return mmh3("IsVisitLocation.BeginningIsland"), sub_label

    def resolve_drop_name(actor: str) -> str:
        if not actor:
            return ""
        parts = actor.split("_")
        while parts:
            key = "_".join(parts) + "_Name"
            if key in items_msg:
                return items_msg[key]
            parts.pop()
        return actor

    data: dict[str, Any] = {
        k: []
        for k in (
            "shrines",
            "lightroots",
            "shops",
            "stables",
            "hidden_koroks",
            "carry_koroks",
            "bubbuls",
            "locations",
            "caves",
            "wells",
            "chasms",
            "skyview_towers",
            "great_fairies",
            "hinoxes",
            "taluses",
            "moldugas",
            "flux_constructs",
            "froxes",
            "gleeoks",
            "lynels",
            "old_maps",
            "sages_wills",
            "addison_signposts",
            "schema_stones",
            "yiga_schematics",
            "dragon_tears",
            "armor_chests",
            "treasure_chests",
            "dispensers",
        )
    }
    data["region_masks"] = [
        {
            "id": tname,
            "x0": -6000 + c0 * 1000,
            "z0": -5000 + r0 * 1000,
            "w": tw * 1000,
            "h": th * 1000,
        }
        for tname, (c0, r0, tw, th) in sorted(OPEN_MASK_BOUNDS.items())
    ]

    places: dict[str, list[float]] = {}
    tear_areas: dict[str, tuple[str, list[float]]] = {}
    shop_names_added: set[str] = set()

    for field in ("MainField", "MinusField"):
        la = parse_byml(romfs.read(f"Banc/{field}/LocationArea/{field}.locationarea.byml.zs")) or {}
        for cat, entries in la.items():
            for e in entries:
                name = _basename(e.get("LocationName"))
                trans = e.get("Trans") or []
                if not trans:
                    continue
                places[name] = trans[0]
                display = names.get(name, name)
                y0 = float(trans[0][1])
                if cat == "Shrine":
                    data["shrines"].append(
                        {
                            "internal_name": name,
                            "display_name": display,
                            "completion_hash": mmh3(f"DungeonState.{name}"),
                            "position": _pos(trans[0]),
                            "layer": "sky" if y0 > 680.0 else "surface",
                        }
                    )
                elif cat == "CheckPoint":
                    data["lightroots"].append(
                        {
                            "internal_name": name,
                            "display_name": display,
                            "completion_hash": mmh3(f"ArrivalPointState.{name}"),
                            "position": _pos(trans[0]),
                            "layer": "depths",
                        }
                    )
                elif cat in ("CaveEntranceNormal", "CaveEntranceSpecial", "CaveEntranceWell"):
                    key = {"CaveEntranceNormal": "caves", "CaveEntranceSpecial": "chasms", "CaveEntranceWell": "wells"}[cat]
                    if key == "caves" and name.startswith("DeepHole"):
                        key = "chasms"
                    for t in trans:
                        data[key].append(
                            {
                                "internal_name": name,
                                "display_name": display,
                                "completion_hash": mmh3(f"IsVisitLocation.{name}"),
                                "position": _pos(t),
                                "layer": "surface",
                            }
                        )
                    markers = e.get("CaveMarkerInfo") or []
                    if markers and not any(b["internal_name"] == name for b in data["bubbuls"]):
                        data["bubbuls"].append(
                            {
                                "internal_name": name,
                                "display_name": display,
                                "completion_hash": mmh3(f"IsGetCaveMasterMedal.{name}"),
                                "position": _pos(markers[0]["Trans"]),
                                "layer": "surface",
                            }
                        )
                elif cat == "Tower":
                    data["skyview_towers"].append(
                        {
                            "internal_name": name,
                            "display_name": display,
                            "completion_hash": mmh3(f"IsOpenCannon.{name}"),
                            "position": _pos(trans[0]),
                            "layer": "surface",
                        }
                    )
                elif cat in SHOP_CATEGORY_ICONS:
                    row = loc_rsdb_map.get(name, {})
                    comp_hash, sub_label = resolve_shop_flag(name, row)
                    icon = SHOP_CATEGORY_ICONS[cat]
                    lyr = "depths" if field == "MinusField" else ("sky" if y0 > 680.0 else "surface")
                    shop_names_added.add(name)
                    for t in trans:
                        data["shops"].append(
                            {
                                "internal_name": name,
                                "display_name": display,
                                "sub_label": sub_label if sub_label != display else "",
                                "icon": icon,
                                "completion_hash": comp_hash,
                                "position": _pos(t),
                                "layer": lyr,
                            }
                        )
                elif cat == "Stable":
                    data["stables"].append(
                        {
                            "internal_name": name,
                            "display_name": display,
                            "icon": "stable",
                            "completion_hash": mmh3(f"IsVisitLocation.{name}"),
                            "position": _pos(trans[0]),
                            "layer": "surface",
                        }
                    )
                elif cat == "DragonTears":
                    fallback = (
                        _ltxt(lang, f"Dragon's Tear {int(name[-2:])}", f"Lágrima do Dragão {int(name[-2:])}")
                        if name[-2:].isdigit()
                        else display
                    )
                    tear_areas[name] = (names.get(name) or fallback, trans[0])
                else:
                    row = loc_rsdb_map.get(name, {})
                    oit = row.get("OverrideIconType") or ""
                    if oit in SPECIAL_SHOP_ICONS:
                        comp_hash, sub_label = resolve_shop_flag(name, row)
                        lyr = "depths" if field == "MinusField" else ("sky" if float(trans[0][1]) > 680.0 else "surface")
                        shop_names_added.add(name)
                        for t in trans:
                            data["shops"].append(
                                {
                                    "internal_name": name,
                                    "display_name": display,
                                    "sub_label": sub_label if sub_label != display else "",
                                    "icon": SPECIAL_SHOP_ICONS[oit],
                                    "completion_hash": comp_hash,
                                    "position": _pos(t),
                                    "layer": lyr,
                                }
                            )
                    elif PLACE_CATEGORIES.match(cat):
                        if cat == "SkyArchipelago":
                            lyr = "sky"
                        elif field == "MinusField":
                            lyr = "depths"
                        else:
                            lyr = "sky" if y0 > 680.0 else "surface"
                        data["locations"].append(
                            {
                                "internal_name": name,
                                "display_name": display,
                                "completion_hash": mmh3(f"IsVisitLocation.{name}"),
                                "position": _pos(trans[0]),
                                "layer": lyr,
                            }
                        )

        rb = parse_byml(romfs.read(f"Banc/{field}/RecycleBox/{field}.recyclebox.byml.zs")) or {}
        for iid, e in rb.items():
            y = float(e["Trans"][1])
            cids = [c for c in (e.get("Contents") or [])]
            data["dispensers"].append(
                {
                    "display_name": _ltxt(lang, "Zonai Dispenser", "Dispensador Zonai"),
                    "completion_hash": mmh3(f"RecycleBoxData.{iid}.IsVisit"),
                    "position": _pos(e["Trans"]),
                    "contents": [items_msg.get(f"{c}_Name", c) for c in cids],
                    "content_ids": cids,
                    "layer": "depths" if field == "MinusField" else ("sky" if y > 680.0 else "surface"),
                }
            )

    # Calcula raio adaptativo para cada Raiz Luminosa baseado na distância às 3 vizinhas mais próximas
    lr_list = data["lightroots"]
    for i, lr in enumerate(lr_list):
        px, pz = lr["position"]["x"], lr["position"]["z"]
        dists = sorted(
            math.hypot(px - other["position"]["x"], pz - other["position"]["z"])
            for j, other in enumerate(lr_list)
            if j != i
        )
        avg3 = sum(dists[:3]) / max(min(len(dists), 3), 1) if dists else 700.0
        lr["reveal_radius"] = int(max(440.0, min(760.0, round(avg3 * 0.78))))

    _set_status(progress=15, message="Lendo arquivos de posicionamento (Banc)...")
    hk = parse_byml(romfs.read("Banc/MainField/HiddenKorok/MainField.hiddenkorok.byml.zs"))

    treasure_maps: dict[str, str] = {}
    for row in pouch_rows:
        if row.get("TreasureMapContent"):
            treasure_maps[row["__RowId"]] = _basename(row["TreasureMapContent"])

    banc_paths = [p for p in romfs.find("Banc/") if BANC_RE.match(p)]

    korok_kind: dict[int, tuple[str, int | None]] = {}
    seen: set[int] = set()
    entity_seen: set[int] = set()
    flowers: list[tuple[list[float], int | None]] = []
    start_blocks: list[list[float]] = []
    landing_blocks: list[list[float]] = []
    vine_pots: list[list[float]] = []
    carry: dict[int, tuple[str, list[float], list[int]]] = {}
    markers: dict[str, tuple[list[float], str]] = {}
    frogs: dict[str, list[float]] = {}
    tears: list[list[float]] = []
    fairies: dict[str, list[float]] = {}

    name_table: list[str] = []
    name_to_idx: dict[str, int] = {}
    resolved_cache: dict[tuple[str, str], int] = {}
    raw_npcs: list[tuple[int, int, int, int, int, str]] = []
    raw_animals: list[tuple[int, int, int, int, int]] = []
    raw_plants: list[tuple[int, int, int, int, int]] = []
    raw_monsters: list[tuple[int, int, int, int, int]] = []
    forsale_actors: list[tuple[str, list[float], str]] = []
    chest_drops: dict[str, list[dict[str, Any]]] = {}
    layer_idx_map = {"surface": 0, "sky": 1, "depths": 2}

    def add_chest_drop(raw_actor: str, kind_label: str, pos_t: list[float], lyr: str) -> None:
        if not raw_actor:
            return
        cid, _ = _canonical_item_id(raw_actor, pouch_ids)
        if cid in pouch_ids:
            chest_drops.setdefault(cid, []).append(
                {"kind": kind_label, "x": round(float(pos_t[0])), "z": round(float(pos_t[2])), "layer": lyr}
            )

    def get_name_idx(cat_kind: str, g: str) -> int:
        ck = (cat_kind, g)
        if ck in resolved_cache:
            return resolved_cache[ck]
        if cat_kind == "npc":
            label = _resolve_npc_name(g, npcs) or giver_fallback_name.get(g, "")
        elif cat_kind == "animal":
            label = _resolve_animal_name(g, pb_msg, items_msg)
        elif cat_kind == "plant":
            label = _resolve_plant_name(g, items_msg, pb_msg)
        else:
            label = _resolve_monster_name(g, bosses_msg)
        if not label:
            resolved_cache[ck] = -1
            return -1
        idx = name_to_idx.get(label)
        if idx is None:
            idx = len(name_table)
            name_table.append(label)
            name_to_idx[label] = idx
        resolved_cache[ck] = idx
        return idx

    def parse_banc_file(path: str) -> tuple[str, list[dict[str, Any]]]:
        doc = parse_byml(romfs.read(path)) or {}
        return path, doc.get("Actors") or []

    total_banc = max(len(banc_paths), 1)
    done_banc = 0
    with ThreadPoolExecutor(max_workers=8) as ex:
        for path, actors in ex.map(parse_banc_file, banc_paths):
            done_banc += 1
            if done_banc % 200 == 0 or done_banc == total_banc:
                _set_status(
                    progress=15 + int(75 * done_banc / total_banc),
                    message=f"Lendo mapa, lojas e entidades ({done_banc}/{total_banc})...",
                )
            for a in actors:
                g = a.get("Gyaml") or ""
                h = a.get("Hash")
                t = a.get("Translate")
                if not h or not t or h in seen:
                    continue
                layer = _infer_banc_layer(path, float(t[1]))
                dyn = a.get("Dynamic") or {}

                if g in KOROK_ACTORS:
                    korok_kind[h] = (g, dyn.get("HideType"))
                elif g == "Obj_Plant_Korok_A_01":
                    flowers.append((t, dyn.get("TrackingFlowerType")))
                elif g.startswith("Enemy_CaveMaster"):
                    frogs.setdefault(dyn.get("LocationName", ""), t)
                elif g == "LocationMarker":
                    loc = dyn.get("Location", "")
                    if MARKER_PLACES.match(loc):
                        markers.setdefault(loc, (t, layer))
                elif g == "FldObj_KorokStartingBlock_A_01":
                    start_blocks.append(t)
                elif g == "FldObj_KorokGoalBlock_A_02":
                    landing_blocks.append(t)
                elif g == "Obj_KorokPotFixedVine_A_01":
                    vine_pots.append(t)
                elif g in ("KorokCarryPassenger_Pair", "KorokCarry_Destination"):
                    links = [l["Dst"] for l in (a.get("Links") or []) if l.get("Dst")]
                    carry[h] = (g, t, links)
                elif g == "FldObj_DragonTears_01":
                    tears.append(t)
                elif re.match(r"Npc_DressFairy_\d\d$", g):
                    fairies.setdefault(g, t)

                handled_special = False
                if g.startswith("Enemy_Lynel"):
                    seen.add(h)
                    handled_special = True
                    bname = bosses_msg.get(f"{g.replace('_Boss', '')}_Name") or _ltxt(lang, "Lynel", "Centaleão")
                    data["lynels"].append({"display_name": bname, "position": _pos(t), "layer": layer})
                elif g.startswith("Enemy_"):
                    kind = g.split("_")[1]
                    bflag = mmh3(f"IsDefeatBossEnemy.{h}")
                    if kind in BOSS_PREFIXES and bflag in bool_flags:
                        seen.add(h)
                        handled_special = True
                        bkey = BOSS_PREFIXES[kind]
                        bname = bosses_msg.get(f"{g}_Name") or g.replace("Enemy_", "").replace("_", " ")
                        data[bkey].append(
                            {"display_name": bname, "completion_hash": bflag, "position": _pos(t), "layer": layer}
                        )
                elif g == "Npc_CraftSignboard001":
                    seen.add(h)
                    handled_special = True
                    data["addison_signposts"].append(
                        {
                            "guid": str(h),
                            "display_name": _ltxt(lang, "Hudson Sign (Addison)", "Placa do Hudson (Addison)"),
                            "position": _pos(t),
                            "layer": layer,
                        }
                    )
                elif g.startswith("TBox_"):
                    handled_special = True
                    drop = dyn.get("Drop__DropActor") or ""
                    sage_lbl = items_msg.get("Obj_SageWill_Name") or _ltxt(lang, "Sage's Will", "Vontade de Sábio")
                    if drop == "Obj_SageWill":
                        seen.add(h)
                        add_chest_drop(drop, sage_lbl, t, layer)
                        data["sages_wills"].append(
                            {
                                "guid": str(h),
                                "display_name": sage_lbl,
                                "position": _pos(t),
                                "layer": layer,
                            }
                        )
                    elif drop in treasure_maps:
                        seen.add(h)
                        omap_lbl = items_msg.get("Obj_TreasureMap_Name") or _ltxt(lang, "Old Map", "Mapa antigo")
                        add_chest_drop(drop, omap_lbl, t, layer)
                        armor_id = treasure_maps[drop]
                        armor_name = resolve_drop_name(armor_id)
                        data["old_maps"].append(
                            {
                                "completion_hash": mmh3(f"IsFindTreasureMap.{armor_id}"),
                                "display_name": f"{omap_lbl} ({armor_name})" if armor_name else f"{omap_lbl} ({drop[-2:]})",
                                "position": _pos(t),
                                "layer": layer,
                            }
                        )
                    elif drop.startswith("Obj_AutoBuilderDraftAssassin_"):
                        seen.add(h)
                        yiga_lbl = _ltxt(lang, "Yiga Schematic", "Esquema Yiga")
                        add_chest_drop(drop, yiga_lbl, t, layer)
                        data["yiga_schematics"].append(
                            {
                                "completion_hash": mmh3(f"ReadyMadeAutoBuilderDraft.{drop}.IsOwned"),
                                "display_name": drafts.get(f"{drop}_Name") or yiga_lbl,
                                "position": _pos(t),
                                "layer": layer,
                            }
                        )
                    else:
                        seen.add(h)
                        key = "armor_chests" if drop.startswith("Armor_") else "treasure_chests"
                        fallback = _ltxt(lang, "Armor", "Armadura") if key == "armor_chests" else _ltxt(lang, "Treasure Chest", "Baú do Tesouro")
                        kind_lbl = _ltxt(lang, "Armor Chest", "Baú de Armadura") if key == "armor_chests" else _ltxt(lang, "Treasure Chest", "Baú do Tesouro")
                        add_chest_drop(drop, kind_lbl, t, layer)
                        data[key].append(
                            {
                                "guid": str(h),
                                "display_name": resolve_drop_name(drop) or fallback,
                                "position": _pos(t),
                                "layer": layer,
                            }
                        )

                for lk in (a.get("Links") or []):
                    if lk.get("Name") == "ForSale" or lk.get("Gyaml") == "ForSale":
                        fs_id = dyn.get("EquipArmorName1") or g
                        if fs_id:
                            forsale_actors.append((fs_id, t, layer))
                        break

                if handled_special or h in entity_seen:
                    continue

                if g.startswith("Npc_") or (g in non_main_givers and g.startswith(("NPC_", "subchallnpc"))):
                    nidx = get_name_idx("npc", g)
                    if nidx >= 0:
                        entity_seen.add(h)
                        raw_npcs.append((round(t[0]), round(t[2]), round(t[1]), layer_idx_map[layer], nidx, g))
                elif g.startswith(("Animal_", "GameRomHorse")):
                    nidx = get_name_idx("animal", g)
                    if nidx >= 0:
                        entity_seen.add(h)
                        raw_animals.append((round(t[0]), round(t[2]), round(t[1]), layer_idx_map[layer], nidx))
                elif g.startswith("Enemy_"):
                    nidx = get_name_idx("monster", g)
                    if nidx >= 0:
                        entity_seen.add(h)
                        raw_monsters.append((round(t[0]), round(t[2]), round(t[1]), layer_idx_map[layer], nidx))
                elif g.startswith(("Item_Plant_", "Item_Fruit_", "Item_Mushroom_")) or g in GATHER_FRUITS:
                    nidx = get_name_idx("plant", g)
                    if nidx >= 0:
                        entity_seen.add(h)
                        raw_plants.append((round(t[0]), round(t[2]), round(t[1]), layer_idx_map[layer], nidx))

    # Koroks
    trails = _flower_trails(flowers)
    pairs = _carry_routes(carry)
    for hk_group, entries in hk.items():
        is_carry = hk_group == "CarryKorok"
        for iid, t in entries.items():
            h = int(iid)
            _, hide = korok_kind.get(h, ("", None))
            layer = "sky" if float(t[1]) > 680.0 else "surface"
            if not is_carry:
                hide_map = HIDE_TYPES_PT if lang == "USpt" else HIDE_TYPES_EN
                puzzle = hide_map.get(hide, _ltxt(lang, "Other", "Outro"))
                if hide == 10 and _nearest(vine_pots, t, 30):
                    puzzle = _ltxt(lang, "Acorn in hole", "Bolota no buraco")
                o: dict[str, Any] = {
                    "completion_hash": mmh3(f"IsAppearKorok.{iid}"),
                    "display_name": f"Korok ({puzzle})",
                    "position": _pos(t),
                    "puzzle_type": puzzle,
                    "layer": layer,
                }
                if hide == 3 and trails:
                    end = min(trails, key=lambda tr: _dist(tr[-1], t))
                    if _dist(end[-1], t) < 35:
                        o["path"] = {"trail": [_pos(p) for p in end]}
                elif hide == 4 and start_blocks:
                    start = _nearest(start_blocks, t, 250)
                    if start:
                        o["path"] = {"start": _pos(start), "end": _pos(t)}
                elif hide == 11 and start_blocks and landing_blocks:
                    start = _nearest(start_blocks, t, 250)
                    land = _nearest(landing_blocks, t, 80)
                    if start and land:
                        o["path"] = {"start": _pos(start), "end": _pos(land)}
                data["hidden_koroks"].append(o)
            else:
                o = {
                    "completion_hash": mmh3(f"KorokCarryProgress.{iid}"),
                    "display_name": _ltxt(lang, "Korok Pair", "Dupla de Koroks"),
                    "position": _pos(t),
                    "puzzle_type": _ltxt(lang, "Carry to friend", "Levar ao amigo"),
                    "layer": layer,
                }
                pair = min(pairs, key=lambda p: _dist(p[1], t)) if pairs else None
                if pair and _dist(pair[1], t) < 5:
                    o["path"] = {"start": _pos(pair[0]), "end": _pos(t)}
                data["carry_koroks"].append(o)

    known_bubbuls = {o["internal_name"] for o in data["bubbuls"]}
    for loc, t in sorted(frogs.items()):
        flag = mmh3(f"IsGetCaveMasterMedal.{loc}")
        if loc and loc not in known_bubbuls and flag in bool_flags:
            data["bubbuls"].append(
                {
                    "internal_name": loc,
                    "display_name": names.get(loc, loc),
                    "completion_hash": flag,
                    "position": _pos(t),
                    "layer": "surface",
                }
            )

    shown_locs = {o["completion_hash"] for o in data["locations"]}
    for loc, (t, layer) in sorted(markers.items()):
        if loc in shop_names_added:
            continue
        flag = mmh3(f"IsVisitLocation.{loc}")
        if flag in bool_flags and flag not in shown_locs:
            data["locations"].append(
                {
                    "internal_name": loc,
                    "display_name": names.get(loc, loc),
                    "completion_hash": flag,
                    "position": _pos(t),
                    "layer": layer,
                }
            )

    for name, (display, t) in sorted(tear_areas.items()):
        flag = mmh3(f"Complete_{name}")
        if flag in bool_flags:
            spot = _nearest(tears, t, 600) or t
            data["dragon_tears"].append(
                {
                    "internal_name": name,
                    "display_name": display,
                    "completion_hash": flag,
                    "position": _pos(spot),
                    "layer": "surface",
                }
            )

    for g, t in sorted(fairies.items()):
        flag = mmh3(f"IsAppear_{g[4:]}")
        if flag in bool_flags:
            data["great_fairies"].append(
                {
                    "display_name": npcs.get(f"{g}_Name") or _ltxt(lang, "Great Fairy", "Grande Fada"),
                    "completion_hash": flag,
                    "position": _pos(t),
                    "layer": "surface",
                }
            )

    for draft, site in SCHEMA_SITES.items():
        if site in places:
            t = places[site]
            data["schema_stones"].append(
                {
                    "completion_hash": mmh3(f"ReadyMadeAutoBuilderDraft.{draft}.IsOwned"),
                    "display_name": drafts.get(f"{draft}_Name") or draft,
                    "position": _pos(t),
                    "layer": "depths",
                }
            )

    _set_status(progress=92, message="Processando estoque de lojas, missões de NPCs e entidades...")

    # 1) Inventário das lojas físicas via links ForSale (filtrando categoria de loja para não cruzar vizinhas)
    cur_zonaite = items_msg.get("Item_Ore_L_Name") or "Zonaite"
    cur_large_zonaite = items_msg.get("Item_Ore_M_Name") or _ltxt(lang, "Large Zonaite", "Zonaíta grande")
    cur_poe = items_msg.get("MinusRupee_00_Name") or "Poes"
    cur_crystal = items_msg.get("Energy_Material_01_Name") or _ltxt(lang, "Crystallized Charge", "Cristal energético")
    smelt_prices: dict[str, tuple[int, str]] = {
        "Energy_Material_02": (3, cur_zonaite),
        "Energy_Material_03": (3, cur_large_zonaite),
        "Item_Enemy_130": (3, cur_zonaite),
        "Item_Enemy_131": (3, cur_large_zonaite),
    }
    shops_list: list[dict[str, Any]] = data["shops"]
    shop_seen_goods: list[set[tuple[str, int]]] = [set() for _ in shops_list]

    def append_shop_good(sidx: int, raw_actor: str, bundle_override: int | None = None, price_override: int | None = None, currency: str = "Rupees") -> None:
        raw_clean = raw_actor.removesuffix("_forDisplay").removesuffix("_Static")
        canon_id, bundle = _canonical_item_id(raw_actor, pouch_ids)
        if bundle_override is not None:
            bundle = bundle_override
        if not canon_id:
            return
        key = (canon_id, bundle)
        if key in shop_seen_goods[sidx]:
            return
        shop_seen_goods[sidx].add(key)

        row_raw = pouch_by_id.get(raw_clean) or pouch_by_id.get(canon_id) or {}
        row_can = pouch_by_id.get(canon_id) or row_raw
        nm, _ = _resolve_item_name_caption(canon_id, items_msg, pb_msg, attach_msg, lang=lang)
        if price_override is not None:
            price = int(price_override)
        else:
            raw_buy = row_raw.get("BuyingPrice")
            if raw_buy is not None and int(raw_buy) > 0:
                price = int(raw_buy)
            else:
                price = int(row_can.get("BuyingPrice") or 0) * bundle
        shops_list[sidx].setdefault("goods", []).append(
            {
                "id": canon_id,
                "name": nm,
                "icon": _resolve_item_icon_name(canon_id, icon_set),
                "price": price,
                "currency": currency,
                "bundle": bundle,
            }
        )

    for fs_actor, t_fs, lyr_fs in forsale_actors:
        is_armor = fs_actor.startswith("Armor_")
        allowed_icons = ("shop_armor", "shop_jewelry") if is_armor else ("shop_general", "shop_energy", "shop_milk", "shop_etc", "shop_inn")
        best_sidx = -1
        best_d2 = 35.0 * 35.0
        for sidx, sh in enumerate(shops_list):
            if sh.get("layer") != lyr_fs or sh.get("icon") not in allowed_icons:
                continue
            max_r = 45.0 if sh.get("internal_name", "").startswith("SmeltShopGolem") else 35.0
            d2 = (sh["position"]["x"] - float(t_fs[0])) ** 2 + (sh["position"]["z"] - float(t_fs[2])) ** 2
            if d2 <= max_r * max_r and d2 < best_d2:
                best_d2 = d2
                best_sidx = sidx
        if best_sidx >= 0:
            sh = shops_list[best_sidx]
            canon_tmp, _ = _canonical_item_id(fs_actor, pouch_ids)
            if sh.get("internal_name", "").startswith("SmeltShopGolem") and canon_tmp in smelt_prices:
                pr, cur = smelt_prices[canon_tmp]
                append_shop_good(best_sidx, fs_actor, price_override=pr, currency=cur)
            else:
                append_shop_good(best_sidx, fs_actor)

    # 2) Inventário de lojas via ShopParam dentro de Pack/Actor/
    def load_shop_param(pack_path: str, sub_path: str) -> list[dict[str, Any]]:
        if not romfs.exists(pack_path):
            return []
        sarc = parse_sarc(romfs.read(pack_path))
        raw = sarc.get(sub_path)
        return (parse_byml(raw) or {}).get("GoodsList") or [] if raw else []

    demon_goods = load_shop_param("Pack/Actor/TwnObj_DemonStatue_C_01.pack.zs", "Component/ShopParam/DemonStatue_Shop.game__component__ShopParam.bgyml")
    battery_goods = load_shop_param("Pack/Actor/Npc_Zonau_Golem_Servant_BaseCamp_01.pack.zs", "Component/ShopParam/TwnObj_BatteryExchange_A_01.game__component__ShopParam.bgyml")
    hateno_armor_goods = (
        load_shop_param("Pack/Actor/Npc_HatenoVillage019.pack.zs", "Component/ShopParam/Npc_HatenoVillage019.game__component__ShopParam.bgyml")
        + load_shop_param("Pack/Actor/Npc_HatenoVillage019_SisterA.pack.zs", "Component/ShopParam/Npc_HatenoVillage019_SisterA.game__component__ShopParam.bgyml")
    )

    def apply_goods_list(sidx: int, glist: list[dict[str, Any]], default_currency: str = "Rupees") -> None:
        for entry in glist:
            act = _basename(entry.get("Actor"))
            if not act:
                continue
            canon_id, bundle = _canonical_item_id(act, pouch_ids)
            row_can = pouch_by_id.get(canon_id) or {}
            pay_list = entry.get("PaymentList") or []
            if pay_list:
                currency = cur_crystal
                price = int(pay_list[0].get("Num") or 3)
            else:
                cur_raw = entry.get("Currency")
                currency = cur_poe if cur_raw == "MinusRupee" else default_currency
                base_buy = int(row_can.get("BuyingPrice") or 0)
                offset = int(entry.get("PriceOffset") or 0)
                price = max(1, base_buy + offset) if (base_buy or offset) else 0
            append_shop_good(sidx, act, bundle_override=bundle, price_override=price, currency=currency)

    for sidx, sh in enumerate(shops_list):
        iname = sh.get("internal_name") or ""
        if iname.startswith("DemonStatue_") or iname == "SmallDemonStatue":
            apply_goods_list(sidx, demon_goods, default_currency=cur_poe)
        elif iname.startswith("BatteryExchangeShop_"):
            apply_goods_list(sidx, battery_goods, default_currency=cur_crystal)
        elif iname == "ShopArmor_Hateno":
            apply_goods_list(sidx, hateno_armor_goods, default_currency="Rupees")
        if sh.get("goods"):
            sh["goods"].sort(key=lambda g: (g["price"], g["name"]))

    masks_lookup = _load_region_masks_lookup(romfs)

    def region_lookup(x: float, z: float) -> int:
        best_id = 0
        best_a = 0
        for reg_id, x0, z0, w_m, h_m, pw, ph, buf in masks_lookup:
            if x0 <= x < x0 + w_m and z0 <= z < z0 + h_m:
                px = min(pw - 1, max(0, int((x - x0) / w_m * pw)))
                py = min(ph - 1, max(0, int((z - z0) / h_m * ph)))
                a = buf[py * pw + px]
                if a > best_a and a > 96:
                    best_a = a
                    best_id = reg_id
        return best_id

    clustered_npcs, npc_tags = _cluster_entities(raw_npcs, 8.0, region_lookup, lr_list, collect_tags=True)
    actor_to_npc_clusters: dict[str, list[int]] = {}
    for cidx, tag_set in enumerate(npc_tags):
        for ga in tag_set:
            actor_to_npc_clusters.setdefault(ga, []).append(cidx)

    npc_quests: dict[str, list[str]] = {}
    for ga, qlist in non_main_givers.items():
        cands = actor_to_npc_clusters.get(ga) or []
        if not cands:
            continue
        for qinfo in qlist:
            qid = qinfo["id"]
            pts = qinfo.get("pts") or []
            chosen = cands
            if len(cands) > 1 and pts:
                q_lyr_idx = 2 if float(pts[0][1]) < -220.0 else (1 if float(pts[0][1]) > 680.0 else 0)
                same_lyr = [c for c in cands if clustered_npcs[c][3] == q_lyr_idx] or cands
                best_c = min(
                    same_lyr,
                    key=lambda c: min((clustered_npcs[c][0] - p[0]) ** 2 + (clustered_npcs[c][1] - p[2]) ** 2 for p in pts),
                )
                min_d2 = min((clustered_npcs[best_c][0] - p[0]) ** 2 + (clustered_npcs[best_c][1] - p[2]) ** 2 for p in pts)
                if min_d2 <= 160.0 * 160.0:
                    chosen = [best_c]
            for cidx in chosen:
                arr = npc_quests.setdefault(str(cidx), [])
                if qid not in arr:
                    arr.append(qid)

    entities = {
        "names": name_table,
        "npcs": clustered_npcs,
        "npc_quests": npc_quests,
        "animals": _cluster_entities(raw_animals, 2.0, region_lookup, lr_list),
        "plants": _cluster_entities(raw_plants, 5.0, region_lookup, lr_list),
        "monsters": _cluster_entities(raw_monsters, 2.0, region_lookup, lr_list),
    }
    _write_json_atomic(ENTITIES_PATH, entities)
    _write_json_atomic(MAP_DATA_PATH, data)
    return data, entities, chest_drops


def _extract_points(dest: Any) -> list[list[float]]:
    found: list[list[float]] = []

    def walk(o: Any) -> None:
        if isinstance(o, dict):
            if {"X", "Y", "Z"} <= o.keys():
                found.append([round(float(o["X"]), 1), round(float(o["Y"]), 1), round(float(o["Z"]), 1)])
                return
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(dest)
    uniq: list[list[float]] = []
    for p in found:
        if p not in uniq:
            uniq.append(p)
    return uniq


def _build_quests_data(romfs: Romfs, mals: dict[str, bytes], gd: dict[str, Any]) -> dict[str, Any]:
    _set_status(step="quests", progress=0, total=100, message="Extraindo diário de aventuras e missões (PT-BR)...")
    challenge_path = _pick_latest_product(romfs, "RSDB/Challenge.Product.", ".rstbl.byml.zs")
    rows = (parse_byml(romfs.read(challenge_path)) or []) if challenge_path else []

    def msgs(name: str) -> dict[str, str]:
        f = f"{name}.msbt"
        return parse_msbt(mals[f]) if f in mals else {}

    npc_names = msgs("ActorMsg/Npc")
    loc_names = {**msgs("LocationMsg/Location"), **msgs("LocationMsg/Dungeon")}

    bool_def = {x["Hash"]: int(bool(x.get("DefaultValue", 0))) for x in (gd.get("Bool") or [])}
    enum_def = {x["Hash"]: {"order": list(x["Values"]), "default": x.get("DefaultValue")} for x in (gd.get("Enum") or [])}
    exp_def = {x["Hash"]: [list(i) for i in x["Values"]] for x in (gd.get("BoolExp") or [])}
    step_enum_to_quest = {mmh3(f"Step_{_basename(r['__RowId'])}"): _basename(r["__RowId"]) for r in rows}
    logic: dict[str, dict[str, Any]] = {"exprs": {}, "bools": {}, "enums": {}}

    def collect(h: int, seen_quests: set[str]) -> None:
        if str(h) in logic["exprs"] or h not in exp_def:
            return
        prog = exp_def[h]
        logic["exprs"][str(h)] = prog
        for ins in prog:
            op = ins[0]
            arg = ins[1] if len(ins) > 1 else None
            if op == 0 and arg in bool_def:
                logic["bools"][str(arg)] = bool_def[arg]
            elif op in (1, 12) and arg in enum_def:
                logic["enums"][str(arg)] = enum_def[arg]
                if arg in step_enum_to_quest:
                    seen_quests.add(step_enum_to_quest[arg])
            elif op == 10 and arg is not None:
                collect(arg, seen_quests)

    def requirement(flag_name: str) -> dict[str, Any]:
        h = mmh3(flag_name)
        needs: set[str] = set()
        if h in exp_def:
            collect(h, needs)
            stack, seen = [h], set()
            while stack:
                e = stack.pop()
                if e in seen:
                    continue
                seen.add(e)
                for ins in exp_def.get(e, []):
                    if ins[0] in (1, 12) and len(ins) > 1 and ins[1] in step_enum_to_quest:
                        needs.add(step_enum_to_quest[ins[1]])
                    elif ins[0] == 10 and len(ins) > 1:
                        stack.append(ins[1])
            return {"kind": "exp", "hash": h, "name": flag_name, "quests": sorted(needs)}
        if h in bool_def:
            logic["bools"][str(h)] = bool_def[h]
            return {"kind": "bool", "hash": h, "name": flag_name, "quests": []}
        return {"kind": "unknown", "hash": h, "name": flag_name, "quests": []}

    quests: list[dict[str, Any]] = []
    for row in rows:
        qid = _basename(row["__RowId"])
        info = msgs(f"ChallengeMsg/Info_{qid}")
        if row.get("IsListAdventureLog") is False or "Name" not in info:
            continue
        giver = _basename(row.get("RequestActor"))
        region = _basename(row.get("RequestLocation"))
        steps: list[dict[str, Any]] = []
        for s in row.get("Steps") or []:
            pts = _extract_points(s.get("DestinationPoint"))
            steps.append(
                {
                    "name": s["Name"],
                    "hash": mmh3(s["Name"]),
                    "text": info.get(s["Name"], ""),
                    "points": pts,
                }
            )
        if not any(s["name"] == "Complete" for s in steps) and "Complete" in info:
            steps.append({"name": "Complete", "hash": mmh3("Complete"), "text": info["Complete"], "points": []})

        giver_pts: list[list[float]] = []
        for s in row.get("Steps") or []:
            for dpt in s.get("DestinationPoint") or []:
                if isinstance(dpt, dict) and dpt.get("Actor") == row.get("RequestActor"):
                    for p in _extract_points(dpt):
                        if p not in giver_pts:
                            giver_pts.append(p)
        exact = bool(giver_pts)
        if not giver_pts:
            giver_pts = next((s["points"] for s in steps if s["points"]), [])
        dep = row.get("DependFlagName")
        quests.append(
            {
                "id": qid,
                "name": info["Name"],
                "category": QUEST_CATEGORY_MAP.get(row.get("Category"), "side_quest"),
                "sort": row.get("SortIndex", 99999),
                "giver": npc_names.get(f"{giver}_Name", ""),
                "region": loc_names.get(region, region),
                "flag": mmh3(f"Step_{qid}"),
                "giver_actor": giver,
                "start": {"points": giver_pts[:4], "exact": exact},
                "requires": requirement(dep) if dep else None,
                "steps": steps,
            }
        )

    quests.sort(key=lambda q: (q["category"], q["sort"], q["name"]))
    by_actor: dict[str, list[dict[str, Any]]] = {}
    for q in quests:
        a = q["giver_actor"].lower()
        if a.startswith(("npc_", "subchallnpc")):
            by_actor.setdefault(q["giver_actor"], []).append(q)
    for group in by_actor.values():
        group.sort(key=lambda q: q["sort"])
        for prev, q in zip(group, group[1:]):
            if q["sort"] - prev["sort"] == 1:
                q["after"] = prev["id"]

    out = {"quests": quests, "logic": logic}
    _write_json_atomic(QUESTS_PATH, out)
    return out


def _build_catalog(
    romfs: Romfs,
    mals: dict[str, bytes],
    pouch_rows: list[dict[str, Any]],
    map_data: dict[str, Any] | None = None,
    entities: dict[str, Any] | None = None,
    chest_drops: dict[str, list[dict[str, Any]]] | None = None,
    lang: str = "USen",
) -> dict[str, Any]:
    _set_status(step="catalog", progress=0, total=100, message="Construindo catálogo wiki de itens, drops e arquivos...")

    def msgs(name: str) -> dict[str, str]:
        f = f"{name}.msbt"
        return parse_msbt(mals[f]) if f in mals else {}

    pouch_msg = msgs("ActorMsg/PouchContent")
    attach_msg = msgs("ActorMsg/Attachment")
    cook_effect_msg = msgs("StaticMsg/CookEffect")
    buff_msg = msgs("StaticMsg/Buff")
    pb_msg = msgs("ActorMsg/PictureBook")
    bosses_msg = {**pb_msg, **msgs("ActorMsg/Boss")}
    cd_msg = msgs("ActorMsg/CharaDirectory")
    dm_msg = msgs("StaticMsg/DragonMemory")
    loc_names = {**msgs("LocationMsg/Location"), **msgs("LocationMsg/Dungeon")}

    icon_set = {p.rsplit("/", 1)[-1].split(".")[0] for p in romfs.find("UI/Tex/Icon/", ".bntx.zs")}
    pouch_ids = {row["__RowId"] for row in pouch_rows if row.get("__RowId")}
    items: dict[str, dict[str, Any]] = {}
    for row in pouch_rows:
        rid = row["__RowId"]
        nm, cap = _resolve_item_name_caption(rid, pouch_msg, pb_msg, attach_msg, lang=lang)
        items[rid] = {
            "id": rid,
            "name": nm,
            "caption": cap,
            "category": row.get("PouchCategory", ""),
            "sort_key": row.get("PouchSortKey", 0),
            "buy": row.get("BuyingPrice", 0),
            "sell": row.get("SellingPrice", 0),
            "heal": row.get("HitPointRecover", 0),
            "power": row.get("EquipmentPerformance", 0),
            "rank": row.get("ArmorRank", 0),
            "effect": row.get("CureEffectType", "None"),
            "icon": _resolve_item_icon_name(rid, icon_set),
        }

    # Extração paralela de drops dos Enemy_*.pack.zs
    enemy_packs = romfs.find("Pack/Actor/Enemy_", ".pack.zs")
    item_to_monsters: dict[str, set[str]] = {}

    def scan_enemy_drops(epath: str) -> tuple[str, set[str]]:
        eg = _basename(epath)
        mname = _resolve_monster_name(eg, bosses_msg)
        if not mname:
            return "", set()
        sarc = parse_sarc(romfs.read(epath))
        found_drops: set[str] = set()
        for k, v in sarc.items():
            if k.startswith("Drop/DropTableElementList/") and k.endswith(".bgyml"):
                doc = parse_byml(v) or {}
                for el in (doc.get("DropTableElement") or []):
                    raw_drop = _basename(el.get("DropActorName"))
                    if raw_drop:
                        cid, _ = _canonical_item_id(raw_drop, pouch_ids)
                        found_drops.add(cid)
        return mname, found_drops

    with ThreadPoolExecutor(max_workers=8) as ex:
        for mname, fdrops in ex.map(scan_enemy_drops, enemy_packs):
            if not mname:
                continue
            for cid in fdrops:
                if cid in items:
                    item_to_monsters.setdefault(cid, set()).add(mname)

    # Indexação de lojas, dispensadores e entidades do mundo para "Onde conseguir"
    item_to_shops: dict[str, list[dict[str, Any]]] = {}
    for sh in ((map_data or {}).get("shops") or []):
        for g in (sh.get("goods") or []):
            cid = g["id"]
            if cid not in items:
                continue
            item_to_shops.setdefault(cid, []).append(
                {
                    "name": sh["display_name"],
                    "sub": sh.get("sub_label") or "",
                    "price": g["price"],
                    "currency": g["currency"],
                    "bundle": g.get("bundle", 1),
                    "x": round(sh["position"]["x"]),
                    "z": round(sh["position"]["z"]),
                    "layer": sh.get("layer", "surface"),
                }
            )

    item_to_dispensers: dict[str, list[dict[str, Any]]] = {}
    capsule_by_content: dict[str, str] = {}
    for row in pouch_rows:
        cap = _basename(row.get("CapsuleContent"))
        if cap:
            capsule_by_content[cap] = row["__RowId"]
    for disp in ((map_data or {}).get("dispensers") or []):
        for cid in (disp.get("content_ids") or []):
            target_id = cid if cid in items else capsule_by_content.get(cid, "")
            if target_id and target_id in items:
                item_to_dispensers.setdefault(target_id, []).append(
                    {
                        "x": round(disp["position"]["x"]),
                        "z": round(disp["position"]["z"]),
                        "layer": disp.get("layer", "surface"),
                    }
                )

    ent_name_counts: dict[str, tuple[str, int]] = {}
    if entities:
        e_names = entities.get("names") or []
        for ecat in ("plants", "animals"):
            per_name: dict[int, int] = {}
            for ent in (entities.get(ecat) or []):
                per_name[ent[4]] = per_name.get(ent[4], 0) + 1
            for nidx, cnt in per_name.items():
                if 0 <= nidx < len(e_names):
                    nm_str = e_names[nidx]
                    if nm_str not in ent_name_counts:
                        ent_name_counts[nm_str] = (ecat, cnt)

    # Enciclopédia de Hyrule (PictureBook)
    res_sarc = parse_sarc(romfs.read("Pack/ResidentCommon.pack.zs"))
    pb_categories = [
        ("Animal", _ltxt(lang, "Creatures", "Animais")),
        ("Enemy", _ltxt(lang, "Monsters", "Monstros")),
        ("Material", _ltxt(lang, "Materials", "Materiais")),
        ("Weapon", _ltxt(lang, "Equipment", "Equipamentos")),
        ("Treasure", _ltxt(lang, "Treasure", "Tesouros")),
    ]
    pb_icons = {p.rsplit("/", 1)[-1].removesuffix("_Icon.bntx.zs") for p in romfs.find("UI/Tex/PictureBook/", "_Icon.bntx.zs")}
    compendium: list[dict[str, Any]] = []
    pb_locs_by_actor: dict[str, list[str]] = {}
    pb_idx = 1
    for cat_key, cat_label in pb_categories:
        doc = parse_byml(res_sarc[f"Game/PictureBookInfo/{cat_key}.game__ui__PictureBookInfo.bgyml"]) or {}
        for entry in doc.get("PictureBookParamArray") or []:
            actor = entry.get("ActorNameShort", "")
            locs = [loc_names.get(l, l) for l in (entry.get("LocationShort") or []) if l != "Unknown"]
            if locs:
                pb_locs_by_actor[actor] = locs
            compendium.append(
                {
                    "index": pb_idx,
                    "id": actor,
                    "category": cat_key,
                    "category_label": cat_label,
                    "name": pb_msg.get(f"{actor}_Name") or items.get(actor, {}).get("name") or actor,
                    "caption": pb_msg.get(f"{actor}_Caption") or "",
                    "locations": locs,
                    "state_hash": mmh3(f"PictureBookData.{actor}.State"),
                    "has_icon": actor in pb_icons,
                }
            )
            pb_idx += 1

    # Anexa sources em cada item do catálogo mantendo payload compacto
    for rid, item in items.items():
        sources: dict[str, Any] = {}
        if rid in item_to_shops:
            sources["shops"] = item_to_shops[rid]
        if chest_drops and rid in chest_drops:
            ch_list = chest_drops[rid]
            sources["chests"] = ch_list[:10]
            sources["chest_total"] = len(ch_list)
        if rid in item_to_dispensers:
            sources["dispensers"] = item_to_dispensers[rid]
        if item["name"] in ent_name_counts:
            w_cat, w_cnt = ent_name_counts[item["name"]]
            sources["world"] = {"cat": w_cat, "name": item["name"], "count": w_cnt}
        if rid in item_to_monsters:
            sources["drops"] = sorted(item_to_monsters[rid])[:10]
        alt_pb = rid.replace("Animal_Fish_", "Item_FishGet_").replace("Animal_Insect_", "Item_InsectGet_")
        regs = pb_locs_by_actor.get(rid) or pb_locs_by_actor.get(alt_pb)
        if regs:
            sources["regions"] = regs
        if sources:
            item["sources"] = sources

    # Guia de Personagens (CharaDirectory)
    boot_sarc = parse_sarc(romfs.read("Pack/Bootup.Nin_NX_NVN.pack.zs"))
    cd_table = parse_byml(boot_sarc["UI/CharaDirectoryParamTable/Default.game__ui__CharaDirectoryParamTable.bgyml"]) or {}
    cd_icons = {p.rsplit("/", 1)[-1].removesuffix("_Icon.bntx.zs") for p in romfs.find("UI/Tex/CharaDirectory/", "_Icon.bntx.zs")}
    profiles: list[dict[str, Any]] = []
    for entry in cd_table.get("ParamTable") or []:
        cid = _basename(entry.get("Name"))
        if not cid:
            continue
        use_flag = entry.get("UseFlag")
        caption = (
            cd_msg.get(f"{cid}_Caption")
            or cd_msg.get(f"{cid}_Second_Caption")
            or cd_msg.get(f"{cid}_Normal_Caption")
            or cd_msg.get(f"{cid}_First_Caption")
            or ""
        )
        alias = (
            cd_msg.get(f"{cid}_Alias")
            or cd_msg.get(f"{cid}_Second_Alias")
            or cd_msg.get(f"{cid}_Normal_Alias")
            or cd_msg.get(f"{cid}_First_Alias")
            or ""
        )
        profiles.append(
            {
                "id": cid,
                "name": cd_msg.get(f"{cid}_Name") or cid,
                "alias": alias,
                "caption": caption,
                "race": entry.get("Race", ""),
                "tips_hash": mmh3(f"CharaDirectory_IsInstantTipsDisplayed.{cid}"),
                "use_hash": mmh3(use_flag) if use_flag else None,
                "have_talked_hash": mmh3(f"HaveTalked.{cid}"),
                "has_icon": cid in cd_icons,
            }
        )

    # Receitas (RecipeCardTable)
    rc_doc = parse_byml(romfs.read("Cooking/RecipeCardTable/RecipeCardTable.game__cooking__RecipeCardTable.bgyml")) or {}
    recipes: list[dict[str, Any]] = []
    for idx, rid in enumerate(rc_doc.get("RecipeArray") or [], 1):
        recipes.append(
            {
                "index": idx,
                "id": rid,
                "name": pouch_msg.get(f"{rid}_Name") or rid,
                "caption": pouch_msg.get(f"{rid}_Caption") or "",
                "flag_hash": mmh3(f"RecipeCard.Content.{rid}.IsCooked"),
                "icon": _resolve_item_icon_name(rid, icon_set),
            }
        )

    # Memórias da Aventura (AdventureMemorySetTable)
    am_doc = parse_byml(romfs.read("UI/AdventureMemorySetTable/AdventureMemorySetTable.game__ui__AdventureMemorySetTable.bgyml")) or {}
    memories: list[dict[str, Any]] = []
    for idx, entry in enumerate(am_doc.get("AdventureMemorySetArray") or [], 1):
        ev = _basename(entry.get("EventName"))
        open_cond = entry.get("OpenCondition") or ""
        memories.append(
            {
                "index": idx,
                "id": ev,
                "dragon_index": entry.get("DragonMemoryIndex"),
                "is_dragon": bool(entry.get("IsDragonMemory")),
                "title": dm_msg.get(f"{ev}_Title") or ev,
                "caption": dm_msg.get(f"{ev}_Caption") or "",
                "flag_hash": mmh3(f"IsGetAdventureMemory.{ev}"),
                "cond_hash": mmh3(open_cond) if open_cond else None,
            }
        )

    # Nomes traduzidos de efeitos culinários e modificadores
    effects: dict[str, str] = {}
    for k, v in {**cook_effect_msg, **buff_msg}.items():
        clean_k = k.split("_", 1)[0] if k.endswith("_Name") else k
        effects[k] = v
        if k.endswith("_Name"):
            effects[k[:-5]] = v

    catalog = {
        "items": items,
        "compendium": compendium,
        "profiles": profiles,
        "recipes": recipes,
        "memories": memories,
        "effects": effects,
    }
    _write_json_atomic(CATALOG_PATH, catalog)
    return catalog


_HMAP_LOCK = threading.Lock()
_HMAP_CACHE: dict[str, tuple[int, int, bytes]] = {}


def sample_heightmap(game_dir: Path, layer: str, x: float, z: float) -> float:
    """Consulta UI/Map/HeightMap/<L>_<CC>-<RR>.bhtmp.zs para obter altitude real Y em (x, z)."""
    fallback = {"surface": 150.0, "sky": 1400.0, "depths": -550.0}.get(layer, 150.0)
    code = LAYERS_MAP.get(layer)
    if not code:
        return fallback
    col = max(0, min(11, int((x + 6000.0) // 1000.0)))
    row = max(0, min(9, int((z + 5000.0) // 1000.0)))
    rpath = f"UI/Map/HeightMap/{code}_{col:02d}-{row:02d}.bhtmp.zs"
    with _HMAP_LOCK:
        entry = _HMAP_CACHE.get(rpath)
        if entry is None:
            try:
                romfs = get_romfs(game_dir)
                if not romfs.exists(rpath):
                    return fallback
                raw = romfs.read(rpath)
                if len(raw) < 16:
                    return fallback
                w, h = struct.unpack_from("<II", raw, 0)
                if len(raw) < 16 + w * h * 8:
                    return fallback
                entry = (w, h, raw)
                _HMAP_CACHE[rpath] = entry
            except Exception:
                return fallback

    w, h, raw = entry
    u = max(0.0, min(0.9999, (x - (-6000.0 + col * 1000.0)) / 1000.0))
    v = max(0.0, min(0.9999, (z - (-5000.0 + row * 1000.0)) / 1000.0))
    px = int(u * w)
    py = int(v * h)
    ht, valid = struct.unpack_from("<ff", raw, 16 + (py * w + px) * 8)
    if valid >= 0.5 and math.isfinite(ht):
        return round(ht + 1.5, 2)

    for radius in range(1, 7):
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if abs(dx) != radius and abs(dy) != radius:
                    continue
                nx, ny = px + dx, py + dy
                if 0 <= nx < w and 0 <= ny < h:
                    ht2, val2 = struct.unpack_from("<ff", raw, 16 + (ny * w + nx) * 8)
                    if val2 >= 0.5 and math.isfinite(ht2):
                        return round(ht2 + 1.5, 2)
    return fallback


def build_all(game_dir: Path, lang: str = "auto", force: bool = False) -> None:
    """Constrói todo o cache (tiles LOD 2, ícones, máscaras, map_data, entities, quests, catalog)."""
    ensure_dirs()
    from config import resolve_effective_language

    if not lang or str(lang).lower() == "auto":
        lang, _, _ = resolve_effective_language(game_dir, {"lang": "auto"})
    if not force and is_cache_ready(game_dir, lang):
        _set_status(state="ready", step="done", progress=1, total=1, message="Pronto", error="")
        return

    t0 = time.monotonic()
    _set_status(state="building", step="init", progress=0, total=100, message="Abrindo RomFS do jogo...", error="")
    try:
        romfs = get_romfs(game_dir)
        _build_overview_tiles(romfs)
        _build_map_icons(romfs, force=force)
        _build_open_masks(romfs, force=force)

        game_version = detect_romfs_version(romfs)
        mals_path = (
            _pick_latest_product(romfs, f"Mals/{lang}.Product.", ".sarc.zs")
            or _pick_latest_product(romfs, "Mals/USen.Product.", ".sarc.zs")
            or _pick_latest_product(romfs, "Mals/", ".sarc.zs")
        )
        if not mals_path:
            raise FileNotFoundError(f"Arquivo Mals/*.sarc.zs não encontrado para idioma {lang!r}")
        mals = parse_sarc(romfs.read(mals_path))

        _set_status(step="gamedata", progress=0, total=100, message="Lendo tabelas do jogo (GameDataList)...")
        gd_path = _pick_latest_product(romfs, "GameData/GameDataList.Product.", ".byml.zs")
        if not gd_path:
            raise FileNotFoundError("GameData/GameDataList.Product.*.byml.zs não encontrado no RomFS")
        gd = parse_byml(romfs.read(gd_path))["Data"]
        pouch_path = _pick_latest_product(romfs, "RSDB/PouchActorInfo.Product.", ".rstbl.byml.zs")
        pouch_rows = (parse_byml(romfs.read(pouch_path)) or []) if pouch_path else []

        quests_data = _build_quests_data(romfs, mals, gd)
        map_data, entities, chest_drops = _build_map_data(romfs, mals, gd, pouch_rows, quests_data=quests_data, lang=lang)
        catalog = _build_catalog(romfs, mals, pouch_rows, map_data=map_data, entities=entities, chest_drops=chest_drops, lang=lang)

        meta = {
            "cache_version": CACHE_VERSION,
            "game_version": game_version,
            "game_dir": str(game_dir),
            "lang": lang,
            "built_at": int(time.time()),
            "elapsed_s": round(time.monotonic() - t0, 2),
            "counts": {
                "shrines": len(map_data["shrines"]),
                "lightroots": len(map_data["lightroots"]),
                "shops": len(map_data["shops"]),
                "stables": len(map_data["stables"]),
                "hidden_koroks": len(map_data["hidden_koroks"]),
                "carry_koroks": len(map_data["carry_koroks"]),
                "npc_quests": len(entities.get("npc_quests") or {}),
                "quests": len(quests_data["quests"]),
                "items": len(catalog["items"]),
                "compendium": len(catalog["compendium"]),
                "profiles": len(catalog["profiles"]),
                "recipes": len(catalog["recipes"]),
                "memories": len(catalog["memories"]),
            },
        }
        _write_json_atomic(META_PATH, meta)
        _set_status(state="ready", step="done", progress=100, total=100, message="Purah Pad pronto!", error="")
    except Exception as exc:
        _set_status(state="error", error=f"{type(exc).__name__}: {exc}", message="Falha ao extrair dados do RomFS")
        raise


if __name__ == "__main__":
    import argparse

    from config import get_game_dir

    ap = argparse.ArgumentParser(description="Constrói o cache de dados do Purah Pad a partir do RomFS do TotK.")
    ap.add_argument("--game-dir", default=None)
    ap.add_argument("--lang", default="auto")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    gdir = get_game_dir(args.game_dir)
    build_all(gdir, lang=args.lang, force=args.force)
    print(json.dumps(json.loads(META_PATH.read_text(encoding="utf-8")), indent=2, ensure_ascii=False))
