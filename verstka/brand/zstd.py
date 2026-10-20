"""Распаковка Zstandard (RFC 8878) на чистом Python — для файлов Figma `.fig`, где сообщение kiwi сжато zstd.

Если установлен пакет `zstandard`, берётся он (быстрее); иначе — этот декодер: кадры, пропускаемые кадры, блоки raw/RLE/
сжатые, литералы (Huffman 1 и 4 потока, повтор таблицы), последовательности (FSE, предопределённые, RLE, повтор таблиц),
повторяемые смещения. Словари не поддерживаются (Figma их не использует). Ошибка формата — `ZstdError`.

`decompress(data, max_output=…)` — защита от «бомбы»: больше `max_output` байт не распаковывается."""

from __future__ import annotations

from typing import Optional

MAGIC = b"\x28\xb5\x2f\xfd"


class ZstdError(ValueError):
    pass


def decompress(data: bytes, *, max_output: int = 512 * 1024 * 1024) -> bytes:
    try:  # the C library when present
        import zstandard  # type: ignore

        try:
            return zstandard.ZstdDecompressor().decompress(data, max_output_size=max_output)
        except zstandard.ZstdError:
            pass  # a frame without its content size: the pure decoder below streams it
    except ImportError:
        pass
    return _Decoder(data, max_output).run()


# ---------------------------------------------------------------------------------------------------------- bit readers
class _BackBits:
    """Обратный поток битов (как в FSE/Huffman): читается от конца к началу, первый единичный бит последнего байта — метка."""

    __slots__ = ("val", "nbits")

    def __init__(self, buf: bytes) -> None:
        if not buf or buf[-1] == 0:
            raise ZstdError("zstd: пустой или повреждённый поток битов")
        self.val = int.from_bytes(buf, "little")
        self.nbits = len(buf) * 8 - (8 - buf[-1].bit_length()) - 1  # bits under the marker

    def read(self, n: int) -> int:
        if n == 0:
            return 0
        self.nbits -= n
        if self.nbits >= 0:
            return (self.val >> self.nbits) & ((1 << n) - 1)
        # past the start: zeros come in from the right (allowed at the very end of a stream)
        v = (self.val << (-self.nbits)) & ((1 << n) - 1)
        return v


class _FwdBits:
    __slots__ = ("buf", "pos")

    def __init__(self, buf: bytes, pos: int = 0) -> None:
        self.buf, self.pos = buf, pos * 8

    def read(self, n: int) -> int:
        v = 0
        for i in range(n):
            byte = self.buf[(self.pos + i) >> 3] if (self.pos + i) >> 3 < len(self.buf) else 0
            v |= ((byte >> ((self.pos + i) & 7)) & 1) << i
        self.pos += n
        return v

    @property
    def byte_pos(self) -> int:
        return (self.pos + 7) >> 3


# ------------------------------------------------------------------------------------------------------------------- FSE
def _fse_read_ncount(buf: bytes, pos: int, max_symbol: int) -> tuple[list[int], int, int]:
    """Нормализованные частоты FSE → (частоты, accuracy_log, новая позиция)."""
    br = _FwdBits(buf, pos)
    acc = br.read(4) + 5
    remaining = (1 << acc) + 1
    counts: list[int] = []
    while remaining > 1 and len(counts) <= max_symbol:
        bits = remaining.bit_length()
        lower = (1 << bits) - 1 - remaining
        v = br.read(bits - 1)
        if v < lower:
            val = v
        else:
            v |= br.read(1) << (bits - 1)
            val = v - lower if v >= (1 << (bits - 1)) else v
        # the two-step read above follows the reference: small values take bits-1 bits
        prob = val - 1
        remaining -= abs(prob) if prob != 0 else 0
        counts.append(prob)
        if prob == 0:
            while True:
                rep = br.read(2)
                counts.extend([0] * rep)
                if rep != 3:
                    break
    if remaining != 1:
        raise ZstdError("zstd: неверная таблица FSE")
    return counts, acc, br.byte_pos


def _fse_table(counts: list[int], acc: int) -> list[tuple[int, int, int]]:
    """Таблица декодирования FSE: состояние → (символ, число бит, база следующего состояния)."""
    size = 1 << acc
    sym = [0] * size
    high = size - 1
    for s, c in enumerate(counts):
        if c == -1:
            sym[high] = s
            high -= 1
    step = (size >> 1) + (size >> 3) + 3
    mask = size - 1
    pos = 0
    for s, c in enumerate(counts):
        for _ in range(max(c, 0)):
            sym[pos] = s
            pos = (pos + step) & mask
            while pos > high:
                pos = (pos + step) & mask
    nxt = [1 if c == -1 else c for c in counts]
    table: list[tuple[int, int, int]] = []
    for st in range(size):
        s = sym[st]
        x = nxt[s]
        nxt[s] += 1
        nb = acc - (x.bit_length() - 1)
        table.append((s, nb, (x << nb) - size))
    return table


