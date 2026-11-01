"""把任意文件以 OLE 包对象（Excel「插入对象 → 由文件创建」）嵌入 xlsx 指定单元格

xlsx 结构对应关系（Excel 2007+ 写法）：
- xl/embeddings/oleObjectN.bin   CFB 复合文档，内含 \\x01Ole 流（Ole10Native 封装原文件）
- xl/media/oleIconN.png          对象外观图（这里用单据首页快照，单元格里看起来像文档）
- xl/drawings/drawing1.xml       形状（cNvPr id == shapeId）承载对象外观
- xl/worksheets/sheet1.xml       <oleObjects><oleObject progId="Package" shapeId=... r:id=.../>
- 对应 .rels                      drawing/sheet 各加一条 oleObject 关系 + 图片关系

用法：xlsx_bytes = inject_ole_objects(xlsx_bytes, items)
items = [{"filename": 原名, "data": bytes, "icon_png": bytes, "col": 0基列, "row": 0基行,
          "w_px": , "h_px": , "shape_id": int}]
"""
import io
import struct
import zipfile
from typing import Dict, List

FREESECT = 0xFFFFFFFF
ENDOFCHAIN = 0xFFFFFFFE
FATSECT = 0xFFFFFFFD
SECTOR = 512
MINI_CUTOFF = 4096

_NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_REL_OLE = f"{_NS_REL}/oleObject"
_REL_IMG = f"{_NS_REL}/image"
_EMU = 9525  # 1px = 9525 EMU


def _ansi(text: str) -> bytes:
    """OLE 包里的文件名串：优先 ANSI，非 ASCII 时退化为 ascii 替换"""
    if not text:
        return b"\x00"
    try:
        return text.encode("ascii") + b"\x00"
    except UnicodeEncodeError:
        return text.encode("ascii", "replace") + b"\x00"


def _ole10_native(filename: str, data: bytes) -> bytes:
    """Ole10Native 流内容（Package 对象）"""
    name = _ansi(filename)
    body = struct.pack("<H", 2) + name + name + b"\x00" + struct.pack("<I", len(data)) + data
    return struct.pack("<I", len(body)) + body


def _dir_entry(name: str, obj_type: int, start: int, size: int, child: int = FREESECT) -> bytes:
    raw = name.encode("utf-16-le") + b"\x00\x00"
    entry = bytearray()
    entry += raw + b"\x00" * (64 - len(raw))
    entry += struct.pack("<H", len(raw))
    entry += struct.pack("<B", obj_type)      # 1=storage 2=stream 5=root
    entry += struct.pack("<B", 1)             # color: black
    entry += struct.pack("<I", FREESECT)      # left sibling
    entry += struct.pack("<I", FREESECT)      # right sibling
    entry += struct.pack("<I", child)         # child
    entry += b"\x00" * 16                     # CLSID
    entry += struct.pack("<I", 0)             # state bits
    entry += b"\x00" * 16                     # create/modify time
    entry += struct.pack("<I", start)
    entry += struct.pack("<I", size)
    entry += b"\x00" * 4
    assert len(entry) == 128
    return bytes(entry)


