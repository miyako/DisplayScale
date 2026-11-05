#pragma once

#include "display.hpp"

namespace display_scale {
inline void verify_window_bounds(const Bounds& window, const Bounds& monitor) {
    if (window.left >= window.right || window.top >= window.bottom)
        throw Failure("WINDOWS_API_ERROR", "invalid probe window bounds");
    if (window.left < monitor.left || window.top < monitor.top ||
        window.right > monitor.right || window.bottom > monitor.bottom)
        throw Failure("TOPOLOGY_CHANGED", "probe window is outside the queried monitor");
}
}

#ifdef _WIN32
#define NOMINMAX
#include <windows.h>
#include <shellscalingapi.h>
#include <exception>
#include <map>

namespace display_scale {
inline std::string from_utf16(std::wstring_view value) {
    if (value.empty()) return "";
    const int size = WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS,
        value.data(), static_cast<int>(value.size()), nullptr, 0, nullptr, nullptr);
    if (!size) throw Failure("WINDOWS_API_ERROR", "UTF-16 conversion failed");
    std::string result(size, '\0');
    if (WideCharToMultiByte(CP_UTF8, WC_ERR_INVALID_CHARS, value.data(),
        static_cast<int>(value.size()), result.data(), size, nullptr, nullptr) != size)
        throw Failure("WINDOWS_API_ERROR", "UTF-16 conversion failed");
    return result;
}

class WindowsBackend final : public Backend {
    using Context = DPI_AWARENESS_CONTEXT;
    using GetThreadContext = Context (WINAPI*)();
    using SetThreadContext = Context (WINAPI*)(Context);
    using GetWindowContext = Context (WINAPI*)(HWND);
    using EqualContexts = BOOL (WINAPI*)(Context, Context);
    using ValidContext = BOOL (WINAPI*)(Context);
    using WindowDpi = UINT (WINAPI*)(HWND);
    GetThreadContext get_thread_ = nullptr;
    SetThreadContext set_thread_ = nullptr;
    GetWindowContext get_window_ = nullptr;
    EqualContexts equal_ = nullptr;
    WindowDpi get_dpi_ = nullptr;
    Context previous_ = nullptr;
    HINSTANCE instance_ = nullptr;
    ATOM class_ = 0;
    std::map<std::uintptr_t, HWND> windows_;
    bool changed_ = false;
    static constexpr const wchar_t* class_name = L"DisplayScale.HiddenDpiProbe";

    template<class T> static T resolve(HMODULE module, const char* name) {
        auto address = GetProcAddress(module, name);
        if (!address) throw Failure("UNSUPPORTED_PLATFORM", unsupported);
        return reinterpret_cast<T>(address);
    }

    static LRESULT CALLBACK window_proc(HWND window, UINT message, WPARAM w, LPARAM l) {
        if (message == WM_NCCREATE) {
            auto creation = reinterpret_cast<CREATESTRUCTW*>(l);
            SetLastError(ERROR_SUCCESS);
            if (!SetWindowLongPtrW(window, GWLP_USERDATA,
                    reinterpret_cast<LONG_PTR>(creation->lpCreateParams)) &&
                GetLastError() != ERROR_SUCCESS)
                return FALSE;
        }
        auto self = reinterpret_cast<WindowsBackend*>(
            GetWindowLongPtrW(window, GWLP_USERDATA));
        if (self && (message == WM_DISPLAYCHANGE || message == WM_DPICHANGED))
            self->changed_ = true;
        if (message == WM_MOUSEACTIVATE) return MA_NOACTIVATE;
        return DefWindowProcW(window, message, w, l);
    }

    void pump() {
        MSG message{};
        constexpr unsigned message_limit = 1024;
        unsigned handled = 0;
        while (handled < message_limit && PeekMessageW(&message, nullptr, 0, 0, PM_REMOVE)) {
            ++handled;
            TranslateMessage(&message);
            DispatchMessageW(&message);
            if (changed_)
                throw Failure("TOPOLOGY_CHANGED", "display topology changed during sampling");
        }
        if (handled == message_limit && PeekMessageW(&message, nullptr, 0, 0, PM_NOREMOVE))
            throw Failure("TOPOLOGY_CHANGED", "message queue did not quiesce during sampling");
        if (changed_)
            throw Failure("TOPOLOGY_CHANGED", "display topology changed during sampling");
        if (!equal_(get_thread_(), DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2))
            throw Failure("DPI_AWARENESS_FAILED", "thread is not PerMonitorV2 aware");
    }

    struct Enumeration {
        std::vector<Monitor> monitors;
        std::exception_ptr error;
    };

    static BOOL CALLBACK enumerate(HMONITOR handle, HDC, LPRECT, LPARAM parameter) {
        auto& state = *reinterpret_cast<Enumeration*>(parameter);
        try {
            MONITORINFOEXW info{};
            info.cbSize = sizeof(info);
            if (!GetMonitorInfoW(handle, reinterpret_cast<MONITORINFO*>(&info)))
                throw Failure("WINDOWS_API_ERROR", "GetMonitorInfoW failed");
            const auto& rect = info.rcMonitor;
            state.monitors.push_back({reinterpret_cast<std::uintptr_t>(handle),
                from_utf16(info.szDevice), (info.dwFlags & MONITORINFOF_PRIMARY) != 0,
                {static_cast<std::int32_t>(rect.left), static_cast<std::int32_t>(rect.top),
                 static_cast<std::int32_t>(rect.right), static_cast<std::int32_t>(rect.bottom)}});
            return TRUE;
        } catch (...) {
            // Exceptions must never unwind through the Windows callback boundary.
            state.error = std::current_exception();
            return FALSE;
        }
    }

