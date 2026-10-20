"""Кодировщик kiwi и сборщик синтетических `.fig` — только для тестов чтения (`verstka/brand/kiwi.py`, `fig.py`).

Схема — уменьшенная копия схемы Figma (те же имена сообщений и полей, что в настоящих файлах): документ, страницы, фреймы,
векторы, текст, переменные и их коллекции, стили; сообщение `Message {nodeChanges, blobs}`. Файл — заголовок «fig-kiwi»,
версия, куски «длина + deflate» (схема, сообщение), как пишет Figma; новый вид — ZIP с `canvas.fig`, `thumbnail.png`,
`meta.json` и `images/`."""

from __future__ import annotations

import io
import json
import struct
import zipfile
import zlib
from typing import Any, Optional

_BUILTIN = {"bool": -1, "byte": -2, "int": -3, "uint": -4, "float": -5, "string": -6, "int64": -7, "uint64": -8}

# (name, kind, [(field, type, is_array)]) — values are 1.. in order (enum values 0..)
SCHEMA: list[tuple[str, str, list]] = [
    ("NodeType", "ENUM", ["NONE", "DOCUMENT", "CANVAS", "FRAME", "VECTOR", "TEXT", "VARIABLE_SET", "VARIABLE", "INSTANCE", "SYMBOL",
                          "ROUNDED_RECTANGLE"]),
    ("PaintType", "ENUM", ["SOLID", "IMAGE"]),
    ("StyleType", "ENUM", ["NONE", "FILL", "TEXT", "GRID"]),
    ("WindingRule", "ENUM", ["NONZERO", "ODD"]),
    ("VariableResolvedDataType", "ENUM", ["BOOLEAN", "FLOAT", "STRING", "COLOR"]),
    ("LayoutGridAxis", "ENUM", ["X", "Y"]),
    ("LayoutGridType", "ENUM", ["MIN", "CENTER", "STRETCH"]),
    ("StackMode", "ENUM", ["NONE", "HORIZONTAL", "VERTICAL"]),
    ("GUID", "STRUCT", [("sessionID", "uint", False), ("localID", "uint", False)]),
    ("Color", "STRUCT", [("r", "float", False), ("g", "float", False), ("b", "float", False), ("a", "float", False)]),
    ("Vector", "STRUCT", [("x", "float", False), ("y", "float", False)]),
    ("Matrix", "STRUCT", [("m00", "float", False), ("m01", "float", False), ("m02", "float", False),
                          ("m10", "float", False), ("m11", "float", False), ("m12", "float", False)]),
    ("ParentIndex", "MESSAGE", [("guid", "GUID", False), ("position", "string", False)]),
    ("Image", "MESSAGE", [("hash", "byte", True), ("name", "string", False)]),
    ("Paint", "MESSAGE", [("type", "PaintType", False), ("color", "Color", False), ("opacity", "float", False),
                          ("visible", "bool", False), ("image", "Image", False)]),
    ("Path", "MESSAGE", [("windingRule", "WindingRule", False), ("commandsBlob", "uint", False)]),
    ("FontName", "MESSAGE", [("family", "string", False), ("style", "string", False), ("postscript", "string", False)]),
    ("LayoutGrid", "MESSAGE", [("type", "LayoutGridType", False), ("axis", "LayoutGridAxis", False), ("visible", "bool", False),
                               ("numSections", "int", False), ("offset", "float", False), ("sectionSize", "float", False),
                               ("gutterSize", "float", False)]),
    ("VariableID", "MESSAGE", [("guid", "GUID", False)]),
    ("VariableSetMode", "MESSAGE", [("id", "GUID", False), ("name", "string", False)]),
    ("VariableAnyValue", "MESSAGE", [("colorValue", "Color", False), ("floatValue", "float", False), ("textValue", "string", False),
                                     ("alias", "VariableID", False)]),
    ("VariableData", "MESSAGE", [("value", "VariableAnyValue", False), ("dataType", "VariableResolvedDataType", False)]),
    ("VariableDataValuesEntry", "MESSAGE", [("modeID", "GUID", False), ("variableData", "VariableData", False)]),
    ("VariableDataValues", "MESSAGE", [("entries", "VariableDataValuesEntry", True)]),
    ("TextData", "MESSAGE", [("characters", "string", False)]),
    ("NodeChange", "MESSAGE", [
        ("guid", "GUID", False), ("parentIndex", "ParentIndex", False), ("type", "NodeType", False), ("name", "string", False),
        ("size", "Vector", False), ("transform", "Matrix", False), ("fillPaints", "Paint", True), ("fillGeometry", "Path", True),
        ("styleType", "StyleType", False), ("fontName", "FontName", False), ("fontSize", "float", False),
        ("layoutGrids", "LayoutGrid", True), ("variableSetModes", "VariableSetMode", True), ("variableSetID", "VariableID", False),
        ("variableResolvedType", "VariableResolvedDataType", False), ("variableDataValues", "VariableDataValues", False),
        ("stackMode", "StackMode", False), ("stackHorizontalPadding", "float", False), ("visible", "bool", False),
        ("textData", "TextData", False),
    ]),
    ("Blob", "MESSAGE", [("bytes", "byte", True)]),
    ("Message", "MESSAGE", [("nodeChanges", "NodeChange", True), ("blobs", "Blob", True)]),
]


