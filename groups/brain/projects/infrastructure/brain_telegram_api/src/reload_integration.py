"""Hot reload integration guide for telegram_api service.

This file documents how to integrate reload_manager.py with main.py.

Integration Steps:
==================

1. Import reload_manager in main.py:
   from reload_manager import ReloadManager, validate_bots_config, build_bots_runtime

2. Add ReloadManager to TelegramAPIService class:
   - In __init__: self._reload_manager = None
   - Add service.enable_hot_reload config check

3. Replace start_hot_reload() method:
   See implementation below

4. Register SIGHUP handler in main.py:
   The ReloadManager handles this internally

Implementation for main.py:
===========================

# Add to TelegramAPIService.__init__:
self.hot_reload_config = self.config.get('service', {}).get('enable_hot_reload', False)

# Replace start_hot_reload() method:
def start_hot_reload(self):
    """Start hot reload with SIGHUP support."""
    if not self.hot_reload_config:
        logger.info("Hot reload disabled (enable_hot_reload=false)")
        return

    bots_yaml_path = "/xkagent_infra/brain/infrastructure/config/third_api/telegram/telegram.yaml"
    if not os.path.exists(bots_yaml_path):
        logger.warning(f"bots.yaml not found: {bots_yaml_path}")
        return

    # Create reload manager
    self._reload_manager = ReloadManager(
        config_path=bots_yaml_path,
        validate_fn=validate_bots_config,
        build_runtime_fn=build_bots_runtime,
        on_reload_callback=self._on_bots_reload
    )

    # Initialize config store
    from config_store import get_config_store
    config_store = get_config_store()

    # Load initial config
    with open(bots_yaml_path, 'r') as f:
        import yaml
        initial_config = yaml.safe_load(f) or {}

    runtime = build_bots_runtime(initial_config)
    config_store.initialize(initial_config, runtime)

    # Start reload manager (registers SIGHUP handler)
    self._reload_manager.start()
    logger.info("Hot reload enabled with SIGHUP support")

5. Update shutdown() to stop reload manager:
   if self._reload_manager:
       self._reload_manager.stop()
"""

# This is a documentation file, not actual code
# Copy the integration steps above into main.py
