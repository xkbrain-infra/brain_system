#include "http_server.h"
#include "logger.h"

#include <json.hpp>
#include <algorithm>
#include <cctype>
#include <cstdlib>

using json = nlohmann::json;

HttpServer::HttpServer(const AppConfig& cfg, IpcBridge& ipc, Router& router,
                       TrafficStats& stats, Permission& perm, RateLimiter& rate_limiter,
                       std::atomic<uint64_t>& uptime_s, std::atomic<bool>& ipc_connected)
    : cfg_(cfg), ipc_(ipc), router_(router), stats_(stats), perm_(perm),
      rate_limiter_(rate_limiter), uptime_s_(uptime_s), ipc_connected_(ipc_connected) {
  RegisterRoutes();
}

std::optional<HttpServer::UpstreamTarget> HttpServer::ResolveLlmUpstream() const {
  const std::string raw = cfg_.llm_gateway.upstream_base_url;
  const std::string http_prefix = "http://";
  if (raw.rfind(http_prefix, 0) != 0) {
    LOG_ERROR("http_server", LogFmt("llm_gateway only supports http upstream now: %s", raw.c_str()));
    return std::nullopt;
  }

  std::string rem = raw.substr(http_prefix.size());
  std::string hostport = rem;
  std::string base_path = "";
  auto slash_pos = rem.find('/');
  if (slash_pos != std::string::npos) {
    hostport = rem.substr(0, slash_pos);
    base_path = rem.substr(slash_pos);
  }
  if (hostport.empty()) return std::nullopt;

  std::string host = hostport;
  int port = 80;
  auto colon_pos = hostport.rfind(':');
  if (colon_pos != std::string::npos && colon_pos + 1 < hostport.size()) {
    host = hostport.substr(0, colon_pos);
    auto port_s = hostport.substr(colon_pos + 1);
    if (port_s.empty()) return std::nullopt;
    for (char c : port_s) {
      if (c < '0' || c > '9') return std::nullopt;
    }
    port = std::atoi(port_s.c_str());
    if (port <= 0) {
      return std::nullopt;
    }
  }
  if (host.empty() || port <= 0) return std::nullopt;
  return UpstreamTarget{host, port, base_path};
}

std::string HttpServer::BuildForwardPath(const UpstreamTarget& upstream, const std::string& endpoint) const {
  std::string path = upstream.base_path;
  if (!path.empty() && path.back() == '/' && !endpoint.empty() && endpoint.front() == '/') {
    path.pop_back();
  }
  path += endpoint;
  return path;
}

