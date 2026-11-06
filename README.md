# DisplayScale

A **real 4D component** wrapping a C++ CLI to read the effective display scaling
currently applied to each monitor on **Windows 10 1703+ / Windows 11 x64**.
Read-only, on demand, with no visible UI or changes to the 4D host's DPI awareness.
This is not a native 4D plug-in.

## Scope and API

Repository, project, component and release identity: `DisplayScale`.
Namespace: `DisplayScale` (independent; check for conflicts in your host).
Feature class: `Display`; executable: `display-scale`; language: C++17.
4D project compatibilityVersion: 2060; local compiler baseline: tool4d 20.7 LTS.
No untested older 4D compatibility is promised.

```4d
var $display : cs.DisplayScale.Display
var $result; $monitor : Object
$display:=cs.DisplayScale.Display.new("Windows-x64")
$result:=$display.monitors()
If ($result.ok)
  For each ($monitor; $result.value.monitors)
    ALERT($monitor.device+": "+String($monitor.scalePercent)+"%")
  End for each
Else
  ALERT($result.error.code+": "+$result.error.message)
End if
```

See the complete [Display API contract](component/DisplayScale/Documentation/Classes/Display.md).
Successful queries preserve `{ok:true,stdout,stderr,exitCode:0,value}`.
Failures retain diagnostics/status and never return partial lists or silently
assume 100%. Calls are synchronous with a 30-second timeout and fresh helper
state. `version()` checks the bundled CLI version.

| Field | Meaning |
| --- | --- |
| `device` | `MONITORINFOEXW.szDevice` identity for the current session/topology, not a permanent hardware GUID |
| `primary` | Primary monitor flag |
| `bounds` | `left`, `top`, `right`, `bottom` in physical desktop pixels; negative coordinates are valid |
| `dpi` | Effective DPI applied to a helper-owned per-monitor-aware window |
| `scalePercent` | `dpi / 96.0 * 100.0`, without integer or predefined scale-enum rounding |

120 DPI gives 125%; 144 gives 150%; fractional results remain Real values.
Applied effective scaling may differ slightly from a custom percentage entered
in Settings due to Windows DPI granularity. This is **not** a registry query,
pending custom scaling, panel physical DPI or a resolution ratio.
Results are primary first, then device-sorted. Enumeration indices are **not**
Windows Settings display numbers or 4D screen numbers.

No macOS feature support, Windows ARM64 promise, settings writes, automatic
event subscription, caching or 4D-window mapping. Remote/headless sessions expose
their own desktop topology, not necessarily physical monitors attached to the
console. No monitors and detected topology churn are explicit errors.

## Native implementation and protocol

The Windows executable declares **PerMonitorV2** DPI awareness in its own
manifest and checks the active process/thread context before creating HWNDs.
It uses `EnumDisplayMonitors` / `GetMonitorInfoW`, creates hidden non-activating
top-level helper windows inside each monitor and checks placement/identity
before using `GetDpiForWindow`. Windows and window-class registrations are
cleaned up. Enumeration is checked again to detect changed topology; no
indefinite retry. The helper does not change the host process's awareness.

