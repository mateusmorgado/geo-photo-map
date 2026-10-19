# Field photos × geology

My geology field-course photos on a map, each one with the rock it was taken on.

`build.py` reads the GPS position of every photo, asks the national geological
survey what lies under that point and writes one GeoJSON point layer for
ArcGIS Online, plus web previews with all metadata removed.

| Country | Geology source | Lookup |
|---|---|---|
| Germany | BGR, GÜK250 (1:250 000) | ArcGIS REST `identify` on the stratigraphy and petrography layers |
| Sweden | SGU, bedrock 1:50 000–1:250 000 | WMS `GetFeatureInfo` on `SE.GOV.SGU.BERGGRUND_NA10` |

German stratigraphy and rock names are translated with `terms_de_en.json`;
SGU already returns English lithology and tectonic units.

## Run

```
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python build.py "C:\path\to\photos"
```

The photo folder holds one subfolder per course; `courses.json` maps each
folder to its course, region and country. A folder named `_not-on-map` is skipped.

Output in `out/`: `photos.geojson` and `previews/large`, `previews/thumb` (WebP, no EXIF).

## Upload

The previews are served from the public Cloud Storage bucket `morgado-geo-photos`
(Frankfurt). Each feature carries `img_url` and `thumb_url` pointing there.

```
gcloud storage cp --recursive out\previews\large out\previews\thumb gs://morgado-geo-photos/ --cache-control="public, max-age=31536000" --content-type=image/webp
```

## Map

Public web map in ArcGIS Online, with the BGR GÜK250 and SGU bedrock layers,
Arcade pop-ups and one bookmark per field trip:
https://www.arcgis.com/apps/mapviewer/index.html?webmap=1a563f33274041efbc0cc80272f0ae15
