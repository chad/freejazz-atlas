"""Load and save venue/musician YAML records from the data/ tree."""

from __future__ import annotations

import os
from pathlib import Path

import yaml

# Repo root = parent of the atlas/ package dir.
ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
VENUES_DIR = DATA / "venues"
MUSICIANS_DIR = DATA / "musicians"


def _load_dir(path: Path) -> list:
    records = []
    if not path.exists():
        return records
    for f in sorted(path.glob("*.yaml")):
        with open(f, "r", encoding="utf-8") as fh:
            doc = yaml.safe_load(fh)
        if doc is None:
            continue
        doc["_path"] = str(f)
        records.append(doc)
    return records


def load_venues() -> list:
    return _load_dir(VENUES_DIR)


def load_musicians() -> list:
    return _load_dir(MUSICIANS_DIR)


# YAML dump tuned for human-editable, diff-friendly files.
class _Dumper(yaml.SafeDumper):
    pass


def _str_presenter(dumper, data):
    style = "|" if "\n" in data else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style=style)


_Dumper.add_representer(str, _str_presenter)


def dump_record(record: dict) -> str:
    clean = {k: v for k, v in record.items() if not k.startswith("_")}
    return yaml.dump(
        clean,
        Dumper=_Dumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=88,
    )


def save_venue(record: dict, path: str | None = None) -> str:
    path = path or record.get("_path")
    if not path:
        path = str(VENUES_DIR / f"{record['id']}.yaml")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(dump_record(record))
    return path
