# Conversation list

The default view shows pinned conversations first, followed by recorded recent activity across projects. The project view keeps the existing project grouping order. The browser remembers the selected view independently for each provider. Search and frontend ordering apply to loaded conversations; use Load more for older results. A refresh, sync heartbeat, or merely opening a conversation does not count as activity.

Use the three-dot button beside a conversation for management actions. Pinned conversations are ordered by activity within their section. Hiding affects only the bridge list; it never deletes history, cancels a task, or archives a native session. Hidden conversations can be restored from the sidebar. DeepSeek stores these preferences in its private bridge data directory and shares them between the local and relay webpages.

DeepSeek ranks event activity and pins before pagination. Activity comes from recorded user/assistant messages, turn events, and tool events. Read-only metadata queries use up to four workers, with a 60-second cache for inactive sessions and five seconds for live sessions. Cached history can temporarily lag behind native activity. No testing conversations are automatically classified or hidden.

Code changes require the local bridge process to reload before new backend metadata and actions become available. Cloud static assets must also be deployed. This document does not authorize a restart or deployment.

Page entry and reload now wait for a manual conversation selection, even if the browser remembers the previous conversation or the URL contains a thread parameter. Merely entering the page does not request conversation bodies.
