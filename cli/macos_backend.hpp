#pragma once

#include "display.hpp"

#ifdef __APPLE__
#include <CoreGraphics/CoreGraphics.h>
#include <cmath>

namespace display_scale {
namespace mac_detail {
constexpr std::uint32_t native_mode_flag = 0x02000000; // kDisplayModeNativeFlag

inline std::int32_t point(CGFloat value) {
    if (!std::isfinite(value) || value < -2147483648.0 || value > 2147483647.0)
        throw Failure("MACOS_API_ERROR", "display bounds are outside the supported range");
    return static_cast<std::int32_t>(std::llround(value));
}

struct ModeRef {
    CGDisplayModeRef mode;
    explicit ModeRef(CGDisplayModeRef value) : mode(value) {}
    ModeRef(const ModeRef&) = delete;
    ModeRef& operator=(const ModeRef&) = delete;
    ~ModeRef() { if (mode) CGDisplayModeRelease(mode); }
};

struct ListRef {
    CFArrayRef list;
    explicit ListRef(CFArrayRef value) : list(value) {}
    ListRef(const ListRef&) = delete;
    ListRef& operator=(const ListRef&) = delete;
    ~ListRef() { if (list) CFRelease(list); }
};
}

class MacBackend final : public Backend {
public:
    const char* platform() const override { return "macos"; }
    void begin() override {}
    void finish() override {}
    unsigned read_dpi(const Monitor&) override { return 0; }

    std::vector<Monitor> snapshot() override {
        CGDirectDisplayID ids[64];
        std::uint32_t count = 0;
        if (CGGetActiveDisplayList(64, ids, &count) != kCGErrorSuccess)
            throw Failure("MACOS_API_ERROR", "CGGetActiveDisplayList failed");
        const auto main = CGMainDisplayID();
        std::vector<Monitor> monitors;
        for (std::uint32_t i = 0; i < count; ++i) {
            const auto bounds = CGDisplayBounds(ids[i]);
            Monitor monitor{ids[i], "display-" + std::to_string(ids[i]), ids[i] == main,
                {mac_detail::point(bounds.origin.x), mac_detail::point(bounds.origin.y),
                 mac_detail::point(bounds.origin.x + bounds.size.width),
                 mac_detail::point(bounds.origin.y + bounds.size.height)}};
            monitors.push_back(monitor);
        }
        return monitors;
    }

    MacScale read_mac(const Monitor& monitor) override {
        const auto id = static_cast<CGDirectDisplayID>(monitor.handle);
        mac_detail::ModeRef current(CGDisplayCopyDisplayMode(id));
        if (!current.mode) throw Failure("MACOS_API_ERROR", "CGDisplayCopyDisplayMode failed");
        MacScale scale;
        scale.backing_width = static_cast<unsigned>(CGDisplayModeGetPixelWidth(current.mode));
        scale.backing_height = static_cast<unsigned>(CGDisplayModeGetPixelHeight(current.mode));

        const void* keys[] = {kCGDisplayShowDuplicateLowResolutionModes};
        const void* values[] = {kCFBooleanTrue};
        CFDictionaryRef options = CFDictionaryCreate(nullptr, keys, values, 1,
            &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
        if (!options) throw Failure("MACOS_API_ERROR", "failed to create display mode options");
        mac_detail::ListRef modes(CGDisplayCopyAllDisplayModes(id, options));
        CFRelease(options);
        if (!modes.list) throw Failure("MACOS_API_ERROR", "CGDisplayCopyAllDisplayModes failed");
        for (CFIndex i = 0; i < CFArrayGetCount(modes.list); ++i) {
            auto mode = static_cast<CGDisplayModeRef>(
                const_cast<void*>(CFArrayGetValueAtIndex(modes.list, i)));
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
            const auto flags = CGDisplayModeGetIOFlags(mode);
#pragma clang diagnostic pop
            if (!(flags & mac_detail::native_mode_flag)) continue;
            const unsigned width = static_cast<unsigned>(CGDisplayModeGetPixelWidth(mode));
            const unsigned height = static_cast<unsigned>(CGDisplayModeGetPixelHeight(mode));
            if (scale.native_width && (scale.native_width != width || scale.native_height != height))
                throw Failure("MACOS_API_ERROR", "display reports conflicting native modes");
            scale.native_width = width;
            scale.native_height = height;
        }
        if (!scale.native_width || !scale.native_height)
            throw Failure("MACOS_API_ERROR", "native display mode is unavailable");
        return scale;
    }
};
}
#endif
