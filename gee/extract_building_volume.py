"""
Annual building volume by Indian district from Google Open Buildings 2.5D Temporal.

Source: GOOGLE/Research/open-buildings-temporal/v1
  - ImageCollection of annual snapshots, one image per year, 2016-2023
  - Bands: building_height (m, [0,100]), building_presence (model confidence,
    [0,1]), building_fractional_count (sums to building COUNT).
  - Rasters are delivered at 0.5 m; effective resolution is ~4 m.

ONLY QUANTITIES LINEAR IN THE PIXEL VALUES ARE SAFE HERE.
We reduce at SCALE_M (100 m), far coarser than native, and Earth Engine
pyramids continuous bands by MEAN before the reducer sees them. Mean-pyramiding
preserves integrals, so `band * pixel_area` gives the same answer at 100 m as at
0.5 m. A threshold does NOT commute with averaging, so `(band > t) * pixel_area`
is computed on already-averaged pixels and measures something else entirely.

That is what the old `footprint_m2 = sum((building_height > 0) * pixel_area)`
did: a 100 m cell holding one 100 m2 building has pyramid-mean height ~0.05 m,
passes `> 0`, and contributes the FULL 10,000 m2. It measured the area of 100 m
cells containing any structure -- built-up extent, inflated by roughly the
inverse of built-up density -- not building footprint. The symptom was a
district mean height of ~0.5 m (= true height x built-up fraction).

For each (district, year) we compute:
  - volume_m3    : sum( building_height * pixel_area )
                   Linear, hence exact at any reduction scale. Unchanged.
  - footprint_m2 : sum( building_presence * pixel_area )     [default]
                   Expected built area. Linear, so exact at 100 m, and free of
                   the threshold cliff that makes pixels near the cutoff flip in
                   and out between years -- which matters for growth rates.
                   Caveat: presence confidence is uncalibrated, so the LEVEL is
                   biased and that bias may drift over time. We take a biased-
                   but-linear estimator over a threshold that is simply wrong at
                   this scale. Use --footprint threshold for the alternative.
  - building_count : sum( building_fractional_count )
                   Linear. Least sensitive to the height model of the three.
  - extent_m2    : sum( (building_height > 0) * pixel_area )
                   The OLD footprint definition, kept so the corrected series
                   can be diffed against existing data/raw/buildings_*.csv.
                   Interpret as built-up extent at SCALE_M, not as footprint.
  - mean_height  : volume_m3 / footprint_m2  (derived downstream)

With --footprint threshold, footprint_m2 instead uses the conventional
`building_presence >= --presence-threshold` mask, applied at NATIVE resolution
and averaged up to a built FRACTION with reduceResolution before being turned
into an area, so the threshold precedes the averaging. Physically interpretable
m2, but much slower. Spot-checked at 100 m against the presence estimator:
0.73x on a sparse rural box, 1.06x on dense urban Mumbai -- thresholding drops
low-confidence pixels entirely where the presence weighting still counts them,
and gives full weight to confident pixels where the weighting discounts them.

Output: one CSV per year exported to Google Drive folder
        `Districts-Of-India-Buildings`.

District boundaries can be supplied either as
  --asset  <gee-asset-id>       (FeatureCollection already uploaded to GEE)
or
  --geojson data/clean/districts_simplified.geojson
                                (loaded inline; useful when no GCS bucket is
                                 available for `earthengine upload table`)

Usage:
  python gee/extract_building_volume.py \
      --project gee-ntl-470405 \
      --geojson data/clean/districts_simplified.geojson \
      --start 2016 --end 2023
"""

import argparse
import json
import ee


COLLECTION = "GOOGLE/Research/open-buildings-temporal/v1"
SCALE_M = 100  # native ~4 m; 100 m is enough at district granularity and much faster

# Rasters ship at 0.5 m in a per-tile UTM CRS (effective resolution ~4 m).
# NB: mosaic() discards that projection -- the mosaic reports EPSG:4326 at
# ~111 km -- so anything projection-sensitive must be done per-image, BEFORE
# mosaicking, and anything per-pixel must be converted to a per-area density
# using the constant below rather than read off the mosaic.
NATIVE_SCALE_M = 0.5
NATIVE_PIXEL_AREA_M2 = NATIVE_SCALE_M ** 2  # UTM is metric, so this is exact
DRIVE_FOLDER = "Districts-Of-India-Buildings"

ID_COLUMNS = ["pc11_s_id", "pc11_d_id", "d_name"]


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--asset", help="GEE FeatureCollection asset id")
    src.add_argument("--geojson", help="Path to a local GeoJSON of districts")
    p.add_argument("--start", type=int, default=2016)
    p.add_argument("--end", type=int, default=2023)
    p.add_argument("--scale", type=int, default=SCALE_M,
                   help=f"Reduction scale in metres (default {SCALE_M})")
    p.add_argument("--footprint", choices=["presence", "threshold"],
                   default="presence",
                   help="footprint_m2 estimator: 'presence' = sum(presence * "
                        "area), linear and exact at any scale (default); "
                        "'threshold' = sum(presence >= t) * area applied at "
                        "native resolution, physically interpretable but slow")
    p.add_argument("--presence-threshold", type=float, default=0.5,
                   help="Confidence cutoff for --footprint threshold (default 0.5)")
    p.add_argument("--project", default=None)
    return p.parse_args()