bool HttpServer::ForwardLlmRequest(
    const httplib::Request& req,
    httplib::Response& res,
    const std::string& endpoint,
    bool allow_stream) const {
  auto upstream_opt = ResolveLlmUpstream();
  if (!upstream_opt) {
    res.status = 500;
    res.set_content(json{{"error", "UPSTREAM_CONFIG_INVALID"}}.dump(), "application/json");
    return false;
  }
  const auto& upstream = *upstream_opt;

  if (req.method == "POST") {
    auto body = json::parse(req.body, nullptr, /*allow_exceptions=*/false);
    const bool wants_stream = (!body.is_discarded() && body.is_object() && body.value("stream", false));
    if (wants_stream && !allow_stream) {
      res.status = 501;
      res.set_content(
          json{
              {"error", "NOT_IMPLEMENTED"},
              {"message", "streaming passthrough is not enabled for this endpoint"},
          }
              .dump(),
          "application/json");
      return false;
    }
    if (wants_stream) {
      return ForwardLlmStream(req, res, endpoint);
    }
  }

  httplib::Client cli(upstream.host, upstream.port);
  cli.set_connection_timeout(3, 0);
  cli.set_read_timeout(static_cast<time_t>(cfg_.llm_gateway.timeout_s), 0);
  cli.set_write_timeout(30, 0);

  std::string path = BuildForwardPath(upstream, endpoint);
  if (!req.params.empty()) {
    path += "?";
    bool first = true;
    for (const auto& kv : req.params) {
      if (!first) path += "&";
      first = false;
      path += kv.first;
      path += "=";
      path += kv.second;
    }
  }

  auto lower = [](std::string s) {
    std::transform(s.begin(), s.end(), s.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return s;
  };

  httplib::Headers headers;
  for (const auto& h : req.headers) {
    auto key = lower(h.first);
    if (key == "host" || key == "content-length") continue;
    headers.emplace(h.first, h.second);
  }

  httplib::Result upstream_res;
  if (req.method == "GET") {
    upstream_res = cli.Get(path, headers);
  } else if (req.method == "POST") {
    auto content_type = req.get_header_value("Content-Type");
    if (content_type.empty()) content_type = "application/json";
    upstream_res = cli.Post(path, headers, req.body, content_type);
  } else {
    res.status = 405;
    res.set_content(json{{"error", "METHOD_NOT_ALLOWED"}}.dump(), "application/json");
    return false;
  }

  if (!upstream_res) {
    res.status = 502;
    res.set_content(
        json{{"error", "UPSTREAM_UNAVAILABLE"},
             {"message", "failed to reach llm upstream"}}.dump(),
        "application/json");
    return false;
  }

  res.status = upstream_res->status;
  std::string ct = upstream_res->get_header_value("Content-Type");
  if (ct.empty()) ct = "application/json";
  res.set_content(upstream_res->body, ct);
  return true;
}

bool HttpServer::ForwardLlmStream(
    const httplib::Request& req,
    httplib::Response& res,
    const std::string& endpoint) const {
  auto upstream_opt = ResolveLlmUpstream();
  if (!upstream_opt) {
    res.status = 500;
    res.set_content(json{{"error", "UPSTREAM_CONFIG_INVALID"}}.dump(), "application/json");
    return false;
  }
  const auto upstream = *upstream_opt;

  auto lower = [](std::string s) {
    std::transform(s.begin(), s.end(), s.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    return s;
  };

  httplib::Headers headers;
  for (const auto& h : req.headers) {
    auto key = lower(h.first);
    if (key == "host" || key == "content-length") continue;
    headers.emplace(h.first, h.second);
  }

  std::string path = BuildForwardPath(upstream, endpoint);
  if (!req.params.empty()) {
    path += "?";
    bool first = true;
    for (const auto& kv : req.params) {
      if (!first) path += "&";
      first = false;
      path += kv.first;
      path += "=";
      path += kv.second;
    }
  }

  auto started = std::make_shared<bool>(false);
  auto req_copy = req;
  res.status = 200;
  res.set_header("Cache-Control", "no-cache");
  res.set_header("Connection", "keep-alive");
  res.set_chunked_content_provider(
      "text/event-stream",
      [this, upstream, headers, path, req_copy, started](size_t, httplib::DataSink& sink) mutable {
        if (*started) return false;
        *started = true;

        httplib::Client cli(upstream.host, upstream.port);
        cli.set_connection_timeout(3, 0);
        cli.set_read_timeout(static_cast<time_t>(cfg_.llm_gateway.timeout_s), 0);
        cli.set_write_timeout(30, 0);

        httplib::Request upstream_req;
        upstream_req.method = "POST";
        upstream_req.path = path;
        upstream_req.headers = headers;
        upstream_req.body = req_copy.body;
        upstream_req.content_receiver = [&sink](const char* data, size_t n, uint64_t, uint64_t) {
          if (n > 0) sink.write(data, n);
          return !sink.is_writable() ? false : true;
        };

        bool response_ok = false;
        upstream_req.response_handler = [&sink, &response_ok](const httplib::Response& upstream_res) {
          response_ok = (upstream_res.status == 200);
          if (!response_ok) {
            std::string payload = "{\"error\":\"UPSTREAM_STATUS\",\"status\":" +
                                  std::to_string(upstream_res.status) + "}";
            std::string evt = "event: error\ndata: " + payload + "\n\n";
            sink.write(evt.c_str(), evt.size());
          }
          return true;
        };

        httplib::Response upstream_res;
        httplib::Error err = httplib::Error::Success;
        bool ok = cli.send(upstream_req, upstream_res, err);
        if (!ok && !response_ok) {
          std::string payload = "{\"error\":\"UPSTREAM_UNAVAILABLE\"}";
          std::string evt = "event: error\ndata: " + payload + "\n\n";
          sink.write(evt.c_str(), evt.size());
        }
        sink.done();
        return false;
      });
  return true;
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

  if (cfg_.llm_gateway.enabled) {
    LOG_INFO("http_server", LogFmt("llm_gateway enabled, upstream=%s",
                                    cfg_.llm_gateway.upstream_base_url.c_str()));

    svr_.Post("/v1/messages", [this](const httplib::Request& req, httplib::Response& res) {
      (void)ForwardLlmRequest(req, res, "/v1/messages", /*allow_stream=*/true);
    });
    svr_.Post("/v1/messages/count_tokens", [this](const httplib::Request& req, httplib::Response& res) {
      (void)ForwardLlmRequest(req, res, "/v1/messages/count_tokens", /*allow_stream=*/true);
    });
    svr_.Post("/v1/chat/completions", [this](const httplib::Request& req, httplib::Response& res) {
      (void)ForwardLlmRequest(req, res, "/v1/chat/completions", /*allow_stream=*/true);
    });
    svr_.Post("/v1/responses", [this](const httplib::Request& req, httplib::Response& res) {
      (void)ForwardLlmRequest(req, res, "/v1/responses", /*allow_stream=*/true);
    });
    svr_.Post("/v1/embeddings", [this](const httplib::Request& req, httplib::Response& res) {
      (void)ForwardLlmRequest(req, res, "/v1/embeddings", /*allow_stream=*/true);
    });
    svr_.Get("/v1/models", [this](const httplib::Request& req, httplib::Response& res) {
      (void)ForwardLlmRequest(req, res, "/v1/models", /*allow_stream=*/true);
    });
  }
}

bool HttpServer::Listen() {
  LOG_INFO("http_server", LogFmt("listening on %s:%d",
                                  cfg_.service.host.c_str(), cfg_.service.port));
  return svr_.listen(cfg_.service.host.c_str(), cfg_.service.port);
}

void HttpServer::Stop() { svr_.stop(); }
