## WP
<!-- e.g. TM-B2 -->

## Summary
<!-- 2–3 sentences, English. -->

## Directories touched
<!-- Must stay within the WP's track. Reviewer rejects if it crosses tracks. -->

## Contracts changed?
- [ ] No
- [ ] Yes — ADR: <link>

## Checklist
- [ ] `uv run task lint` passes
- [ ] `uv run task test` passes
- [ ] `uv run task dbt-parse` passes if `dbt/` or `contracts/sql/` was touched
- [ ] `pnpm --dir web lint` passes if `web/` was touched
- [ ] `pnpm --dir web build` passes if `web/` was touched
- [ ] New files or deps justified
- [ ] Linear issue referenced (`Closes TM-X`)