def fc_from_geojson(path):
    with open(path) as f:
        gj = json.load(f)
    feats = []
    for feat in gj["features"]:
        geom = ee.Geometry(feat["geometry"], proj="EPSG:4326", geodesic=False)
        props = {k: feat["properties"].get(k) for k in ID_COLUMNS}
        feats.append(ee.Feature(geom, props))
    return ee.FeatureCollection(feats)


def year_image(year, scale, footprint_mode="presence", presence_threshold=0.5):
    """Annual image carrying the per-district sum bands.

    Every band here is linear in the pixel values -- `band * pixel_area` --
    which is what makes the reduction at `scale` exact despite mean-pyramiding.
    The one exception is `extent_m2`, retained only for backward comparison,
    and `footprint_m2` under --footprint threshold, which handles the
    non-linearity explicitly via reduceResolution at native resolution.
    """
    start = ee.Date.fromYMD(year, 1, 1)
    end = ee.Date.fromYMD(year + 1, 1, 1)
    coll = ee.ImageCollection(COLLECTION).filterDate(start, end)
    img = coll.mosaic()

    pixel_area = ee.Image.pixelArea()
    height = img.select("building_height")
    presence = img.select("building_presence")
    frac_count = img.select("building_fractional_count")

    volume = height.multiply(pixel_area).rename("volume_m3")
    # Old definition. Built-up extent at `scale`, NOT footprint -- see module docstring.
    extent = pixel_area.multiply(height.gt(0)).rename("extent_m2")

    # building_fractional_count is a count PER NATIVE PIXEL, not a density, so
    # summing pyramid-averaged values silently drops the (scale/0.5)^2
    # aggregation factor. Convert to count per m2 first; that IS linear in area
    # and therefore exact at any reduction scale.
    count = (frac_count.divide(NATIVE_PIXEL_AREA_M2)
             .multiply(pixel_area).rename("building_count"))

    if footprint_mode == "presence":
        footprint = presence.multiply(pixel_area).rename("footprint_m2")
    elif footprint_mode == "threshold":
        # Threshold FIRST, in each tile's own native UTM projection, then sum up
        # to `scale`. Done per-image because mosaic() would have thrown the
        # projection away. 0.5 m -> 100 m is 200x200 = 40,000 pixels, inside the
        # 65,535 cap.
        def agg(im):
            p = im.select("building_presence")
            # Average the 0/1 mask to a built FRACTION, then convert to area at
            # the coarse scale. Keeping pixelArea() outside reduceResolution
            # matters: inside, it is evaluated against the requested pyramid
            # level rather than the native grid.
            return (p.gte(presence_threshold)
                    .reduceResolution(reducer=ee.Reducer.mean(),
                                      maxPixels=65535, bestEffort=True)
                    .reproject(crs=p.projection().atScale(scale)))

        built_fraction = coll.map(agg).mosaic()
        footprint = built_fraction.multiply(pixel_area).rename("footprint_m2")
    else:
        raise ValueError(f"unknown footprint_mode: {footprint_mode}")

    return volume.addBands(footprint).addBands(count).addBands(extent)


BANDS = ["footprint_m2", "volume_m3", "building_count", "extent_m2"]


def export_year(year, districts, id_cols, scale,
                footprint_mode="presence", presence_threshold=0.5):
    img = year_image(year, scale, footprint_mode, presence_threshold)

    reduced = img.reduceRegions(
        collection=districts,
        reducer=ee.Reducer.sum(),
        scale=scale,
        tileScale=8,
    )

    def tag(f):
        return ee.Feature(None,
                          f.toDictionary(id_cols + BANDS).set("year", year))

    fc = reduced.map(tag)

    desc = f"buildings_{year}"
    task = ee.batch.Export.table.toDrive(
        collection=fc,
        description=desc,
        folder=DRIVE_FOLDER,
        fileNamePrefix=desc,
        fileFormat="CSV",
        selectors=id_cols + ["year"] + BANDS,
    )
    task.start()
    print(f"  [{year}] task started: {task.id}")


def main():
    args = parse_args()

    if args.project:
        ee.Initialize(project=args.project)
    else:
        ee.Initialize()

    if args.asset:
        districts = ee.FeatureCollection(args.asset)
    else:
        districts = fc_from_geojson(args.geojson)
    print(f"Districts loaded: {districts.size().getInfo()} features")

    print(f"footprint_m2 estimator: {args.footprint}"
          + (f" (presence >= {args.presence_threshold})"
             if args.footprint == "threshold" else ""))

    for year in range(args.start, args.end + 1):
        export_year(year, districts, ID_COLUMNS, args.scale,
                    args.footprint, args.presence_threshold)

    print(f"\nAll tasks queued. Monitor at https://code.earthengine.google.com/tasks")
    print(f"CSVs will appear in Google Drive folder: {DRIVE_FOLDER}/")


if __name__ == "__main__":
    main()
