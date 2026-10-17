import time

from lapse import jobs

TTL_SECONDS = 300


def submit(uid: str, change_id: str, code: str) -> None:
    jobs.client().set(f"lapse:otp:{uid}:{change_id}", code, ex=TTL_SECONDS)


def wait(uid: str, change_id: str, timeout_s: float = 300) -> str | None:
    deadline = time.monotonic() + timeout_s
    while True:
        code = jobs.client().getdel(f"lapse:otp:{uid}:{change_id}")
        if code is not None:
            return code
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return None
        time.sleep(min(0.1, remaining))
