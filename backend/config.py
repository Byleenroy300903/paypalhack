from functools import lru_cache
from pathlib import Path
from typing import Literal
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / '.env', extra='ignore')
    database_url: str = 'sqlite:///./nexus.db'
    vercel: bool = False
    ollama_api_key: str = ''
    ollama_model: str = 'gpt-oss:120b'
    ollama_timeout: float = Field(default=90, gt=0, le=300)
    elasticsearch_url: str = ''
    elasticsearch_api_key: str = ''
    paypal_client_id: str = ''
    paypal_client_secret: str = ''
    paypal_env: Literal['sandbox'] = 'sandbox'
    sandbox_api_token: str = ''
    public_url: str = 'http://localhost:4200'
    cors_origins: str = 'http://localhost:4200,http://127.0.0.1:4200'
    step_delay: float = 1.0


@lru_cache
def get_settings() -> Settings:
    return Settings()