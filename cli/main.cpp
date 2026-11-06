#include "display.hpp"
#include "macos_backend.hpp"
#include "windows_backend.hpp"
#include <cstdio>
#include <iostream>

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

namespace {
#if !defined(_WIN32) && !defined(__APPLE__)
class UnsupportedBackend final : public display_scale::Backend {
public:
    void begin() override {
        throw display_scale::Failure("UNSUPPORTED_PLATFORM", display_scale::unsupported);
    }
    std::vector<display_scale::Monitor> snapshot() override { return {}; }
    unsigned read_dpi(const display_scale::Monitor&) override { return 0; }
    void finish() override {}
};
#endif

int run(const std::vector<std::string>& arguments) {
#ifdef _WIN32
    display_scale::WindowsBackend backend;
#elif defined(__APPLE__)
    display_scale::MacBackend backend;
#else
    UnsupportedBackend backend;
#endif
    const auto result = display_scale::execute(arguments, backend);
    std::cout << result.stdout_text;
    std::cerr << result.stderr_text;
    return result.status;
}
}

#ifdef _WIN32
int wmain(int argc, wchar_t* argv[]) {
    if (_setmode(_fileno(stdout), _O_BINARY) == -1 ||
        _setmode(_fileno(stderr), _O_BINARY) == -1) {
        std::cerr << display_scale::error_json("WINDOWS_API_ERROR",
            "failed to configure binary output streams");
        return 3;
    }
    std::vector<std::string> arguments;
    try {
        for (int i = 1; i < argc; ++i)
            arguments.push_back(display_scale::from_utf16(argv[i]));
    } catch (const display_scale::Failure&) {
        std::cerr << display_scale::error_json("INVALID_ARGUMENTS", display_scale::usage);
        return 2;
    }
    return run(arguments);
}
#else
int main(int argc, char* argv[]) {
    return run(std::vector<std::string>(argv + 1, argv + argc));
}
#endif
