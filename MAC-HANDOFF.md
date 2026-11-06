# macOS support handoff

Status: **proposal / handoff only.** Nothing in this file changes the current
contract. Until the work below lands, DisplayScale remains Windows 10 1703+ /
Windows 11 x64 only, and the macOS build stays a development-only unsupported
backend (see [AGENTS.md](AGENTS.md) "DisplayScale destination scope").

Continue this work in a session on a native Apple Silicon Mac. Read
`AGENTS.md`, `README.md`, `template.json`,
`component/DisplayScale/Documentation/Classes/Display.md` and this file first.
Do **not** reinitialize the repository.

## 1. Decisions to settle before writing code

Ask the user; do not guess these. Each changes the public contract.

1. **Meaning of `scalePercent` on macOS.** macOS has no single DPI value:
   * *Backing scale*: `pixelWidth / pointWidth` of the current display mode
     (1.0 or 2.0 in practice). 200% on every Retina panel, regardless of
     "Larger text"/"More space".
   * *Effective scale vs. native panel pixels*: `nativePixelWidth /
     pointWidth`. Default "looks like" settings often give exactly 200%, while
     "More space" yields a non-integer value (e.g. a 3024-px panel at
     1800 pt ≈ 168%). This is the closest analogue of the Windows feature
     ("how large is UI relative to physical pixels").
   * Recommendation to propose: report both, with one explicitly chosen as
     `scalePercent`.
2. **Protocol.** Options: keep `protocol:1` and add optional macOS-only fields,
   or bump to `protocol:2` with a platform-tagged schema. `Display.4dm`
   `_decode` currently rejects anything but `protocol:1` and enforces
   `scalePercent == dpi / 96 * 100` (lines ~42–117), so a fake 96-based `dpi`
   on macOS would be misleading. Prefer an honest schema over reusing `dpi`.
3. **Coordinate space.** `CGDisplayBounds` is in global *points* (origin at the
   top-left of the main display, y down). Windows `bounds` are physical
   pixels. Decide whether macOS reports points, pixels, or both, and document
   that `bounds` are not comparable across platforms.
4. **Minimum macOS version.** `build_cli.py` sets
   `MACOSX_DEPLOYMENT_TARGET=11.0`; confirm that is the support floor.
5. **Signing.** Unsigned bundled executables downloaded from a release may be
   blocked by Gatekeeper/quarantine. Decide whether macOS-supporting versions
   are listed in `release-policy.json.apple_notarized_versions` (the signed,
   notarized DMG path is implemented in `scripts/sign_release.py`; it needs the
   seven Apple secrets described in AGENTS.md §8).
6. **Mirrored and headless displays.** Whether mirror-set secondaries are
   omitted, and what happens when there is no active display (e.g. a hosted CI
   runner or a locked/remote session): a clear error, never an assumed 100%.

## 2. Suggested native implementation

Use the CoreGraphics C API only (no AppKit window, no Objective-C required),
linked with `-framework CoreGraphics` (or `ApplicationServices`). Verify every
call against Apple's current documentation before use.

* Enumerate: `CGGetActiveDisplayList`; primary: `CGMainDisplayID`.
* Mirroring: `CGDisplayIsInMirrorSet` / `CGDisplayMirrorsDisplay` (omit or flag
  secondaries per decision 6).
* Geometry: `CGDisplayBounds` (points).
* Current mode: `CGDisplayCopyDisplayMode`, `CGDisplayModeGetWidth/Height`
  (points), `CGDisplayModeGetPixelWidth/Height` (backing pixels),
  `CGDisplayModeRelease`.
* Native panel pixels: `CGDisplayCopyAllDisplayModes` with
  `kCGDisplayShowDuplicateLowResolutionModes`, selecting the native mode (IO
  flags `kDisplayModeNativeFlag`); if no native mode is identifiable, fail with
  an explicit error code rather than guessing.
* Identity: `CGDirectDisplayID` is per-session/topology, like Windows
  `szDevice`; it is not a permanent hardware ID. Optionally expose
  `CGDisplayIsBuiltin`, vendor/model/serial numbers.
* Topology stability: reuse the existing `execute()` sample–read–resample
  structure in `cli/display.hpp` (`TOPOLOGY_CHANGED`), so partial lists are
  never returned.

