#include "config.h"
#include "gateway.h"
#include "logger.h"

#include <csignal>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <memory>
#include <string>
#include <sys/file.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

static Gateway* g_gateway = nullptr;

namespace {

constexpr const char* kSupervisorProgram = "brain_gateway";
constexpr const char* kDefaultLockPath = "/tmp/brain_gateway.lock";

class InstanceLock {
 public:
  ~InstanceLock() {
    if (fd_ >= 0) {
      flock(fd_, LOCK_UN);
      close(fd_);
    }
  }

  bool Acquire(const std::string& lock_path) {
    fd_ = open(lock_path.c_str(), O_CREAT | O_RDWR, 0644);
    if (fd_ < 0) {
      LOG_ERROR("main", LogFmt("failed to open lock file: %s", lock_path.c_str()));
      return false;
    }
    if (flock(fd_, LOCK_EX | LOCK_NB) != 0) {
      LOG_WARN("main", LogFmt("another brain_gateway instance already holds lock: %s", lock_path.c_str()));
      return false;
    }

    const std::string pid = std::to_string(getpid()) + "\n";
    if (ftruncate(fd_, 0) == 0) {
      const ssize_t written = write(fd_, pid.c_str(), pid.size());
      (void)written;
    }
    return true;
  }

 private:
  int fd_ = -1;
};

bool StartedBySupervisor() {
  const char* enabled = getenv("SUPERVISOR_ENABLED");
  if (enabled && strcmp(enabled, "1") == 0) {
    return true;
  }
  const char* process_name = getenv("SUPERVISOR_PROCESS_NAME");
  return process_name && strcmp(process_name, kSupervisorProgram) == 0;
}

bool SupervisorReportsRunning() {
  FILE* fp = popen("supervisorctl status brain_gateway 2>/dev/null", "r");
  if (!fp) {
    return false;
  }
  char buffer[256];
  std::string output;
  while (fgets(buffer, sizeof(buffer), fp)) {
    output += buffer;
  }
  const int rc = pclose(fp);
  return rc == 0 && output.find("RUNNING") != std::string::npos;
}

int DelegateStartToSupervisor() {
  if (SupervisorReportsRunning()) {
    LOG_INFO("main", "brain_gateway already running under supervisord");
    return 0;
  }
  LOG_WARN("main", "brain_gateway launched outside supervisord; delegating to 'supervisorctl start brain_gateway'");
  const int status = std::system("supervisorctl start brain_gateway");
  if (status == -1) {
    LOG_ERROR("main", "failed to execute supervisorctl");
    return 1;
  }
  if (WIFEXITED(status) && WEXITSTATUS(status) == 0) {
    LOG_INFO("main", "delegated startup to supervisord");
    return 0;
  }
  if (WIFEXITED(status)) {
    LOG_ERROR("main", LogFmt("supervisorctl start brain_gateway failed with exit code %d", WEXITSTATUS(status)));
    return WEXITSTATUS(status);
  }
  LOG_ERROR("main", "supervisorctl start brain_gateway terminated abnormally");
  return 1;
}

std::string ResolveLockPath() {
  const char* env_lock = getenv("BRAIN_GATEWAY_LOCK_PATH");
  if (env_lock && strlen(env_lock) > 0) {
    return env_lock;
  }
  return kDefaultLockPath;
}

}  // namespace

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

  if (!StartedBySupervisor()) {
    return DelegateStartToSupervisor();
  }

  InstanceLock instance_lock;
  if (!instance_lock.Acquire(ResolveLockPath())) {
    return 1;
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
