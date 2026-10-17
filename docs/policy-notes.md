# Service policy research

Reviewed on 2026-10-17. The catalogue models standard documented account access, including passwordless login and password resets that retain enrolled second factors. Results describe access **under the methods we model**. Services without a usable policy are **unknown, not safe**.

## Method semantics and scope

`needs_roles` is an AND gate over possession roots. Templates are OR alternatives. A password is knowledge, so password-only login has no possession roots and sets `needs_password: true`. Password methods assume the user has a configured password; they never grant a stranger password knowledge.

`requires_absent_roles: [sms_2fa, totp_device]` excludes password-only and single-proof reset templates whenever either factor is recorded on the account. MFA variants require the reset inbox or phone **and** the enrolled factor. GitHub's fixture therefore has only password-plus-TOTP and email-reset-plus-TOTP. Dropbox has password-plus-SMS and email-reset-plus-SMS. Resetting a password does not silently remove these factors.

The compiler uses recorded account roles, including unconfirmed evidence. Missing role evidence is not proof that MFA is disabled. Confirm the demo account configuration before interpreting results. Passwordless-only accounts, enforced SSO, passkeys, backup codes, email-only MFA, trusted-device approval and adaptive identity checks are not fully represented by the shared contract. These limits do not make all standard flows unknown. An account known to use an unsupported mode can still be marked `modelled: false`.

`compile_user_graph(g, policies, account_ids=None)` recompiles all accounts by default. A list recompiles those accounts and their hosted mailbox methods, preserving unrelated methods. An empty list does nothing. Old and new grant targets determine which derived `ENABLES` edges need rebuilding, including when a selected account or mailbox closes.

## Sources and service limits

Every method links to its official flow documentation in `services.yaml`. Reset-plus-factor methods combine the reset documentation with the service's second-factor rules. They represent standard flows, not a promise that a vendor never requests additional proof.

