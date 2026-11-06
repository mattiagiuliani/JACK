import pytest
from pydantic_settings import SettingsConfigDict

from app.config import Settings


class TestSettings(Settings):
    __test__ = False

    model_config = SettingsConfigDict(
        env_file=None,
        extra="forbid",
    )


def test_default_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("APP_NAME", "APP_VERSION", "ENVIRONMENT"):
        monkeypatch.delenv(name, raising=False)

    settings = TestSettings()

    assert settings.app_name == "JACK API"
    assert settings.app_version == "0.1.0"
    assert settings.environment == "development"


def test_environment_override(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_NAME", "JACK Test API")

    settings = TestSettings()

    assert settings.app_name == "JACK Test API"
