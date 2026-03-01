#include "hot_reload.h"
#include "logger.h"

#include <chrono>
#include <cstring>
#include <filesystem>
#include <thread>

#ifdef __linux__
#include <sys/inotify.h>
#endif

// Debounce window in seconds
static constexpr double kDebounceSeconds = 2.0;

HotReloadManager::HotReloadManager(const std::string& config_path, ReloadCallback callback)
    : config_path_(config_path), callback_(std::move(callback)) {}

HotReloadManager::~HotReloadManager() {
    Stop();
}

HotReloadManager::HotReloadManager(HotReloadManager&& other) noexcept
    : config_path_(std::move(other.config_path_)),
      callback_(std::move(other.callback_)),
      running_(other.running_.load()),
      monitor_thread_(std::move(other.monitor_thread_)) {
#ifdef __linux__
    inotify_fd_ = other.inotify_fd_;
    watch_fd_ = other.watch_fd_;
    other.inotify_fd_ = -1;
    other.watch_fd_ = -1;
#endif
}

HotReloadManager& HotReloadManager::operator=(HotReloadManager&& other) noexcept {
    if (this != &other) {
        Stop();
        config_path_ = std::move(other.config_path_);
        callback_ = std::move(other.callback_);
        running_ = other.running_.load();
        monitor_thread_ = std::move(other.monitor_thread_);
#ifdef __linux__
        inotify_fd_ = other.inotify_fd_;
        watch_fd_ = other.watch_fd_;
        other.inotify_fd_ = -1;
        other.watch_fd_ = -1;
#endif
    }
    return *this;
}

bool HotReloadManager::Start() {
    if (running_.load()) {
        return true;
    }

    if (!std::filesystem::exists(config_path_)) {
        LOG_WARN("hot_reload", ("Config file does not exist: " + config_path_).c_str());
        return false;
    }

#ifdef __linux__
    // Initialize inotify
    inotify_fd_ = inotify_init1(IN_NONBLOCK | IN_CLOEXEC);
    if (inotify_fd_ < 0) {
        LOG_ERROR("hot_reload", ("Failed to init inotify: " + std::string(strerror(errno))).c_str());
        return false;
    }

    // Watch for file modifications
    watch_fd_ = inotify_add_watch(inotify_fd_, config_path_.c_str(), IN_MODIFY);
    if (watch_fd_ < 0) {
        LOG_ERROR("hot_reload", ("Failed to watch config file: " + std::string(strerror(errno))).c_str());
        ::close(inotify_fd_);
        inotify_fd_ = -1;
        return false;
    }

    LOG_INFO("hot_reload", ("Watching config file for changes: " + config_path_).c_str());
#else
    LOG_WARN("hot_reload", "Hot reload not supported on this platform, using polling fallback");
#endif

    running_.store(true);
    monitor_thread_ = std::make_unique<std::thread>(&HotReloadManager::MonitorLoop, this);

    return true;
}

void HotReloadManager::Stop() {
    if (!running_.exchange(false)) {
        return;
    }

#ifdef __linux__
    if (watch_fd_ >= 0) {
        inotify_rm_watch(inotify_fd_, watch_fd_);
        watch_fd_ = -1;
    }
    if (inotify_fd_ >= 0) {
        ::close(inotify_fd_);
        inotify_fd_ = -1;
    }
#endif

    if (monitor_thread_ && monitor_thread_->joinable()) {
        monitor_thread_->join();
    }

    LOG_INFO("hot_reload", "Hot reload stopped");
}

void HotReloadManager::MonitorLoop() {
    LOG_INFO("hot_reload", "Hot reload monitor started");

#ifdef __linux__
    constexpr size_t kEventSize = sizeof(struct inotify_event);
    constexpr size_t kBufSize = 1024 * (kEventSize + 16);

    char buffer[kBufSize];

    while (running_.load()) {
        ssize_t n = read(inotify_fd_, buffer, kBufSize);

        if (n < 0) {
            if (errno == EAGAIN || errno == EWOULDBLOCK) {
                std::this_thread::sleep_for(std::chrono::milliseconds(500));
                continue;
            }
            LOG_ERROR("hot_reload", ("Read error: " + std::string(strerror(errno))).c_str());
            break;
        }

        // Process events
        size_t i = 0;
        while (i < static_cast<size_t>(n)) {
            struct inotify_event* event = reinterpret_cast<struct inotify_event*>(&buffer[i]);

            if (event->mask & IN_MODIFY) {
                LOG_INFO("hot_reload", "Config file modified, triggering reload");
                HandleReload();
            }

            i += kEventSize + event->len;
        }
    }
#else
    // Polling fallback for non-Linux platforms
    auto last_mtime = std::filesystem::last_write_time(config_path_);

    while (running_.load()) {
        std::this_thread::sleep_for(std::chrono::seconds(2));

        try {
            auto current_mtime = std::filesystem::last_write_time(config_path_);
            if (current_mtime != last_mtime) {
                last_mtime = current_mtime;
                LOG_INFO("hot_reload", "Config file changed (polling), triggering reload");
                HandleReload();
            }
        } catch (const std::exception& e) {
            LOG_ERROR("hot_reload", ("Error checking config: " + std::string(e.what())).c_str());
        }
    }
#endif
}

void HotReloadManager::HandleReload() {
    // Debounce: add small delay to avoid multiple rapid reloads
    static double last_reload = 0;
    auto now = std::chrono::duration_cast<std::chrono::milliseconds>(
        std::chrono::steady_clock::now().time_since_epoch()).count() / 1000.0;

    if (now - last_reload < kDebounceSeconds) {
        return;
    }
    last_reload = now;

    if (callback_) {
        callback_();
    }
}
