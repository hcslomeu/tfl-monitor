/**
 * Runtime environment flags read once at module load.
 *
 * `USE_MOCKS` is opt-in. Production and preview deploys leave
 * `NEXT_PUBLIC_USE_MOCKS` unset so the dashboard hits the live API;
 * local contributors who want offline mode set the variable to `"true"`
 * in `web/.env.local`. The flag is read via the `NEXT_PUBLIC_*` prefix
 * so it survives Next.js bundling for client components.
 */

export const USE_MOCKS = process.env.NEXT_PUBLIC_USE_MOCKS === "true";
