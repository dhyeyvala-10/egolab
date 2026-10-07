"""Print the OpenAPI schema. The web app generates its TypeScript types from it (`npm run gen:api`)."""

import json
import sys

from egolabs.app import create_app


def main() -> None:
    json.dump(create_app().openapi(), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
