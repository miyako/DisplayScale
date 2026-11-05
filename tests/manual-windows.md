# Manual Windows acceptance

Record commit/input digest, Windows build, native x64 architecture, compiler,
CLI SHA256, 4D version, desktop session and JSON from each query. Run both
`display-scale monitors` and `cs.DisplayScale.Display.new("Windows-x64").monitors()`
from the source component and the **unpacked final source-stripped compiled ZIP**.
Verify `Is compiled mode` through the host fixture. Never equate CLI success
with Windows 4D loading.

| Scenario | Required observation |
| --- | --- |
| Mixed monitors at 100%, 125%, 150% | All session monitors present exactly once; expected effective DPI 96, 120, 144 and scale 100, 125, 150; compare by device/position, not array numbering |
| Applied custom scaling | Compare observed effective window DPI and scale with the applied setting; record DPI-granularity differences without expecting the exact saved percentage |
| Pending custom scaling | Do not claim a pending/sign-out setting is applied |
| Change scale mid-session | Subsequent calls reflect applied changes without restarting 4D; no caching |
| Reconnect/primary/topology changes during queries | Complete consistent observation or explicit error; no truncated success, duplicates or assumed 96 DPI |
| Monitor left/above primary | Negative physical desktop bounds retained; correct positive rectangle extent |
| Remote Desktop connect/disconnect and reconnect | Results describe that session's topology/scaling; document differences from console |
| Headless/disconnected session | Actual enumerated virtual topology or explicit NO_MONITORS/API error; never fabricated monitor |
| API/awareness/window failure | Nonzero exit, empty stdout, diagnostic JSON; 4D preserves error/status |
| UI behavior | No visible window, activation/focus change, settings writes or host DPI-awareness change |

Save failures as failures with their diagnostics. Unexecuted rows are `not_run`,
not passed or waived. Native Windows CLI hosted CI validates only its observed
topology; these scenarios require separate real environment evidence.
