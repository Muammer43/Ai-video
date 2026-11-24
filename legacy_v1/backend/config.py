from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    app_name: str = "AI Video Factory"
    database_url: str = "sqlite:///./data/video_factory.db"
    output_dir: str = "./data/outputs"
    openai_api_key: str = ""
    openai_text_model: str = "gpt-4.1-mini"
    openai_image_model: str = "gpt-image-1"
    openai_tts_model: str = "tts-1"
    openai_tts_voice: str = "alloy"
    use_ai_images: bool = False
    use_ai_voice: bool = False
    demo_mode: bool = True
    auto_publish: bool = False
    allowed_origins: str = "*"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
