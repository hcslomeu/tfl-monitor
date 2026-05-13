/**
 * Runtime environment flags read once at module load.
 *
 * `USE_MOCKS` is default-on so the dashboard renders against fixtures
 * unless the deploy explicitly opts in to live data. The flag is read
 * via the `NEXT_PUBLIC_*` prefix so it survives Next.js bundling for
 * client components.
 */

export const USE_MOCKS = process.env.NEXT_PUBLIC_USE_MOCKS !== "false";
