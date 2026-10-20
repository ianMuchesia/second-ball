import json

from scripts.export_contracts import (
    COMBINED,
    SCHEMA_DIR,
    combined_schema,
    model_schemas,
)


def committed(name):
    return json.loads((SCHEMA_DIR / name).read_text())


def test_committed_schemas_match_python_models():
    for name, schema in model_schemas().items():
        assert committed(f"{name}.schema.json") == schema, (
            f"run `make contracts` ({name})"
        )
    assert committed(COMBINED) == combined_schema(), "run `make contracts`"
