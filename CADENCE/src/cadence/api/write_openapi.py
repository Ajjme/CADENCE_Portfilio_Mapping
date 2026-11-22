"""Write the API's schema to frontend/openapi.json, for the frontend's TypeScript types.

Run it after changing an endpoint in main.py or a model in schemas.py:

    python -m cadence.api.write_openapi

then, from the frontend folder, run `npm run api:types`. tests/test_api.py fails
until the saved schema matches the API, so the frontend can't fall out of step.
"""

from __future__ import annotations

import json

from cadence.api.main import app
from cadence.ui.paths import CADENCE_ROOT

SCHEMA_PATH = CADENCE_ROOT.parent / "frontend" / "openapi.json"


def schema_text() -> str:
    return json.dumps(app.openapi(), indent=2) + "\n"


def main() -> None:
    SCHEMA_PATH.write_text(schema_text(), encoding="utf-8")
    print(f"Wrote {SCHEMA_PATH}")


if __name__ == "__main__":
    main()
