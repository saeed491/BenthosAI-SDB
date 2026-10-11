"""Download the example Sentinel-2 input used by the BenthosAI SDB proof of concept.

Fetches three Sentinel-2 Level-2A scenes over Jebel Dhanna (Abu Dhabi, UAE) from the
Microsoft Planetary Computer STAC (free, no account needed) and writes small clips to
data/sample_input/:

  S2_<date>_aoi10m.tif   bands B01 B02 B03 B04 B05 B08 B11 SCL, 10 m, 400 x 580 px
  S2_<date>_ctx60m.tif   same bands, 60 m, 290 x 290 px (wider context for deep-water reference)
  s2_scenes.json         scene IDs, acquisition time, processing baseline, sun zenith

Run from the repository root:   python scripts/download_sample.py
"""
import json
import os
import sys

import numpy as np
import planetary_computer
import pystac_client
import rasterio
from odc.geo.geobox import GeoBox
import odc.stac

STAC_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION = "sentinel-2-l2a"
CRS = "EPSG:32639"                       # UTM zone 39N (Sentinel-2 tile T39QXG)
SCENE_IDS = [
    "S2A_MSIL2A_20220829T065641_R063_T39QXG_20240718T033121",
    "S2B_MSIL2A_20220903T065629_R063_T39QXG_20220903T175254",
    "S2B_MSIL2A_20220923T065629_R063_T39QXG_20240725T151945",
]
BANDS = ["B01", "B02", "B03", "B04", "B05", "B08", "B11", "SCL"]
AOI_BOUNDS = (659500, 2676900, 663500, 2682700)      # x0, y0, x1, y1 in metres (UTM 39N)
CTX_BOUNDS = (653000, 2671000, 670400, 2688400)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "data", "sample_input")


def write_tif(path, ds, gbox):
    arr = np.stack([np.nan_to_num(ds[b].values, nan=0).astype("uint16") for b in BANDS])
    prof = dict(driver="GTiff", width=gbox.width, height=gbox.height, count=len(BANDS), dtype="uint16",
                crs=CRS, transform=gbox.transform, compress="deflate", predictor=2, nodata=0)
    with rasterio.open(path, "w", **prof) as dst:
        dst.write(arr)
        for i, b in enumerate(BANDS, 1):
            dst.set_band_description(i, b)


def main():
    os.makedirs(OUT, exist_ok=True)
    cat = pystac_client.Client.open(STAC_URL, modifier=planetary_computer.sign_inplace)
    items = list(cat.search(collections=[COLLECTION], ids=SCENE_IDS).items())
    if len(items) != len(SCENE_IDS):
        sys.exit(f"Expected {len(SCENE_IDS)} scenes, found {len(items)}: {[i.id for i in items]}")
    aoi_box = GeoBox.from_bbox(AOI_BOUNDS, crs=CRS, resolution=10)
    ctx_box = GeoBox.from_bbox(CTX_BOUNDS, crs=CRS, resolution=60)
    meta = []
    for it in sorted(items, key=lambda i: i.datetime):
        date = it.datetime.strftime("%Y%m%d")
        print(f"{it.id}  ({it.datetime:%Y-%m-%d %H:%M} UTC)")
        aoi = odc.stac.load([it], bands=BANDS, geobox=aoi_box,
                            resampling={"SCL": "nearest", "*": "bilinear"}).isel(time=0)
        ctx = odc.stac.load([it], bands=BANDS, geobox=ctx_box,
                            resampling={"SCL": "mode", "*": "average"}).isel(time=0)
        write_tif(os.path.join(OUT, f"S2_{date}_aoi10m.tif"), aoi, aoi_box)
        write_tif(os.path.join(OUT, f"S2_{date}_ctx60m.tif"), ctx, ctx_box)
        meta.append(dict(id=it.id, date=f"{it.datetime:%Y-%m-%d}", datetime_utc=it.datetime.isoformat(),
                         processing_baseline=it.properties.get("s2:processing_baseline"),
                         sun_zenith_deg=it.properties.get("s2:mean_solar_zenith"),
                         cloud_cover_pct=it.properties.get("eo:cloud_cover"),
                         aoi_file=f"S2_{date}_aoi10m.tif", ctx_file=f"S2_{date}_ctx60m.tif"))
    with open(os.path.join(OUT, "s2_scenes.json"), "w") as fh:
        json.dump(dict(source=STAC_URL, collection=COLLECTION, crs=CRS, aoi_bounds=AOI_BOUNDS,
                       ctx_bounds=CTX_BOUNDS, bands=BANDS, scenes=meta), fh, indent=2)
    print(f"Done. Files written to {OUT}")


if __name__ == "__main__":
    main()
