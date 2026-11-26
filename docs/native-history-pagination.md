# Native history pagination

The Windows bridge reads thread metadata with `thread/read` and
`includeTurns: false`, then reads the requested window with
`thread/turns/list`, `sortDirection: desc`, and `itemsView: full`.
The default window is six turns. Native `nextCursor` values remain opaque;
the bridge follows them when the requested window spans multiple pages,
deduplicates turn IDs, then renders turns chronologically.

The native response does not include an exact total. Until the oldest page
has been reached, `bridgeTotalTurns` is null and `bridgeHasMoreTurns` tells
the browser whether older history exists. The UI displays the loaded recent
count and offers another six turns or an explicit full-history request.
It does not load all turns just to calculate a total.

The server's ordinary `threads` payload stores at most six turns. An explicitly
expanded window is cached separately in `history_windows`; later six-turn
updates preserve that window and replace overlapping recent turns. Disjoint
windows are re-requested rather than joined across a gap. This does not change
or trim the native conversation or the model's context.

Task-state polling uses the recent window. Resuming for message submission
sets `excludeTurns: true`. Explicit older voice playback and Feishu history
requests still load the history needed for that user action.

Only a runtime that explicitly lacks the turn-pagination method may use the
legacy full-history read as a compatibility fallback. Transport, ownership,
invalid-page and incomplete-item failures do not trigger that fallback.

Reference: [Codex App Server history APIs](https://learn.chatgpt.com/docs/app-server#list-thread-turns).
