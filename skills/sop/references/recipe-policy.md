# Recipe Promotion Policy

Every recipe needs stable JSON output, stable error codes, an explicit risk level, representative
fixtures, documented completion criteria, and dry-run for writes. Normal writes also require atomic
commit, input/output conflict protection, and idempotency. High-risk operations may generate and
validate a candidate only until the user approves the exact target. Project differences belong in
Profiles, Adapters, contracts, or fixtures; core code must not contain real project paths or knowledge.
