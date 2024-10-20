from reattempt import reattempt
import pytest
import aiohttp

from pydantic2_settings_vault import VaultConfigSettingsSource
from test.settings import get_app_settings, AppSettings


@pytest.mark.asyncio
async def test_lock(disable_logging_exception):
    settings:AppSettings = get_app_settings()
    assert settings.AES_KEY.get_secret_value() == "AES_KEY"