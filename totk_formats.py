"""Leitores dos formatos nativos do Nintendo Switch / Tears of the Kingdom (RomFS, SARC, MSBT, BYML, BNTX)."""
from __future__ import annotations

import json
import re
import struct
import threading
from pathlib import Path
from typing import Any

import texture2ddecoder
import zstandard as zstd
from PIL import Image

ASTC_BLOCKS: dict[int, tuple[int, int]] = {
    0x2D: (4, 4),
    0x2E: (5, 4),
    0x2F: (5, 5),
    0x30: (6, 5),
    0x31: (6, 6),
    0x32: (8, 5),
    0x33: (8, 6),
    0x34: (8, 8),
    0x35: (10, 5),
    0x36: (10, 6),
    0x37: (10, 8),
    0x38: (10, 10),
    0x39: (12, 10),
    0x3A: (12, 12),
}

BC_FORMATS: dict[int, tuple[int, str]] = {
    0x1A: (8, "decode_bc1"),
    0x1C: (16, "decode_bc3"),
    0x1D: (8, "decode_bc4"),
    0x1E: (16, "decode_bc5"),
    0x20: (16, "decode_bc7"),
}


def mmh3(text: str, seed: int = 0) -> int:
    """MurmurHash3 x86 32-bit usado pelo motor do TotK para chaves de GameData e enums."""
    key = text.encode("utf-8")
    h = seed & 0xFFFFFFFF
    c1, c2 = 0xCC9E2D51, 0x1B873593
    n = len(key) // 4
    for i in range(n):
        k = struct.unpack_from("<I", key, i * 4)[0]
        k = (k * c1) & 0xFFFFFFFF
        k = ((k << 15) | (k >> 17)) & 0xFFFFFFFF
        k = (k * c2) & 0xFFFFFFFF
        h ^= k
        h = ((h << 13) | (h >> 19)) & 0xFFFFFFFF
        h = (h * 5 + 0xE6546B64) & 0xFFFFFFFF
    tail = key[n * 4 :]
    k = 0
    if len(tail) >= 3:
        k ^= tail[2] << 16
    if len(tail) >= 2:
        k ^= tail[1] << 8
    if tail:
        k ^= tail[0]
        k = (k * c1) & 0xFFFFFFFF
        k = ((k << 15) | (k >> 17)) & 0xFFFFFFFF
        k = (k * c2) & 0xFFFFFFFF
        h ^= k
    h ^= len(key)
    h ^= h >> 16
    h = (h * 0x85EBCA6B) & 0xFFFFFFFF
    h ^= h >> 13
    h = (h * 0xC2B2AE35) & 0xFFFFFFFF
    h ^= h >> 16
    return h


def parse_sarc(data: bytes) -> dict[str, bytes]:
    """Desempacota um arquivo SARC em {nome: bytes}."""
    if data[:4] != b"SARC":
        raise ValueError("Arquivo não é SARC válido")
    bom = data[6:8]
    e = "<" if bom == b"\xff\xfe" else ">"
    header_size = struct.unpack_from(e + "H", data, 4)[0]
    data_start = struct.unpack_from(e + "I", data, 0x0C)[0]
    sfat = header_size
    if data[sfat : sfat + 4] != b"SFAT":
        raise ValueError("Cabeçalho SFAT ausente no SARC")
    count = struct.unpack_from(e + "H", data, sfat + 6)[0]
    nodes = [struct.unpack_from(e + "IIII", data, sfat + 12 + i * 16) for i in range(count)]
    sfnt = sfat + 12 + count * 16
    names_start = sfnt + 8
    out: dict[str, bytes] = {}
    for h_val, attr, start, end in nodes:
        if attr & 0x01000000:
            name_off = (attr & 0xFFFF) * 4
            nul = data.index(b"\0", names_start + name_off)
            name = data[names_start + name_off : nul].decode("utf-8", "replace")
        else:
            name = f"{h_val:08x}"
        out[name] = data[data_start + start : data_start + end]
    return out


