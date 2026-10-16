# buy-the-dip

Forward test of the S&P 500 volatile-dip limit buy on Pepperstone cTrader

Generated from [platform](https://github.com/i-osipchyk/platform) v0.1.2
(`uvx copier update --trust` pulls template changes).

## Develop

```bash
uv sync
cp .env.example .env    # fill in
uv run pytest
uv run ruff check . && uv run mypy
```

## Deploy

Pushing to the `dev` branch runs CI, then deploys **dev** (Pepperstone cTrader **demo** account).
**prod is not deployed**: `infra/env/prod.tfvars` is config only and the deploy workflow has no
prod job. You can also deploy dev by hand: Actions → Deploy → Run workflow.

One-time setup (platform `docs/deployment.md` has the details):
1. Add `btd = { repo = "buy-the-dip" }` to platform `bootstrap/terraform.tfvars`, then apply it.
2. GitHub repo → Settings → Environments: create `dev`.
3. GitHub repo → Settings → Variables: set `AWS_ACCOUNT_ID`. Set `AWS_REGION` too if it isn't eu-west-1.
4. Secrets: `uv run python scripts/put_secrets.py --env dev`.

Functions start with their schedules disabled (`schedules_enabled = false` in
`infra/env/dev.tfvars`). Flip that once a manual invoke looks right.

Docs: `docs/STRATEGY_SPEC.md` (the strategy), `docs/ARCHITECTURE.md` (what we trade and how),
`docs/IMPLEMENTATION_PLAN.md` (build phases).

### Terraform by hand (plan only; applies go through CI)

```bash
export AWS_REGION="${AWS_REGION:-eu-west-1}" TF_VAR_region="${AWS_REGION:-eu-west-1}"
ACCOUNT=$(aws sts get-caller-identity --query Account --output text)
terraform -chdir=infra init -backend-config="bucket=tfstate-$ACCOUNT-$AWS_REGION" \
  -backend-config="key=btd/dev.tfstate" -backend-config="region=$AWS_REGION"
terraform -chdir=infra plan -var-file=env/dev.tfvars -var="image_uri=<repo@sha256:...>"
```
