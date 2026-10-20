"""Export core/contracts to JSON Schema (docs/schemas/) and TypeScript (web/src/types/).

Run with `make contracts`. CI runs `make contracts-check`, which fails if the
committed files no longer match the Python models.
"""

import json
import subprocess
from pathlib import Path

from pydantic.json_schema import models_json_schema

from core.contracts import CONTRACTS

ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = ROOT / "docs" / "schemas"
TS_FILE = ROOT / "web" / "src" / "types" / "contracts.ts"
COMBINED = "contracts.schema.json"
BANNER = "// Generated from core/contracts by `make contracts`. Do not edit."


def model_schemas():
    return {
        model.__name__: model.model_json_schema(mode="serialization")
        for model in CONTRACTS
    }


def combined_schema():
    _, schema = models_json_schema(
        [(model, "serialization") for model in CONTRACTS],
        ref_template="#/$defs/{model}",
    )
    defs = {name: strip_property_titles(d) for name, d in schema["$defs"].items()}
    return {
        "title": "Contracts",
        "type": "object",
        "properties": {
            m.__name__: {"$ref": f"#/$defs/{m.__name__}"} for m in CONTRACTS
        },
        "additionalProperties": False,
        "$defs": defs,
    }


def strip_property_titles(node):
    # Pydantic titles every field; json2ts would turn each into a named alias.
    if isinstance(node, dict):
        node = {k: strip_property_titles(v) for k, v in node.items()}
        for prop in node.get("properties", {}).values():
            prop.pop("title", None)
        return node
    if isinstance(node, list):
        return [strip_property_titles(v) for v in node]
    return node


def dump(obj):
    return json.dumps(obj, indent=2, sort_keys=True) + "\n"


def main():
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    for name, schema in model_schemas().items():
        (SCHEMA_DIR / f"{name}.schema.json").write_text(dump(schema))
    (SCHEMA_DIR / COMBINED).write_text(dump(combined_schema()))

    TS_FILE.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "npx",
            "--no-install",
            "json2ts",
            "--input",
            str(SCHEMA_DIR / COMBINED),
            "--output",
            str(TS_FILE),
            "--bannerComment",
            BANNER,
            "--additionalProperties",
            "false",
        ],
        cwd=ROOT / "web",
        check=True,
    )


if __name__ == "__main__":
    main()