def _clean_msbt_text(raw: bytes, endian: str) -> str:
    """Converte texto UTF-16 de uma entrada TXT2 removendo tags de controle 0x0E e 0x0F."""
    n = len(raw) // 2
    if n == 0:
        return ""
    chars = struct.unpack_from(f"{endian}{n}H", raw)
    out: list[str] = []
    i = 0
    while i < n:
        c = chars[i]
        if c == 0:
            break
        if c == 0x0E:
            size = chars[i + 3] if i + 3 < n else 0
            i += 4 + size // 2
            continue
        if c == 0x0F:
            i += 3
            continue
        out.append(chr(c))
        i += 1
    text = "".join(out).replace("\r\n", "\n").replace("\r", "\n")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parse_msbt(data: bytes) -> dict[str, str]:
    """Lê um arquivo MSBT e retorna {label: texto_limpo}."""
    if data[:8] != b"MsgStdBn":
        raise ValueError("Arquivo não é MSBT válido")
    e = "<" if data[8:10] == b"\xff\xfe" else ">"
    sections = struct.unpack_from(e + "H", data, 0x0E)[0]
    off = 0x20
    labels: dict[str, int] = {}
    texts: list[str] = []
    for _ in range(sections):
        if off + 16 > len(data):
            break
        magic = data[off : off + 4]
        size = struct.unpack_from(e + "I", data, off + 4)[0]
        body = off + 16
        if magic == b"LBL1":
            groups = struct.unpack_from(e + "I", data, body)[0]
            for g in range(groups):
                cnt, loff = struct.unpack_from(e + "II", data, body + 4 + g * 8)
                p = body + loff
                for _ in range(cnt):
                    ln = data[p]
                    name = data[p + 1 : p + 1 + ln].decode("utf-8", "replace")
                    idx = struct.unpack_from(e + "I", data, p + 1 + ln)[0]
                    labels[name] = idx
                    p += 1 + ln + 4
        elif magic == b"TXT2":
            cnt = struct.unpack_from(e + "I", data, body)[0]
            offs = list(struct.unpack_from(e + f"{cnt}I", data, body + 4)) + [size]
            texts = [_clean_msbt_text(data[body + offs[i] : body + offs[i + 1]], e) for i in range(cnt)]
        off = (body + size + 15) & ~15
    return {name: texts[idx] for name, idx in labels.items() if idx < len(texts)}


def parse_byml(data: bytes) -> Any:
    """Decodifica um documento BYML (v2 a v7) para objetos Python."""
    if data[:2] not in (b"YB", b"BY"):
        raise ValueError("Arquivo não é BYML válido")
    e = "<" if data[:2] == b"YB" else ">"
    byteorder = "little" if e == "<" else "big"
    _ver, key_off, str_off, root_off = struct.unpack_from(e + "HIII", data, 2)

    def read_strtab(off: int) -> list[str]:
        if not off:
            return []
        cnt = int.from_bytes(data[off + 1 : off + 4], byteorder)
        offs = struct.unpack_from(e + f"{cnt}I", data, off + 4)
        out: list[str] = []
        for o in offs:
            end = data.index(b"\0", off + o)
            out.append(data[off + o : end].decode("utf-8", "replace"))
        return out

    keys = read_strtab(key_off)
    strings = read_strtab(str_off)

    def read_val(t: int, raw: int) -> Any:
        if t == 0xA0:
            return strings[raw]
        if t == 0xA1:
            sz = struct.unpack_from(e + "I", data, raw)[0]
            return data[raw + 4 : raw + 4 + sz]
        if t == 0xD0:
            return bool(raw)
        if t == 0xD1:
            return struct.unpack(e + "i", struct.pack(e + "I", raw))[0]
        if t == 0xD2:
            return struct.unpack(e + "f", struct.pack(e + "I", raw))[0]
        if t == 0xD3:
            return raw
        if t in (0xD4, 0xD5, 0xD6):
            fmt = {0xD4: "q", 0xD5: "Q", 0xD6: "d"}[t]
            return struct.unpack_from(e + fmt, data, raw)[0]
        if t == 0xFF:
            return None
        if t in (0xC0, 0xC1, 0x20, 0x21):
            return read_node(raw)
        return raw

    def read_node(off: int) -> Any:
        t = data[off]
        cnt = int.from_bytes(data[off + 1 : off + 4], byteorder)
        if t == 0xC0:
            types = data[off + 4 : off + 4 + cnt]
            vals = off + 4 + ((cnt + 3) & ~3)
            return [read_val(types[i], struct.unpack_from(e + "I", data, vals + i * 4)[0]) for i in range(cnt)]
        if t == 0xC1:
            out: dict[str, Any] = {}
            for i in range(cnt):
                p = off + 4 + i * 8
                k = int.from_bytes(data[p : p + 3], byteorder)
                vt = data[p + 3]
                out[keys[k]] = read_val(vt, struct.unpack_from(e + "I", data, p + 4)[0])
            return out
        if t in (0x20, 0x21):
            # Nós de tabela hash presentes em alguns BYMLs recentes
            out_h: dict[str, Any] = {}
            entry_size = 8 if t == 0x20 else 12
            val_types_off = off + 4 + cnt * entry_size
            for i in range(cnt):
                p = off + 4 + i * entry_size
                h_key = struct.unpack_from(e + ("I" if t == 0x20 else "Q"), data, p)[0]
                v_raw = struct.unpack_from(e + "I", data, p + (4 if t == 0x20 else 8))[0]
                vt = data[val_types_off + i]
                out_h[f"0x{h_key:x}"] = read_val(vt, v_raw)
            return out_h
        raise ValueError(f"Tipo de nó BYML não suportado: 0x{t:02x}")

    return read_node(root_off) if root_off else None