- **Google:** [recovery](https://support.google.com/accounts/answer/7682439), [recovery contacts](https://support.google.com/accounts/answer/183723), and [2-Step Verification](https://support.google.com/accounts/answer/185839). Password login and recovery-phone or recovery-email resets have factor variants. Recovery remains risk-adaptive and can require a familiar device, additional answers or a delay. The model's recovery paths are standard branches, not a guarantee that a recycled number opens Gmail. Contact changes refer to recovery information, not renaming a Gmail address.
- **Microsoft:** [password reset](https://support.microsoft.com/en-us/accounts-billing/manage/reset-a-forgotten-microsoft-account-password), [two-step verification](https://support.microsoft.com/en-us/accounts-billing/security/how-to-use-two-step-verification-with-your-microsoft-account), and [passwordless codes](https://support.microsoft.com/en-us/accounts-billing/security/how-to-go-passwordless-with-your-microsoft-account). Personal-account security contacts support recovery. Two-step reset requires two proofs, so phone plus the same SMS number is not offered as a two-proof reset. Email-code login assumes an eligible external alias. A Microsoft-hosted login mailbox must not serve as its own recovery proof. Email-only 2SV and tenant-specific work or school policies remain unrepresented.
- **Apple:** [password plus trusted-phone verification](https://support.apple.com/en-us/102660) is modelled. Apple trusted devices are not TOTP devices. Device passcodes and delayed recovery are omitted.
- **GitHub:** [password reset](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/updating-your-github-access-credentials) and [2FA sign-in](https://docs.github.com/en/authentication/securing-your-account-with-two-factor-authentication-2fa/accessing-github-using-two-factor-authentication). Primary or verified backup email can reset the password, retaining SMS or TOTP. Managed users and recovery codes are outside the policy.
- **Amazon.in and Amazon.com:** official customer-help mirror for [password or code login](https://digprjsurvey.amazon.com/csad/help/node/GAM5QWMWMTFCHEQT), [email or SMS reset](https://digprjsurvey.amazon.com/csad/help/node/GH3NM2YWEFEL2CQ4), and [2SV](https://digprjsurvey.amazon.com/csad/help/node/G3PWZPU52FKN7PW4). Code login is a passwordless account mode. India equivalence has not been verified in an authenticated account. Contact-change proof destinations remain unspecified, so both procedures stay tier 3.
- **PayPal:** [reset](https://www.paypal.com/c2/cshelp/article/i-forgot-my-password-how-do-i-reset-it-help143?locale.x=en_C2), [security checks](https://www.paypal.com/us/cshelp/article/why-do-i-have-to-complete-a-security-check-help171), and [second factors](https://www.paypal.com/us/security/protect-your-account). The standard email recovery branch retains enrolled SMS or TOTP. Card or other identity checks may replace or supplement it. Account access does not assert permission to complete a payment.
- **College Workspace:** [institution account sign-in](https://support.google.com/a/answer/6142901). The institution template uses a password alone when no factor is recorded, or password plus enrolled SMS or TOTP under [Google 2SV](https://support.google.com/accounts/answer/185839). It has no self-service migration of the mailbox to Gmail. Closing the account or mailbox removes hosted-email access. No generic college sender domain can distinguish arbitrary institutions.
- **LinkedIn:** [email or verified-phone reset](https://www.linkedin.com/help/linkedin/answer/a1382101) and [SMS or app 2FA](https://www.linkedin.com/help/linkedin/answer/a1381088). Phone reset assumes the selected reset-enabled number. Device approvals can add challenges.
- **X:** [email or phone reset](https://help.x.com/en/managing-your-account/forgotten-or-lost-password-reset) and [2FA](https://help.x.com/en/managing-your-account/two-factor-authentication). Reset retains the factor; SMS eligibility varies by account.
- **Instagram:** [email or phone reset](https://www.facebook.com/help/instagram/409847499070242?locale=ru_RU) and [factor setup](https://www.facebook.com/help/instagram/1124604297705184?locale=ja_JP). **Facebook:** [reset](https://www.facebook.com/help/105487009541643?locale=fr_CA) and [second factors](https://www.facebook.com/help/1052552578831700?locale=es_LA). Official localized pages were accessible while English help was gated. Factor retention after reset is inferred from their separate sign-in requirement, not a separately verified recovery session. Linked Meta accounts and recovery reviews are omitted.
- **Discord:** [reset](https://support.discord.com/hc/en-us/articles/218410947-How-to-Reset-or-Change-Your-Forgotten-Password-on-Discord) explicitly retains MFA; [factor documentation](https://support.discord.com/hc/en-us/articles/219576828-Setting-up-Multi-Factor-Authentication) supports TOTP and enrolled SMS backup. Phone-only accidental-account recovery is not a general reset method.
- **Reddit:** [email reset](https://support.reddithelp.com/hc/en-us/articles/16976987585300-Why-haven-t-I-received-my-password-reset-email) and [password plus TOTP](https://support.reddithelp.com/hc/en-us/articles/360043470031-What-is-two-factor-authentication-and-how-do-I-set-it-up). Local password accounts are modelled; phone-only and SSO modes differ.
- **Dropbox:** [email reset](https://help.dropbox.com/security/password-reset) and [SMS or authenticator 2FA](https://help.dropbox.com/account-access/enable-2-factor-authentication). The fixture assumes an existing supported SMS enrollment. [SMS availability changed by country in 2026](https://help.dropbox.com/account-access/sms-discontinuation-two-factor-authentication-faqs). Team SSO and backup codes are omitted.
- **Slack:** [email-code sign-in](https://slack.com/help/articles/212681477-Sign-in-to-Slack), [password reset](https://slack.com/help/articles/201909068-Reset-your-password), and [2FA](https://slack.com/help/articles/204509068-Set-up-two-factor-authentication). Email codes retain the workspace's enrolled factor. SSO-enforced workspaces need their identity-provider policy.
- **Spotify:** [password reset](https://support.spotify.com/us/article/reset-password/), [login methods](https://support.spotify.com/us/article/login-methods/), and [phone-code login](https://support.spotify.com/ae-en/article/cannot-remember-login/). Consumer local-password and phone-login branches are modelled. A billing phone is not a login phone. No unsupported magic-link claim is added.
- **Netflix:** [password and code sign-in](https://help.netflix.com/en/node/529303577956964) and [email or SMS reset](https://help.netflix.com/en/node/365). Roles refer to the primary account owner's contacts, not a profile-only email or phone.
- **Swiggy:** the [public consumer sign-in](https://www.swiggy.com/) and its loaded authentication code show phone OTP login. No OTP was requested. This is primary interface evidence rather than a help article. [Unusual-login approval](https://www.swiggy.com/2fa) can add a challenge. Contact changes remain undocumented.
- **Zomato:** the [official consumer account authorization screen](https://mcp-server.zomato.com/consent) asks for the registered mobile number, sends an OTP and verifies it. This is consumer interface evidence, not merchant login documentation. No email recovery or contact-change procedure is invented.
- **Paytm:** [reinstall and account restoration](https://paytm.com/support/upi/deleted-paytm-app-what-happens-account-upi) uses the registered phone OTP. This grants profile access, not UPI PIN knowledge or bank-payment authority.
- **Generic Indian bank:** remains unknown because there is no identified bank and no universal reset policy. Bank-specific cards, PINs, device binding and identity checks need a real service policy. The existing tier 4 contact-change fallback is retained.
- **Notion:** [email codes and passwords](https://www.notion.com/help/log-in-and-out), [reset links](https://www.notion.com/help/cant-log-in), and [SMS or TOTP](https://www.notion.com/help/two-step-verification). Passwordless email login is excluded when a second factor is recorded. Enforced SSO remains outside these local-account methods.
- **Figma:** [email reset](https://help.figma.com/hc/en-us/articles/4418812476695-Reset-your-password) and [SMS or TOTP](https://help.figma.com/hc/en-us/articles/360039817634-Enable-two-factor-authentication-2FA). Local account methods do not describe Google or SAML sign-in.
- **Canva:** [email-code login](https://www.canva.com/help/sign-up-log-in/), [email reset](https://www.canva.com/help/reset-password/), and [MFA](https://www.canva.com/help/login-verification/). SMS methods cover legacy enrollments; the phone number cannot be replaced. SSO-managed accounts follow administrator policy.
- **Coursera:** [login settings](https://www.coursera.support/s/article/learner-000002204?language=en_US) documents email reset and optional authenticator 2FA. Local learners are modelled. Institution-enforced SSO is not.

## Contact changes

Existing structured change procedures are retained. Tier 1 identifies documented automation candidates after sign-in, not completed live automation. `recipe: null` still means no executor recipe is supplied by this package. Verification messages are not proof that the old contact was removed.

- **Notion, tier 1 email:** add and verify the new alias, make it primary, then remove the old alias. [Account settings](https://www.notion.com/help/account-settings) and [lost-email guidance](https://www.notion.com/help/cant-log-in) support this flow. The latter warns that accounts without a password may still need an old-inbox check. The tier 1 procedure assumes an authenticated password-configured personal account.
- **Canva, tier 1 email:** [email change](https://www.canva.com/help/change-email/) verifies both inboxes. Losing the old inbox can prevent this route. Managed accounts need administrator approval.
- **Figma and Coursera, tier 3 email:** published settings instructions do not establish the proof destinations needed to promote them. No live contact change was attempted.

`ChangeProcedure.root_kind` cannot distinguish login email from recovery email, or login phone from SMS 2FA. Google and Microsoft procedures concern recovery/security contacts. Executors must not apply those procedures to every role of the same root kind. Empty tier 3 `requires` lists mean unresolved requirements, not proof-free changes.

## Sender attribution

Domains are attribution hints, not authenticated-sender allowlists. Parent domains already match transactional subdomains. The catalogue includes Google's account and notification hosts, Microsoft's `accountprotection.microsoft.com`, Amazon's account-update hosts, and both legacy and current X and Notion domains.

Added `account.canva.com` from [Canva's code-delivery guidance](https://www.canva.com/help/not-receiving-emails/) and `cs.linkedin.com` and `el.linkedin.com` from [LinkedIn's official sender list](https://www.linkedin.com/help/linkedin/answer/a1335274). [Reddit's official list](https://support.reddithelp.com/hc/en-us/articles/360045734831-How-do-I-know-if-a-message-from-Reddit-is-official) supports its three mail domains. [Swiggy's email-verification page](https://www.swiggy.com/email-verification) identifies `swiggy.in`. No generic college or bank sender is fabricated.

No real inbox was inspected. Phone-suffix extraction and completed-change regexes still need redacted account messages. Masked digits on a vendor's website do not prove that its emails expose those digits.

## Carrier timing

The [Supreme Court order of 30 October 2023 in Rajeswari v. Union of India](https://api.sci.gov.in/supremecourt/2021/13468/13468_2021_3_45_47839_Judgement_30-Oct-2023.pdf), page 1, records the regulator's statement that a number deactivated for non-use or disconnected on request is not assigned to a new subscriber for at least 90 days. The four Indian entries apply this common minimum to Jio, Airtel, Vi, and BSNL. It is not a promise that reassignment occurs on day 90, nor a rule that begins when someone simply removes a SIM.

The [Princeton number-recycling research](https://recyclednumbers.cs.princeton.edu/) identifies a US minimum aging period of 45 days. [T-Mobile](https://www.t-mobile.com/support/account/change-your-phone-number) currently states 45 to 90 days; the YAML stores the earliest point. [Verizon](https://www.verizon.com/support/disconnect-cancel-mobile/) states a 45-day wait before reassignment. No reliable AT&T-specific period was found, so `generic_us` is the fallback. These are earliest possible reissue dates measured from actual disconnection, not forecasts or guarantees of the current assignee.

## Demo and verification

`scripts/load_fixture.py` loads `lapse/policy/services.yaml` and `carriers.yaml`. `fixtures/policy.yaml` remains the synthetic unit-test policy. Missing services get an unknown placeholder only in the user graph, so Splitwise remains visible without adding it to the policy catalogue. The script prints method counts for every account.

Isolated verification on shared FalkorDB uses:

```sh
uv sync
uv run pytest -q
uv run ruff check .
uv run ruff format --check lapse/policy/compile.py scripts/load_fixture.py tests/conftest.py tests/test_fixture_compile.py tests/test_policy_compile.py tests/test_policy_yaml.py
uv run python scripts/load_fixture.py --graph-prefix lapse:test:wp2r2:demo
```

Without `--graph-prefix`, the loader retains its normal `lapse:policy` and `lapse:u:demo` destinations. WP2r2 verification uses only `lapse:test:wp2r2:*` graphs.

Regression tests cover the full persona, GitHub and Dropbox factor retention, unknown Splitwise, absent-role eligibility, selective recompilation, mailbox closure, and unchanged unrelated graph objects. YAML tests require modelled persona services, valid exclusion roles, and at least one method for every modelled service. Live sign-ins and contact changes remain unverified.

Repository-wide formatting also reports a pre-existing line-wrap issue in `lapse/contracts.py:133`. The shared contract is unchanged, as required by this work package. Ruff lint passes.
