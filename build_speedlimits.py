#!/usr/bin/env python3
"""
OpenStreetMap yollarından çevrimdışı hız sınırı dosyası (speedlimits_tr.bin) üretir.

Girdi: `osmium export -f geojsonseq` çıktısı (yalnızca araç yolları; bkz. build.sh).
Çıktı biçimi (küçük-uçlu / little-endian; okuyucu: SpeedLimitStore.java):

  Başlık   "SLTR" | u16 sürüm (2) | u16 kare boyu (1/10000 derece: 100 = 0,01°) | u32 kare sayısı
           | u32 veri tarihi (yyyymmdd)
  Dizin    kare sayısı × { i32 enlem sırası | i32 boylam sırası | u32 konum | u32 uzunluk }  (sıralı)
  Veri     kare başına: varint parça sayısı, sonra parçalar:
             u32 OSM yol kimliği | u8 yol türü | u8 bayraklar | u8 sınır | u8 ileri | u8 geri | u8 tür sınırı
             | varint nokta sayısı | noktalar (1e-5 derece; ilki kare köşesine göre, sonrakiler farkla; zigzag varint)
           sonra (sürüm 2) varint uyarı noktası sayısı, noktalar:
             u8 tür (1 hız kamerası, 2 trafik ışığı, 3 tümsek) | u8 sınır (kamerada; 0 bilinmiyor)
             | zigzag varint enlem, boylam (1e-5 derece, kare köşesine göre)

  Bayraklar: bit 0-1 tek yön (0 iki yönlü, 1 düğüm sırasıyla, 2 ters), bit 2 adında cadde/sokak/bulvar.
  Sınır baytları: 0 bilinmiyor, 255 sınır yok ("none"), diğerleri km/sa.

Uzun yollar karelere bölünür: her kare yalnızca kendisine değen parçaları tutar (aynı yol kimliğiyle).
Noktalar Douglas-Peucker ile ~2,5 m toleransla sadeleştirilir.

Kullanım: build_speedlimits.py yollar.geojsonseq cikti.bin [yyyymmdd [noktalar.geojsonseq]]
          build_speedlimits.py --selftest
"""
import json
import math
import re
import struct
import sys
from collections import defaultdict

TILE = 0.01
TILE_CODE = 100  # TILE * 10000
SCALE = 100_000  # 1e-5 derece
SIMPLIFY_M = 2.5

HIGHWAYS = ["motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
            "living_street", "road", "motorway_link", "trunk_link", "primary_link", "secondary_link",
            "tertiary_link"]
HIGHWAY_CODE = {h: i + 1 for i, h in enumerate(HIGHWAYS)}

# Uyarı noktaları ("ileride"): hız kamerası, trafik ışığı, tümsek. Titreşimli şerit, ada, şikan alınmaz.
HAZARD_CAMERA, HAZARD_SIGNALS, HAZARD_BUMP = 1, 2, 3
BUMPS = {"bump", "hump", "table", "cushion", "mini_bumps", "mini_bump", "dip", "yes", "short bump"}


def hazard_kind(props):
    if props.get("highway") == "speed_camera":
        return HAZARD_CAMERA
    if props.get("highway") == "traffic_signals":
        return HAZARD_SIGNALS
    if props.get("traffic_calming") in BUMPS:
        return HAZARD_BUMP
    return None

UNKNOWN, NONE = 0, 255
TR_IMPLICIT = {"tr:urban": 50, "tr:rural": 90, "tr:trunk": 110, "tr:dual_carriageway": 110,
               "tr:expressway": 110, "tr:motorway": 120}
URBAN_NAME = re.compile(r"(?<![^\W_])(cadde|caddesi|cad\.|cd\.?|sokak|sokağı|sok\.|sk\.?|bulvar|bulvarı|"
                        r"blv\.?|bulv\.)(?![^\W_])", re.IGNORECASE)


def parse(value):
    """maxspeed değeri → bayt (0 bilinmiyor, 255 sınır yok, diğerleri km/sa). SpeedLimits.java ile aynı kurallar."""
    if value is None:
        return UNKNOWN
    v = value.split(";")[0].strip()
    if not v:
        return UNKNOWN
    l = v.lower()
    if l == "none":
        return NONE
    if l in TR_IMPLICIT:
        return TR_IMPLICIT[l]
    m = re.match(r"^(\d+)\s*(.*)$", l)
    if not m:
        return UNKNOWN
    n, unit = int(m.group(1)), m.group(2).strip()
    if unit in ("", "km/h", "kmh", "kph"):
        kmh = n
    elif unit == "mph":
        kmh = round(n * 1.609344)
    elif unit == "knots":
        kmh = round(n * 1.852)
    else:
        return UNKNOWN
    return kmh if 5 <= kmh <= 200 else UNKNOWN


