# Backstage Agent TODO

## Near Term

- Set up a daily 9am local run on this Mac with `launchd`.
- Add a clear run log file so we can see each day's messages, parsed roles, decisions, and errors.
- Keep dry-run mode on until application submission is verified end to end.
- Add a dashboard view for application drafts, not only screening decisions.
- Add a quick way to mark a decision as wrong and record the correction.

## Parsing And Email Quality

- Continue hardening Backstage digest parsing with examples from real emails.
- Add tests for every parser bug we find: missing first project, multi-role projects, fake metadata roles, and per-role Apply links.
- Store the email subject and message date with every decision for easier debugging.
- Store the original email snippet around each parsed role so dashboard review is easier.
- Detect duplicate scans and avoid inserting the same role twice.

## Screening Quality

- Consider moving the first-pass screener from OpenAI `gpt-4o-mini` to AI Builder `deepseek-v4-flash` for lower cost, while keeping the strict reviewer on `deepseek-v4-pro`.
- Improve age-range logic with deterministic local checks before the LLM.
- Improve gender, location, union, compensation, and travel matching with local rules.
- Keep comfort boundaries explicit: do not infer discomfort unless the profile or notice says so.
- Add a profile editor or simple profile summary page in the dashboard.
- Add a feedback loop so rejected/accepted manual corrections improve future prompts.

## Backstage Page Access

- Use the logged-in browser session to open each Apply link and read the full role page.
- Send a notification when `backstage-login-check` reports that the persistent browser profile is logged out.
- Compare email summary details with the full Backstage page before deciding.
- Capture application questions from the page and pause for user input when needed.
- Avoid submitting final applications without explicit confirmation until we trust the flow.
- Handle login expiration, cookie issues, CAPTCHA, and session prompts gracefully.

## Automation Reliability

- Add a `scan-date` or `--since-date` option for exact-date reruns.
- Add a command to delete/rebuild decisions for a specific project date.
- Add better error handling when Gmail, OpenAI, or Backstage is unavailable.
- Send a daily summary notification after each run.
- Keep secrets out of logs and dashboard output.

## Longer Term

- Consider moving the daily job to a small server or cloud runner if laptop sleep becomes annoying.
- Add secure secret storage instead of relying only on `.env`.
- Add cost controls and a monthly LLM usage summary.
- Add export/report features for decisions and applications.
- Build real application submission only after full-page inspection and confirmation are robust.
