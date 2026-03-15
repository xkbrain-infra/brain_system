#pragma once

#include <atomic>
#include <functional>
#include <memory>
#include <string>
#include <thread>

/**
 * Hot reload manager for brain_gateway.
 *
 * Monitors configuration files for changes and triggers reload callbacks
 * without requiring service restart.
 *
 * Uses inotify on Linux for efficient file system event monitoring.
 */
class HotReloadManager {
public:
    using ReloadCallback = std::function<void()>;

    /**
     * Create hot reload manager.
     *
     * @param config_path Path to configuration file to monitor
     * @param callback Function to call when config changes detected
     */
    HotReloadManager(const std::string& config_path, ReloadCallback callback);

    ~HotReloadManager();

    // Non-copyable
    HotReloadManager(const HotReloadManager&) = delete;
    HotReloadManager& operator=(const HotReloadManager&) = delete;

    // Movable
    HotReloadManager(HotReloadManager&& other) noexcept;
    HotReloadManager& operator=(HotReloadManager&& other) noexcept;

    /**
     * Start monitoring configuration file.
     *
     * @return true if monitoring started successfully
     */
    bool Start();

    /**
     * Stop monitoring.
     */
    void Stop();

    /**
     * Check if monitoring is active.
     */
    bool IsRunning() const { return running_.load(); }

private:
    void MonitorLoop();
    void HandleReload();

    std::string config_path_;
    ReloadCallback callback_;
    std::atomic<bool> running_{false};
    std::unique_ptr<std::thread> monitor_thread_;

#ifdef __linux__
    int inotify_fd_ = -1;
    int watch_fd_ = -1;
#endif
};
