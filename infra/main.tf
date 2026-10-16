module "data" {
  source  = "git::https://github.com/i-osipchyk/platform.git//terraform/modules/data-bucket?ref=v0.1.2"
  project = var.project
  env     = var.env
}

module "app" {
  source    = "git::https://github.com/i-osipchyk/platform.git//terraform/modules/lambda-app?ref=v0.1.2"
  project   = var.project
  env       = var.env
  image_uri = var.image_uri

  # The runs of ARCHITECTURE §5. Every run is idempotent; retries come from the schedule, so
  # async retries stay 0. spike_fetch (read-only Wikipedia + yfinance check, Phase 1 item 1) goes
  # when Phase 1 closes.
  functions = {
    evening       = { handler = "btd.handlers.evening_handler", timeout = 600, memory = 2048 }
    open_exit     = { handler = "btd.handlers.open_exit_handler", timeout = 120 }
    morning_check = { handler = "btd.handlers.morning_check_handler", timeout = 120 }
    heartbeat     = { handler = "btd.handlers.heartbeat_handler", timeout = 60 }
    spike_fetch   = { handler = "btd.handlers.spike_fetch", timeout = 600, memory = 2048 }
  }

  # ARCHITECTURE §5, New York time (EventBridge handles DST); handlers skip non-sessions.
  # The trading schedules are gated by trading_enabled (off until the supervised first run);
  # schedules_enabled stays the master switch.
  schedules = {
    evening_half  = { function = "evening", expression = "cron(30 16-22 ? * MON-FRI *)", timezone = "America/New_York", enabled = var.trading_enabled }
    evening_hour  = { function = "evening", expression = "cron(0 17-23 ? * MON-FRI *)", timezone = "America/New_York", enabled = var.trading_enabled }
    open_exit     = { function = "open_exit", expression = "cron(35 9 ? * MON-FRI *)", timezone = "America/New_York", enabled = var.trading_enabled }
    morning_check = { function = "morning_check", expression = "cron(50 9 ? * MON-FRI *)", timezone = "America/New_York", enabled = var.trading_enabled }
    heartbeat     = { function = "heartbeat", expression = "cron(15 23 ? * MON-FRI *)", timezone = "America/New_York", enabled = var.trading_enabled }
    spike1630     = { function = "spike_fetch", expression = "cron(30 16 ? * MON-FRI *)", timezone = "America/New_York" }
    spike1700     = { function = "spike_fetch", expression = "cron(0 17 ? * MON-FRI *)", timezone = "America/New_York" }
  }
  schedules_enabled  = var.schedules_enabled
  log_retention_days = 400 # the run logs are the forward test's audit trail (as gtb)

  environment = {
    DATA_BUCKET = module.data.name
  }
  write_bucket_arns = [module.data.arn]
}
