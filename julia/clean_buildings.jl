#!/usr/bin/env julia
# Concatenate per-year Open Buildings CSVs into a single district-year panel.
#
# Input  : data/raw/buildings_<year>.csv     (one file per year from GEE)
# Output : data/clean/bv_annual.csv
#          columns: pc11_s_id, pc11_d_id, d_name, year,
#                   footprint_m2, volume_m3, building_count, extent_m2,
#                   mean_height_m, builtup_density
#
# mean_height_m is only a real height once footprint_m2 comes from the presence
# band. Against the old `building_height > 0` footprint it came out around 0.5 m
# nationally, because that denominator was built-up EXTENT at the 100 m
# reduction scale rather than building area -- see gee/extract_building_volume.py.
# extent_m2 is that old measure, retained for comparison.

using CSV
using DataFrames

const ROOT      = joinpath(@__DIR__, "..")
const RAW_DIR   = joinpath(ROOT, "data", "raw")
const CLEAN_DIR = joinpath(ROOT, "data", "clean")

function main()
    files = sort(filter(f -> startswith(f, "buildings_") && endswith(f, ".csv"),
                        readdir(RAW_DIR)))
    isempty(files) && error("No buildings_*.csv in $RAW_DIR")
    df = reduce(vcat, [CSV.read(joinpath(RAW_DIR, f), DataFrame) for f in files])
    df = df[df.footprint_m2 .> 0, :]
    df.year = Int.(df.year)
    # Mean building height over built area (m).
    df.mean_height_m = df.volume_m3 ./ df.footprint_m2
    # Share of built-up extent that is actually building. Only defined against
    # the legacy extent band, so skip it on older exports that lack the column.
    if hasproperty(df, :extent_m2)
        df.builtup_density = ifelse.(df.extent_m2 .> 0,
                                     df.footprint_m2 ./ df.extent_m2,
                                     missing)
    end
    sort!(df, [:pc11_s_id, :pc11_d_id, :year])

    mkpath(CLEAN_DIR)
    out = joinpath(CLEAN_DIR, "bv_annual.csv")
    CSV.write(out, df)
    println("wrote $(nrow(df)) rows → $out")
end

isinteractive() || main()
