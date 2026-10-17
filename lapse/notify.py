import json

from lapse import jobs


def notify(uid: str, text: str, buttons: list[dict] | None = None) -> None:
    jobs.client().publish(
        f"lapse:notify:{uid}", json.dumps({"text": text, "buttons": buttons if buttons is not None else []})
    )
