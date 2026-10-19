"""Field photos x geology.

Reads the GPS position of every photo in PHOTO_ROOT/<course folder>/, looks up the
bedrock or surface geology under each point at the national geological survey
(BGR for Germany, SGU for Sweden), writes web previews without any metadata and
one GeoJSON point layer for ArcGIS Online.

    python build.py "C:/Users/mateu/Pictures/geology"
"""
import json
import re
import sys
import time
from pathlib import Path

import requests
from PIL import Image, ImageOps

HERE = Path(__file__).parent
COURSES = json.loads((HERE / "courses.json").read_text(encoding="utf-8"))
TERMS = json.loads((HERE / "terms_de_en.json").read_text(encoding="utf-8"))
OUT = HERE / "out"
SKIP = {"_not-on-map"}
# public bucket that serves out/previews (see README: upload)
IMG_BASE = "https://storage.googleapis.com/morgado-geo-photos"

BGR = "https://services.bgr.de/arcgis/rest/services/geologie/guek250/MapServer/identify"
SGU = "https://maps3.sgu.se/geoserver/berg/ows"
http = requests.Session()
http.headers["User-Agent"] = "geo-photo-map (portfolio project; morgado.tech)"


# ---------- photo metadata ----------
def _deg(dms, ref):
    d, m, s = (float(x) for x in dms)
    v = d + m / 60 + s / 3600
    return -v if ref in ("S", "W") else v


def read_photo(path):
    with Image.open(path) as im:
        exif = im.getexif()
        gps = exif.get_ifd(0x8825)
        sub = exif.get_ifd(0x8769)
    if 2 not in gps or 4 not in gps:
        return None
    taken = sub.get(36867) or exif.get(306)
    return {
        "lat": round(_deg(gps[2], gps.get(1, "N")), 6),
        "lon": round(_deg(gps[4], gps.get(3, "E")), 6),
        "alt_m": round(float(gps[6])) if 6 in gps else None,
        "date": taken[:10].replace(":", "-") if taken else None,
    }


def write_previews(path, slug):
    """Large image and thumbnail as WebP. Pillow writes no EXIF unless asked, so no GPS leaves the machine."""
    with Image.open(path) as im:
        im = ImageOps.exif_transpose(im).convert("RGB")
        for name, edge, q in (("large", 1600, 80), ("thumb", 480, 75)):
            out = OUT / "previews" / name / f"{slug}.webp"
            out.parent.mkdir(parents=True, exist_ok=True)
            copy = im.copy()
            copy.thumbnail((edge, edge), Image.LANCZOS)
            copy.save(out, "WEBP", quality=q, method=6)


# ---------- geology lookups ----------
TERM_RE = re.compile("|".join(re.escape(t) for t in sorted(TERMS, key=len, reverse=True)))


def en(text):
    """German BGR wording to English in one pass, longest terms first so 'Oberjura' beats 'Jura'."""
    if not text:
        return text
    out = TERM_RE.sub(lambda m: TERMS[m.group(0)], text.strip())
    return out[0].upper() + out[1:]


def geology_germany(lat, lon):
    r = http.get(BGR, params={
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "sr": 4326,
        "layers": "all:5,8", "tolerance": 0, "returnGeometry": "false", "f": "json",
        "mapExtent": f"{lon - .01},{lat - .01},{lon + .01},{lat + .01}", "imageDisplay": "400,400,96",
    }, timeout=30)
    r.raise_for_status()
    by_layer = {x["layerId"]: x["attributes"] for x in r.json().get("results", [])}
    strat = by_layer.get(5, {}).get("Stratigraphie - gesamt")
    rock = by_layer.get(8, {}).get("Petrographie - kurz")
    return {
        "geo_age_de": strat,
        "geo_age": en(strat),
        "geo_rock_de": None if rock in (None, "keine Angaben") else rock,
        "geo_rock": None if rock in (None, "keine Angaben") else en(rock),
        "geo_unit": None,
        "geo_source": "BGR, GÜK250 (1:250 000)",
    }


def geology_sweden(lat, lon):
    d = 0.0005
    r = http.get(SGU, params={
        "service": "WMS", "version": "1.3.0", "request": "GetFeatureInfo",
        "layers": "SE.GOV.SGU.BERGGRUND_NA10", "query_layers": "SE.GOV.SGU.BERGGRUND_NA10",
        "crs": "EPSG:4326", "bbox": f"{lat - d},{lon - d},{lat + d},{lon + d}",
        "width": 101, "height": 101, "i": 50, "j": 50, "styles": "",
        "info_format": "application/json",
    }, timeout=30)
    r.raise_for_status()
    feats = r.json().get("features", [])
    p = feats[0]["properties"] if feats else {}
    lith = p.get("lithology") or ""
    age = lith[lith.rfind("(") + 1:-1] if lith.endswith(")") else None
    rock = lith[:lith.rfind("(")].strip() if age else lith or None
    unit = " · ".join(x for x in (p.get("subunit"), p.get("tect_unit")) if x) or None
    return {
        "geo_age_de": None, "geo_age": age,
        "geo_rock_de": None, "geo_rock": rock,
        "geo_unit": unit,
        "geo_source": "SGU, Bedrock 1:50 000–1:250 000",
        "_sgu_props": sorted(p),
    }


# ---------- main ----------
def main(root):
    root = Path(root)
    features, missing = [], []
    for folder in sorted(p for p in root.iterdir() if p.is_dir() and p.name not in SKIP):
        course = COURSES.get(folder.name)
        if not course:
            sys.exit(f"No course entry for folder '{folder.name}' in courses.json")
        for path in sorted(folder.iterdir()):
            if path.suffix.lower() not in (".jpg", ".jpeg"):
                continue
            meta = read_photo(path)
            if not meta:
                missing.append(str(path))
                continue
            slug = f"{folder.name}-{path.stem}".lower().replace(" ", "-")
            write_previews(path, slug)
            geo = geology_sweden(meta["lat"], meta["lon"]) if course["country"] == "Sweden" else geology_germany(meta["lat"], meta["lon"])
            time.sleep(0.3)  # be gentle with the survey services
            props = {"id": slug, "file": path.name, **course, **meta, **geo,
                     "img_url": f"{IMG_BASE}/large/{slug}.webp", "thumb_url": f"{IMG_BASE}/thumb/{slug}.webp"}
            features.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [meta["lon"], meta["lat"]]}, "properties": props})
            print(f"{slug:32} {meta['date']}  {geo['geo_age'] or '-':30} {(geo['geo_rock'] or '-')[:60]}")
    OUT.mkdir(exist_ok=True)
    for f in features:
        f["properties"].pop("_sgu_props", None)
    (OUT / "photos.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n{len(features)} photos written to out/photos.geojson")
    if missing:
        print("No GPS, skipped:", *missing, sep="\n  ")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "photos")
