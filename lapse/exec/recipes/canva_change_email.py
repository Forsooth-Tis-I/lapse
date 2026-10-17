from lapse.contracts import UseRole
from lapse.exec.recipes.dsl import (
    AwaitInboxCode,
    Click,
    Expect,
    Fill,
    Goto,
    Recipe,
    Screenshot,
    Selector,
)

SETTINGS_URL = "https://www.canva.com/settings/your-account"

RECIPE = Recipe(
    name="canva_change_email",
    service_id="canva",
    roles=(UseRole.login_email,),
    settings_url=SETTINGS_URL,
    allowed_domains=("www.canva.com", "canva.com", "account.canva.com"),
    validated=False,
    confirmed=True,
    steps=(
        Goto(SETTINGS_URL),
        Expect("{old_value}"),
        Click(
            (
                Selector("Edit", "button", within="Email address"),
                Selector("Edit email address", "button"),
                Selector("Edit", "button", within="Email address", container_role="group"),
            )
        ),
        AwaitInboxCode(
            inbox="old",
            sender_pattern=r"(?i)@(?:[a-z0-9-]+\.)?canva\.com(?:>|$)",
            subject_pattern=r"(?i)(?:verification|verify|code)",
        ),
        Fill(
            (Selector("Verification code", "textbox"), Selector("Code", "textbox")),
            "{code}",
        ),
        Click((Selector("Continue", "button"), Selector("Verify", "button"))),
        Fill(
            (Selector("New email address", "textbox"), Selector("Email address", "textbox")),
            "{new_value}",
        ),
        Click((Selector("Continue", "button"), Selector("Save", "button"))),
        AwaitInboxCode(
            inbox="new",
            sender_pattern=r"(?i)@(?:[a-z0-9-]+\.)?canva\.com(?:>|$)",
            subject_pattern=r"(?i)(?:verification|verify|code)",
        ),
        Fill(
            (Selector("Verification code", "textbox"), Selector("Code", "textbox")),
            "{code}",
        ),
        Click((Selector("Confirm", "button"), Selector("Verify", "button"))),
        Goto(SETTINGS_URL),
        Expect("{new_value}"),
        Expect("{old_value}", absent=True),
        Screenshot("Your <b>Canva</b> email settings after the change"),
    ),
)
