"""Kiwi (формат сообщений Figma, evanw/kiwi) на чистом Python: двоичная схема → определения, сообщение по схеме → словари.

Файл Figma (`canvas.fig` внутри ZIP нового `.fig` или сам старый `.fig`): заголовок из 8 байт («fig-kiwi», у FigJam
«fig-jam.»), версия uint32, затем куски «uint32 длина + данные»: первый — схема kiwi (deflate без заголовка), второй —
сообщение (deflate или zstd, сигнатура 28 b5 2f fd). Схема лежит в самом файле, поэтому разбор не зависит от версии Figma.

Значения: перечисления — строкой (имя значения), структуры и сообщения — dict, массивы — list, массив байтов — bytes.
`decode_message(..., deadline=…)` останавливается по времени на длинном массиве верхнего уровня и возвращает прочитанное
(флаг `partial`)."""

from __future__ import annotations

import struct
import time
import zlib
from dataclasses import dataclass, field
from typing import Any, Optional


class KiwiError(ValueError):
    pass


_TYPES = ["bool", "byte", "int", "uint", "float", "string", "int64", "uint64"]


@dataclass
class Field:
    name: str
    type: str  # built-in name or a definition's name
    is_array: bool
    value: int


@dataclass
class Definition:
    name: str
    kind: str  # ENUM | STRUCT | MESSAGE
    fields: list[Field] = field(default_factory=list)
    by_value: dict[int, Field] = field(default_factory=dict)


class _Buf:
    __slots__ = ("b", "p")

    def __init__(self, b: bytes) -> None:
        self.b, self.p = b, 0

    def byte(self) -> int:
        if self.p >= len(self.b):
            raise KiwiError("kiwi: данные кончились раньше времени")
        v = self.b[self.p]
        self.p += 1
        return v

    def uint(self) -> int:
        b, p = self.b, self.p
        shift = v = 0
        while True:
            if p >= len(b):
                raise KiwiError("kiwi: данные кончились раньше времени")
            x = b[p]
            p += 1
            v |= (x & 127) << shift
            if x < 128 or shift >= 28:
                break
            shift += 7
        self.p = p
        return v & 0xFFFFFFFF

    def uint64(self) -> int:
        shift = v = 0
        while True:
            x = self.byte()
            if shift == 56:
                v |= x << 56
                break
            v |= (x & 127) << shift
            if x < 128:
                break
            shift += 7
        return v

    def int(self) -> int:
        v = self.uint()
        return ~(v >> 1) if v & 1 else v >> 1

    def int64(self) -> int:
        v = self.uint64()
        return ~(v >> 1) if v & 1 else v >> 1

    def float(self) -> float:
        first = self.byte()
        if first == 0:
            return 0.0
        if self.p + 3 > len(self.b):
            raise KiwiError("kiwi: данные кончились раньше времени")
        bits = first | (self.b[self.p] << 8) | (self.b[self.p + 1] << 16) | (self.b[self.p + 2] << 24)
        self.p += 3
        bits = ((bits << 23) | (bits >> 9)) & 0xFFFFFFFF
        return struct.unpack("<f", struct.pack("<I", bits))[0]

    def string(self) -> str:
        end = self.b.find(b"\x00", self.p)
        if end < 0:
            raise KiwiError("kiwi: строка без конца")
        s = self.b[self.p:end].decode("utf-8", "replace")
        self.p = end + 1
        return s

    def bytes_(self) -> bytes:
        n = self.uint()
        if self.p + n > len(self.b):
            raise KiwiError("kiwi: данные кончились раньше времени")
        v = bytes(self.b[self.p:self.p + n])
        self.p += n
        return v


def decode_schema(data: bytes) -> dict[str, Definition]:
    bb = _Buf(data)
    n = bb.uint()
    raw: list[tuple[str, str, list[tuple[str, int, bool, int]]]] = []
    for _ in range(n):
        name = bb.string()
        kind = bb.byte()
        nf = bb.uint()
        fields = []
        for _ in range(nf):
            fname = bb.string()
            ftype = bb.int()
            is_array = bool(bb.byte() & 1)
            value = bb.uint()
            fields.append((fname, ftype, is_array, value))
        if kind not in (0, 1, 2):
            raise KiwiError("kiwi: неизвестный вид определения")
        raw.append((name, ("ENUM", "STRUCT", "MESSAGE")[kind], fields))
    defs: dict[str, Definition] = {}
    for name, kind, fields in raw:
        d = Definition(name, kind)
        for fname, ftype, is_array, value in fields:
            if kind == "ENUM":
                t = ""
            elif ftype < 0:
                if ~ftype >= len(_TYPES):
                    raise KiwiError("kiwi: неизвестный тип поля")
                t = _TYPES[~ftype]
            else:
                if ftype >= len(raw):
                    raise KiwiError("kiwi: ссылка на несуществующий тип")
                t = raw[ftype][0]
            f = Field(fname, t, is_array, value)
            d.fields.append(f)
            d.by_value[value] = f
        defs[name] = d
    return defs