def oneway(highway, ow, junction):
    if ow in ("yes", "true", "1"):
        return 1
    if ow in ("-1", "reverse"):
        return 2
    if ow in ("no", "false", "0"):
        return 0
    if highway == "motorway" or junction in ("roundabout", "circular"):
        return 1
    return 0


def is_urban_name(name):
    return bool(name) and URBAN_NAME.search(name) is not None


def simplify(pts, tol_m):
    """Douglas-Peucker (yerel metre izdüşümünde)."""
    if len(pts) <= 2:
        return pts
    lat0 = pts[0][1]
    kx = 111_320.0 * math.cos(math.radians(lat0))
    ky = 110_540.0
    xy = [((p[0] - pts[0][0]) * kx, (p[1] - pts[0][1]) * ky) for p in pts]
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        ax, ay = xy[a]
        bx, by = xy[b]
        dx, dy = bx - ax, by - ay
        l2 = dx * dx + dy * dy
        best, idx = -1.0, -1
        for i in range(a + 1, b):
            px, py = xy[i]
            if l2 == 0:
                d = math.hypot(px - ax, py - ay)
            else:
                t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / l2))
                d = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            if d > best:
                best, idx = d, i
        if best > tol_m:
            keep[idx] = True
            stack.append((a, idx))
            stack.append((idx, b))
    return [p for p, k in zip(pts, keep) if k]


def varint(n, out):
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return


def zigzag(n):
    return (n << 1) ^ (n >> 63)


def tiles_of_segment(p, q):
    la0, la1 = sorted((p[1], q[1]))
    lo0, lo1 = sorted((p[0], q[0]))
    for a in range(math.floor(la0 / TILE), math.floor(la1 / TILE) + 1):
        for b in range(math.floor(lo0 / TILE), math.floor(lo1 / TILE) + 1):
            yield a, b


def encode_piece(out, way_id, hw, flags, limits, pts, la, lo):
    out += struct.pack("<IBB4B", way_id & 0xFFFFFFFF, hw, flags, *limits)
    varint(len(pts), out)
    base_lat = round(la * TILE * SCALE)
    base_lon = round(lo * TILE * SCALE)
    plat, plon = base_lat, base_lon
    for lon, lat in pts:
        ilat, ilon = round(lat * SCALE), round(lon * SCALE)
        varint(zigzag(ilat - plat), out)
        varint(zigzag(ilon - plon), out)
        plat, plon = ilat, ilon


