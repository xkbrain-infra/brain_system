#include <gtest/gtest.h>
#include "router.h"
#include "config.h"

// Helper: build minimal RoutingConfig
static RoutingConfig MakeConfig() {
  RoutingConfig cfg;
  cfg.platforms["telegram"]  = "agent_system_frontdesk";
  cfg.chat_types["channel"]  = "agent_system_pmo";
  cfg.keywords.push_back({"(bug|crash)", "agent_system_qa"});
  cfg.default_target         = "agent_system_frontdesk";
  cfg.reply_targets["telegram"] = "service-telegram_api";
  cfg.bot_service_map["XKAgentBot"]  = "service-telegram_api";
  return cfg;
}

// T-ROUTE-001: keyword 优先级最高
TEST(RouterTest, KeywordMatchHasPriority) {
  auto cfg = MakeConfig();
  Router router(cfg);
  IncomingMsg msg;
  msg.platform  = "telegram";
  msg.content   = "crash: null pointer";
  msg.chat_type = "private";
  auto result = router.RouteIncoming(msg);
  EXPECT_EQ(result.target,       "agent_system_qa");
  EXPECT_EQ(result.rule_matched, "keyword");
}

// T-ROUTE-002: chat_type 次于 keyword
TEST(RouterTest, ChatTypeRouteWhenNoKeyword) {
  auto cfg = MakeConfig();
  Router router(cfg);
  IncomingMsg msg;
  msg.platform  = "telegram";
  msg.content   = "hello world";
  msg.chat_type = "channel";
  auto result = router.RouteIncoming(msg);
  EXPECT_EQ(result.target,       "agent_system_pmo");
  EXPECT_EQ(result.rule_matched, "chat_type");
}

// T-ROUTE-003: platform 规则
TEST(RouterTest, PlatformRouteWhenNoChatType) {
  auto cfg = MakeConfig();
  Router router(cfg);
  IncomingMsg msg;
  msg.platform  = "telegram";
  msg.content   = "普通消息";
  msg.chat_type = "";  // no chat_type match
  auto result = router.RouteIncoming(msg);
  EXPECT_EQ(result.target,       "agent_system_frontdesk");
  EXPECT_EQ(result.rule_matched, "platform");
}

// T-ROUTE-004: default 兜底
TEST(RouterTest, DefaultFallback) {
  auto cfg = MakeConfig();
  Router router(cfg);
  IncomingMsg msg;
  msg.platform  = "unknown_platform";
  msg.content   = "消息";
  msg.chat_type = "";
  auto result = router.RouteIncoming(msg);
  EXPECT_EQ(result.target,       "agent_system_frontdesk");
  EXPECT_EQ(result.rule_matched, "default");
}

// T-ROUTE-005: reply 消息路由
TEST(RouterTest, ReplyRouteToTelegramApi) {
  auto cfg = MakeConfig();
  Router router(cfg);
  ReplyMsg reply;
  reply.from              = "agent_system_frontdesk";
  reply.reply_to_platform = "telegram";
  reply.target_bot        = "";
  auto result = router.RouteReply(reply);
  EXPECT_EQ(result.target,    "service-telegram_api");
  EXPECT_EQ(result.direction, "outbound");
}

// IsIncoming / IsReply classification
TEST(RouterTest, MessageClassification) {
  EXPECT_TRUE(Router::IsIncoming("service-telegram_api"));
  EXPECT_FALSE(Router::IsIncoming("agent_system_frontdesk"));
  EXPECT_TRUE(Router::IsReply("agent_system_frontdesk"));
  EXPECT_TRUE(Router::IsReply("agent_system_pmo"));
  EXPECT_FALSE(Router::IsReply("service-telegram_api"));
}

// Bot service map routing
TEST(RouterTest, ReplyRouteViaBotServiceMap) {
  auto cfg = MakeConfig();
  Router router(cfg);
  ReplyMsg reply;
  reply.from              = "agent_system_frontdesk";
  reply.reply_to_platform = "telegram";
  reply.target_bot        = "XKAgentBot";
  auto result = router.RouteReply(reply);
  EXPECT_EQ(result.target, "service-telegram_api");
}
