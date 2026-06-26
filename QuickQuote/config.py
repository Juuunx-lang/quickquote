from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    APP_NAME: str = "智能报价智能体系统"
    API_PREFIX: str = "/api/v1"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    ALLOWED_ORIGINS: str = "*"

    # Runtime database configuration. Fill these through environment variables.
    ORDER_DB_HOST: str = ""
    ORDER_DB_PORT: int = 3306
    ORDER_DB_USER: str = ""
    ORDER_DB_PASSWORD: str = ""
    ORDER_DB_NAME: str = ""

    PURCHASE_DB_HOST: str = ""
    PURCHASE_DB_PORT: int = 3306
    PURCHASE_DB_USER: str = ""
    PURCHASE_DB_PASSWORD: str = ""
    PURCHASE_DB_NAME: str = ""

    LLM_API_KEY: str = ""
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    MODEL_NAME: str = "gpt-4o-mini"
    MODEL_SQL: str = "gpt-4o-mini"
    MODEL_THINK: str = "gpt-4.1-mini"
    LLM_TIMEOUT: int = 120
    NODE_PARSE_TIMEOUT: int = 60
    NODE_SQL_TIMEOUT: int = 180
    NODE_REASON_TIMEOUT: int = 60
    NODE_MAX_RETRIES: int = 2
    NODE_SQL_MAX_CONCURRENCY: int = 2
    NODE_SQL_MAX_ITEMS: int = 2000
    QUERY_CANDIDATE_LIMIT: int = 5
    PURCHASE_CANDIDATE_SCAN_LIMIT: int = 100
    MAX_INPUT_ITEMS: int = 2000
    JOB_INPUT_THRESHOLD: int = 100
    DB_CANDIDATE_BATCH_SIZE: int = 25
    DB_CANDIDATE_QUERY_TIMEOUT: int = 8
    DB_CANDIDATE_LIMIT_MULTIPLIER: int = 4
    ORDER_QUERY_MAX_CONCURRENCY: int = 5
    JUSHUITAN_QUERY_MAX_CONCURRENCY: int = 10
    EXTERNAL_QUERY_MAX_CONCURRENCY: int = 10
    CACHE_TTL_SECONDS: int = 120

    JUSHUITAN_ENV: str = "prod"
    JUSHUITAN_BASE_URL: str = "https://openapi.jushuitan.com"
    JUSHUITAN_BASE_URL_TEST: str = "https://dev-api.jushuitan.com"
    JUSHUITAN_APP_KEY: str = ""
    JUSHUITAN_APP_SECRET: str = ""
    JUSHUITAN_AUTH_CODE: str = ""
    JUSHUITAN_ACCESS_TOKEN: str = ""
    JUSHUITAN_REFRESH_TOKEN: str = ""
    JUSHUITAN_ENABLE_TOKEN_CACHE: bool = True
    JUSHUITAN_TOKEN_CACHE_FILE: str = "/app/data/.jushuitan_token_cache.json"
    JUSHUITAN_AUTH_CODE_RANDOM_LENGTH: int = 6
    JUSHUITAN_QUERY_MAX_PAGES: int = 2
    JUSHUITAN_INVENTORY_MAX_CONCURRENCY: int = 3
    JUSHUITAN_INVENTORY_MAX_WAREHOUSES: int = 4
    JUSHUITAN_INVENTORY_WMS_CO_IDS: str = ""
    JUSHUITAN_QUERY_CACHE_TTL_SECONDS: int = 300
    JUSHUITAN_AUTH_INIT_PATH: str = "/openWeb/auth/getInitToken"
    JUSHUITAN_AUTH_INIT_PATH_TEST: str = "/openWebIsv/auth/getInitToken"
    JUSHUITAN_SKU_QUERY_PATH: str = "/open/sku/query"
    JUSHUITAN_INVENTORY_QUERY_PATH: str = "/open/inventory/query"
    JUSHUITAN_PURCHASE_IN_QUERY_PATH: str = "/open/purchasein/query"
    JUSHUITAN_DYNAMIC_COST_LOOKBACK_DAYS: int = 30
    JUSHUITAN_DYNAMIC_COST_MAX_PAGES: int = 20
    JUSHUITAN_DEFAULT_WMS_CO_ID: int = 0
    JUSHUITAN_TIMEOUT: int = 30
    JUSHUITAN_MAX_ITEMS: int = 100
    JUSHUITAN_PAGE_SIZE: int = 100
    JUSHUITAN_CHARSET: str = "utf-8"
    JUSHUITAN_VERSION: str = "2"
    JUSHUITAN_SIGN_ALGO: str = "md5"
    JUSHUITAN_SIGN_LOWERCASE: bool = True

    UPLOAD_DIR: str = "uploads"
    QUOTE_ARCHIVE_DIR: str = "/app/data"
    MAX_FILE_SIZE_MB: int = 10

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