def read_hazards(src):
    """Nokta dosyası (osmium export, Point) → kare → [(tür, sınır, enlem, boylam)]."""
    out = defaultdict(list)
    with open(src, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip().lstrip("\x1e")
            if not line:
                continue
            feat = json.loads(line)
            geom = feat.get("geometry") or {}
            if geom.get("type") != "Point":
                continue
            props = feat.get("properties") or {}
            kind = hazard_kind(props)
            if kind is None:
                continue
            lon, lat = float(geom["coordinates"][0]), float(geom["coordinates"][1])
            limit = parse(props.get("maxspeed")) if kind == HAZARD_CAMERA else UNKNOWN
            if limit == NONE:
                limit = UNKNOWN
            out[(math.floor(lat / TILE), math.floor(lon / TILE))].append((kind, limit, lat, lon))
    return out


def encode_hazards(out, items, la, lo):
    varint(len(items), out)
    base_lat = round(la * TILE * SCALE)
    base_lon = round(lo * TILE * SCALE)
    for kind, limit, lat, lon in items:
        out += struct.pack("<BB", kind, limit)
        varint(zigzag(round(lat * SCALE) - base_lat), out)
        varint(zigzag(round(lon * SCALE) - base_lon), out)


def build(src, dst, date, hazards_src=None):
    tiles = defaultdict(bytearray)
    counts = defaultdict(int)
    ways = pieces = points_in = points_out = tagged = 0
    with open(src, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip().lstrip("\x1e")
            if not line:
                continue
            feat = json.loads(line)
            geom = feat.get("geometry") or {}
            if geom.get("type") != "LineString":
                continue
            props = feat.get("properties") or {}
            hw = HIGHWAY_CODE.get(props.get("highway"))
            if hw is None:
                continue
            fid = str(feat.get("id", props.get("@id", "")))
            m = re.search(r"(\d+)$", fid)
            if not m:
                continue
            way_id = int(m.group(1))
            pts = [(float(c[0]), float(c[1])) for c in geom["coordinates"]]
            if len(pts) < 2:
                continue
            ways += 1
            points_in += len(pts)
            pts = simplify(pts, SIMPLIFY_M)
            points_out += len(pts)
            typ = props.get("maxspeed:type") or props.get("source:maxspeed") or props.get("zone:maxspeed")
            limits = (parse(props.get("maxspeed")), parse(props.get("maxspeed:forward")),
                      parse(props.get("maxspeed:backward")), parse(typ))
            if any(v != UNKNOWN for v in limits):
                tagged += 1
            flags = oneway(props.get("highway"), props.get("oneway"), props.get("junction"))
            if is_urban_name(props.get("name")):
                flags |= 4
            # Her karenin değdiği ardışık parçalar
            per_tile = defaultdict(list)
            for i in range(len(pts) - 1):
                for t in tiles_of_segment(pts[i], pts[i + 1]):
                    per_tile[t].append(i)
            for t, segs in per_tile.items():
                run = [segs[0]]
                for s in segs[1:] + [None]:
                    if s is not None and s == run[-1] + 1:
                        run.append(s)
                        continue
                    piece = pts[run[0]:run[-1] + 2]
                    encode_piece(tiles[t], way_id, hw, flags, limits, piece, t[0], t[1])
                    counts[t] += 1
                    pieces += 1
                    if s is not None:
                        run = [s]

    hazards = read_hazards(hazards_src) if hazards_src else {}
    keys = sorted(set(tiles) | set(hazards))
    header = struct.pack("<4sHHII", b"SLTR", 2, TILE_CODE, len(keys), date)
    index_size = 16 * len(keys)
    offset = len(header) + index_size
    index = bytearray()
    blobs = []
    for k in keys:
        blob = bytearray()
        varint(counts[k], blob)
        blob += tiles[k]
        encode_hazards(blob, hazards.get(k, []), k[0], k[1])
        index += struct.pack("<iiII", k[0], k[1], offset, len(blob))
        offset += len(blob)
        blobs.append(blob)
    with open(dst, "wb") as f:
        f.write(header)
        f.write(index)
        for b in blobs:
            f.write(b)
    print(f"yol {ways}, sınır etiketli {tagged} (%{100 * tagged / max(1, ways):.1f}), parça {pieces}, "
          f"kare {len(keys)}, nokta {points_in} → {points_out}, "
          f"uyarı {sum(len(v) for v in hazards.values())}, dosya {offset / 1e6:.1f} MB")


def selftest():
    assert parse("50") == 50
    assert parse(" 70 km/h") == 70
    assert parse("30 mph") == 48
    assert parse("50;70") == 50
    assert parse("TR:urban") == 50
    assert parse("TR:motorway") == 120
    assert parse("none") == NONE
    assert parse("signals") == UNKNOWN
    assert parse("999") == UNKNOWN
    assert parse(None) == UNKNOWN
    assert oneway("motorway", None, None) == 1
    assert oneway("primary", "-1", None) == 2
    assert oneway("primary", None, "roundabout") == 1
    assert is_urban_name("Atatürk Cd.")
    assert is_urban_name("Gül Sokağı")
    assert is_urban_name("Cumhuriyet Bulvarı")
    assert not is_urban_name("Sokakçılar Yolu")
    assert not is_urban_name("Kocadere Yolu")
    out = bytearray()
    varint(300, out)
    assert out == bytearray([0xAC, 0x02])
    assert zigzag(-1) == 1 and zigzag(1) == 2
    line = [(29.0, 41.0), (29.00001, 41.000001), (29.0001, 41.0)]
    assert simplify(line, 2.5) == [(29.0, 41.0), (29.0001, 41.0)]
    assert hazard_kind({"highway": "speed_camera"}) == HAZARD_CAMERA
    assert hazard_kind({"highway": "traffic_signals"}) == HAZARD_SIGNALS
    assert hazard_kind({"traffic_calming": "hump"}) == HAZARD_BUMP
    assert hazard_kind({"traffic_calming": "rumble_strip"}) is None
    assert hazard_kind({"traffic_calming": "island"}) is None
    print("selftest tamam")


if __name__ == "__main__":
    if len(sys.argv) == 2 and sys.argv[1] == "--selftest":
        selftest()
    elif len(sys.argv) in (3, 4, 5):
        build(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) >= 4 else 0,
              sys.argv[4] if len(sys.argv) == 5 else None)
    else:
        print(__doc__)
        sys.exit(2)
