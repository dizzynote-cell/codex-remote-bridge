# Browser sessions and staged startup

After Feishu owner verification, the Codex page asks whether this is a temporary or personal device. Temporary is the default and expires one hour after login. A personal session expires seven days after login. Access only updates last-seen time; it never extends expiry. Device names and browser/device hints are display metadata, not identity checks. Only the authenticated user choice sets the mode.

The server stores SHA-256 digests of random 256-bit session tokens in browser-sessions.db beside the history database. Cookies are host-only, Secure, HttpOnly and SameSite=Lax. Confirming the device choice rotates the token and invalidates the previous one. Changing the configured owner invalidates saved sessions. Session state survives service restarts; the old in-memory sessions do not migrate and users must authenticate once after this upgrade.

The Login devices button can log out the current device, revoke a selected device, or revoke all other logins. Each subsequent protected request checks server-side validity. Revoking a session does not cancel submitted tasks. Session write endpoints require JSON and reject cross-origin browser requests. Ordinary Codex history and DSH relay access continue using the shared owner authentication; the DSH application and its loading flow are unchanged.

Startup validates authentication and device choice first, renders the conversation list next, then starts independent status, quota, models, interactions and voice settings in parallel after a paint opportunity. Foreground list/history reads prevent new optional reads from starting; existing requests and submitted tasks are not cancelled. A failed list request leaves a retry message and releases the optional stage. No conversation body is requested until the user selects a conversation.

Deployment updates only allowlisted bridge files, creates a backup, checks expected hashes and restarts codex-history.service once. This does not restart Windows bridges or the server machine. The shared public entry will briefly disconnect, including the DSH relay; the local DSH process remains running. Deployment and restart require the user's current authorization.

Explicit logout and detected revoked/expired Codex sessions land on a static signed-out page. That page does not automatically restart OAuth; signing in again requires the user to choose the login link.
