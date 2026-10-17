# Executor validation and integration

WP8 adds account-change executors. Every supplied browser recipe has `validated=False` until a real account completes the checks below. Fake-page tests establish runner behavior; they do not validate vendor selectors.

## Recipe status

| Recipe | Tier and supported role | Current status |
| --- | --- | --- |
| `notion_change_email` | T1, login email | Candidate. Add and verify alias, make it primary, remove old alias, reload and check both addresses. |
| `canva_change_email` | T1, login email | Candidate. Read old-inbox code, change address, read new-inbox code, reload and check both addresses. |
| `x_change_phone` | T2, login phone | Candidate. Replace phone, wait for Telegram SMS relay, reload and check both numbers. |

Notion's [account settings documentation](https://www.notion.com/help/account-settings) now describes email aliases. A verified alias remains usable for login, so the recipe removes the old address. The proposed `https://www.notion.so/settings/account` link and accessible row controls need live validation. If the link does not open account settings, capture the actual settings URL and update the recipe before executing.

Canva's [email-change instructions](https://www.canva.com/help/change-email/) require proof from both inboxes. The recipe selects the old and new root IDs separately. Existing ingestion settings support `email_college` and `email_primary`.

X is the T2 candidate because its [phone-change flow](https://help.x.com/en/managing-your-account/how-to-update-your-account-phone-number) replaces the number directly. LinkedIn can require email proof and device approval. Dropbox's documented phone change concerns 2FA and has country restrictions. Amazon.in's proof destinations are unresolved in the policy. These are reasons to try X first, not evidence that it works without a password challenge. X's exact selectors and phone display format remain unverified. A password prompt falls back to assisted execution; the agent never asks for or fills a password.

The DSL is a tuple of typed steps with a single runner. Locator fallbacks select a unique visible control before acting. An action that fails after selection is not retried against another control. Final browser confirmation requires reloading settings, seeing the new contact, and seeing that the old contact is absent. Receiving a code alone never marks the change done.

## Validate with the demo accounts

1. Create personal, unmanaged Notion and Canva accounts with the stand-in college email. Keep the replacement email free of separate accounts on those services. Configure a local account password manually if required by the service.
2. Configure both inboxes through the normal Lapse setup. Confirm that IMAP watches `email_college` and `email_primary`. Do not paste app passwords into logs, screenshots, or this document.
3. Install the browser dependency and Chromium:

   ```sh
   uv sync --extra browser
   uv run playwright install chromium
   ```

4. Create each persistent profile. Sign in manually, finish any challenge, open the account settings page, then press Enter in the terminal:

   ```sh
   uv run python scripts/browser_login.py --service notion --uid demo
   uv run python scripts/browser_login.py --service canva --uid demo
   uv run python scripts/browser_login.py --service x --uid demo
   ```

5. Check navigation without changing contacts:

   ```sh
   uv run python scripts/exec_dry_run.py --service notion --uid demo
   uv run python scripts/exec_dry_run.py --service canva --uid demo
   uv run python scripts/exec_dry_run.py --service x --uid demo
   ```

   Inspect the screenshots under `data/screens/demo/`. Resolve login redirects, settings URLs, accessible control labels and X number formatting before approval. Login must stay on recipe domains; external SSO is unsupported.

6. Start the worker with `EXEC_HEADED=true` for the demo. Through the normal plan and approval flow, approve one Notion login-email change from `email_college` to `email_primary`. Check that the executor receives the new-inbox code automatically, makes the new alias primary and removes the old alias. Confirm the settings state after a reload, then verify the graph change is done.
7. Approve Canva's equivalent change. Check that the first code is read from the college inbox and the second from the primary inbox. Reload settings and verify the saved address and graph result.
8. For X, prepare a logged-in account with the old number and complete any password challenge manually. Approve only its login-phone replacement. When Telegram requests a code for the new number, enter that SMS code there. Confirm that the runner resumes, the number changes after reload and the graph marks the change done. A recovery-phone or SMS-2FA change stays assisted.
9. Exercise fallback with an unavailable control in a test recipe. Expect a masked screenshot, the service settings link and `awaiting_user`, with no graph repoint. Confirm that no earlier action is replayed.
10. Record the date, account mode, selectors, settings URL and outcome here. Set only the successfully exercised recipe's `validated` flag to true. Keep codes, tokens and private account details out of the record.

If a recipe partially changes an account before fallback, inspect the service state before starting another approved attempt. Queue redelivery does not replay a running change. A worker crash leaves the change claimed; reconcile the account and clear its `exec_active` flag through an operator-controlled recovery before verification or a new approval.

## Verification and reminders

`verify_pending(uid, trace=None)` checks changes in `running` or `awaiting_user` after browser execution has released them. Each change stores `started_at`. Evidence must support that exact account, arrive later than the start, identify a contact change, come from a service domain and match a procedure regex. A replacement must appear in the message. The parser must identify the intended replacement and the confirmation must describe the changed role. A recovery-phone message cannot confirm an SMS-factor change. A matching subject that omits the replacement remains pending rather than guessing.

Notion and Canva currently have empty policy `confirmation_patterns`. Their recipes can close a change using final browser assertions. Their assisted fallbacks cannot auto-close until the policy owner adds tested confirmation patterns. This package edits only recipe names and the X phone tier, as requested. Ingestion also identifies accounts using service plus email: a confirmation delivered to the new email can support a different account node. The ingestion owner must preserve account identity across email changes before those messages can verify the original change.

T4 emits a checklist and an editable request template. It stores a due reminder in Redis, sends the first reminder within a day or by the change deadline, and repeats daily. Completed, skipped and failed changes remove their reminders. No request is submitted automatically.

## Wire these hooks in the lead package

- Register `handle_execute_change` for `execute_change` with `lapse.exec.jobs.register_handlers()`. The handler is async; the worker must await it. Job payload is `{"change_id": "..."}`. The module has no registration side effect so importing it before WP5 exists is safe.
- Call `lapse.exec.t4_offline.register_reminders(scheduler)` once when the worker scheduler starts.
- Call `verify_pending(uid)` after evidence ingestion and periodically for users with pending changes. No process or scheduler starts on import.
- The approval consumer must mark the exact approved changes `approved` before enqueueing. This handler atomically claims only that status. It does not mint or consume tokens again.
- Serve screenshots through an authenticated, user-scoped `/api/screens/<uid>/<filename>` route. The latest screenshot is Redis JSON at `lapse:screen:<uid>` with `url` and `caption`.
- Map notification buttons using `action="open_url"`, `payload={"url": ...}`. SMS notifications include the change ID in the parallel `ExecStep` event and use the existing `otp.wait(uid, change_id)` relay.
- Keep graph queries traceable by passing the optional `trace` argument. Execution steps publish `ExecStep` JSON through `events.publish(uid, "exec", data)`.

## Safety and remaining gaps

Browser navigation is restricted to recipe domains. Persistent profiles are separated by user and service; concurrent Chromium use of the same profile must be serialized by the worker. Keep the manual-login helper closed during execution.

Codes and message bodies stay in memory. The IMAP reader uses read-only folders and `BODY.PEEK[]`, does not alter ingestion watermarks, and never writes messages or codes. IMAP timestamps have one-second precision, so the request second is included; a matching message from less than one second before the request cannot be distinguished by timestamp alone. Steps, errors and notifications omit code values and verification URLs. Screenshots mask input controls, editable content and six-digit text. Verification links open in a guarded, temporary browser context with the current session copied in memory. The persistent page reloads afterward. The supplied recipes expect numeric codes; a link in those flows causes assisted fallback at code entry. No Playwright tracing, videos or console capture is enabled. The browser's password manager is disabled.

Profiles necessarily retain session cookies and other browser state. Profile directories have owner-only permissions; screenshot files are owner-readable and writable only. **Application-level profile encryption required by the broader build plan is not implemented here.** Use local disk encryption and treat profiles and screenshots as sensitive. This is an explicit security gap, not an encryption claim. The executor does not read `.env` or `persona.local.yaml` itself; normal configuration loads environment values.

Sender-domain checks are attribution filters, not cryptographic mail authentication. Live validation must use expected service mail in the connected inbox. A successful migration describes the graph update under the methods we model, not proof about every service access method.

## Recorded verification

On 2026-10-17, `uv sync --extra browser` and `uv run playwright install chromium` completed. The executor suite passed 111 tests, including an isolated FalkorDB graph, real Chromium redirect interception and verification-token disk scans. `uv run pytest -m "not db" -q` passed 270 tests with 75 deselected. `uv run ruff check .` and `git diff --check` passed. The actual missing-profile dry run exited 1 with login instructions and no traceback.

Independent implementation and standards reviews found and verified fixes for contact-direction matching, role confusion, IMAP timestamp precision, redirect interception and token caching. Reviews used the same provider; no cross-provider review or live vendor-account validation was performed. The comment review removed one redundant test comment and retained the documented external-protocol constraints.
