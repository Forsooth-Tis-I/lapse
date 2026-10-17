from lapse.contracts import UseRole
from lapse.exec.recipes.dsl import (
    AwaitOTP,
    Click,
    Expect,
    Fill,
    Goto,
    Recipe,
    Screenshot,
    Selector,
)

SETTINGS_URL = "https://x.com/settings/phone"

RECIPE = Recipe(
    name="x_change_phone",
    service_id="x",
    roles=(UseRole.login_phone,),
    settings_url=SETTINGS_URL,
    allowed_domains=("x.com", "www.x.com", "twitter.com", "www.twitter.com"),
    validated=False,
    confirmed=True,
    steps=(
        Goto(SETTINGS_URL),
        Expect("{old_value}"),
        Click(
            (
                Selector("Update number", "button"),
                Selector("Update number", "link"),
                Selector("Update number"),
                Selector("Update phone number"),
            )
        ),
        Fill(
            (Selector("Phone number", "textbox"), Selector("Phone", "textbox")),
            "{new_value}",
        ),
        Click((Selector("Next", "button"), Selector("Continue", "button"))),
        Click((Selector("Get a code", "button"), Selector("Send code", "button"))),
        AwaitOTP(channel="sms"),
        Fill(
            (Selector("Verification code", "textbox"), Selector("Enter your code", "textbox")),
            "{code}",
        ),
        Click((Selector("Verify", "button"), Selector("Confirm", "button"))),
        Goto(SETTINGS_URL),
        Expect("{new_value}"),
        Expect("{old_value}", absent=True),
        Screenshot("Your <b>X</b> phone settings after the change"),
    ),
)
