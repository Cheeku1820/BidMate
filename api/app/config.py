from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    test_database_url: str = ""
    session_ttl_hours: int = 12
    cookie_secure: bool = False

    # Object storage for uploaded documents (MinIO locally, S3 in
    # deployment). Keys are tenant-scoped by construction -- see
    # app/documents/service.py. Dev values live in docker-compose.yml;
    # nothing here has a default that would silently point at a real bucket.
    blob_endpoint: str = "http://localhost:9000"
    blob_access_key: str = ""
    blob_secret_key: str = ""
    blob_bucket: str = "bidmate-documents"
    blob_region: str = "us-east-1"


settings = Settings()
