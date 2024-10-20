import pytest

SHOW_EXCEPTIONS = False


@pytest.fixture
def disable_logging_exception(mocker):
    if not SHOW_EXCEPTIONS:
        mocker.patch("logging.exception", lambda *args, **kwargs: None)
