#include "gateway.h"
#include "logger.h"

#include <chrono>
#include <filesystem>
#include <thread>

Gateway::Gateway(AppConfig cfg)
    : cfg_(std::move(cfg)),
      ipc_(cfg_.ipc, cfg_.service.name),
      router_(cfg_.routing),
      perm_(cfg_.permissions),
      rate_limiter_(cfg_.rate_limit.tokens_per_minute) {
  LOG_INFO("gateway", "constructor complete");
}

void Gateway::ReloadConfig() {
  // Reload configuration from file
  const std::string config_path = "/brain/infrastructure/service/brain_gateway/config/brain_gateway.json";

  LOG_INFO("gateway", "Reloading configuration...");

  auto new_cfg = LoadConfig(config_path);
  if (!new_cfg) {
    LOG_ERROR("gateway", "Failed to reload configuration");
    return;
  }

  // Update routing config (bot_service_map)
  cfg_.routing = new_cfg->routing;
  router_.ReloadConfig(cfg_.routing);

  LOG_INFO("gateway", "Configuration reloaded successfully");
}

Gateway::~Gateway() { Shutdown(); }

bool Gateway::Run() {
  running_.store(true);

  // Start hot reload watcher for config file
  const std::string config_path = "/brain/infrastructure/service/brain_gateway/config/brain_gateway.json";
  if (std::filesystem::exists(config_path)) {
    hot_reload_ = std::make_unique<HotReloadManager>(config_path, [this]() { ReloadConfig(); });
    if (hot_reload_->Start()) {
      LOG_INFO("gateway", "Hot reload enabled for configuration");
    }
  }

  // Connect IPC (exit on startup failure, per T-LC-002)
  if (!ipc_.Connect()) {
    LOG_ERROR("gateway", "failed to connect to brain_ipc daemon on startup");
    running_.store(false);
    return false;
  }
  ipc_connected_.store(true);

  // Create HTTP server
  http_ = std::make_unique<HttpServer>(cfg_, ipc_, router_, stats_, perm_, rate_limiter_,
                                       uptime_s_, ipc_connected_);

  // Start background threads
  ipc_poller_thread_ = std::thread([this] { IpcPollerLoop(); });
  heartbeat_thread_  = std::thread([this] { HeartbeatLoop(); });
  stats_flush_thread_ = std::thread([this] { StatsFlushLoop(); });
  uptime_thread_ = std::thread([this] {
    while (running_.load()) {
      std::this_thread::sleep_for(std::chrono::seconds(1));
      uptime_s_.fetch_add(1);
    }
  });

  LOG_INFO("gateway", "all threads started");

  // Block on HTTP server (main thread)
  http_->Listen();

  LOG_INFO("gateway", "shutdown complete");
  return true;
}

void Gateway::Shutdown() {
  if (!running_.exchange(false)) return;
  LOG_INFO("gateway", "shutdown initiated");

  // Stop hot reload
  if (hot_reload_) {
    hot_reload_->Stop();
  }

  if (http_) http_->Stop();
  if (ipc_poller_thread_.joinable()) ipc_poller_thread_.join();
  if (heartbeat_thread_.joinable())  heartbeat_thread_.join();
  if (stats_flush_thread_.joinable()) stats_flush_thread_.join();
  if (uptime_thread_.joinable())      uptime_thread_.join();
}

void Gateway::IpcPollerLoop() {
  auto poll_interval = std::chrono::milliseconds(cfg_.ipc.poll_interval_ms);
  auto reconnect_interval = std::chrono::seconds(cfg_.ipc.reconnect_interval_s);

  while (running_.load()) {
    auto msgs = ipc_.Recv(20);
    bool ok = ipc_.IsConnected();
    if (!ok) {
      ipc_connected_.store(false);
      LOG_WARN("gateway", "IPC unreachable, attempting reconnect");
      std::this_thread::sleep_for(reconnect_interval);
      if (ipc_.Connect()) {
        ipc_connected_.store(true);
        LOG_INFO("gateway", "IPC reconnected");
      }
      continue;
    }
    ipc_connected_.store(true);
    std::vector<std::string> ack_ids;
    for (auto& msg : msgs) {
      ProcessMessage(msg);
      ack_ids.push_back(msg.msg_id);
    }
    if (!ack_ids.empty()) {
      ipc_.Ack(ack_ids);
    }
    std::this_thread::sleep_for(poll_interval);
  }
}

void Gateway::HeartbeatLoop() {
  auto interval = std::chrono::seconds(cfg_.ipc.heartbeat_interval_s);
  while (running_.load()) {
    std::this_thread::sleep_for(interval);
    if (!ipc_.Heartbeat()) {
      LOG_WARN("gateway", "heartbeat failed");
      ipc_connected_.store(false);
    }
  }
}

