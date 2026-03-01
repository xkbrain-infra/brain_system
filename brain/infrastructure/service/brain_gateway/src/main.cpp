#include "config.h"
#include "gateway.h"
#include "logger.h"

#include <csignal>
#include <cstdlib>
#include <cstring>
#include <memory>
#include <string>

static Gateway* g_gateway = nullptr;

static void SignalHandler(int sig) {
  if (g_gateway) {
    LOG_INFO("main", LogFmt("received signal %d, shutting down", sig));
    g_gateway->Shutdown();
  }
}

int main(int argc, char* argv[]) {
  std::string config_path = "/brain/infrastructure/service/brain_gateway/config/brain_gateway.json";

  for (int i = 1; i < argc; ++i) {
    if ((strcmp(argv[i], "--config") == 0 || strcmp(argv[i], "-c") == 0) && i + 1 < argc) {
      config_path = argv[++i];
    }
  }

  // Allow env override
  const char* env_cfg = getenv("GATEWAY_CONFIG");
  if (env_cfg && strlen(env_cfg) > 0) {
    config_path = env_cfg;
  }

  auto cfg = LoadConfig(config_path);
  if (!cfg) {
    // Error already logged in LoadConfig
    return 1;
  }

  // Set log level
  const std::string& ll = cfg->service.log_level;
  if (ll == "DEBUG") SetLogLevel(LogLevel::DEBUG);
  else if (ll == "WARN") SetLogLevel(LogLevel::WARN);
  else if (ll == "ERROR") SetLogLevel(LogLevel::ERROR);
  else SetLogLevel(LogLevel::INFO);

  LOG_INFO("main", LogFmt("brain_gateway starting, config: %s", config_path.c_str()));
  LOG_INFO("main", "constructing Gateway...");

  Gateway gw(std::move(*cfg));
  LOG_INFO("main", "Gateway constructed OK");
  g_gateway = &gw;

  struct sigaction sa{};
  sa.sa_handler = SignalHandler;
  sigemptyset(&sa.sa_mask);
  sigaction(SIGTERM, &sa, nullptr);
  sigaction(SIGINT,  &sa, nullptr);

  LOG_INFO("main", "calling Gateway::Run()");
  if (!gw.Run()) {
    LOG_INFO("main", "brain_gateway failed to start");
    return 1;
  }

  LOG_INFO("main", "brain_gateway exited");
  return 0;
}
