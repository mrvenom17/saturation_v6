# Flood signal saturation study (pipeline v6.1.2)

Code, pre-registration and outputs of a pre-registered test of whether a geoparsed news / social-media layer adds
information to physical flood-susceptibility models, across ten flood events.

## Layout
| Path | What it is |
|---|---|
| `saturation_v6_1_2.ipynb` | The Colab notebook that runs everything (acquisition and analysis). |
| `code_v6_1_2/` | The five modules the notebook loads, split into parts at function boundaries, with `_manifest.json` (SHA-256 of each reassembled module; the notebook refuses edited files). |
| `outputs/INDEX.md` | Written by the pipeline: what every folder and `*_ERROR.txt` is, which events are in the study set. |
| `outputs/preregistration.json` | The pre-registration in force (`sha256`); earlier versions are `preregistration_<sha8>.json`. |
| `outputs/deviations.md` | Every change to the pre-registration, with the date and the reason. |
| `outputs/paper_synthesis/` | Cross-city tables T1–T14 and `RESULTS_SUMMARY.md`. T12–T14 are post-hoc (v6.1.2). |
| `outputs/<event>/` | Per-event results: effects, ladders, nulls, bootstrap, sensitivity, placebo, calibration, maps. |
| `outputs/archive_<sha8>/` | The cross-city tables produced under an earlier pre-registration. |

## Study set
Chennai 2015, Valencia 2024, Emilia-Romagna 2023 (first wave), Forlì 2023, York 2015, Carlisle 2015, Porto Alegre 2024,
Taquari Valley 2024, Houston / San Jacinto 2017 (tier A, authoritative labels) and Jakarta 2020 (tier B, crowdsourced
label, never pooled). Other event folders in `outputs/` come from acquisitions for an earlier design and are not
part of the study; `INDEX.md` says which.

## Reproducing
1. Open the notebook in Google Colab, set `GCP_PROJECT` and `CONTACT` in cell 2, add optional API keys as Colab
   secrets (`FLICKR_API_KEY`, `YOUTUBE_API_KEY`, `WIKIMEDIA_ACCESS_TOKEN`).
2. Run all with `RUN_MODE="acquire"` until every event shows `complete = True`, then with `RUN_MODE="analyse"`.
3. `requirements.txt` lists the package versions recorded by the analysis run.

Earth Engine, BigQuery (GDELT), GeoNames, Nominatim and the social sources need network access; the analysis step
needs none. Licences of the third-party data are listed in the notebook's data table.
