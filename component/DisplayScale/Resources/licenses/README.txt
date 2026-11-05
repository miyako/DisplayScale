DisplayScale uses Windows system APIs and C++17, with no third-party feature
library. The original scaffold is MIT; its LICENSE is included by the packer.

Windows builds use the Microsoft C/C++ static runtime (/MT). Microsoft compiler
and runtime redistribution rights derive from the applicable Visual Studio
license and REDIST terms, not from this project's MIT license. Native Windows
CI records the actual compiler version, verifies Release|x64 MultiThreaded (/MT)
and compiled LIBCMT directives, and inspects the exact executable with dumpbin.
Only allowlisted Windows system DLL imports are accepted; no dynamic/debug CRT
dependency is approved. runtime-status.json preserves the binary/source hashes
and explicitly records clean-machine execution as not_run. These technical checks
do not certify the publisher's license rights. Confirm applicable Visual Studio
redistribution eligibility before publishing. No standalone CRT
DLLs, Windows SDK libraries or vendor tool4d installation are packaged here.
The exact api-ms-win-shcore-scaling-l1-1-1.dll import is an OS loader contract for
GetProcessDpiAwareness, not a separately redistributed runtime DLL. Its documented
SHCORE.dll host is also allowlisted. No wildcard API-set/CRT imports are approved.
Official references:
https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files
https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution
https://visualstudio.microsoft.com/license-terms/
https://learn.microsoft.com/en-us/windows/win32/api/shellscalingapi/nf-shellscalingapi-getprocessdpiawareness
https://learn.microsoft.com/en-us/windows/win32/apiindex/windows-apisets

macOS development-only binaries use system libc++/libSystem dynamically.
They are unsupported-platform test backends, not macOS feature releases.
