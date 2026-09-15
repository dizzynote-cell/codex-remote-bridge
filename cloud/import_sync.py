# SPDX-License-Identifier: MIT
# Copyright (c) 2026 xiyannan
# Project: Codex Remote Bridge

import json, sqlite3, sys
import history_store

DB='/opt/codex-history/data/history.db'
db=sqlite3.connect(DB,timeout=10)
history_store.initialize(db)
print(json.dumps(history_store.ingest(db,json.load(sys.stdin))))
