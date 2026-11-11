from pydantic import BaseModel, Field


class PushTokenRegister(BaseModel):
    token: str = Field(..., min_length=10, max_length=512)
    platform: str = Field(default="web", pattern="^(web|android|ios)$")
    device_label: str | None = Field(default=None, max_length=150)


class PushTokenOut(BaseModel):
    id: str
    platform: str
    device_label: str | None
    is_active: bool
    last_seen_at: str


class PushPublicConfig(BaseModel):
    enabled: bool
    web_config: dict | None = None
    android_config: dict | None = None
    vapid_key: str | None = None


class PushAdminConfigIn(BaseModel):
    enabled: bool = False
    # Leave empty/None to keep the currently stored values.
    service_account_json: str | None = None
    web_config_json: str | None = None
    android_config_json: str | None = None
    vapid_key: str | None = None


class PushAdminConfigOut(BaseModel):
    enabled: bool
    has_service_account: bool
    project_id: str | None = None
    web_config: dict | None = None
    android_config: dict | None = None
    vapid_key: str | None = None
    tokens_count: int = 0


class PushTestRequest(BaseModel):
    title: str = "Prueba de notificación"
    body: str = "Si ves esto, las notificaciones push funcionan correctamente."
    only_self: bool = True
