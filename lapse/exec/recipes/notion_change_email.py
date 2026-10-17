import re

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

SETTINGS_URL = "https://www.notion.so/home"
WORKSPACE_MENU = Selector(re.compile(r".+ Close sidebar$"), "button")
OPEN_EMAILS = (
    Goto(SETTINGS_URL, ready=WORKSPACE_MENU),
    Click((WORKSPACE_MENU,), ready=Selector("Settings")),
    Click((Selector("Settings"),), ready=Selector("Search settings", "textbox")),
    Fill((Selector("Search settings", "textbox"),), "email"),
    Click((Selector("Email", "button"),), ready=Selector("Manage emails", "button")),
    Click((Selector("Manage emails", "button"),), ready=Selector("Add email address", "button")),
)
SENDER = r"(?i)^notify@updates\.notion\.com$"
CODE_PATTERN = r"(?m)^[A-Za-z0-9]{6}(?=\r?$)"

RECIPE = Recipe(
    name="notion_change_email",
    service_id="notion",
    roles=(UseRole.login_email,),
    settings_url=SETTINGS_URL,
    allowed_domains=("www.notion.so", "notion.so", "www.notion.com", "notion.com"),
    validated=True,
    confirmed=True,
    steps=(
        *OPEN_EMAILS,
        Expect("{old_value}"),
        Screenshot("Notion email addresses before migration"),
        Click((Selector("Add email address", "button"),), ready=Selector("example@company.com", "textbox")),
        Fill((Selector("example@company.com", "textbox"),), "{new_value}"),
        Click((Selector("Add email", "button"),), ready=Selector("Verify email", "button")),
        Expect("Verify email address"),
        AwaitInboxCode("new", SENDER, r"(?i)(?:verify|verification|code)", CODE_PATTERN),
        Fill(
            (Selector("e.g. dqYVcm", "textbox", within="Code sent to {new_value}", container_role=None),),
            "{code}",
        ),
        AwaitInboxCode("old", SENDER, r"(?i)(?:verify|verification|code)", CODE_PATTERN),
        Fill(
            (Selector("e.g. dqYVcm", "textbox", within="Code sent to {old_value}", container_role=None),),
            "{code}",
        ),
        Click((Selector("Verify email", "button"),), ready=Selector("{new_value}")),
        Expect("{new_value}"),
        Screenshot("Notion verified replacement email"),
        Click(
            (Selector("Make primary", "button", within="{new_value}"),),
            ready=Selector("Remove", "button", within="{old_value}"),
        ),
        Screenshot("Notion replacement email made primary"),
        Click((Selector("Remove", "button", within="{old_value}"),)),
        Expect("{old_value}", absent=True),
        *OPEN_EMAILS,
        Expect("{new_value}"),
        Expect("{old_value}", absent=True),
        Screenshot("Notion email addresses after migration"),
    ),
)
