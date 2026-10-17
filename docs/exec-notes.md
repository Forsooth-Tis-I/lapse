# Executor validation and integration

WP8 adds account-change executors. Notion was validated against a real account on 2026-10-18. Canva and X remain `validated=False`. Fake-page tests establish runner behavior; they do not validate vendor selectors.

## Recipe status

| Recipe | Tier and supported role | Current status |
| --- | --- | --- |
| `notion_change_email` | T1, login email | Validated 2026-10-18. Add alias using codes from both inboxes, make it primary, remove old alias, reload and check both addresses. |
| `canva_change_email` | T1, login email | Candidate. Read old-inbox code, change address, read new-inbox code, reload and check both addresses. |
| `x_change_phone` | T2, login phone | Candidate. Replace phone, wait for Telegram SMS relay, reload and check both numbers. |

Notion uses email aliases. A verified alias remains usable for login, so the recipe removes the old address. The live entry point is `https://www.notion.so/home`; `/settings/account` redirects to the workspace instead of opening settings. The recipe opens the workspace-name menu, selects **Settings**, searches settings for `email`, selects **Email**, then **Manage emails**. Searching avoids depending on the user's profile name. Both inboxes must be accessible for this validated T1 flow.

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

6. Start the worker with `EXEC_HEADED=true` for the demo. Through the normal plan and approval flow, approve one Notion login-email change from `email_college` to `email_primary`. Check that the executor receives both the new-inbox and old-inbox codes automatically, makes the new alias primary and removes the old alias. Confirm the settings state after a reload, then verify the graph change is done.
7. Approve Canva's equivalent change. Check that the first code is read from the college inbox and the second from the primary inbox. Reload settings and verify the saved address and graph result.
8. For X, prepare a logged-in account with the old number and complete any password challenge manually. Approve only its login-phone replacement. When Telegram requests a code for the new number, enter that SMS code there. Confirm that the runner resumes, the number changes after reload and the graph marks the change done. A recovery-phone or SMS-2FA change stays assisted.
9. Exercise fallback with an unavailable control in a test recipe. Expect a masked screenshot, the service settings link and `awaiting_user`, with no graph repoint. Confirm that no earlier action is replayed.
10. Record the date, account mode, selectors, settings URL and outcome here. Set only the successfully exercised recipe's `validated` flag to true. Keep codes, tokens and private account details out of the record.

If a recipe partially changes an account before fallback, inspect the service state before starting another approved attempt. Queue redelivery does not replay a running change. A worker crash leaves the change claimed; reconcile the account and clear its `exec_active` flag through an operator-controlled recovery before verification or a new approval.

## Verification and reminders

`verify_pending(uid, trace=None)` checks changes in `running` or `awaiting_user` after browser execution has released them. Each change stores `started_at`. Evidence must support that exact account, arrive later than the start, identify a contact change, come from a service domain and match a procedure regex. A replacement must appear in the message. The parser must identify the intended replacement and the confirmation must describe the changed role. A recovery-phone message cannot confirm an SMS-factor change. A matching subject that omits the replacement remains pending rather than guessing.

Notion and Canva have conservative completed-email-change patterns. Exact vendor subjects still need live validation. Ingestion preserves an existing Account ID across email changes and associates confirmation evidence with that account. Ambiguous account matches stop ingestion for review.

T4 emits a checklist and an editable request template. It stores a due reminder in Redis, sends the first reminder within a day or by the change deadline, and repeats daily. Completed, skipped and failed changes remove their reminders. No request is submitted automatically.

## Worker integration

- Worker startup calls `lapse.exec.jobs.register_handlers()` and awaits `handle_execute_change`. Job payload is `{"change_id": "..."}`.
- Worker startup registers T4 reminders, checked every minute.
- The worker calls `verify_pending(uid)` after ingestion and queues verification for every tenant every five minutes. No scheduler starts on import.
- The approval consumer must mark the exact approved changes `approved` before enqueueing. This handler atomically claims only that status. It does not mint or consume tokens again.
- Screenshots use `/api/screens/<uid>/<filename>` and are confined to the selected user’s directory. The local UID selector is not authentication. The latest screenshot is Redis JSON at `lapse:screen:<uid>` with `url` and `caption`.
- Map notification buttons using `action="open_url"`, `payload={"url": ...}`. SMS notifications include the change ID in the parallel `ExecStep` event and use the existing `otp.wait(uid, change_id)` relay.
- Keep graph queries traceable by passing the optional `trace` argument. Execution steps publish `ExecStep` JSON through `events.publish(uid, "exec", data)`.

## Safety and remaining gaps

Browser navigation is restricted to recipe domains. Persistent profiles are separated by user and service; concurrent Chromium use of the same profile must be serialized by the worker. Keep the manual-login helper closed during execution.