Microsoft references:
[GetDpiForWindow](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getdpiforwindow),
[DPI awareness contexts](https://learn.microsoft.com/en-us/windows/win32/hidpi/dpi-awareness-context),
[EnumDisplayMonitors](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-enumdisplaymonitors).
`GetScaleFactorForMonitor` returns a predefined enum, so it is not used to
promise arbitrary custom percentages.
[GetDpiForMonitor](https://learn.microsoft.com/en-us/windows/win32/api/shellscalingapi/nf-shellscalingapi-getdpiformonitor)
warns against calling it from a per-monitor-aware thread; it is not this backend.

Strict UTF-8, protocol 1, **one JSON object plus LF**, including on Windows:

| Command | Exit | Streams |
| --- | --- | --- |
| `display-scale monitors` | 0 | stdout `{"protocol":1,"monitors":[...]}`; empty stderr |
| `display-scale --version` | 0 | stdout `{"protocol":1,"version":"0.1.1"}`; empty stderr |
| Invalid arguments | 2 | empty stdout; versioned error JSON on stderr |
| Unsupported platform, API/awareness/topology/no-monitor failure | 3 | empty stdout; versioned error JSON on stderr |

Error form: `{"protocol":1,"error":{"code":"CODE","message":"diagnostic"}}`.
The 4D generic adapter reports nonzero status as `cli_error`, preserving that
JSON on stderr and in `error.message`. No shell, undocumented DisplayConfig DPI
packets, registry heuristics or fallback DPI. Generic process/quoting
infrastructure remains separate from feature validation.

## Build and acceptance

Read [AGENTS.md](AGENTS.md) before changing identity or acceptance tooling.
C++17/CMake; Windows uses MSVC and the static CRT. The scaffold is MIT;
retain [LICENSE](LICENSE) and component redistribution notices. No third-party
feature library is bundled; vendor tool4d is not redistributable in Resources.
Compiler/runtime redistribution terms still require review.

```sh
python3 -m unittest discover -s tests -v
python3 scripts/generate_icons.py --check
python3 scripts/build_cli.py --root . --target windows-x64
```

Windows builds/tests must execute on native Windows x64. Hosted runner tests
check **only that runner's actual topology**, not mixed-scale/custom/RDP physical
scenarios. Platform-independent conversion/error/protocol tests also run on
macOS using an explicit `UNSUPPORTED_PLATFORM` backend. Test-only argument echo
helpers are never packaged. Follow [manual Windows acceptance](tests/manual-windows.md)
for mixed 100/125/150%, custom scaling, session changes, reconnects, negative
coordinates and Remote Desktop.

The native Windows job additionally runs `python scripts/check_windows_runtime.py`.
It verifies the generated Release|x64 MSVC project selects retail static `/MT`,
checks the actual compiled objects' `LIBCMT` directives, and uses the configured
compiler's `dumpbin /DEPENDENTS` on the provenance-bound executable. Only the
explicit Windows system DLL allowlist is accepted; dynamic/debug CRT or unexpected
imports fail CI. Evidence (`runtime-status.json`, imports and object directives)
is uploaded with `cli-windows-x64`. This is **not** a clean-machine deployment
test or a legal certification of the publisher's Visual Studio license.
The scaling import may be `SHCORE.dll` or the verified exact OS API-set contract
`api-ms-win-shcore-scaling-l1-1-1.dll`, documented for
[GetProcessDpiAwareness](https://learn.microsoft.com/en-us/windows/win32/api/shellscalingapi/nf-shellscalingapi-getprocessdpiawareness).
[API sets identify Windows loader contracts, not redistributable files](https://learn.microsoft.com/en-us/windows/win32/apiindex/windows-apisets).
No blanket API-set prefix or VC runtime DLL allowlist is used.

Local macOS 4D source/compiler/compiled-package checks exercise protocol
validation, generic execution and the unsupported-platform error, **not Windows
monitor detection**. Development artifacts are not installable production
releases. Production packaging requires current Windows resources/provenance,
real compilation and the unpacked final compiled package's host acceptance.
Signing is optional; no credentials, activation or signing is needed for
unsigned local tool4d compilation.

On native Apple Silicon, explicitly select the development profile:

```sh
python3 scripts/ci_config.py download-tool4d --root .
python3 scripts/accept_local.py --root . --repository miyako/DisplayScale \
  --tool4d .tools/tool4d.app/Contents/MacOS/tool4d --local-development
```

This builds the native unsupported backend, tests a real source host, compiles,
packs and tests the actual unpacked compiled package. Output:
`dist/development/DisplayScale.zip` with adjacent
`DisplayScale.acceptance.json`; `build/acceptance.json` records the latest
attempt. The ZIP includes an explicit DEVELOPMENT marker and no Windows
resource. It is **not** the production `dist/DisplayScale.zip` and remains
`release_ready:false`. No C++ cross-build is attempted.

Native Windows 4D acceptance uses the free fixed tool4d
`package.json.tool_windows` pin (20.7 build 101905, Windows x64, SHA256-verified
`win/tool4d_win.tar.xz`, a bzip2 TAR despite its name). The downloader requires a
**native** Windows x64 host (ARM64 emulation is rejected) and installs
`.tools/tool4d/tool4d.exe`. On Windows the compiler driver builds
`x86_64_generic` only, because Windows 4D cannot link `arm64_macOS_lib`
([#2](https://github.com/miyako/DisplayScale/issues/2)); the packager and release
verifier accept that x86_64-only target set only for this Windows-only
configuration and only with native Windows host evidence (`windows_4d` passed).

```sh
python scripts/ci_config.py download-tool4d --root .
python scripts/accept_hosted.py --root . --repository miyako/DisplayScale \
  --tool4d .tools/tool4d/tool4d.exe
```

`accept_hosted.py` needs the same-revision `build/windows-x64` CLI and manifest,
then runs real source host tests, compilation, packaging and the unpacked
compiled-ZIP host test. Physical mixed-scale/RDP topologies
([manual checks](tests/manual-windows.md)) and Dependency-manager installation
remain separate, `not_run` acceptance. No release/tag is created by build or
package commands.

### Running workflows from the Actions tab

Both workflows are started with **Actions → Run workflow**:

* **CI** (any branch): configuration and Python checks, the native Windows x64
  CLI build/tests and runtime-import check, and production resource assembly.
  With the repository variable `FOURD_ENABLED=true`, the `windows-host` job
  (native `windows-2022`) runs source host, x86_64 compile, packaging and the
  unpacked compiled-ZIP host test, retaining `compiled-component` for 30 days
  without publication; the macOS development-backend job also runs.
* **Publish** (`main` only): choose **patch**, **minor** or **major**. The
  next version is computed from the highest stable `X.Y.Z` tag, counting the
  legacy `v0.1.1` tag only as a migration baseline (patch now yields `0.1.2`).
  New release tags equal the version with **no `v` prefix** (e.g. `0.1.2`), as
  the 4D Dependency manager expects; prefixed tags are rejected. The legacy
  `v0.1.1` tag/release is left untouched. The workflow stages the
  version surfaces (`scripts/bump_release.py`), then validates before
  committing anything: `ci_config.py validate --release` requires
  `FOURD_ENABLED=true` and a valid native Windows x64 tool4d pin, otherwise the
  run stops with no commit, tag or release. Publish then commits the version
  bump to `main`, builds the Windows CLI from that exact SHA, and on native
  `windows-2022` host-tests the source, compiles, packages and host-tests the
  unpacked compiled ZIP; it creates the tag and release only after final asset
  validation. Apple signing/notarization does not apply: the workflow uses no
  Apple secrets and rejects a `release-policy.json` that would require it.
## Installation after an accepted release

No production release is implied by this initial implementation. A future
accepted asset must be exactly `DisplayScale.zip`, containing
`DisplayScale.4dbase/DisplayScale.4DZ` and external Resources/Libraries, with 4D
source stripped and compiler-generated completion metadata retained.
Use a compatible host's Dependency manager GitHub dependency
`miyako/DisplayScale` and an actually published tag, or copy the unpacked
`DisplayScale.4dbase` to the host's `Components/`. Dependency-manager download/
installation is separate acceptance; do not treat a local copy as evidence.