class Romfs:
    """Leitor thread-safe de romfs/index.json + romfs/romfs.bin com descompressão Zstd/ZsDic."""

    def __init__(self, romfs_dir: Path | str) -> None:
        self.dir = Path(romfs_dir)
        index_path = self.dir / "index.json"
        bin_path = self.dir / "romfs.bin"
        if not index_path.is_file() or not bin_path.is_file():
            raise FileNotFoundError(f"RomFS inválido em {self.dir}")
        with index_path.open("r", encoding="utf-8") as f:
            entries = json.load(f)["files"]
        self.files: dict[str, tuple[int, int]] = {e["path"]: (e["offset"], e["size"]) for e in entries}
        self._paths: list[str] = list(self.files.keys())
        self._bin_path = bin_path
        self._fp = bin_path.open("rb")
        self._io_lock = threading.Lock()
        self._local = threading.local()
        self._dicts: list[bytes] = []
        self._load_dicts()

    def _load_dicts(self) -> None:
        if "Pack/ZsDic.pack.zs" not in self.files:
            return
        raw = self.read_raw("Pack/ZsDic.pack.zs")
        sarc_data = zstd.ZstdDecompressor().decompress(raw)
        entries = parse_sarc(sarc_data)
        self._dicts = list(entries.values())

    def _get_decompressors(self) -> list[zstd.ZstdDecompressor]:
        dlist = getattr(self._local, "decompressors", None)
        if dlist is None:
            dlist = [zstd.ZstdDecompressor()] + [
                zstd.ZstdDecompressor(dict_data=zstd.ZstdCompressionDict(d)) for d in self._dicts
            ]
            self._local.decompressors = dlist
        return dlist

    def exists(self, path: str) -> bool:
        return path in self.files

    def find(self, prefix: str = "", suffix: str = "") -> list[str]:
        return [p for p in self._paths if p.startswith(prefix) and p.endswith(suffix)]

    def read_raw(self, path: str) -> bytes:
        off, size = self.files[path]
        with self._io_lock:
            self._fp.seek(off)
            return self._fp.read(size)

    def read(self, path: str) -> bytes:
        raw = self.read_raw(path)
        if not path.endswith(".zs"):
            return raw
        for dctx in self._get_decompressors():
            try:
                return dctx.decompress(raw)
            except zstd.ZstdError:
                continue
        raise ValueError(f"Não foi possível descomprimir {path}")

    def close(self) -> None:
        with self._io_lock:
            if not self._fp.closed:
                self._fp.close()


def _div_up(a: int, b: int) -> int:
    return (a + b - 1) // b


