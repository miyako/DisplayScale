#include "display.hpp"
#include "windows_backend.hpp"
#include <cstdio>
#include <iostream>

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

namespace {
int echo_arguments(const std::vector<std::string>& arguments) {
    for (const auto& argument : arguments) {
        if (!display_scale::valid_utf8(argument) ||
            argument.find('\0') != std::string::npos) {
            std::cerr << display_scale::error_json("INVALID_ARGUMENTS",
                "arguments must be valid UTF-8");
            return 2;
        }
    }
    std::string output = "{\"protocol\":1,\"arguments\":[";
    bool first = true;
    for (const auto& argument : arguments) {
        if (!first) output += ',';
        first = false;
        output += display_scale::quote(argument);
    }
    std::cout << output << "]}\n";
    return 0;
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
        std::cerr << display_scale::error_json("INVALID_ARGUMENTS",
            "arguments must be valid UTF-8");
        return 2;
    }
    return echo_arguments(arguments);
}
#else
int main(int argc, char* argv[]) {
    return echo_arguments(std::vector<std::string>(argv + 1, argv + argc));
}
#endif
