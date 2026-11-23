#!/bin/bash
# Üretilen speedlimits_tr.bin'i GitHub sürümü olarak yayımlar: sıkıştırılmış dosya + manifest.properties.
# Uygulama .../releases/latest/download/manifest.properties adresine bakar. Son 3 sürüm tutulur.
# Kullanım (Actions içinde, GH_TOKEN ve GITHUB_REPOSITORY tanımlı): ./publish.sh /yol/speedlimits_tr.bin
set -euo pipefail

BIN="$1"
REPO="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY yok}"
WORK="$(mktemp -d)"
read -r VERSION DATE < <(python3 -I -c '
import struct, sys
h = open(sys.argv[1], "rb").read(16)
assert h[:4] == b"SLTR", "başlık yok"
print(struct.unpack("<H", h[4:6])[0], struct.unpack("<I", h[12:16])[0])' "$BIN")
TAG="veri-$DATE"

if gh release view "$TAG" -R "$REPO" >/dev/null 2>&1; then
	echo "$TAG zaten yayımlanmış; OSM dosyası değişmemiş."
	exit 0
fi

gzip -9 -n -c "$BIN" > "$WORK/speedlimits_tr.bin.gz"
cat > "$WORK/manifest.properties" <<MAN
# Sade yol verisi (hız sınırı, uyarı noktaları). © OpenStreetMap katkıcıları, ODbL 1.0
version=$VERSION
date=$DATE
url=https://github.com/$REPO/releases/download/$TAG/speedlimits_tr.bin.gz
size=$(stat -c %s "$WORK/speedlimits_tr.bin.gz")
raw_size=$(stat -c %s "$BIN")
sha256=$(sha256sum "$BIN" | cut -d' ' -f1)
MAN
cat "$WORK/manifest.properties"

gh release create "$TAG" -R "$REPO" --latest \
	--title "Türkiye yol verisi ${DATE:0:4}-${DATE:4:2}-${DATE:6:2}" \
	--notes "OpenStreetMap Türkiye verisinden (Geofabrik) üretilmiş hız sınırları, hız kameraları, trafik ışıkları ve tümsekler. Biçim sürümü $VERSION.

© OpenStreetMap katkıcıları. Veri Open Database License (ODbL) 1.0 ile kullanılabilir: https://www.openstreetmap.org/copyright" \
	"$WORK/speedlimits_tr.bin.gz" "$WORK/manifest.properties"

# Eski sürümleri sil (son 3 kalsın)
gh release list -R "$REPO" --limit 100 --json tagName -q '.[].tagName' | grep '^veri-' | sort -r | tail -n +4 |
	while read -r old; do gh release delete "$old" -R "$REPO" --yes --cleanup-tag; done

# Depoda bir değişiklik bırak: GitHub, 60 gün hareketsiz açık depolarda zamanlanmış işleri kapatıyor
echo "$DATE" > SON_VERI
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add SON_VERI
git commit -m "Veri $DATE yayımlandı" && git push || true