def _rle_table(symbol: int) -> list[tuple[int, int, int]]:
    return [(symbol, 0, 0)]


_LL_DEFAULT = [4, 3, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3, 2, 1, 1, 1, 1, 1, -1, -1, -1, -1]
_ML_DEFAULT = [1, 4, 3, 2, 2, 2, 2, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1,
               1, 1, 1, 1, 1, 1, 1, 1, -1, -1, -1, -1, -1, -1, -1]
_OF_DEFAULT = [1, 1, 1, 1, 1, 1, 2, 2, 2, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, -1, -1, -1, -1, -1]
_LL_BASE = list(range(16)) + [16, 18, 20, 22, 24, 28, 32, 40, 48, 64, 128, 256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536]
_LL_BITS = [0] * 16 + [1, 1, 1, 1, 2, 2, 3, 3, 4, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]
_ML_BASE = list(range(3, 35)) + [35, 37, 39, 41, 43, 47, 51, 59, 67, 83, 99, 131, 259, 515, 1027, 2051, 4099, 8195, 16387, 32771, 65539]
_ML_BITS = [0] * 32 + [1, 1, 1, 1, 2, 2, 3, 3, 4, 4, 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]
_DEFAULT_TABLES = {
    "ll": _fse_table(_LL_DEFAULT, 6), "ml": _fse_table(_ML_DEFAULT, 6), "of": _fse_table(_OF_DEFAULT, 5),
}


# --------------------------------------------------------------------------------------------------------------- Huffman
def _huff_table(weights: list[int]) -> tuple[list[tuple[int, int]], int]:
    """Веса Huffman (последний вес выводится) → таблица (символ, длина) по max_bits бит префикса."""
    total = sum((1 << (w - 1)) for w in weights if w > 0)
    if total == 0:
        raise ZstdError("zstd: пустое дерево Huffman")
    max_bits = total.bit_length()  # the next power of two above the sum
    left = (1 << max_bits) - total
    if left & (left - 1):
        raise ZstdError("zstd: неверные веса Huffman")
    weights = weights + [left.bit_length()]
    lens = [(max_bits + 1 - w) if w > 0 else 0 for w in weights]
    table: list[tuple[int, int]] = [(0, 0)] * (1 << max_bits)
    # canonical: by length descending → codes ascending (the reference fills by weight ascending)
    pos = 0
    for w in range(1, max_bits + 1):
        for s, ww in enumerate(weights):
            if ww == w:
                n = 1 << (w - 1)
                ln = max_bits + 1 - w
                for k in range(pos, pos + n):
                    table[k] = (s, ln)
                pos += n
    return table, max_bits


def _huff_weights(buf: bytes, pos: int) -> tuple[list[int], int]:
    hb = buf[pos]
    pos += 1
    if hb >= 128:
        n = hb - 127
        w: list[int] = []
        nbytes = (n + 1) // 2
        for i in range(nbytes):
            b = buf[pos + i]
            w += [b >> 4, b & 15]
        return w[:n], pos + nbytes
    # FSE-compressed weights (two interleaved states)
    data = buf[pos:pos + hb]
    counts, acc, p = _fse_read_ncount(data, 0, 255)
    table = _fse_table(counts, acc)
    br = _BackBits(data[p:])
    s1 = br.read(acc)
    s2 = br.read(acc)
    out: list[int] = []
    while True:
        sym, nb, base = table[s1]
        out.append(sym)
        s1 = base + br.read(nb)
        if br.nbits < 0:
            out.append(table[s2][0])
            break
        sym, nb, base = table[s2]
        out.append(sym)
        s2 = base + br.read(nb)
        if br.nbits < 0:
            out.append(table[s1][0])
            break
        if len(out) > 255:
            raise ZstdError("zstd: слишком много весов Huffman")
    return out, pos + hb


def _huff_stream(data: bytes, table: list[tuple[int, int]], max_bits: int, n: int, out: bytearray) -> None:
    br = _BackBits(data)
    val, nbits = br.val, br.nbits
    mask = (1 << max_bits) - 1
    for _ in range(n):
        if nbits >= max_bits:
            idx = (val >> (nbits - max_bits)) & mask
        else:
            idx = (val << (max_bits - nbits)) & mask
        s, ln = table[idx]
        out.append(s)
        nbits -= ln
    if nbits != 0:
        raise ZstdError("zstd: поток Huffman не сошёлся")


