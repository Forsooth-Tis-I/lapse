# Demo identity setup (done by a human, in parallel with the build)

The demo runs on a fresh test identity with real accounts, so every email in the graph is genuine. The only staged item is the college closure notice (step 5), and the README says so.

Keep every welcome, OTP, sign-in and security email. Don't delete or archive anything. Those emails are the evidence the agent reads.

## 1. Two Gmail accounts
| Mailbox | Plays | Setup |
|---|---|---|
| **Primary** | The person's main email (the hub) | Recovery phone = **OLD** number. 2-Step Verification by SMS to the **OLD** number. Recovery email = the College stand-in. |
| **College stand-in** | A college address that will be closed | Name it to read like a student address (e.g. `firstname.lastname.<college>.student@gmail.com`). 2-Step Verification on, using the **NEW** number (needed for app passwords). |

For **both** mailboxes, create an **app password**: Google Account → Security → 2-Step Verification → App passwords. Then put the values in `/home/traskar/Dev/lapse/.env`:
```
PRIMARY_IMAP_USER=<primary address>
PRIMARY_IMAP_PASSWORD=<16-char app password>
COLLEGE_IMAP_USER=<college stand-in address>
COLLEGE_IMAP_PASSWORD=<16-char app password>
```

## 2. Phone numbers
Fill both numbers into `/home/traskar/Dev/lapse/persona.local.yaml`:
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
| LinkedIn | Primary | **NEW** | none | Already migrated, shown as safe |
| Figma | College stand-in | none | none | Lost when the college email closes; Tier 1 auto-fix candidate |
| Canva | College stand-in | none | none | Same |
| Coursera | College stand-in | none | none | Same |
| Microsoft account | College stand-in | none | none | Lost on closure; Tier 2/3 fix |
| Splitwise (or any small app) | Primary | none | none | "Not in the graph": unknown, not safe |

Don't change any of these afterwards unless the agent asks. The demo shows the agent fixing them.

## 4. Telegram
- Revoke the bot token that was pasted in chat (BotFather → `/revoke`).
- Put the new token in `.env` as `TELEGRAM_BOT_TOKEN=`.
- Put the OpenCode API key in `.env` as `LLM_API_KEY=`.

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

## 6. Later (the agent will ask in Telegram)
- Sign in once to Figma, Canva, Notion and Coursera in the agent's browser window, so it can make Tier 1 changes.
- Type SMS codes into Telegram when a Tier 2 step asks for one.
