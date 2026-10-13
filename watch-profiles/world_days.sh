#!/usr/bin/env bash
set -Eeuo pipefail

# World-Days is source-first: datasets and platform scaffolding are generated
# deterministically before Flutter analysis/build. Mirror its own CI contract.
./tool/bootstrap_platforms.sh
python3 tool/validate_dataset.py
python3 tool/validate_editorial.py
python3 tool/validate_editorial_locales.py
python3 tool/validate_discovery.py
python3 tool/validate_localizations.py