Code layout: add `cli/macos_backend.hpp` implementing `display_scale::Backend`
(`begin/snapshot/read_dpi/finish` — rename/extend `read_dpi` and `Monitor` if
the protocol changes), select it under `__APPLE__` in `cli/main.cpp` instead
of `UnsupportedBackend`, and add the framework link in `cli/CMakeLists.txt`.
Keep generic execution (`_CLI`, `_Process`, `_CaptureError`) unchanged except
where `_CLI.4dm` target handling must stay `"macOS-universal"`.

## 3. Change inventory

| Area | Files | Change |
| --- | --- | --- |
| Identity/scope | `template.json` | `resource_targets` → `["macos-x64","macos-arm64","windows-x64"]`; remove `"Darwin"` from `unsupported_backend_platforms`; update `feature` text |
| Metadata | `package.json` | `description`; `tool` (macOS ARM64 tool4d pin) is already present |
| CLI | `cli/main.cpp`, new `cli/macos_backend.hpp`, `cli/display.hpp`, `cli/CMakeLists.txt` | Real macOS backend; `unsupported` message; protocol/schema changes |
| CLI tests | `cli/tests.cpp`, `tests/cli-contract.json`, `tests/test_cli.py` | Fake-backend unit tests for macOS math/errors; native vectors (use `stdoutPattern` for topology-dependent output) |
| 4D API | `Project/Sources/Classes/Display.4dm` | `_decode` validation for the macOS schema/protocol; keep strict type guards |
| Host tests | `tests/host/Project/Sources/Methods/Smoke.4dm`, `tests/host/contract.json`, `tests/test_windows_host_contract.py` | macOS semantic checks with `"macOS-universal"`; keep all generic negative cases |
| Docs | `README.md`, `Documentation/Classes/Display.md`, `AGENTS.md` scope section, `.github/skills/4d-cli-component/SKILL.md` if it restates scope; new `tests/manual-macos.md` | Platform matrix, schema, limitations, manual topology checks (built-in + external, mirroring, "More space", sidecar if relevant) |
| Licenses | `component/DisplayScale/Resources/licenses/` | Review any new notices (system frameworks need none bundled; confirm) |
| Build/assembly | `scripts/ci_config.py`, `scripts/build_cli.py`, `scripts/accept_local.py`, `scripts/doctor.py` | Remove "development-only" macOS path as the only Darwin mode; production assembly builds universal `lipo` from both macOS slices plus Windows x64 (infrastructure inherited from the template) |
| Compile | `scripts/compile_component.py` | macOS host compiles `x86_64_generic` + `arm64_macOS_lib`; release must require both targets |
| Acceptance | `scripts/accept_hosted.py`, `scripts/release_assets.py` | Require macOS source/compiled 4D host `passed` in addition to `windows_4d`; keep `native_intel_4d` honest (`not_run` unless actually executed) |
| CI/Publish | `.github/workflows/ci.yml`, `.github/workflows/publish.yml` | Replace the `development-host` job with a real macOS host job; Publish compiles on macOS too (or merges Windows + macOS evidence) and downloads macOS CLI artifacts; decide signing input per decision 5 |
| Versioning | `scripts/bump_release.py`, `tests/test_bump_release.py` | Update if new version surfaces are added |

## 4. Acceptance on the Mac (local, unsigned)

```sh
python3 scripts/doctor.py --root .
python3 -m unittest discover -s tests -v
python3 scripts/build_cli.py --root . --target macos-arm64
python3 scripts/ci_config.py download-tool4d --root .
python3 scripts/accept_local.py --root . --repository miyako/DisplayScale \
  --tool4d .tools/tool4d.app/Contents/MacOS/tool4d
```

C++ cannot cross-build: the `macos-x64` and `windows-x64` artifacts plus their
`build-manifest.json` must come from native CI for the **same commit**. A
local Apple Silicon run is partial (`release_ready:false`); Intel macOS 4D,
Windows 4D and Dependency Manager installation remain separate checks. Also
run the manual topology checks on real hardware (built-in Retina, external
non-Retina, mixed, mirrored, "More space") and record observed values.

## 5. Out of scope unless requested

Live change notifications, per-window scale lookup, 4D screen-number mapping,
writing display settings, Windows ARM64, and Windows Authenticode signing.
