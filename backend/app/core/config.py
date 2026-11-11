from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    APP_NAME: str = "TuPedidoJR"
    DEBUG: bool = True
    NOINDEX: bool = False
    CORS_ORIGINS: str = "*"
    ALLOWED_HOSTS: str = "*"
    DATABASE_URL: str = "postgresql+asyncpg://tupedido:tupedido123@localhost:5432/tupedidojr"
    DATABASE_URL_SYNC: str = "postgresql://tupedido:tupedido123@localhost:5432/tupedidojr"
    SECRET_KEY: str = "supersecretkey-cambiar-en-produccion"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
    WS_LOCATION_BUFFER_SECONDS: int = 30
    WS_LOCATION_BUFFER_COUNT: int = 50
    MERCADO_PAGO_ACCESS_TOKEN: str = ""
    MERCADO_PAGO_WEBHOOK_SECRET: str = ""
    MERCADO_PAGO_SUCCESS_URL: str = "https://tupedidojr.app/pago-exitoso"
    MERCADO_PAGO_FAILURE_URL: str = "https://tupedidojr.app/pago-fallido"
    MERCADO_PAGO_PENDING_URL: str = "https://tupedidojr.app/pago-pendiente"
    APP_URL: str = "http://localhost:8080"

    class Config:
        env_file = ".env"


settings = Settings()
