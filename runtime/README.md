# SOP Factory Framework Runtime

This runtime contains the complete deterministic CLI and recipe implementation without bundled
project profiles, adapters, business contracts, learned models, local state, caches, credentials,
or generated artifacts.

Run `python3 sop.py recipe list --json` to inspect capabilities. Add project knowledge through
`profiles/`, `.sop/profiles/`, user configuration, or the adapter directories described in the
root README. Writes remain dry-run by default where supported, and packaging remains high risk.
