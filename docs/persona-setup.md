# Demo identity setup

For a live demonstration, use a fresh test identity with real accounts. The college closure notice (step 5) is staged. This guide is an illustrative account setup, not a list of validated browser integrations; see [execution support](exec-notes.md). The README screenshots use synthetic frontend preview data instead.

Keep every welcome, OTP, sign-in and security email. Don't delete or archive anything. Those emails are the evidence the agent reads.

## 1. Two Gmail accounts
| Mailbox | Plays | Setup |
|---|---|---|
| **Primary** | The person's main email (the hub) | Recovery phone = **OLD** number. 2-Step Verification by SMS to the **OLD** number. Recovery email = the College stand-in. |
| **College stand-in** | A college address that will be closed | Name it to read like a student address (e.g. `firstname.lastname.<college>.student@gmail.com`). 2-Step Verification on, using the **NEW** number (needed for app passwords). |

For **both** mailboxes, create an **app password**: Google Account → Security → 2-Step Verification → App passwords. Then put the values in the repository's local `.env`:
```
PRIMARY_IMAP_USER=<primary address>
PRIMARY_IMAP_PASSWORD=<16-char app password>
COLLEGE_IMAP_USER=<college stand-in address>
COLLEGE_IMAP_PASSWORD=<16-char app password>
```

## 2. Phone numbers
Fill both numbers into the repository's local `persona.local.yaml`:
- **OLD:** the number being dropped. Include its carrier and a drop date.
- **NEW:** the number it is moving to.

Don't paste numbers into chat.

## 3. Sign-ups (designed so the graph has depth, AND gates, and a hub)
| Service | Sign up with | Phone | 2FA | Why it's in the demo |
|---|---|---|---|---|
| Notion | Primary | none | none (email code login) | Falls through the Gmail hub (depth 2) |
| Spotify | Primary | none | none | Depth 2 through Gmail |
| X | Primary | add **OLD** | none | Reachable directly from the number and through Gmail |
| Amazon.in | Primary | **OLD** (login phone) | none | Depth 1: phone OTP login |
| Swiggy | **OLD** phone; add Primary email in profile | **OLD** | none | Depth 1 |
| Zomato | **OLD** phone; add Primary email in profile | **OLD** | none | Depth 1 |
| Dropbox | Primary | **OLD** | 2-step via SMS to **OLD** | AND gate (email + SMS), satisfied through Gmail |
| PayPal (optional, if signup is easy) | Primary | **OLD** | SMS | AND gate |
| GitHub *or* Discord | Primary | none | **authenticator app** on your phone | AND gate that blocks a stranger: "2FA saved you" |
| LinkedIn | Primary | **NEW** | none | Already migrated; assess remaining dependencies under modelled methods |
| Figma | College stand-in | none | none | Demonstrates college-email dependency; do not assume sign-in loss or browser automation |
| Canva | College stand-in | none | none | Same |
| Coursera | College stand-in | none | none | Same |
| Microsoft account | College stand-in | none | none | Lost on closure; Tier 2/3 fix |
| Splitwise (or any small app) | Primary | none | none | "Not in the graph": unknown, not safe |

Treat expected outcomes as policy-dependent. Lockout and recovery loss are different results; an email dependency alone does not establish either. Review the actual graph and supported execution tier before the demo.

## 4. Telegram
- Create a bot through BotFather and keep its token local; revoke any exposed token.
- Put the token in `.env` as `TELEGRAM_BOT_TOKEN=`, and set `TELEGRAM_BOT_USERNAME` to its handle without `@`.
- Configure `LLM_BASE_URL`, `LLM_MODEL`, and `LLM_API_KEY` for your provider.

## 5. Staged college closure email (do this last, after the sign-ups)
- **From:** the Primary mailbox, or any other address.
- **To:** the College stand-in.
- **Subject:** `IT Services: Your student email account will be deactivated on 15 November 2026`
- **Body:**
> Dear student,
>
> As part of the graduation process, your student email account and all associated data will be permanently deactivated on 15 November 2026. Please update any external services that use this address before that date. After deactivation, emails sent to this address will not be delivered.
>
> IT Services

## 6. Approved execution
- Prepare a browser profile for the supported Notion flow using the [host login workflow](../README.md#4-enable-a-supported-browser-action). Other services may require assisted/manual steps; signing in does not make a recipe validated.
- Relay an SMS code only when an approved Tier 2 step requests it.
- For repeat demonstrations, deliberately restore the external test-account state before rediscovery. Never reload a fixture over a personal graph to reset an external account.