class _W:
    def __init__(self) -> None:
        self.b = bytearray()

    def uint(self, v: int) -> None:
        v &= 0xFFFFFFFF
        while True:
            x = v & 127
            v >>= 7
            if v:
                self.b.append(x | 128)
            else:
                self.b.append(x)
                return

    def int(self, v: int) -> None:
        self.uint((v << 1) ^ (v >> 31))

    def float(self, v: float) -> None:
        bits = struct.unpack("<I", struct.pack("<f", v))[0]
        bits = ((bits >> 23) | (bits << 9)) & 0xFFFFFFFF
        if bits & 255 == 0:
            self.b.append(0)
            return
        self.b += struct.pack("<I", bits)

    def string(self, s: str) -> None:
        self.b += s.encode("utf-8") + b"\x00"


def encode_schema(schema: list = SCHEMA) -> bytes:
    index = {name: i for i, (name, _, _) in enumerate(schema)}
    w = _W()
    w.uint(len(schema))
    for name, kind, fields in schema:
        w.string(name)
        w.b.append({"ENUM": 0, "STRUCT": 1, "MESSAGE": 2}[kind])
        w.uint(len(fields))
        for i, f in enumerate(fields):
            if kind == "ENUM":
                w.string(f)
                w.int(0)
                w.b.append(0)
                w.uint(i)
            else:
                fname, ftype, arr = f
                w.string(fname)
                w.int(_BUILTIN[ftype] if ftype in _BUILTIN else index[ftype])
                w.b.append(1 if arr else 0)
                w.uint(i + 1)
    return bytes(w.b)


def encode_message(value: dict, root: str = "Message", schema: list = SCHEMA) -> bytes:
    defs = {name: (kind, fields) for name, kind, fields in schema}
    w = _W()

    def one(t: str, v: Any) -> None:
        if t in _BUILTIN:
            if t == "bool" or t == "byte":
                w.b.append(int(v))
            elif t == "uint":
                w.uint(v)
            elif t == "int":
                w.int(v)
            elif t == "float":
                w.float(v)
            elif t == "string":
                w.string(v)
            return
        kind, fields = defs[t]
        if kind == "ENUM":
            w.uint(fields.index(v))
        elif kind == "STRUCT":
            for fname, ftype, _ in fields:
                one(ftype, v.get(fname, 0))
        else:
            for i, (fname, ftype, arr) in enumerate(fields):
                if fname not in v or v[fname] is None:
                    continue
                w.uint(i + 1)
                field(ftype, arr, v[fname])
            w.uint(0)

    def field(t: str, arr: bool, v: Any) -> None:
        if not arr:
            one(t, v)
        elif t == "byte":
            w.uint(len(v))
            w.b += bytes(v)
        else:
            w.uint(len(v))
            for x in v:
                one(t, x)

    one(root, value)
    return bytes(w.b)


def deflate_raw(data: bytes) -> bytes:
    c = zlib.compressobj(9, zlib.DEFLATED, -15)
    return c.compress(data) + c.flush()


def fig_bytes(message: dict, *, header: bytes = b"fig-kiwi", version: int = 101) -> bytes:
    """Старый `.fig` (он же `canvas.fig` внутри нового): заголовок, версия, сжатые схема и сообщение."""
    out = bytearray(header + struct.pack("<I", version))
    for chunk in (deflate_raw(encode_schema()), deflate_raw(encode_message(message))):
        out += struct.pack("<I", len(chunk)) + chunk
    return bytes(out)


def fig_zip(canvas: Optional[bytes], *, thumbnail: Optional[bytes] = None, meta: Optional[dict] = None,
            images: Optional[dict[str, bytes]] = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        if canvas is not None:
            z.writestr("canvas.fig", canvas)
        if thumbnail is not None:
            z.writestr("thumbnail.png", thumbnail)
        z.writestr("meta.json", json.dumps(meta or {"file_name": "Тест"}))
        for h, data in (images or {}).items():
            z.writestr(f"images/{h}", data)
    return buf.getvalue()


# ---- building blocks of a document --------------------------------------------------------------------------------------
def g(local: int, session: int = 1) -> dict:
    return {"sessionID": session, "localID": local}


def rgb(hex_: str, a: float = 1.0) -> dict:
    h = hex_.lstrip("#")
    return {"r": int(h[0:2], 16) / 255, "g": int(h[2:4], 16) / 255, "b": int(h[4:6], 16) / 255, "a": a}


def solid(hex_: str, a: float = 1.0) -> dict:
    return {"type": "SOLID", "color": rgb(hex_, a), "opacity": 1.0, "visible": True}


def node(local: int, parent: Optional[int], type_: str, name: str, **kw: Any) -> dict:
    n = {"guid": g(local), "type": type_, "name": name, **kw}
    if parent is not None:
        n["parentIndex"] = {"guid": g(parent), "position": kw.pop("position", "!")}
    return n


def path_blob(commands: list[tuple]) -> dict:
    """[("M", x, y), ("L", x, y), ("C", …6), ("Z",)] → blob контура Figma."""
    code = {"Z": 0, "M": 1, "L": 2, "Q": 3, "C": 4}
    b = bytearray()
    for c in commands:
        b.append(code[c[0]])
        for v in c[1:]:
            b += struct.pack("<f", v)
    return {"bytes": bytes(b)}


def identity(x: float = 0.0, y: float = 0.0) -> dict:
    return {"m00": 1.0, "m01": 0.0, "m02": x, "m10": 0.0, "m11": 1.0, "m12": y}
