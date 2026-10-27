# Cloud snapshots and live operations

The public DSH page and static assets are served by the bridge server. Authenticated list, balance, status and history reads use a separate dsh-history.db database. Browser sessions and device management are shared with the Codex public entry. Local pages keep their existing loopback access.

Windows runs independent outbound history and metadata synchronization workers alongside the command relay. Summaries, reversible hide/pin metadata and public settings are uploaded periodically. A history upload contains at most one conversation; the shared history-store module retains six recent turns and separate requested older windows. The first three recent conversations may be warmed in the background. No browser conversation is selected or read automatically.

The server returns available snapshots immediately. Selecting a conversation registers interest for asynchronous refresh. Cached content stays readable when Windows is offline, with explicit stale/offline labels. A conversation that has never been cached shows a waiting/unavailable notice. Independent per-metadata timestamps prevent an active history heartbeat from making an old wallet value appear fresh.

Messages, model/permission changes, approvals, voice generation, attachments and other live operations retain the existing authenticated outbound relay. A successful write can update related cached metadata. Writes are never automatically replayed after an ambiguous timeout. The initial deployment remains compatible with an older Windows process: until its first catalog snapshot arrives, API reads continue through the existing relay.

Model execution, runtime credentials and voice API keys stay on Windows. Static assets and read-only snapshots use the existing owner authentication. Static files support private browser caching and ETags; APIs remain no-store. Codex and DSH histories use separate databases and namespaces.

The Codex server deployment includes cloud/dsh_gateway.py, cloud/dsh_snapshots.py and the DSH web assets in dsh-web/. The Windows DSH bridge must load app/snapshot_sync.py after a user-authorized restart. Do not restart Windows or unrelated server projects.
