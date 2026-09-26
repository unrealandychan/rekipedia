"""Tests for Vertex AI ADC (Application Default Credentials) configuration."""
from __future__ import annotations

import os
import pytest

from rekipedia.llm.client import LLMClient
from rekipedia.models.contracts import LLMConfig


def test_llm_client_vertex_adc_kwargs(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("VERTEX_PROJECT", "my-gcp-project")
    monkeypatch.setenv("VERTEX_LOCATION", "us-east4")

    cfg = LLMConfig(model="vertex_ai/gemini-1.5-flash")
    client = LLMClient(cfg)
    kwargs = client._base_kwargs()

    assert kwargs["model"] == "vertex_ai/gemini-1.5-flash"
    assert kwargs["vertex_project"] == "my-gcp-project"
    assert kwargs["vertex_location"] == "us-east4"


def test_llm_client_vertex_default_location(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("VERTEX_LOCATION", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_REGION", raising=False)
    monkeypatch.delenv("GCP_REGION", raising=False)
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "auto-project")

    cfg = LLMConfig(model="vertex_ai/gemini-2.5-flash")
    client = LLMClient(cfg)
    kwargs = client._base_kwargs()

    assert kwargs["vertex_project"] == "auto-project"
    assert kwargs["vertex_location"] == "us-central1"