class _Reader:
    def __init__(self, defs: dict[str, Definition], data: bytes, deadline: Optional[float]) -> None:
        self.defs = defs
        self.bb = _Buf(data)
        self.deadline = deadline
        self.partial = False
        self.enum_names = {n: {f.value: f.name for f in d.fields} for n, d in defs.items() if d.kind == "ENUM"}

    def value(self, t: str) -> Any:
        bb = self.bb
        if t == "uint":
            return bb.uint()
        if t == "float":
            return bb.float()
        if t == "string":
            return bb.string()
        if t == "int":
            return bb.int()
        if t == "bool":
            return bb.byte() != 0
        if t == "byte":
            return bb.byte()
        if t == "int64":
            return bb.int64()
        if t == "uint64":
            return bb.uint64()
        d = self.defs[t]
        if d.kind == "ENUM":
            v = bb.uint()
            return self.enum_names[t].get(v, v)
        if d.kind == "STRUCT":
            return {f.name: self.field(f) for f in d.fields}
        out: dict[str, Any] = {}
        while True:
            tag = bb.uint()
            if tag == 0:
                return out
            f = d.by_value.get(tag)
            if f is None:
                raise KiwiError(f"kiwi: поле {tag} не описано в схеме «{t}»")
            out[f.name] = self.field(f)

    def field(self, f: Field, top: bool = False) -> Any:
        if not f.is_array:
            return self.value(f.type)
        if f.type == "byte":
            return self.bb.bytes_()
        n = self.bb.uint()
        if n > len(self.bb.b):
            raise KiwiError("kiwi: неверная длина массива")
        out = []
        for i in range(n):
            if top and self.deadline is not None and i and (i & 255) == 0 and time.monotonic() > self.deadline:
                self.partial = True
                break
            out.append(self.value(f.type))
        return out


def decode_message(defs: dict[str, Definition], data: bytes, root: str = "Message", *,
                   deadline: Optional[float] = None) -> tuple[dict, bool]:
    """Сообщение `root` → (dict, partial). `deadline` (time.monotonic) — прервать длинный массив верхнего уровня."""
    if root not in defs:
        root = next((n for n, d in defs.items() if d.kind == "MESSAGE"), "")
        if not root:
            raise KiwiError("kiwi: в схеме нет сообщений")
    d = defs[root]
    r = _Reader(defs, data, deadline)
    out: dict[str, Any] = {}
    while True:
        tag = r.bb.uint()
        if tag == 0:
            break
        f = d.by_value.get(tag)
        if f is None:
            raise KiwiError(f"kiwi: поле {tag} не описано в схеме «{root}»")
        out[f.name] = r.field(f, top=True)
        if r.partial:
            break
    return out, r.partial


# ------------------------------------------------------------------------------------------------------- the Figma file
@dataclass
class FigArchive:
    header: str
    version: int
    schema: dict[str, Definition]
    message: dict
    partial: bool


def _inflate(chunk: bytes, max_output: int) -> bytes:
    from verstka.brand.zstd import MAGIC, decompress

    if chunk[:4] == MAGIC:
        return decompress(chunk, max_output=max_output)
    for wbits in (-15, 15, 31):
        try:
            d = zlib.decompressobj(wbits)
            out = d.decompress(chunk, max_output)
            if d.unconsumed_tail:
                raise KiwiError("kiwi: распакованные данные слишком большие")
            return out
        except zlib.error:
            continue
    return chunk  # stored as is


def split_chunks(data: bytes) -> tuple[str, int, list[bytes]]:
    if len(data) < 12 or not data[:4] == b"fig-":
        raise KiwiError("не файл Figma: нет заголовка «fig-kiwi»")
    header = data[:8].decode("latin-1")
    version = int.from_bytes(data[8:12], "little")
    p = 12
    chunks: list[bytes] = []
    while p + 4 <= len(data):
        n = int.from_bytes(data[p:p + 4], "little")
        p += 4
        if p + n > len(data):
            raise KiwiError("файл Figma обрезан")
        chunks.append(data[p:p + n])
        p += n
    if len(chunks) < 2:
        raise KiwiError("в файле Figma нет схемы и данных")
    return header, version, chunks


def read_fig_archive(data: bytes, *, max_output: int = 400 * 1024 * 1024, deadline: Optional[float] = None) -> FigArchive:
    header, version, chunks = split_chunks(data)
    schema = decode_schema(_inflate(chunks[0], 64 * 1024 * 1024))
    msg, partial = decode_message(schema, _inflate(chunks[1], max_output), deadline=deadline)
    return FigArchive(header, version, schema, msg, partial)
