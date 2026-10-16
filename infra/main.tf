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

  # Phase 1 spike (throwaway, read-only): Wikipedia + yfinance from AWS at 16:30 and 17:00 New
  # York. Phase 4 replaces this with the real functions and schedules (ARCHITECTURE §5).
  functions = {
    spike_fetch = { handler = "btd.handlers.spike_fetch", timeout = 600, memory = 2048 }
  }

  schedules = {
    spike1630 = { function = "spike_fetch", expression = "cron(30 16 ? * MON-FRI *)", timezone = "America/New_York" }
    spike1700 = { function = "spike_fetch", expression = "cron(0 17 ? * MON-FRI *)", timezone = "America/New_York" }
  }
  schedules_enabled = var.schedules_enabled

  environment = {
    DATA_BUCKET = module.data.name
  }
  write_bucket_arns = [module.data.arn]
}
