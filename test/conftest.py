import pytest


def pytest_addoption(parser):
    parser.addoption("--endpoint", action="store", default="http://localhost:9990")
    parser.addoption("--save", action="store_true", default=False)


def pytest_configure(config):
    pytest.endpoint = config.getoption("--endpoint").strip("/")
    pytest.save = config.getoption("--save")
