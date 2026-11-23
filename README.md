# sade-osm-veri

Sade (Android Auto sürüş paneli) için çevrimdışı yol verisi: Türkiye'deki yolların hız sınırları ve
"ileride" uyarı noktaları (hız kamerası, trafik ışığı, tümsek).

- Her ayın 2'sinde GitHub Actions, [Geofabrik](https://download.geofabrik.de/europe/turkey.html)'ten güncel
  OpenStreetMap Türkiye dosyasını indirir, `build.sh` ile `speedlimits_tr.bin` üretir ve `publish.sh` ile sürüm
  olarak yayımlar (`speedlimits_tr.bin.gz` + `manifest.properties`). Elle çalıştırmak için: Actions → "Aylık yol
  verisi" → Run workflow.
- Uygulama günde bir, Wi-Fi'dayken
  `https://github.com/uquro/sade-osm-veri/releases/latest/download/manifest.properties` adresine bakar; tarih
  eldekinden yeniyse dosyayı indirir, SHA-256 ve boyutunu denetleyip kullanır. Konum ya da kişisel bilgi gönderilmez.
- `build.sh` ve `build_speedlimits.py` uygulama deposundaki `scripts/speedlimits/` ile birebir aynıdır; orada
  değişince buraya kopyalanır. Dosya biçimi `build_speedlimits.py`'nin başında anlatılıyor.

## Lisans

Veri © [OpenStreetMap katkıcıları](https://www.openstreetmap.org/copyright), Open Database License (ODbL) 1.0.
