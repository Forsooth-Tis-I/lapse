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

SETTINGS_URL = "https://www.notion.so/settings/account"

RECIPE = Recipe(
    name="notion_change_email",
    service_id="notion",
    roles=(UseRole.login_email,),
    settings_url=SETTINGS_URL,
    allowed_domains=("www.notion.so", "notion.so", "www.notion.com", "notion.com"),
    validated=False,
    confirmed=True,
    steps=(
        Goto(SETTINGS_URL),
        Click((Selector("Manage emails", "button"), Selector("Manage emails"))),
        Expect("{old_value}"),
        Click((Selector("Add email", "button"), Selector("Add email"))),
        Fill(
            (Selector("Email address", "textbox"), Selector("Email", "textbox")),
            "{new_value}",
        ),
        Click((Selector("Continue", "button"), Selector("Add email", "button"))),
        AwaitInboxCode(
            inbox="new",
            sender_pattern=r"(?i)@(?:[a-z0-9-]+\.)?notion\.(?:so|com)(?:>|$)",
            subject_pattern=r"(?i)(?:verification|verify|code)",
        ),
        Fill(
            (Selector("Verification code", "textbox"), Selector("Code", "textbox")),
            "{code}",
        ),
        Click((Selector("Verify", "button"), Selector("Continue", "button"))),
        Click(
            (
                Selector("More options", "button", within="{new_value}"),
                Selector("•••", "button", within="{new_value}"),
                Selector("More options", "button", within="{new_value}", container_role="listitem"),
            )
        ),
        Click((Selector("Make primary", "menuitem"), Selector("Make primary"))),
        Click(
            (
                Selector("More options", "button", within="{old_value}"),
                Selector("•••", "button", within="{old_value}"),
                Selector("More options", "button", within="{old_value}", container_role="listitem"),
            )
        ),
        Click((Selector("Remove", "menuitem"), Selector("Remove", "button"))),
        Goto(SETTINGS_URL),
        Click((Selector("Manage emails", "button"), Selector("Manage emails"))),
        Expect("{new_value}"),
        Expect("{old_value}", absent=True),
        Screenshot("Notion email aliases after migration"),
    ),
)
