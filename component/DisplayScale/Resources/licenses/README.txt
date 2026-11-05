DisplayScale uses Windows system APIs and C++17, with no third-party feature
library. The original scaffold is MIT; its LICENSE is included by the packer.

Windows builds use the Microsoft C/C++ static runtime (/MT). Microsoft compiler
and runtime redistribution rights derive from the applicable Visual Studio
license and REDIST terms, not from this project's MIT license. Native Windows
release review must record the actual compiler/runtime version, inspect imports,
and confirm redistribution eligibility before publishing. No standalone CRT
DLLs, Windows SDK libraries or vendor tool4d installation are packaged here.
Official references:
https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files
https://learn.microsoft.com/en-us/visualstudio/releases/2022/redistribution
https://visualstudio.microsoft.com/license-terms/

macOS development-only binaries use system libc++/libSystem dynamically.
They are unsupported-platform test backends, not macOS feature releases.