# --------------------------------------------------------------------------------------------------------------- decoder
class _Decoder:
    def __init__(self, data: bytes, max_output: int) -> None:
        self.d = memoryview(bytes(data))
        self.max = max_output
        self.out = bytearray()
        self.huff: Optional[tuple[list, int]] = None
        self.tables: dict[str, Optional[list]] = {"ll": None, "of": None, "ml": None}
        self.rep = [1, 4, 8]

    def run(self) -> bytes:
        d = self.d
        pos = 0
        while pos < len(d):
            magic = bytes(d[pos:pos + 4])
            if len(magic) < 4:
                raise ZstdError("zstd: обрезанный кадр")
            if magic[1:] == b"\x2a\x4d\x18" and 0x50 <= magic[0] <= 0x5F:  # skippable frame
                size = int.from_bytes(d[pos + 4:pos + 8], "little")
                pos += 8 + size
                continue
            if magic != MAGIC:
                if pos > 0:
                    break  # trailing garbage after a frame
                raise ZstdError("zstd: нет сигнатуры кадра")
            pos = self._frame(pos + 4)
        return bytes(self.out)

    def _frame(self, pos: int) -> int:
        d = self.d
        fhd = d[pos]
        pos += 1
        fcs_flag = fhd >> 6
        single = (fhd >> 5) & 1
        checksum = (fhd >> 2) & 1
        dict_flag = fhd & 3
        if fhd & 0x08:
            raise ZstdError("zstd: зарезервированный бит заголовка")
        if not single:
            pos += 1  # window descriptor
        if dict_flag:
            did = int.from_bytes(d[pos:pos + (1, 2, 4)[dict_flag - 1]], "little")
            pos += (1, 2, 4)[dict_flag - 1]
            if did:
                raise ZstdError("zstd: кадр со словарём не поддерживается")
        fcs_size = (1 if single else 0, 2, 4, 8)[fcs_flag]
        pos += fcs_size
        self.huff = None
        self.tables = {"ll": None, "of": None, "ml": None}
        self.rep = [1, 4, 8]
        while True:
            if pos + 3 > len(d):
                raise ZstdError("zstd: обрезанный блок")
            bh = int.from_bytes(d[pos:pos + 3], "little")
            pos += 3
            last, btype, bsize = bh & 1, (bh >> 1) & 3, bh >> 3
            if btype == 0:
                self.out += d[pos:pos + bsize]
                pos += bsize
            elif btype == 1:
                self.out += bytes([d[pos]]) * bsize
                pos += 1
            elif btype == 2:
                self._block(bytes(d[pos:pos + bsize]))
                pos += bsize
            else:
                raise ZstdError("zstd: зарезервированный тип блока")
            if len(self.out) > self.max:
                raise ZstdError("zstd: распакованные данные слишком большие")
            if last:
                break
        if checksum:
            pos += 4
        return pos

    # -- literals
    def _literals(self, b: bytes) -> tuple[bytes, int]:
        h = b[0]
        ltype = h & 3
        sf = (h >> 2) & 3
        if ltype in (0, 1):
            if sf in (0, 2):
                size, pos = h >> 3, 1
            elif sf == 1:
                size, pos = (h >> 4) + (b[1] << 4), 2
            else:
                size, pos = (h >> 4) + (b[1] << 4) + (b[2] << 12), 3
            if ltype == 0:
                return b[pos:pos + size], pos + size
            return bytes([b[pos]]) * size, pos + 1
        if sf in (0, 1):
            v = int.from_bytes(b[0:3], "little")
            regen, comp, pos = (v >> 4) & 0x3FF, (v >> 14) & 0x3FF, 3
            streams = 1 if sf == 0 else 4
        elif sf == 2:
            v = int.from_bytes(b[0:4], "little")
            regen, comp, pos, streams = (v >> 4) & 0x3FFF, (v >> 18) & 0x3FFF, 4, 4
        else:
            v = int.from_bytes(b[0:5], "little")
            regen, comp, pos, streams = (v >> 4) & 0x3FFFF, (v >> 22) & 0x3FFFF, 5, 4
        start = pos
        if ltype == 2:
            weights, p2 = _huff_weights(b, pos)
            self.huff = _huff_table(weights)
            pos = p2
        elif self.huff is None:
            raise ZstdError("zstd: повтор таблицы Huffman без таблицы")
        table, max_bits = self.huff
        data = b[pos:start + comp]
        out = bytearray()
        if streams == 1:
            _huff_stream(data, table, max_bits, regen, out)
        else:
            s1, s2, s3 = (int.from_bytes(data[i:i + 2], "little") for i in (0, 2, 4))
            seg = (regen + 3) // 4
            p = 6
            parts = [data[p:p + s1], data[p + s1:p + s1 + s2], data[p + s1 + s2:p + s1 + s2 + s3], data[p + s1 + s2 + s3:]]
            for i, part in enumerate(parts):
                _huff_stream(part, table, max_bits, seg if i < 3 else regen - 3 * seg, out)
        return bytes(out), start + comp

    # -- sequences
    def _seq_table(self, kind: str, mode: int, b: bytes, pos: int, max_sym: int) -> int:
        if mode == 0:
            self.tables[kind] = _DEFAULT_TABLES[kind]
        elif mode == 1:
            self.tables[kind] = _rle_table(b[pos])
            pos += 1
        elif mode == 2:
            counts, acc, p = _fse_read_ncount(b, pos, max_sym)
            self.tables[kind] = _fse_table(counts, acc)
            pos = p
        elif self.tables[kind] is None:
            raise ZstdError("zstd: повтор таблицы FSE без таблицы")
        return pos

    def _block(self, b: bytes) -> None:
        lits, pos = self._literals(b)
        n = b[pos]
        if n == 0:
            self.out += lits
            return
        if n < 128:
            pos += 1
        elif n < 255:
            n = ((n - 128) << 8) + b[pos + 1]
            pos += 2
        else:
            n = b[pos + 1] + (b[pos + 2] << 8) + 0x7F00
            pos += 3
        modes = b[pos]
        pos += 1
        pos = self._seq_table("ll", modes >> 6, b, pos, 35)
        pos = self._seq_table("of", (modes >> 4) & 3, b, pos, 31)
        pos = self._seq_table("ml", (modes >> 2) & 3, b, pos, 52)
        llt, oft, mlt = self.tables["ll"], self.tables["of"], self.tables["ml"]
        br = _BackBits(b[pos:])
        acc_ll = (len(llt) - 1).bit_length()  # type: ignore[arg-type]
        acc_of = (len(oft) - 1).bit_length()  # type: ignore[arg-type]
        acc_ml = (len(mlt) - 1).bit_length()  # type: ignore[arg-type]
        sll, sof, sml = br.read(acc_ll), br.read(acc_of), br.read(acc_ml)
        out = self.out
        rep = self.rep
        lp = 0
        for i in range(n):
            ofc = oft[sof][0]  # type: ignore[index]
            mlc = mlt[sml][0]  # type: ignore[index]
            llc = llt[sll][0]  # type: ignore[index]
            if ofc > 31:
                raise ZstdError("zstd: неверный код смещения")
            ofv = (1 << ofc) + br.read(ofc)
            ml = _ML_BASE[mlc] + br.read(_ML_BITS[mlc])
            ll = _LL_BASE[llc] + br.read(_LL_BITS[llc])
            if ofv > 3:
                off = ofv - 3
                rep[2], rep[1], rep[0] = rep[1], rep[0], off
            else:
                idx = ofv - 1 + (1 if ll == 0 else 0)
                if idx == 0:
                    off = rep[0]
                elif idx == 3:
                    off = rep[0] - 1
                    rep[2], rep[1], rep[0] = rep[1], rep[0], off
                else:
                    off = rep[idx]
                    if idx == 1:
                        rep[1], rep[0] = rep[0], off
                    else:
                        rep[2], rep[1], rep[0] = rep[1], rep[0], off
            out += lits[lp:lp + ll]
            lp += ll
            if off <= 0 or off > len(out):
                raise ZstdError("zstd: смещение за пределами данных")
            start = len(out) - off
            if off >= ml:
                out += out[start:start + ml]
            else:
                chunk = out[start:]
                while ml > 0:
                    take = min(ml, len(chunk))
                    out += chunk[:take]
                    ml -= take
                    chunk = out[start:]
            if len(out) > self.max:
                raise ZstdError("zstd: распакованные данные слишком большие")
            if i < n - 1:
                s, nb, base = llt[sll]  # type: ignore[index]
                sll = base + br.read(nb)
                s, nb, base = mlt[sml]  # type: ignore[index]
                sml = base + br.read(nb)
                s, nb, base = oft[sof]  # type: ignore[index]
                sof = base + br.read(nb)
        out += lits[lp:]
