#pragma once

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <locale>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace display_scale {
inline constexpr const char* usage = "expected monitors or --version";
inline constexpr const char* unsupported =
    "monitors requires Windows 10 version 1703 or later on x64, or macOS 11 or later";

class Failure : public std::runtime_error {
public:
    std::string code;
    Failure(std::string code_, const std::string& message)
        : std::runtime_error(message), code(std::move(code_)) {}
};

inline bool valid_utf8(std::string_view value) {
    for (std::size_t i = 0; i < value.size();) {
        auto first = static_cast<unsigned char>(value[i++]);
        if (first <= 0x7f) continue;
        unsigned remaining, codepoint, minimum;
        if (first >= 0xc2 && first <= 0xdf) {
            remaining = 1; codepoint = first & 0x1f; minimum = 0x80;
        } else if (first >= 0xe0 && first <= 0xef) {
            remaining = 2; codepoint = first & 0x0f; minimum = 0x800;
        } else if (first >= 0xf0 && first <= 0xf4) {
            remaining = 3; codepoint = first & 0x07; minimum = 0x10000;
        } else return false;
        if (remaining > value.size() - i) return false;
        while (remaining-- > 0) {
            auto next = static_cast<unsigned char>(value[i++]);
            if ((next & 0xc0) != 0x80) return false;
            codepoint = (codepoint << 6) | (next & 0x3f);
        }
        if (codepoint < minimum || codepoint > 0x10ffff ||
            (codepoint >= 0xd800 && codepoint <= 0xdfff)) return false;
    }
    return true;
}

inline std::string quote(std::string_view value) {
    constexpr char hex[] = "0123456789abcdef";
    std::string result = "\"";
    for (unsigned char character : value) {
        switch (character) {
        case '"': result += "\\\""; break;
        case '\\': result += "\\\\"; break;
        case '\b': result += "\\b"; break;
        case '\f': result += "\\f"; break;
        case '\n': result += "\\n"; break;
        case '\r': result += "\\r"; break;
        case '\t': result += "\\t"; break;
        default:
            if (character < 0x20) {
                result += "\\u00";
                result += hex[character >> 4];
                result += hex[character & 0x0f];
            } else result += static_cast<char>(character);
        }
    }
    return result + '"';
}

struct Bounds {
    std::int32_t left, top, right, bottom;
    bool operator==(const Bounds& other) const {
        return left == other.left && top == other.top &&
            right == other.right && bottom == other.bottom;
    }
};

struct MacScale {
    unsigned backing_width = 0, backing_height = 0, native_width = 0, native_height = 0;
    bool operator==(const MacScale& other) const {
        return backing_width == other.backing_width && backing_height == other.backing_height &&
            native_width == other.native_width && native_height == other.native_height;
    }
};

struct Monitor {
    std::uintptr_t handle;
    std::string device;
    bool primary;
    Bounds bounds;
    unsigned dpi = 0;
    MacScale mac{};
    bool same_topology(const Monitor& other) const {
        return handle == other.handle && device == other.device &&
            primary == other.primary && bounds == other.bounds;
    }
};

inline double scale_percent(unsigned dpi) {
    if (!dpi) throw Failure("WINDOWS_API_ERROR", "GetDpiForWindow returned zero");
    return static_cast<double>(dpi) / 96.0 * 100.0;
}

// Effective scale of a macOS display: native panel pixels per point of the
// current mode. Bounds are points, so the horizontal ratio is used.
inline double mac_scale_percent(const MacScale& mac, const Bounds& bounds) {
    const auto points = static_cast<double>(bounds.right) - bounds.left;
    if (!mac.native_width || !mac.native_height || points <= 0)
        throw Failure("MACOS_API_ERROR", "native display mode is unavailable");
    return static_cast<double>(mac.native_width) / points * 100.0;
}

inline double mac_backing_percent(const MacScale& mac, const Bounds& bounds) {
    const auto points = static_cast<double>(bounds.right) - bounds.left;
    if (!mac.backing_width || !mac.backing_height || points <= 0)
        throw Failure("MACOS_API_ERROR", "display backing size is unavailable");
    return static_cast<double>(mac.backing_width) / points * 100.0;
}

class Backend {
public:
    virtual ~Backend() = default;
    virtual const char* platform() const { return "windows"; }
    virtual void begin() = 0;
    virtual std::vector<Monitor> snapshot() = 0;
    virtual unsigned read_dpi(const Monitor&) = 0;
    virtual MacScale read_mac(const Monitor&) {
        throw Failure("MACOS_API_ERROR", "macOS scale is unavailable on this backend");
    }
    virtual void finish() = 0;
};

inline bool is_macos(const Backend& backend) {
    return std::string_view(backend.platform()) == "macos";
}

inline void normalize(std::vector<Monitor>& monitors, const char* api_code = "WINDOWS_API_ERROR") {
    if (monitors.empty()) throw Failure("NO_MONITORS", "no display monitors found");
    std::sort(monitors.begin(), monitors.end(), [](const Monitor& a, const Monitor& b) {
        if (a.primary != b.primary) return a.primary > b.primary;
        return a.device < b.device;
    });
    unsigned primary_count = 0;
    std::vector<std::string> devices;
    for (const auto& monitor : monitors) {
        if (monitor.device.empty() || !valid_utf8(monitor.device) ||
            monitor.bounds.left >= monitor.bounds.right ||
            monitor.bounds.top >= monitor.bounds.bottom || !monitor.handle)
            throw Failure(api_code, "invalid monitor information");
        primary_count += monitor.primary ? 1 : 0;
        if (std::find(devices.begin(), devices.end(), monitor.device) != devices.end())
            throw Failure("TOPOLOGY_CHANGED", "display topology changed during sampling");
        devices.push_back(monitor.device);
    }
    if (primary_count != 1)
        throw Failure("TOPOLOGY_CHANGED", "display topology changed during sampling");
}

inline void require_same(const std::vector<Monitor>& a, const std::vector<Monitor>& b) {
    if (a.size() != b.size() ||
        !std::equal(a.begin(), a.end(), b.begin(),
            [](const Monitor& x, const Monitor& y) { return x.same_topology(y); }))
        throw Failure("TOPOLOGY_CHANGED", "display topology changed during sampling");
}

inline std::string collect(Backend& backend) {
    const bool mac = is_macos(backend);
    const char* api_code = mac ? "MACOS_API_ERROR" : "WINDOWS_API_ERROR";
    const auto read = [&](Monitor& monitor) {
        if (mac) {
            monitor.mac = backend.read_mac(monitor);
            (void)mac_scale_percent(monitor.mac, monitor.bounds);
            (void)mac_backing_percent(monitor.mac, monitor.bounds);
        } else {
            monitor.dpi = backend.read_dpi(monitor);
            (void)scale_percent(monitor.dpi);
        }
    };
    const auto changed = [&](const Monitor& monitor) {
        Monitor again = monitor;
        again.dpi = 0;
        again.mac = {};
        read(again);
        return again.dpi != monitor.dpi || !(again.mac == monitor.mac);
    };
    backend.begin();
    auto monitors = backend.snapshot();
    normalize(monitors, api_code);
    for (auto& monitor : monitors) read(monitor);
    auto after = backend.snapshot();
    if (after.empty())
        throw Failure("TOPOLOGY_CHANGED", "display topology changed during sampling");
    normalize(after, api_code);
    require_same(monitors, after);
    for (const auto& monitor : monitors) {
        if (changed(monitor))
            throw Failure("TOPOLOGY_CHANGED", "display topology changed during sampling");
    }
    auto final = backend.snapshot();
    if (final.empty())
        throw Failure("TOPOLOGY_CHANGED", "display topology changed during sampling");
    normalize(final, api_code);
    require_same(monitors, final);
    backend.finish();
    std::ostringstream output;
    output.imbue(std::locale::classic());
    output << std::setprecision(std::numeric_limits<double>::max_digits10)
           << "{\"protocol\":2,\"platform\":\"" << (mac ? "macos" : "windows")
           << "\",\"monitors\":[";
    bool first = true;
    for (const auto& monitor : monitors) {
        if (!first) output << ',';
        first = false;
        output << "{\"device\":" << quote(monitor.device)
               << ",\"primary\":" << (monitor.primary ? "true" : "false")
               << ",\"bounds\":{\"left\":" << monitor.bounds.left
               << ",\"top\":" << monitor.bounds.top
               << ",\"right\":" << monitor.bounds.right
               << ",\"bottom\":" << monitor.bounds.bottom << '}';
        if (mac) {
            output << ",\"backingPixels\":{\"width\":" << monitor.mac.backing_width
                   << ",\"height\":" << monitor.mac.backing_height
                   << "},\"nativePixels\":{\"width\":" << monitor.mac.native_width
                   << ",\"height\":" << monitor.mac.native_height
                   << "},\"backingScalePercent\":"
                   << mac_backing_percent(monitor.mac, monitor.bounds)
                   << ",\"scalePercent\":"
                   << mac_scale_percent(monitor.mac, monitor.bounds) << '}';
        } else {
            output << ",\"dpi\":" << monitor.dpi
                   << ",\"scalePercent\":" << scale_percent(monitor.dpi) << '}';
        }
    }
    return output.str() + "]}\n";
}

inline std::string error_json(const std::string& code, const std::string& message) {
    return "{\"protocol\":2,\"error\":{\"code\":" + quote(code) +
        ",\"message\":" + quote(message) + "}}\n";
}

struct Result {
    int status;
    std::string stdout_text, stderr_text;
};

inline Result execute(const std::vector<std::string>& arguments, Backend& backend) {
    for (const auto& argument : arguments)
        if (!valid_utf8(argument) || argument.find('\0') != std::string::npos)
            return {2, "", error_json("INVALID_ARGUMENTS", usage)};
    if (arguments == std::vector<std::string>{"--version"})
        return {0, "{\"protocol\":2,\"version\":\"0.1.0\"}\n", ""};
    if (arguments != std::vector<std::string>{"monitors"})
        return {2, "", error_json("INVALID_ARGUMENTS", usage)};
    try {
        return {0, collect(backend), ""};
    } catch (const Failure& error) {
        return {3, "", error_json(error.code, error.what())};
    } catch (const std::exception&) {
        return {3, "", error_json(is_macos(backend) ? "MACOS_API_ERROR" : "WINDOWS_API_ERROR",
            "unexpected sampling failure")};
    }
}
} // namespace display_scale