def deswizzle(data: bytes, width_blocks: int, height_blocks: int, bpp: int, block_height_log2: int) -> bytes:
    """Converte memória Tegra X1 block-linear para linear (em unidades de blocos de bpp bytes)."""
    block_height = 1 << block_height_log2
    gobs_wide = _div_up(width_blocks * bpp, 64)
    row_bytes = width_blocks * bpp
    out = bytearray(row_bytes * height_blocks)
    mv = memoryview(data)
    max_len = len(mv)
    for y in range(height_blocks):
        y_base = (
            (y // (8 * block_height)) * 512 * block_height * gobs_wide
            + (y % (8 * block_height) // 8) * 512
            + ((y % 8) // 2) * 64
            + (y % 2) * 16
        )
        o = y * row_bytes
        for x in range(width_blocks):
            xb = x * bpp
            addr = (
                y_base
                + (xb // 64) * 512 * block_height
                + ((xb % 64) // 32) * 256
                + ((xb % 32) // 16) * 32
                + (xb % 16)
            )
            if addr + bpp <= max_len:
                out[o : o + bpp] = mv[addr : addr + bpp]
            o += bpp
    return bytes(out)


def list_bntx_textures(data: bytes) -> list[tuple[str, int]]:
    """Lista todas as texturas BRTI em um arquivo BNTX: [(nome, offset)]."""
    out: list[tuple[str, int]] = []
    idx = data.find(b"BRTI")
    while idx >= 0:
        if idx + 0x78 <= len(data):
            name_at = struct.unpack_from("<Q", data, idx + 0x60)[0]
            if name_at + 2 <= len(data):
                n = struct.unpack_from("<H", data, name_at)[0]
                if name_at + 2 + n <= len(data):
                    name = data[name_at + 2 : name_at + 2 + n].decode("utf-8", "replace")
                    out.append((name, idx))
        idx = data.find(b"BRTI", idx + 4)
    return out


def decode_bntx_image(data: bytes, offset: int | None = None) -> Image.Image:
    """Decodifica a textura BRTI no offset especificado (ou primeira) em uma PIL.Image RGBA."""
    i = data.find(b"BRTI") if offset is None else offset
    if i < 0:
        raise ValueError("Nenhuma textura BRTI encontrada no BNTX")
    fmt = struct.unpack_from("<I", data, i + 0x1C)[0]
    width, height = struct.unpack_from("<II", data, i + 0x24)
    layout = struct.unpack_from("<I", data, i + 0x34)[0]
    image_size = struct.unpack_from("<I", data, i + 0x50)[0]
    ptrs = struct.unpack_from("<Q", data, i + 0x70)[0]
    mip0 = struct.unpack_from("<Q", data, ptrs)[0]
    kind = fmt >> 8

    if kind in ASTC_BLOCKS:
        bw, bh = ASTC_BLOCKS[kind]
        bpp = 16
        raw = deswizzle(data[mip0 : mip0 + image_size], _div_up(width, bw), _div_up(height, bh), bpp, layout & 7)
        bgra = texture2ddecoder.decode_astc(raw, width, height, bw, bh)
        return Image.frombytes("RGBA", (width, height), bgra, "raw", "BGRA")
    if kind in BC_FORMATS:
        bw = bh = 4
        bpp, fn_name = BC_FORMATS[kind]
        raw = deswizzle(data[mip0 : mip0 + image_size], _div_up(width, bw), _div_up(height, bh), bpp, layout & 7)
        bgra = getattr(texture2ddecoder, fn_name)(raw, width, height)
        img = Image.frombytes("RGBA", (width, height), bgra, "raw", "BGRA")
        if kind == 0x1D:  # BC4 máscara monocromática -> RGB branco, R no canal alpha
            img = Image.merge("RGBA", (*([Image.new("L", img.size, 255)] * 3), img.getchannel("R")))
        return img
    if kind == 0x0B:  # RGBA8
        raw = deswizzle(data[mip0 : mip0 + image_size], width, height, 4, layout & 7)
        return Image.frombytes("RGBA", (width, height), raw, "raw", "RGBA")
    raise ValueError(f"Formato de textura BNTX não suportado: 0x{fmt:04x}")
