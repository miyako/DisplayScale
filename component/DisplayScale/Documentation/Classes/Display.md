# Display

`cs.DisplayScale.Display.new("Windows-x64")` (or `"macOS-universal"`) constructs the synchronous,
read-only feature API. Internally the class is `cs.Display`. The independent
namespace `DisplayScale` must not conflict with another component in your host;
the initializer cannot establish uniqueness across future dependencies.

| Method | Result |
| --- | --- |
| `monitors() : Object` | Query effective scaling currently applied to every monitor in the calling desktop/session |
| `version() : Object` | Check bundled CLI protocol/version |

Supported feature platform: **Windows 10 version 1703 (build 15063) or later /
Windows 11, x64** (pass `"Windows-x64"`) and **macOS 11+**, Apple Silicon and
Intel (pass `"macOS-universal"`). Windows ARM64, including x64 emulation, is
not a support promise.

```4d
var $display : cs.DisplayScale.Display
var $result; $monitor : Object
$display:=cs.DisplayScale.Display.new("Windows-x64")
$result:=$display.monitors()
If ($result.ok)
  For each ($monitor; $result.value.monitors)
    // scalePercent is a Real; do not coerce to Integer.
    ALERT($monitor.device+": "+String($monitor.scalePercent)+"%")
  End for each
Else
  ALERT($result.error.code+": "+$result.error.message)
End if
```

Successful calls return `{ok:true,stdout:Text,stderr:Text,exitCode:0,value:Object}`.
`monitors().value` contains:

```json
{
  "protocol": 2,
  "platform": "windows",
  "monitors": [{
    "device": "\\\\.\\DISPLAY1",
    "primary": true,
    "bounds": {"left": 0, "top": 0, "right": 1920, "bottom": 1080},
    "dpi": 120,
    "scalePercent": 125
  }]
}
```

On macOS `platform` is `"macos"` and each monitor has no `dpi`; it has
`bounds` in points, `backingPixels`/`nativePixels` (`{width,height}`),
`backingScalePercent` and `scalePercent`:

```json
{
  "protocol": 2,
  "platform": "macos",
  "monitors": [{
    "device": "display-1",
    "primary": true,
    "bounds": {"left": 0, "top": 0, "right": 1800, "bottom": 1169},
    "backingPixels": {"width": 3600, "height": 2338},
    "nativePixels": {"width": 3024, "height": 1964},
    "backingScalePercent": 200,
    "scalePercent": 168
  }]
}
```

`scalePercent` is `nativePixels.width / (bounds.right - bounds.left) * 100`
(effective UI size relative to physical panel pixels; non-integer for "More
space"); `backingScalePercent` uses the current mode's backing pixels (200 for
every Retina mode). macOS bounds are CoreGraphics global points, so they are not
comparable with Windows physical-pixel bounds. `device` is
`display-<CGDirectDisplayID>` for the current session only. Mirror sets are
reported once. No active display or topology churn is an
error, never an assumed 100%.

The Windows example above is an illustrative topology, not a fixed test expectation. Bounds are
physical desktop pixel coordinates in the helper's per-monitor-aware context;
left/top can be negative. `dpi` is the effective DPI applied to a helper-owned
window on that monitor, **not raw physical panel DPI**. `scalePercent` is
`dpi / 96.0 * 100.0` without integer/enum rounding (121 DPI is approximately
126.04166666666667%). Windows DPI granularity can make this differ slightly
from a user-entered custom percentage. This API does not expose the registry's
saved percentage or a custom setting pending sign-out.

`device` comes from `MONITORINFOEXW.szDevice`, identifying the monitor in the
current session/topology. It is not a permanent hardware GUID. Results are
primary first, then sorted by device; array indices do **not** correspond to
Windows Settings display numbers or 4D screen numbers. No mapping to a 4D
window is supplied.

Each call launches a fresh CLI with a finite 30-second timeout; no subscriptions,
caching, settings writes, focus changes or shared per-call state. Results are
a bounded observation, not an atomic operating-system snapshot. Detected
topology changes fail the whole query; no partial monitor list or assumed
96 DPI/100% is returned. Requery after changes or transient errors.

Failures preserve stdout/stderr/exitCode when available, with
`ok:false,error:{code,message{,details}}`. Prelaunch failures do not invent an
exit code. Generic adapter codes include `missing_executable`,
`unsupported_platform`, `unsupported_architecture`, `invalid_argument`,
`launch_failed`, `process_error`, `process_terminated`, and `cli_error`.
A nonzero CLI exit is `cli_error`; its message retains the **original native
error JSON on stderr**, including the uppercase operational code. A nonempty
stderr alone is not a failure. Invalid JSON, wrong framing/version/types,
empty/duplicate monitors, invalid bounds/DPI, missing primary or inconsistent
scaling is `invalid_protocol`; no decoded `value` is produced.

The generic `_CLI`/`_Process` adapter uses bundled Resources only, quotes literal
arguments into SystemWorker command-line Text, closes stdin and captures errors
narrowly. It does not modify the 4D host's DPI awareness, use a shell, download
executables or fall back to PATH. `_decode` and `_cli` are internal by convention,
not a language access-control boundary.
