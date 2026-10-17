# WP6 verification

Verified 2026-10-17 in the local worktree, against the mock API.

- `npm run typecheck`, `npm test`: passed; 12 tests cover REST/SSE parsing, 5-to-10 account reach, mailbox Root distinction, AND prerequisites, unknown service, college lockout, approval/OTP transitions, graph rewiring, migrated-email takeover risk, stable tiers, bulk T4 exclusion, secret clearing, and stale explanation refresh.
- `npm run build`: passed. Bundler reports a large graph-inclusive bundle; no build failure. `npm audit`: zero reported vulnerabilities after selecting the current Vitest release.
- Real browser, 1920×1080 viewport: direct/full cascade; Dropbox path and both prerequisites; GitHub blocked; Splitwise unknown; college 4/4; combined 9/14; approval, OTP, verification, graph count reduction; agent screenshot and 26 trace rows.
- Connections: fictional credentials submitted, password cleared before response; streamed 1,240 emails, 17 accounts, inferred/confirmed counts; Telegram placeholder displayed. Browser localStorage/sessionStorage remained empty. OTP did not appear in trace text.
- Light appearance and 390px connections layout: no horizontal overflow.
- Reduced motion checked on the real browser by injecting the `matchMedia` preference and activating the existing reduced-motion CSS rule. Full chain immediately showed round 3/3; button transitions contained only background-color and opacity. Native OS-level preference emulation was not available through the collaborative browser.
- Independent read-only review found two defects, both corrected: migrated college accounts incorrectly lost takeover exposure, and an open explanation could remain stale after a verified change. A follow-up review found that compaction hid fixed nodes; completed accounts and their descendants now remain visible. Live Cytoscape checks confirmed Google and Dropbox were green, the phone_new-to-Google edge remained present, and Splitwise was not safe. The final reviewer found no remaining blocker. A comment review found no source comments or suppressions requiring changes.

## Replay

1. Start `npm run dev`; reload to reset the mock.
2. Verify 5 direct / 10 full accounts, then switch Full chain and wait for round 3/3. Inspect Dropbox, scroll evidence, then GitHub and Splitwise.
3. Choose College email closes and verify four affected accounts; inspect Google for retained sign-in. Choose Both and verify nine direct / fourteen full accounts.
4. Build the fix plan. Approve all T1–T3. Confirm Zomato T4 remains unapproved, Google and Swiggy await OTP, T1 completes, and T3 awaits the user before simulated confirmation.
5. Submit six digits for Google; return to the map with Dropbox selected. Its previous derivation must disappear. One unknown account must remain.
6. Inspect Agent activity. The screenshot is labelled simulated; query names, timings, row counts and outcomes are visible.
7. Connect with fictional credentials. Confirm the password field clears and discovery counters progress. Check light appearance, narrow viewport, and reduced motion.

Live backend interoperability remains unverified because the backend is built in parallel. Screenshot files are browser artifacts, resized by the preview capture tool from the desktop viewport.
