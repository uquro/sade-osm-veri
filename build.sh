#!/bin/bash
# Çevrimdışı hız sınırı ve "ileride" verisini üretir: Geofabrik Türkiye OSM dosyası → araç yolları ve uyarı
# noktaları → speedlimits_tr.bin (varsayılan: uygulamanın assets klasörü). Dosya git'e eklenmiyor (.gitignore).
#
# Uygulama güncel veriyi kendisi indirir: aynı betik açık "sade-osm-veri" deposunda her ay GitHub Actions ile
# çalışıp sonucu yayımlıyor. Bu betik ya da build_speedlimits.py değişirse ikisini o depoya da kopyalayın
# (dosyalar birebir aynı); dosya biçimi değişirse SpeedLimitStore.MAX_VERSION'ı da artırın.
#
# Gerekenler: osmium-tool (brew/apt install osmium-tool), python3, ~2 GB boş yer.
# Kullanım:   scripts/speedlimits/build.sh            # varsa önbellekteki OSM dosyasıyla
#             SPEEDLIMITS_REFRESH=1 scripts/speedlimits/build.sh   # OSM dosyasını yeniden indir
#             SPEEDLIMITS_OUT=/yol/dosya.bin SPEEDLIMITS_CACHE=/önbellek scripts/speedlimits/build.sh
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
if [ "$(uname)" = Darwin ]; then DEFAULT_CACHE="$HOME/Library/Caches/sade-osm"
else DEFAULT_CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/sade-osm"; fi
CACHE="${SPEEDLIMITS_CACHE:-$DEFAULT_CACHE}"
PBF="$CACHE/turkey-latest.osm.pbf"
OUT="${SPEEDLIMITS_OUT:-$HERE/../../fermata/src/main/assets/speedlimits_tr.bin}"
URL="https://download.geofabrik.de/europe/turkey-latest.osm.pbf"

command -v osmium >/dev/null || { echo "osmium yok: brew install osmium-tool (Linux: apt install osmium-tool)"; exit 1; }
mkdir -p "$CACHE" "$(dirname "$OUT")"

if [ ! -s "$PBF" ] || [ "${SPEEDLIMITS_REFRESH:-0}" = "1" ]; then
	echo "İndiriliyor: $URL"
	curl -fL -o "$PBF.part" "$URL"
	mv "$PBF.part" "$PBF"
fi

echo "Araç yolları ayıklanıyor…"
osmium tags-filter --overwrite -o "$CACHE/roads.osm.pbf" "$PBF" \
	w/highway=motorway,trunk,primary,secondary,tertiary,unclassified,residential,living_street,road,motorway_link,trunk_link,primary_link,secondary_link,tertiary_link
osmium export --overwrite -f geojsonseq --geometry-types=linestring --add-unique-id=type_id \
	-o "$CACHE/roads.geojsonseq" "$CACHE/roads.osm.pbf"

echo "Uyarı noktaları ayıklanıyor (hız kamerası, trafik ışığı, tümsek)…"
osmium tags-filter --overwrite -o "$CACHE/hazards.osm.pbf" "$PBF" \
	n/highway=speed_camera,traffic_signals n/traffic_calming
osmium export --overwrite -f geojsonseq --geometry-types=point --add-unique-id=type_id \
	-o "$CACHE/hazards.geojsonseq" "$CACHE/hazards.osm.pbf"

# Veri tarihi: OSM dosyasının zaman damgası (yoksa bugün)
STAMP="$(osmium fileinfo -g header.option.osmosis_replication_timestamp "$PBF" 2>/dev/null | cut -c1-10 | tr -d '-')"
[ -n "$STAMP" ] || STAMP="$(date +%Y%m%d)"

echo "Dönüştürülüyor…"
python3 -I "$HERE/build_speedlimits.py" "$CACHE/roads.geojsonseq" "$OUT" "$STAMP" "$CACHE/hazards.geojsonseq"
ls -lh "$OUT"
