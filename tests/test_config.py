"""Tests for Config defaults and environment variable handling."""

from __future__ import annotations

from simpleq.config import Config


class TestConfigDefaults:
    def test_default_region(self):
        config = Config()
        assert config.region == "us-east-1"

    def test_default_endpoint_url_is_none(self, monkeypatch):
        monkeypatch.delenv("SIMPLEQ_ENDPOINT_URL", raising=False)
        config = Config()
        assert config.endpoint_url is None

    def test_default_auto_create(self):
        config = Config()
        assert config.auto_create is True

    def test_default_visibility_timeout(self):
        config = Config()
        assert config.visibility_timeout == 30

    def test_default_dead_letter_queue(self):
        config = Config()
        assert config.dead_letter_queue is False

    def test_default_batch_size(self):
        config = Config()
        assert config.batch_size == 10

    def test_default_wait_seconds(self):
        config = Config()
        assert config.wait_seconds == 20


class TestConfigEnvOverrides:
    def test_endpoint_url_from_env(self, monkeypatch):
        monkeypatch.setenv("SIMPLEQ_ENDPOINT_URL", "http://localhost:4566")
        config = Config()
        assert config.endpoint_url == "http://localhost:4566"

    def test_explicit_endpoint_url_wins(self, monkeypatch):
        monkeypatch.setenv("SIMPLEQ_ENDPOINT_URL", "http://from-env")
        config = Config(endpoint_url="http://explicit")
        assert config.endpoint_url == "http://explicit"

    def test_region_from_env(self, monkeypatch):
        monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
        config = Config()
        assert config.region == "eu-west-1"

    def test_explicit_region_wins(self, monkeypatch):
        monkeypatch.setenv("AWS_DEFAULT_REGION", "eu-west-1")
        config = Config(region="ap-southeast-1")
        assert config.region == "ap-southeast-1"
