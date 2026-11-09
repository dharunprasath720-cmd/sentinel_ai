import os
from dataclasses import dataclass, field

REQUIRED = ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET", "PAYPAL_WEBHOOK_ID")


@dataclass(frozen=True)
class PayPalSettings:
    client_id: str
    client_secret: str = field(repr=False)  # never shown in repr/logs
    webhook_id: str

    @classmethod
    def from_env(cls) -> "PayPalSettings":
        missing = [k for k in REQUIRED if not os.environ.get(k)]
        if missing:  # names only: values (even partial ones) are never echoed
            raise RuntimeError("missing PayPal environment variables: " + ", ".join(missing))
        return cls(os.environ["PAYPAL_CLIENT_ID"], os.environ["PAYPAL_CLIENT_SECRET"],
                   os.environ["PAYPAL_WEBHOOK_ID"])
