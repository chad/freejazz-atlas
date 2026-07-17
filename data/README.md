# Data

This directory is the canonical dataset: one YAML file per venue
(`venues/`) and per musician (`musicians/`). These files are meant to be edited
by hand and by pull request. See [`../docs/DATA_MODEL.md`](../docs/DATA_MODEL.md)
for the schema and [`../CONTRIBUTING.md`](../CONTRIBUTING.md) for how to add or
correct an entry.

## Provenance & confidence

Every record records who added it, when, from what sources, and whether it still
needs human review. Entries carry a `confidence` (0–1). Verified-this-session
seed entries sit around 0.8–0.9; well-known venues not re-verified this session
are ~0.5 and marked `needs_human_review: true`. See the rubric for how score and
confidence differ.

## License

The data in this directory is dedicated to the public domain under
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/). Mirror it,
correct it, and build on it freely. Attribution is appreciated but not required.
