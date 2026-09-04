# Marker file so tests/fixtures/ is importable as a Python package.
# Gold standard YAML files in this directory are loaded via
# ``yaml.safe_load(Path(...).read_text(...))`` — no Python imports are
# expected, but having the package marker keeps tooling consistent with
# the rest of tests/.