void Gateway::StatsFlushLoop() {
  if (!cfg_.stats.enabled) return;
  auto interval = std::chrono::seconds(cfg_.stats.flush_interval_s);
  while (running_.load()) {
    std::this_thread::sleep_for(interval);
    auto summary = stats_.GetSummary();
    LOG_INFO("gateway", LogFmt("stats_flush: %s", summary.dump().c_str()));
  }
}

void Gateway::ProcessMessage(const IpcMessage& msg) {
  std::string from = msg.from;

  if (Router::IsIncoming(from)) {
    // Message from platform service -> route to agent
    IncomingMsg in;
    in.from     = from;
    in.platform = msg.payload.value("platform", "");
    in.content  = msg.payload.value("content", "");
    if (msg.payload.contains("metadata") && msg.payload["metadata"].is_object()) {
      in.chat_type = msg.payload["metadata"].value("chat_type", "");
    }

    std::string user_id = msg.payload.value("user_id", "");
    if (!perm_.IsAllowed(in.platform, user_id)) {
      LOG_WARN("gateway", LogFmt("IPC message rejected (permission): user=%s", user_id.c_str()));
      stats_.RecordError(in.platform);
      return;
    }
    if (!in.platform.empty() && !rate_limiter_.Allow(in.platform + ":" + user_id)) {
      LOG_WARN("gateway", LogFmt("IPC message rate limited: user=%s", user_id.c_str()));
      stats_.RecordError(in.platform);
      return;
    }

    auto result = router_.RouteIncoming(in);
    if (result.target.empty()) {
      LOG_ERROR("gateway", "no route for incoming IPC message");
      stats_.RecordError(in.platform);
      return;
    }
    ipc_.Send(cfg_.service.name, result.target, msg.payload, "request");
    stats_.RecordMessage(in.platform, "inbound");
    stats_.RecordRoute(result.target);

  } else if (Router::IsReply(from)) {
    // Reply from agent -> route to platform service
    // Agents using MCP ipc_send wrap their message as {"content": JSON_STRING}.
    // Extract direct fields first, then fall back to parsing content as JSON.
    ReplyMsg reply;
    reply.from = from;
    reply.reply_to_platform = msg.payload.value("reply_to_platform",
                                msg.payload.value("platform", ""));
    reply.target_bot = msg.payload.value("target_bot", "");
    std::string chat_id = msg.payload.value("chat_id",
                            msg.payload.value("user_id", ""));
    std::string content  = msg.payload.value("content", "");

    // If platform or chat_id are missing, try JSON-parsing content
    if (reply.reply_to_platform.empty() || chat_id.empty()) {
      auto parsed = nlohmann::json::parse(content, nullptr, /*exceptions=*/false);
      if (!parsed.is_discarded() && parsed.is_object()) {
        if (reply.reply_to_platform.empty())
          reply.reply_to_platform = parsed.value("platform", "");
        if (chat_id.empty())
          chat_id = parsed.value("chat_id", parsed.value("user_id", ""));
        if (reply.target_bot.empty())
          reply.target_bot = parsed.value("target_bot",
                               parsed.value("source_bot", ""));
        if (parsed.contains("content"))
          content = parsed.value("content", content);
        LOG_INFO("gateway", LogFmt("parsed JSON content for reply: platform=%s, chat_id=%s",
                                    reply.reply_to_platform.c_str(), chat_id.c_str()));
      }
    }

    // Default platform to telegram when chat_id is known
    if (reply.reply_to_platform.empty() && !chat_id.empty())
      reply.reply_to_platform = "telegram";

    auto result = router_.RouteReply(reply);
    if (result.target.empty()) {
      LOG_ERROR("gateway", LogFmt("no reply route for platform: %s",
                                   reply.reply_to_platform.c_str()));
      stats_.RecordError(reply.reply_to_platform);
      return;
    }
    nlohmann::json send_payload = {
        {"type", "send_message_request"},
        {"chat_id", chat_id},
        {"content", content},
        {"platform", reply.reply_to_platform},
        {"target_bot", reply.target_bot}
    };
    LOG_INFO("gateway", LogFmt("routing reply: platform=%s, chat_id=%s, target_bot=%s -> %s",
        reply.reply_to_platform.c_str(), chat_id.c_str(),
        reply.target_bot.c_str(), result.target.c_str()));
    ipc_.Send(cfg_.service.name, result.target, send_payload, "request");
    stats_.RecordMessage(reply.reply_to_platform, "outbound");
    stats_.RecordRoute(result.target);

  } else {
    LOG_INFO("gateway", LogFmt("skipping message from: %s", from.c_str()));
  }
}