    void cleanup() noexcept {
        for (const auto& entry : windows_)
            if (entry.second) DestroyWindow(entry.second);
        windows_.clear();
        if (class_) UnregisterClassW(class_name, instance_);
        class_ = 0;
        if (previous_ && set_thread_) set_thread_(previous_);
        previous_ = nullptr;
    }

public:
    ~WindowsBackend() override { cleanup(); }

    void begin() override {
        SYSTEM_INFO system{};
        GetNativeSystemInfo(&system);
        if (sizeof(void*) != 8 ||
            system.wProcessorArchitecture != PROCESSOR_ARCHITECTURE_AMD64)
            throw Failure("UNSUPPORTED_PLATFORM", unsupported);
        const auto user32 = GetModuleHandleW(L"user32.dll");
        if (!user32) throw Failure("WINDOWS_API_ERROR", "User32 module unavailable");
        get_thread_ = resolve<GetThreadContext>(user32, "GetThreadDpiAwarenessContext");
        set_thread_ = resolve<SetThreadContext>(user32, "SetThreadDpiAwarenessContext");
        get_window_ = resolve<GetWindowContext>(user32, "GetWindowDpiAwarenessContext");
        equal_ = resolve<EqualContexts>(user32, "AreDpiAwarenessContextsEqual");
        get_dpi_ = resolve<WindowDpi>(user32, "GetDpiForWindow");
        auto valid = resolve<ValidContext>(user32, "IsValidDpiAwarenessContext");
        if (!valid(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2))
            throw Failure("UNSUPPORTED_PLATFORM", unsupported);
        PROCESS_DPI_AWARENESS awareness = PROCESS_DPI_UNAWARE;
        if (GetProcessDpiAwareness(nullptr, &awareness) != S_OK ||
            awareness != PROCESS_PER_MONITOR_DPI_AWARE ||
            !equal_(get_thread_(), DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2))
            throw Failure("DPI_AWARENESS_FAILED", "process is not PerMonitorV2 aware");
        previous_ = set_thread_(DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2);
        if (!previous_ ||
            !equal_(get_thread_(), DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2))
            throw Failure("DPI_AWARENESS_FAILED", "thread is not PerMonitorV2 aware");
        instance_ = GetModuleHandleW(nullptr);
        if (!instance_) throw Failure("WINDOWS_API_ERROR", "module handle unavailable");
        WNDCLASSW definition{};
        definition.lpfnWndProc = window_proc;
        definition.hInstance = instance_;
        definition.lpszClassName = class_name;
        class_ = RegisterClassW(&definition);
        if (!class_) throw Failure("WINDOWS_API_ERROR", "RegisterClassW failed");
    }

    std::vector<Monitor> snapshot() override {
        pump();
        Enumeration state;
        const auto succeeded = EnumDisplayMonitors(nullptr, nullptr, enumerate,
            reinterpret_cast<LPARAM>(&state));
        if (state.error) std::rethrow_exception(state.error);
        if (!succeeded) throw Failure("WINDOWS_API_ERROR", "EnumDisplayMonitors failed");
        pump();
        return state.monitors;
    }

    unsigned read_dpi(const Monitor& monitor) override {
        pump();
        auto found = windows_.find(monitor.handle);
        HWND window;
        if (found == windows_.end()) {
            const auto& b = monitor.bounds;
            const int x = static_cast<int>((static_cast<std::int64_t>(b.left) + b.right) / 2);
            const int y = static_cast<int>((static_cast<std::int64_t>(b.top) + b.bottom) / 2);
            // No WS_VISIBLE, owner, message-only parent, or activation: a real monitor-local HWND.
            window = CreateWindowExW(WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
                class_name, L"", WS_POPUP, x, y, 1, 1, nullptr, nullptr, instance_, this);
            if (!window) throw Failure("WINDOWS_API_ERROR", "CreateWindowExW failed");
            try {
                windows_.emplace(monitor.handle, window);
            } catch (...) {
                DestroyWindow(window);
                throw;
            }
        } else window = found->second;
        pump();
        if (!equal_(get_window_(window), DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2))
            throw Failure("DPI_AWARENESS_FAILED", "window is not PerMonitorV2 aware");
        if (MonitorFromWindow(window, MONITOR_DEFAULTTONULL) !=
            reinterpret_cast<HMONITOR>(monitor.handle))
            throw Failure("TOPOLOGY_CHANGED", "display topology changed during sampling");
        RECT rectangle{};
        if (!GetWindowRect(window, &rectangle))
            throw Failure("WINDOWS_API_ERROR", "GetWindowRect failed");
        verify_window_bounds(
            {static_cast<std::int32_t>(rectangle.left), static_cast<std::int32_t>(rectangle.top),
             static_cast<std::int32_t>(rectangle.right), static_cast<std::int32_t>(rectangle.bottom)},
            monitor.bounds);
        const unsigned dpi = get_dpi_(window);
        if (!dpi) throw Failure("WINDOWS_API_ERROR", "GetDpiForWindow returned zero");
        pump();
        return dpi;
    }

    void finish() override {
        pump();
        for (auto& entry : windows_) {
            if (entry.second && !DestroyWindow(entry.second))
                throw Failure("WINDOWS_API_ERROR", "DestroyWindow failed");
            entry.second = nullptr;
        }
        windows_.clear();
        if (class_ && !UnregisterClassW(class_name, instance_))
            throw Failure("WINDOWS_API_ERROR", "UnregisterClassW failed");
        class_ = 0;
        if (previous_) {
            auto expected = previous_;
            if (!set_thread_(expected) || !equal_(get_thread_(), expected))
                throw Failure("DPI_AWARENESS_FAILED", "thread DPI awareness restoration failed");
            previous_ = nullptr;
        }
    }
};
} // namespace display_scale
#endif
