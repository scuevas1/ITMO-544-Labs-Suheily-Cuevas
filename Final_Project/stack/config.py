"""Settings for the stack, read from the same .env file as Lab06."""
from pathlib import Path

REQUIRED_KEYS = (
    "AWS_REGION", "AZ_A", "AZ_B", "AMI_ID", "INSTANCE_TYPE",
    "APP_SECURITY_GROUP_ID", "ALB_NAME", "ALB_SG_NAME",
    "GEMINI_KEY_PARAM", "GEMINI_MODEL", "CONTACT_EMAIL",
    "SNS_TOPIC_NAME", "FACTS_TABLE_NAME", "REPORT_TABLE_NAME",
    "COUNTER_TABLE_NAME",
) + tuple(
    f"{tier}_{suffix}"
    for tier in ("WEATHER", "ADVISOR")
    for suffix in ("ROLE_NAME", "PROFILE_NAME", "LT_NAME", "TG_NAME",
                   "ASG_NAME", "LISTENER_PORT")
)


def load_dotenv(path=".env"):
    """Read key=value settings without executing a shell script."""
    values = {}
    for raw in Path(path).read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def settings(path=".env"):
    """Validate required settings and project-owned resource names."""
    values = load_dotenv(path)
    missing = [name for name in REQUIRED_KEYS if not values.get(name)]
    if missing:
        raise ValueError("Missing keys in .env: " + ", ".join(missing))
    if not values["APP_SECURITY_GROUP_ID"].startswith("sg-"):
        raise ValueError("Invalid application security group ID")
    if values["GEMINI_KEY_PARAM"] != "/itmo-544-final/gemini-api-key":
        raise ValueError("Unexpected Gemini key parameter name")
    for key, value in values.items():
        if key.endswith("_NAME") and key != "KEY_NAME":
            if not value.startswith("itmo-544-final-"):
                raise ValueError("Unexpected resource name: " + key)
    if values["WEATHER_LISTENER_PORT"] == values["ADVISOR_LISTENER_PORT"]:
        raise ValueError("Listener ports must differ")
    return values
