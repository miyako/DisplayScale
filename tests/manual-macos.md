# Manual macOS acceptance

Hosted CI observes only its runner's topology (a headless runner may report
`NO_MONITORS`). Run on real hardware and record the output of
`display-scale monitors` for each case. Local unsigned acceptance does not
replace these checks.

| Case | Expected |
| --- | --- |
| Built-in Retina, default resolution | `scalePercent` 200, `backingScalePercent` 200 |
| Built-in Retina, "More space" | `scalePercent` below 200 (e.g. 168 for a 3024-px panel at 1800 pt); `backingScalePercent` 200 |
| Built-in Retina, "Larger text" | `scalePercent` above the default value; `backingScalePercent` 200 |
| External non-Retina display | `scalePercent` 100, `backingScalePercent` 100 |
| External HiDPI at a scaled mode | `nativePixels` is the panel's native size; `scalePercent` matches `nativePixels.width / point width` |
| Built-in + external | Primary first; `bounds` positions follow Displays arrangement (negative coordinates allowed) |
| Mirrored displays | Mirror set reported once |
| Change resolution mode, then rerun | New values; no stale cache |
| Display unplugged/plugged during query | `TOPOLOGY_CHANGED`, never a partial list |
| Locked/remote/headless session | Explicit `NO_MONITORS` or `MACOS_API_ERROR`, never 100% |
| Apple Silicon and Intel Macs | Same schema; Intel 4D loading is a separate check |