Codes and message bodies stay in memory. The IMAP reader uses read-only folders and `BODY.PEEK[]`, does not alter ingestion watermarks, and never writes messages or codes. IMAP timestamps have one-second precision, so the request second is included; a matching message from less than one second before the request cannot be distinguished by timestamp alone. Steps, errors and notifications omit code values and verification URLs. Screenshots capture the last visible dialog when present and mask its input controls, editable content and six-digit text. Otherwise they capture the page with the same masks. Scoping masks to the dialog prevents an underlying Notion document from covering account controls with a magenta rectangle. Verification links open in a guarded, temporary browser context with the current session copied in memory. The persistent page reloads afterward. Notion expects a bare six-character alphanumeric code in the plain-text message body. It supplies an explicit code pattern to the inbox reader; other recipes retain numeric extraction. A link in a code-only flow cannot confirm a change and stops at code entry. No Playwright tracing, videos or console capture is enabled. The browser's password manager is disabled.

Profiles necessarily retain session cookies and other browser state. Profile directories have owner-only permissions; screenshot files are owner-readable and writable only. **Application-level profile encryption required by the broader build plan is not implemented here.** Use local disk encryption and treat profiles and screenshots as sensitive. This is an explicit security gap, not an encryption claim. The executor does not read `.env` or `persona.local.yaml` itself; normal configuration loads environment values.

Sender-domain checks are attribution filters, not cryptographic mail authentication. Live validation must use expected service mail in the connected inbox. A successful migration describes the graph update under the methods we model, not proof about every service access method.

## Recorded verification

On 2026-10-17, `uv sync --extra browser` and `uv run playwright install chromium` completed. The executor suite passed 111 tests, including an isolated FalkorDB graph, real Chromium redirect interception and verification-token disk scans. `uv run pytest -m "not db" -q` passed 270 tests with 75 deselected. `uv run ruff check .` and `git diff --check` passed. The actual missing-profile dry run exited 1 with login instructions and no traceback.

Independent implementation and standards reviews found and verified fixes for contact-direction matching, role confusion, IMAP timestamp precision, redirect interception and token caching. Reviews used the same provider; no cross-provider review or live vendor-account validation was performed. The comment review removed one redundant test comment and retained the documented external-protocol constraints.


### Notion live validation, 2026-10-18

A saved session for a personal, unmanaged account completed the email migration in headless Chromium at 1440×900. No password, re-login or bot challenge appeared. No GPU flags or user-agent changes were needed.

The observed flow was:

1. Open `/home`, wait for the workspace-menu button, then open **Settings**. Search for `email`, select **Email**, and open **Manage emails**.
2. Select **Add email address**. Fill the textbox named `example@company.com` and select **Add email**.
3. Notion sends separate messages from `notify@updates.notion.com` to the new and current addresses. The **Verify email address** dialog requires both six-character alphanumeric codes. Each textbox has the same placeholder, `e.g. dqYVcm`; select it within the parent of the exact `Code sent to <address>` text. Poll each root's inbox using the timestamp immediately before **Add email**. No codes or email bodies are logged or saved.
4. Select **Verify email**. In the new address's row, select **Make primary** and wait for **Remove** to appear in the old address's row.
5. Select **Remove** in the old address's row. Removal is immediate; there is no second confirmation button.
6. Navigate to `/home` again, reopen **Manage emails**, and verify that the new address is present and the old address is absent.

Navigation waits for `domcontentloaded` and the workspace control rather than the full page load or a fixed sleep. Clicks that replace a dialog wait for the destination control before taking a screenshot. This avoids capturing a detached, closing workspace menu. The solid magenta document area in earlier screenshots was the privacy mask, not a rendering failure.

Only the previously approved change `change:3a3021db12504b4ebfe5468a4373ae36` was executed for `live`. The executor ran in-process from this worktree; no job was enqueued and the existing worker stayed running. The temporary operator script resolved the explicitly shared profile root, preserving the production symlink guard.

The mutation run verified both inboxes, made the replacement primary and removed the old alias. It then paused at an incorrectly anticipated second removal button. That step was deleted. A reload-only reconciliation ran through `handle_execute_change`, confirmed the final account state and called `apply_change_done` without replaying mutations. The corrected mutation steps and final verification were therefore exercised in separate phases, not by repeating the migration on another account.

The final change is `done`, `exec_active` is false, and Notion's `USES` edge for `login_email` points only to `email_primary`. Exposure was recomputed using the existing lockout scenario evaluator; Notion no longer appears among accounts affected by losing `email_college`, under the methods we model. Confirmation-email ingestion and `verify_pending` were unnecessary.

Evidence under `data/screens/live/`:

- `change:3a3021db12504b4ebfe5468a4373ae36-11.png`: the two-inbox verification dialog, with fields masked.
- `change:3a3021db12504b4ebfe5468a4373ae36-19.png`: verified replacement alias.
- `change:3a3021db12504b4ebfe5468a4373ae36-109.png`: fresh account settings showing only the replacement address, marked primary.

The recipe's `validated=True` records this live migration and successful reconciliation. It does not establish support for managed workspaces, accounts with different re-authentication requirements or future Notion UI changes.

Post-change verification on 2026-10-18: the full suite passed with 724 tests (`uv run pytest -q -x`). `uv run ruff check .`, formatting checks for all changed Python files, and `git diff --check` passed. The live dry run waited for workspace content before writing `data/screens/live/dry-run-notion.png`. A fresh read-only reviewer found no blocking findings in the final diff and ran 50 focused recipe/inbox tests. That reviewer did not independently operate the live account. One earlier full-suite attempt was interrupted by SIGTERM; the complete rerun passed.