def build_ole_object(filename: str, data: bytes) -> bytes:
    """生成 oleObjectN.bin：单流 CFB（\\x01Ole → Ole10Native）"""
    stream = _ole10_native(filename, data)
    if len(stream) < MINI_CUTOFF:            # 避免 miniFAT：小文件补齐到阈值
        stream += b"\x00" * (MINI_CUTOFF - len(stream))

    data_sectors = (len(stream) + SECTOR - 1) // SECTOR
    fat_sectors = 1
    while True:
        total = fat_sectors + 1 + data_sectors        # FAT + 目录 + 数据
        need = (total * 4 + SECTOR - 1) // SECTOR
        if need <= fat_sectors:
            break
        fat_sectors = need

    dir_sector = fat_sectors
    first_data = fat_sectors + 1
    fat = [FREESECT] * (fat_sectors * SECTOR // 4)
    for i in range(fat_sectors):
        fat[i] = FATSECT
    fat[dir_sector] = ENDOFCHAIN
    for i in range(data_sectors):
        idx = first_data + i
        fat[idx] = ENDOFCHAIN if i == data_sectors - 1 else idx + 1

    header = bytearray(bytes.fromhex("D0CF11E0A1B11AE1"))
    header += b"\x00" * 16                                  # CLSID
    header += struct.pack("<HH", 0x003E, 0x0003)            # version 3, 512 扇区
    header += struct.pack("<H", 0xFFFE)                     # little endian
    header += struct.pack("<HH", 9, 6)                       # 512 / 64 bytes
    header += b"\x00" * 6
    header += struct.pack("<I", 0)                          # dir sectors (v3 = 0)
    header += struct.pack("<I", fat_sectors)
    header += struct.pack("<I", dir_sector)
    header += struct.pack("<I", 0)                          # transaction id
    header += struct.pack("<I", MINI_CUTOFF)
    header += struct.pack("<I", ENDOFCHAIN)                 # first mini FAT
    header += struct.pack("<I", 0)                          # num mini FAT
    header += struct.pack("<I", ENDOFCHAIN)                 # first DIFAT
    header += struct.pack("<I", 0)                          # num DIFAT
    difat = list(range(fat_sectors)) + [FREESECT] * (109 - fat_sectors)
    header += b"".join(struct.pack("<I", v) for v in difat)
    assert len(header) == 512

    root = _dir_entry("Root Entry", 5, ENDOFCHAIN, 0, child=1)
    ole = _dir_entry("\x01Ole", 2, first_data, len(stream))
    dir_bytes = root + ole + b"\x00" * 128 * 2

    fat_bytes = b"".join(struct.pack("<I", v) for v in fat)
    body = fat_bytes + dir_bytes + stream
    if len(body) % SECTOR:
        body += b"\x00" * (SECTOR - len(body) % SECTOR)
    return bytes(header) + body


def _anchor_xml(item: Dict) -> str:
    """对象外观形状: 用图片填充的 sp, shapeId 与 sheet 里的 oleObject 对应。
    openpyxl 写的 drawing 用默认命名空间(无 xdr: 前缀), 这里保持一致。"""
    col, row = int(item["col"]), int(item["row"])
    w, h = int(item["w_px"]), int(item["h_px"])
    dx, dy = int(item.get("dx_px") or 0), int(item.get("dy_px") or 0)
    sid = int(item["shape_id"])
    return (
        '<twoCellAnchor editAs="oneCell">'
        f"<from><col>{col}</col><colOff>{dx * _EMU}</colOff>"
        f"<row>{row}</row><rowOff>{dy * _EMU}</rowOff></from>"
        f"<to><col>{col}</col><colOff>{(dx + w) * _EMU}</colOff>"
        f"<row>{row}</row><rowOff>{(dy + h) * _EMU}</rowOff></to>"
        '<sp macro="" textlink="">'
        f'<nvSpPr><cNvPr id="{sid}" name="Object {sid}"/><cNvSpPr/></nvSpPr>'
        f'<spPr><a:xfrm xmlns:a="{_NS_A}"><a:off x="0" y="0"/>'
        f'<a:ext cx="{w * _EMU}" cy="{h * _EMU}"/></a:xfrm>'
        f'<a:prstGeom xmlns:a="{_NS_A}" prst="rect"><a:avLst/></a:prstGeom>'
        f'<a:blipFill xmlns:a="{_NS_A}" xmlns:r="{_NS_REL}">'
        f'<a:blip r:embed="{item["icon_rid"]}"/>'
        "<a:stretch><a:fillRect/></a:stretch></a:blipFill>"
        "</spPr></sp><clientData/></twoCellAnchor>"
    )


def _ensure_ns(xml: str, prefix: str, uri: str) -> str:
    """在根元素上补命名空间声明 (只认根标签上的声明; 跳过 <?xml ...?>) """
    start = 0
    if xml.lstrip().startswith("<?xml"):
        start = xml.index("?>") + 2
    while True:
        start = xml.index("<", start)
        if not xml.startswith("<?", start) and not xml.startswith("<!", start):
            break
        start = xml.index(">", start) + 1
    end = xml.index(">", start)
    root_tag = xml[start:end]
    if f"xmlns:{prefix}=" in root_tag:
        return xml
    return f'{xml[:end]} xmlns:{prefix}="{uri}"{xml[end:]}'


def inject_ole_objects(xlsx_bytes: bytes, items: List[Dict]) -> bytes:
    """把文件以 OLE 对象形式写入 xlsx（失败时原样返回）"""
    if not items:
        return xlsx_bytes
    try:
        with zipfile.ZipFile(io.BytesIO(xlsx_bytes)) as zin:
            names = zin.namelist()
            data = {n: zin.read(n) for n in names}
        draw_name = "xl/drawings/drawing1.xml"
        sheet_name = "xl/worksheets/sheet1.xml"
        if draw_name not in data or sheet_name not in data:
            return xlsx_bytes
        draw_rels_name = "xl/drawings/_rels/drawing1.xml.rels"
        sheet_rels_name = "xl/worksheets/_rels/sheet1.xml.rels"

        draw = data[draw_name].decode("utf-8")
        sheet = data[sheet_name].decode("utf-8")
        draw_rels = data.get(draw_rels_name, b"").decode("utf-8")
        sheet_rels = data.get(sheet_rels_name, b"").decode("utf-8")
        if not draw_rels:
            draw_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                         '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                         "</Relationships>")
        if not sheet_rels:
            sheet_rels = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                          '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                          "</Relationships>")

        draw_anchors, draw_rel_xml, sheet_rel_xml, ole_xml = [], [], [], []
        for k, item in enumerate(items, start=1):
            emb = f"xl/embeddings/oleObject{k}.bin"
            icon = f"xl/media/oleIcon{k}.png"
            data[emb] = build_ole_object(str(item.get("filename") or f"附件{k}"),
                                         bytes(item["data"]))
            data[icon] = bytes(item["icon_png"])
            item["icon_rid"] = f"rIdIcon{k}"
            draw_rel_xml.append(
                f'<Relationship Id="rIdOle{k}" Type="{_REL_OLE}" Target="../embeddings/oleObject{k}.bin"/>')
            draw_rel_xml.append(
                f'<Relationship Id="rIdIcon{k}" Type="{_REL_IMG}" Target="../media/oleIcon{k}.png"/>')
            sheet_rel_xml.append(
                f'<Relationship Id="rIdEmb{k}" Type="{_REL_OLE}" Target="../embeddings/oleObject{k}.bin"/>')
            ole_xml.append(
                f'<oleObject progId="Package" dvAspect="DVASPECT_CONTENT" '
                f'shapeId="{int(item["shape_id"])}" r:id="rIdEmb{k}"/>')
            draw_anchors.append(_anchor_xml(item))

        if "</xdr:wsDr>" in draw:
            draw = draw.replace("</xdr:wsDr>", "".join(draw_anchors) + "</xdr:wsDr>")
        else:
            draw = draw.replace("</wsDr>", "".join(draw_anchors) + "</wsDr>")
        sheet = _ensure_ns(sheet, "r", _NS_REL)
        sheet = sheet.replace("</worksheet>", f"<oleObjects>{''.join(ole_xml)}</oleObjects></worksheet>")
        draw_rels = draw_rels.replace("</Relationships>", "".join(draw_rel_xml) + "</Relationships>")
        sheet_rels = sheet_rels.replace("</Relationships>", "".join(sheet_rel_xml) + "</Relationships>")

        data[draw_name] = draw.encode("utf-8")
        data[sheet_name] = sheet.encode("utf-8")
        data[draw_rels_name] = draw_rels.encode("utf-8")
        data[sheet_rels_name] = sheet_rels.encode("utf-8")
        # 内容类型注册（.bin 为 OLE 对象）
        ct = data.get("[Content_Types].xml", b"").decode("utf-8")
        if 'Extension="bin"' not in ct:
            ct = ct.replace("</Types>",
                            '<Default Extension="bin" ContentType="application/vnd.openxmlformats-'
                            'officedocument.oleObject"/></Types>')
            data["[Content_Types].xml"] = ct.encode("utf-8")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zout:
            for name in data:
                zout.writestr(name, data[name])
        return buf.getvalue()
    except Exception:
        return xlsx_bytes
