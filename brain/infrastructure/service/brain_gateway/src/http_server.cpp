#include "http_server.h"
#include "logger.h"

#include <json.hpp>

using json = nlohmann::json;

HttpServer::HttpServer(const AppConfig& cfg, IpcBridge& ipc, Router& router,
                       TrafficStats& stats, Permission& perm, RateLimiter& rate_limiter,
                       std::atomic<uint64_t>& uptime_s, std::atomic<bool>& ipc_connected)
    : cfg_(cfg), ipc_(ipc), router_(router), stats_(stats), perm_(perm),
      rate_limiter_(rate_limiter), uptime_s_(uptime_s), ipc_connected_(ipc_connected) {
  RegisterRoutes();
}

void HttpServer::RegisterRoutes() {
  // GET /health
  svr_.Get("/health", [this](const httplib::Request&, httplib::Response& res) {
    json body = {
        {"status", "ok"},
        {"service", cfg_.service.name},
        {"uptime_s", uptime_s_.load()},
        {"ipc_connected", ipc_connected_.load()}
    };
    res.set_content(body.dump(), "application/json");
  });

  // POST /api/v1/messages
  svr_.Post("/api/v1/messages", [this](const httplib::Request& req, httplib::Response& res) {
    auto body = json::parse(req.body, nullptr, /*allow_exceptions=*/false);
    if (body.is_discarded()) {
      res.status = 400;
      res.set_content(json{{"error", "BAD_REQUEST"}, {"message", "invalid JSON body"}}.dump(),
                      "application/json");
      return;
    }
    if (!body.contains("platform") || !body["platform"].is_string()) {
      res.status = 400;
      res.set_content(json{{"error", "BAD_REQUEST"}, {"message", "missing required field: platform"}}.dump(),
                      "application/json");
      return;
    }
    if (!body.contains("content")) {
      res.status = 400;
      res.set_content(json{{"error", "BAD_REQUEST"}, {"message", "missing required field: content"}}.dump(),
                      "application/json");
      return;
    }

    std::string platform = body["platform"].get<std::string>();
    std::string user_id  = body.value("user_id", "");

    // Permission check
    if (!perm_.IsAllowed(platform, user_id)) {
      res.status = 403;
      res.set_content(json{{"error", "FORBIDDEN"}, {"message", "user not in whitelist"}}.dump(),
                      "application/json");
      stats_.RecordError(platform);
      return;
    }

    // Rate limit check
    std::string rl_key = platform + ":" + user_id;
    if (!rate_limiter_.Allow(rl_key)) {
      res.status = 429;
      res.set_content(json{{"error", "RATE_LIMITED"}, {"message", "too many requests"}}.dump(),
                      "application/json");
      stats_.RecordError(platform);
      return;
    }

    // Build IncomingMsg and route
    IncomingMsg msg;
    msg.platform = platform;
    msg.content  = body.value("content", "");
    msg.from     = "http";
    if (body.contains("metadata") && body["metadata"].is_object()) {
      msg.chat_type = body["metadata"].value("chat_type", "");
    }

    auto result = router_.RouteIncoming(msg);
    if (result.target.empty()) {
      res.status = 500;
      res.set_content(json{{"error", "INTERNAL_ERROR"}, {"message", "no route found"}}.dump(),
                      "application/json");
      stats_.RecordError(platform);
      return;
    }

    // Forward to target agent via IPC
    json payload = body;
    payload["_routed_to"] = result.target;

    bool ok = ipc_.Send(cfg_.service.name, result.target, payload, "request");
    if (!ok) {
      res.status = 500;
      res.set_content(json{{"error", "INTERNAL_ERROR"}, {"message", "IPC send failed"}}.dump(),
                      "application/json");
      stats_.RecordError(platform);
      return;
    }

    stats_.RecordMessage(platform, "inbound");
    stats_.RecordRoute(result.target);

    // Generate simple msg_id
    static std::atomic<uint64_t> seq{0};
    std::string msg_id = "gw-" + std::to_string(seq.fetch_add(1));

    res.status = 202;
    res.set_content(json{{"status", "queued"}, {"msg_id", msg_id},
                         {"routed_to", result.target}}.dump(),
                    "application/json");
  });

  // GET /api/v1/agents
  svr_.Get("/api/v1/agents", [this](const httplib::Request&, httplib::Response& res) {
    auto data = ipc_.ListAgents();
    json out = json::object();
    json agents_arr = json::array();
    if (data.contains("agents") && data["agents"].is_array()) {
      for (auto& a : data["agents"]) {
        json entry;
        entry["name"]   = a.value("name", "");
        entry["status"] = a.value("online", false) ? "online" : "offline";
        agents_arr.push_back(entry);
      }
    }
    out["agents"] = agents_arr;
    out["count"]  = agents_arr.size();
    res.set_content(out.dump(), "application/json");
  });

  // GET /api/v1/stats
  svr_.Get("/api/v1/stats", [this](const httplib::Request&, httplib::Response& res) {
    auto s = stats_.GetSummary();
    s["uptime_s"] = uptime_s_.load();
    res.set_content(s.dump(), "application/json");
  });

  // GET /api/v1/stats/agents
  svr_.Get("/api/v1/stats/agents", [this](const httplib::Request&, httplib::Response& res) {
    auto s = stats_.GetSummary();
    json out = {{"agents", s.value("by_agent", json::object())}};
    res.set_content(out.dump(), "application/json");
  });

  // GET /api/v1/stats/platforms
  svr_.Get("/api/v1/stats/platforms", [this](const httplib::Request&, httplib::Response& res) {
    auto s = stats_.GetSummary();
    json out = {{"platforms", s.value("by_platform", json::object())}};
    res.set_content(out.dump(), "application/json");
  });

  // POST /api/v1/nodes/{id}/relay
  svr_.Post(R"(/api/v1/nodes/([^/]+)/relay)", [](const httplib::Request&, httplib::Response& res) {
    res.status = 501;
    res.set_content(json{{"error", "NOT_IMPLEMENTED"},
                         {"message", "cluster relay is planned for M2"}}.dump(),
                    "application/json");
  });
}

bool HttpServer::Listen() {
  LOG_INFO("http_server", LogFmt("listening on %s:%d",
                                  cfg_.service.host.c_str(), cfg_.service.port));
  return svr_.listen(cfg_.service.host.c_str(), cfg_.service.port);
}

void HttpServer::Stop() { svr_.stop(); }
