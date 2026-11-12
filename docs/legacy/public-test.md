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

To seed labeled demo data explicitly, name the database with suffix `_demo`, set `SEED_DEMO=true`, and set a new secret `DEMO_PASSWORD` of at least 12 characters. The startup script seeds only an empty catalog. Accounts are `demo.admin` and `demo.inspector`. No default password is included in source. The public demo runner now opens directly without a login screen. Each visitor gets a separate browser session and CSRF token for the shared public.guest demo identity; visitors can use the shared sample data. Catalog mutations require a manager/admin session; the ordinary guest identity is rejected server-side even if its stored role is admin. For this public test, PUBLIC_DEMO_CATALOG_LOGIN=true enables entering any password in the catalog sign-in dialog, using the shared public.catalog manager identity. This requires ENVIRONMENT=demo and PUBLIC_DEMO_ACCESS=true; ordinary account login is unchanged. See [catalog lifecycle](catalog-lifecycle.md). This is only enabled when ENVIRONMENT=demo. Set PUBLIC_DEMO_ACCESS=false to restore login; normal production configuration still requires authentication. Human identity cannot be inferred from shared guest audit events. Source HTTPS cookies are always Secure in this runner.

Verify health, login, QR read-only lookup, confirmation, export completion, import completion and persistent data after restart before handing out the URL. A build configuration is not evidence of deployment. The existing public test runs on Render Free. Verify the live commit before treating a local change as deployed. Migration 002 intentionally blocks a release when existing catalog names conflict; resolve those names with the data owner before deployment. File storage on this Free deployment is ephemeral; it does not currently satisfy the persistent-storage recommendation above.
