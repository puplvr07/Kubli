import socket
import pytest
from app.services import network
from app.services import llm
import asyncio
from fastapi import HTTPException


def test_external_socket_and_dns_are_blocked():
    network.install_guard()
    with pytest.raises(PermissionError): socket.getaddrinfo('example.com', 443)
    with socket.socket() as sock:
        with pytest.raises(PermissionError): sock.connect(('8.8.8.8', 443))
    assert network.blocked_connections >= 2
    assert socket.getaddrinfo('127.0.0.1', 8000)


def test_missing_ollama_and_model_messages(monkeypatch):
    import httpx
    class Client:
        def __init__(self, **kwargs):
            assert kwargs['trust_env'] is False and kwargs['follow_redirects'] is False
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kwargs):
            assert url.startswith('http://127.0.0.1:11434/')
            return httpx.Response(404)
    monkeypatch.setattr(httpx, 'AsyncClient', Client)
    with pytest.raises(HTTPException) as error:
        asyncio.run(llm.local_post('/api/chat', {'model':'qwen2.5:3b-instruct'}))
    assert 'ollama pull qwen2.5:3b-instruct' in error.value.detail
