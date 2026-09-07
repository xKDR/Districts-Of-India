# India · Built & Lit — build orchestration.
#
# Common entry points:
#   make boundaries        — shapefile → data/clean/districts.geojson (full) +
#                            data/boundaries/districts_simplified.geojson (committed)
#   make export-bv         — queue building-volume tasks on GEE
#   make export-viirs      — queue monthly-VIIRS raster tasks on GEE
#   make tasks             — list current GEE task status
#   make viirs             — run NighttimeLights.clean_complete + zonal aggregation
#   make panel             — merge cleaned VIIRS + raw buildings into district_panel.csv
#   make dashboard         — generate docs/index.html
#   make blog              — article markdown → Blogger-ready article_current.html
#   make quarto            — article markdown → Quarto website in blog/_site/
#   make all               — boundaries → panel → dashboard (assumes raw CSVs already in place)
#   make clean             — remove cleaned outputs (raw GEE downloads kept)
#
# GEE-export targets queue tasks server-side; they DON'T block on completion.
# After they finish, copy the resulting files from Google Drive into:
#     data/raw/viirs/             (viirs_YYYY_MM.tif)
#     data/raw/                   (buildings_YYYY.csv)

PROJECT       ?= gee-ntl-470405
GEOJSON       ?= data/boundaries/districts_simplified.geojson
NTL_URL       ?= https://github.com/xKDR/NighttimeLights.jl

BV_START      ?= 2016
BV_END        ?= 2023

PY            := python3
JULIA         := julia --project=julia --threads=8

RAW_DIR       := data/raw
CLEAN_DIR     := data/clean
DASH_DATA     := docs/data
BLOG          := blog
BLOG_MD       := $(BLOG)/article_current.md $(BLOG)/article_appendix.md
BLOG_HTML     := $(BLOG_MD:.md=.html)
BV_CSVS       := $(wildcard $(RAW_DIR)/buildings_*.csv)

.PHONY: all boundaries export-bv tasks julia-deps viirs bv dashboard blog quarto serve clean help

help:
	@awk 'BEGIN{FS=":.*##"} /^[a-z][a-zA-Z0-9_-]+:.*##/{printf "  %-15s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

all: boundaries bv viirs dashboard  ## boundaries → bv + viirs → dashboard

boundaries: $(CLEAN_DIR)/districts.geojson  ## SHRUG shapefile → GeoJSONs

# One run of prepare_boundaries.jl writes BOTH the full geojson (data/clean/,
# gitignored) and the simplified one (data/boundaries/, committed).
$(CLEAN_DIR)/districts.geojson data/boundaries/districts_simplified.geojson &: \
		data/boundaries/district.shp julia/prepare_boundaries.jl
	$(JULIA) julia/prepare_boundaries.jl

julia-deps:  ## Instantiate the Julia env (NighttimeLights.jl from GitHub)
	$(JULIA) -e 'using Pkg; Pkg.add(url="$(NTL_URL)"); Pkg.instantiate()'

export-bv: $(GEOJSON)  ## Queue building-volume tasks on GEE
	$(PY) gee/extract_building_volume.py \
	    --project $(PROJECT) --geojson $(GEOJSON) \
	    --start $(BV_START) --end $(BV_END)

tasks:  ## List current GEE task status
	earthengine task list | head -30

viirs: $(CLEAN_DIR)/viirs_monthly.csv  ## Per-district readnl + clean_complete + zonal sum (local SL TIFs)

$(CLEAN_DIR)/viirs_monthly.csv: julia/clean_viirs.jl julia/read_district.jl $(CLEAN_DIR)/districts.geojson
	$(JULIA) julia/clean_viirs.jl

bv: $(CLEAN_DIR)/bv_annual.csv  ## Concatenate per-year building CSVs → bv_annual.csv

$(CLEAN_DIR)/bv_annual.csv: julia/clean_buildings.jl $(BV_CSVS)
	$(JULIA) julia/clean_buildings.jl

dashboard: $(DASH_DATA)/districts_simplified.geojson \
           $(DASH_DATA)/bv_annual.csv \
           $(if $(wildcard $(CLEAN_DIR)/viirs_monthly.csv),$(DASH_DATA)/viirs_monthly.csv)  ## Stage data into docs/data/

$(DASH_DATA)/districts_simplified.geojson: data/boundaries/districts_simplified.geojson
	@mkdir -p $(DASH_DATA)
	cp $< $@

$(DASH_DATA)/bv_annual.csv: $(CLEAN_DIR)/bv_annual.csv
	@mkdir -p $(DASH_DATA)
	cp $< $@

$(DASH_DATA)/viirs_monthly.csv: $(CLEAN_DIR)/viirs_monthly.csv
	@mkdir -p $(DASH_DATA)
	cp $< $@

blog: $(BLOG_HTML)  ## Article markdown → Blogger-ready HTML

# One run writes both files, so they are a grouped target -- same shape as the
# boundaries rule above.
$(BLOG_HTML) &: $(BLOG_MD) $(BLOG)/md_to_blog_html.py
	$(PY) $(BLOG)/md_to_blog_html.py

quarto: $(BLOG)/_site/index.html  ## Article + appendix → Quarto website in blog/_site/

# Needs quarto on PATH (https://quarto.org/docs/download/). The .qmd files are
# regenerated every run, so they are ignored by git; blog/_site/ is the artifact.
$(BLOG)/_site/index.html: $(BLOG_MD) $(BLOG)/md_to_quarto.py
	$(PY) $(BLOG)/md_to_quarto.py
	cd $(BLOG) && quarto render .

serve: dashboard  ## Local preview at http://localhost:8080/
	$(PY) -m http.server --directory docs 8080

clean:  ## Remove cleaned outputs, staged dashboard data and the rendered blog site
	rm -f $(CLEAN_DIR)/*.csv $(CLEAN_DIR)/*.geojson
	rm -rf $(DASH_DATA)
	rm -rf $(BLOG)/_site $(BLOG)/.quarto $(BLOG)/*.qmd
