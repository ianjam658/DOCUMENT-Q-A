import os


class Config:
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
    GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
    DATABASE_URL = os.environ.get("DATABASE_URL")
    API_SECRET_KEY = os.environ.get("API_SECRET_KEY")
    REDIS_URL = os.environ.get("REDIS_URL")  # optional — used for rate limiting across multiple instances
    MAX_FILE_SIZE_MB = int(os.environ.get("MAX_FILE_SIZE_MB", "15"))
    ALLOWED_ORIGINS = os.environ.get("ALLOWED_ORIGINS", "*")
    RATE_LIMIT_DEFAULT = os.environ.get("RATE_LIMIT_DEFAULT", "60 per minute")
    RATE_LIMIT_UPLOAD = os.environ.get("RATE_LIMIT_UPLOAD", "10 per minute")
    RATE_LIMIT_ASK = os.environ.get("RATE_LIMIT_ASK", "20 per minute")

    REQUIRED = ["GROQ_API_KEY", "DATABASE_URL", "API_SECRET_KEY"]

    @classmethod
    def validate(cls):
        missing = [name for name in cls.REQUIRED if not getattr(cls, name)]
        if missing:
            raise RuntimeError(
                f"Missing required environment variable(s): {', '.join(missing)}. "
                f"Copy .env.example to .env and fill these in."
            )
