#include "display.hpp"
#include "windows_backend.hpp"
#include <iostream>

using namespace display_scale;

namespace {
void check(bool condition, const char* message) {
    if (!condition) throw std::runtime_error(message);
}

struct FakeBackend : Backend {
    std::vector<Monitor> monitors = {
        {2, "\\\\.\\DISPLAY10", false, {-1600, 0, 0, 900}},
        {1, "主 😀 \"display\"\\", true, {0, 0, 1920, 1080}},
        {3, "\\\\.\\DISPLAY2", false, {1920, -100, 3520, 800}}
    };
    int snapshots = 0, reads = 0, stage = 0;
    bool finished = false;
    std::string fault_code;
    void fault(int current) {
        if (current == stage && !fault_code.empty())
            throw Failure(fault_code, "injected API failure");
    }
    void begin() override { fault(1); }
    std::vector<Monitor> snapshot() override {
        fault(++snapshots == 1 ? 2 : 4);
        return monitors;
    }
    unsigned read_dpi(const Monitor&) override {
        fault(3);
        ++reads;
        return 120;
    }
    void finish() override { fault(5); finished = true; }
};

void error(const Result& result, const std::string& code) {
    check(result.status == 3, "operational failure status");
    check(result.stdout_text.empty(), "must not emit partial output");
    check(result.stderr_text.find("\"code\":\"" + code + "\"") != std::string::npos,
        "operational failure code");
    check(result.stderr_text.back() == '\n', "error framing");
}

void tests() {
    check(scale_percent(96) == 100, "96 DPI");
    check(scale_percent(120) == 125, "120 DPI");
    check(scale_percent(144) == 150, "144 DPI");
    check(std::abs(scale_percent(121) - 126.04166666666667) < 1e-12,
        "fractional scaling must not round");
    check(quote("世界 café 😀") == "\"世界 café 😀\"", "Unicode encoding");
    verify_window_bounds({-800, -450, -799, -449}, {-1600, -900, 0, 0});
    verify_window_bounds({-1600, -900, -1599, -899}, {-1600, -900, 0, 0});
    verify_window_bounds({-1, -1, 0, 0}, {-1600, -900, 0, 0});
    for (const auto bounds : {Bounds{-800, -450, -800, -449},
                             Bounds{-800, -450, -799, -450}}) {
        bool rejected = false;
        try { verify_window_bounds(bounds, {-1600, -900, 0, 0}); }
        catch (const Failure& failure) { rejected = failure.code == "WINDOWS_API_ERROR"; }
        check(rejected, "empty probe bounds must fail");
    }
    for (const auto bounds : {Bounds{-1601, -900, -1600, -899},
                             Bounds{-1600, -901, -1599, -900},
                             Bounds{-1, -1, 1, 0}, Bounds{-1, -1, 0, 1},
                             Bounds{10, 10, 11, 11}}) {
        bool rejected = false;
        try { verify_window_bounds(bounds, {-1600, -900, 0, 0}); }
        catch (const Failure& failure) { rejected = failure.code == "TOPOLOGY_CHANGED"; }
        check(rejected, "outside probe bounds must fail");
    }
    check(quote("\"\\\n\t\r\b\f\1") == "\"\\\"\\\\\\n\\t\\r\\b\\f\\u0001\"",
        "JSON escaping");
    check(valid_utf8("世界 😀"), "valid UTF-8");
#ifdef _WIN32
    check(from_utf16(L"世界 café \U0001F600") == "世界 café 😀", "UTF-16 to UTF-8");
    check(from_utf16(L"").empty(), "empty UTF-16");
    for (const auto value : {std::wstring(1, static_cast<wchar_t>(0xd800)),
                            std::wstring(1, static_cast<wchar_t>(0xdfff))}) {
        bool rejected = false;
        try { (void)from_utf16(value); }
        catch (const Failure&) { rejected = true; }
        check(rejected, "malformed UTF-16 must be rejected");
    }
#endif
    for (auto value : {"\x80", "\xff", "\xc0\xaf", "\xed\xa0\x80", "\xf4\x90\x80\x80"})
        check(!valid_utf8(value), "invalid UTF-8");

    FakeBackend good;
    const auto result = execute({"monitors"}, good);
    check(result.status == 0 && result.stderr_text.empty() && good.finished, "success");
    check(result.stdout_text.find("\"dpi\":120,\"scalePercent\":125") != std::string::npos,
        "scale JSON");
    check(result.stdout_text.find(quote("主 😀 \"display\"\\")) <
        result.stdout_text.find(quote("\\\\.\\DISPLAY10")), "primary first");
    check(result.stdout_text.find(quote("\\\\.\\DISPLAY10")) <
        result.stdout_text.find(quote("\\\\.\\DISPLAY2")), "lexical not numeric ordering");
    check(good.snapshots == 3 && good.reads == 6, "double DPI and triple topology sampling");
    check(result.stdout_text.back() == '\n' &&
        result.stdout_text.find('\n') == result.stdout_text.size() - 1, "one JSON line");

    struct Fractional : FakeBackend {
        unsigned read_dpi(const Monitor&) override { return 121; }
    } fractional;
    const auto fraction = execute({"monitors"}, fractional);
    check(fraction.status == 0 &&
        fraction.stdout_text.find("\"scalePercent\":126.04166666666667") != std::string::npos,
        "fractional JSON precision");

    for (int stage = 1; stage <= 5; ++stage) {
        FakeBackend failed;
        failed.stage = stage;
        failed.fault_code = stage == 1 ? "DPI_AWARENESS_FAILED" : "WINDOWS_API_ERROR";
        error(execute({"monitors"}, failed), failed.fault_code);
        check(!failed.finished, "no finish on failure");
    }
    FakeBackend empty;
    empty.monitors.clear();
    error(execute({"monitors"}, empty), "NO_MONITORS");

    struct Changing : FakeBackend {
        std::vector<Monitor> snapshot() override {
            auto value = FakeBackend::snapshot();
            if (snapshots > 1) value[0].bounds.left -= 1;
            return value;
        }
    } changing;
    error(execute({"monitors"}, changing), "TOPOLOGY_CHANGED");
    struct Removed : FakeBackend {
        std::vector<Monitor> snapshot() override {
            auto value = FakeBackend::snapshot();
            if (snapshots > 1) value.clear();
            return value;
        }
    } removed;
    error(execute({"monitors"}, removed), "TOPOLOGY_CHANGED");
    struct DpiChange : FakeBackend {
        unsigned read_dpi(const Monitor& monitor) override {
            auto dpi = FakeBackend::read_dpi(monitor);
            return reads > 3 ? dpi + 1 : dpi;
        }
    } dpi_change;
    error(execute({"monitors"}, dpi_change), "TOPOLOGY_CHANGED");
    struct ZeroDpi : FakeBackend {
        unsigned read_dpi(const Monitor&) override { return 0; }
    } zero;
    error(execute({"monitors"}, zero), "WINDOWS_API_ERROR");
    FakeBackend duplicate;
    duplicate.monitors[0].device = duplicate.monitors[1].device;
    error(execute({"monitors"}, duplicate), "TOPOLOGY_CHANGED");
    FakeBackend invalid_bounds;
    invalid_bounds.monitors[0].bounds.right = invalid_bounds.monitors[0].bounds.left;
    error(execute({"monitors"}, invalid_bounds), "WINDOWS_API_ERROR");
    FakeBackend invalid_device;
    invalid_device.monitors[0].device = "\xff";
    error(execute({"monitors"}, invalid_device), "WINDOWS_API_ERROR");
    FakeBackend unsupported_backend;
    unsupported_backend.stage = 1;
    unsupported_backend.fault_code = "UNSUPPORTED_PLATFORM";
    error(execute({"monitors"}, unsupported_backend), "UNSUPPORTED_PLATFORM");
    check(execute({"--version"}, unsupported_backend).status == 0, "version bypasses API");
    for (auto args : {std::vector<std::string>{}, {"monitors", "extra"}, {"greet"},
                     {std::string("monitors\0", 9)}, {"\xff"}}) {
        const auto invalid = execute(args, unsupported_backend);
        check(invalid.status == 2 && invalid.stdout_text.empty(), "invalid arguments");
        check(invalid.stderr_text == error_json("INVALID_ARGUMENTS", usage), "usage error");
    }
}
}

int main() {
    try {
        tests();
        std::cout << "pure conversion, UTF-8, ordering, API faults and topology checks passed\n";
        return 0;
    } catch (const std::exception& exception) {
        std::cerr << exception.what() << '\n';
        return 1;
    }
}
