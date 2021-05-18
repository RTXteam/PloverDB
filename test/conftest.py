import pytest


def pytest_addoption(parser):
    parser.addoption("--endpoint", action="store", default="http://localhost:9990")


def pytest_configure(config):
    pytest.endpoint = config.getoption("--endpoint").strip("/")
