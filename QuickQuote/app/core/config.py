from config import settings


def allowed_origins_list() -> list[str]:
    raw = settings.ALLOWED_ORIGINS.strip()
    if raw == "*":
        return ["*"]
    return [item.strip() for item in raw.split(",") if item.strip()]
