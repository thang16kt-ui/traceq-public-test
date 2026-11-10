# Public test deployment

The deployment image is `deploy/public.Dockerfile`, built with repository root as context. It builds React and runs the real FastAPI API plus three independent scheduler/worker/importer processes. The process supervisor exits if any required process dies so the hosting service can restart it. This test layout has one shared failure domain; the Compose deployment remains available for separately managed services.

Configure a separate managed PostgreSQL database and persistent storage mounted at `/data`. Never publish the development database, its credentials or the runtime directory. Do not publish database ports. Public traffic uses the hosting provider's HTTPS endpoint. Configure `/health/ready` as health check.

Required environment:

| Name | Value |
|---|---|
| `DATABASE_URL` | Hosting provider PostgreSQL secret; postgres:// and postgresql:// are normalized to psycopg |
| `APP_ORIGIN` | Actual https:// public origin; Render/Railway domain environment variables are supported as fallback |
| `DATA_DIR` | `/data`, backed by a persistent volume |
| `ENVIRONMENT` | `demo` for the public test instance |
| `PORT` | Set by hosting provider, defaults to 8000 |

To seed labeled demo data explicitly, name the database with suffix `_demo`, set `SEED_DEMO=true`, and set a new secret `DEMO_PASSWORD` of at least 12 characters. The startup script seeds only an empty catalog. Accounts are `demo.admin` and `demo.inspector`. No default password is included in source. The app still requires login even when the URL is publicly accessible. Source HTTPS cookies are always Secure in this runner.

Verify health, login, QR read-only lookup, confirmation, export completion, import completion and persistent data after restart before handing out the URL. A build configuration is not evidence of deployment. The public image has not yet been built or deployed; a connected hosting account is still required. Billing/plan selection must be reviewed in the provider account.
