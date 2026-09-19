from __future__ import annotations

from pathlib import Path

import httpx
import openai
import pytest

from app.providers.openai.tts import OpenAITTSProvider, TTSGenerationError

_FAKE_WAV_BYTES = b"RIFF....WAVEfmt fake audio bytes for testing"


class _FakeStreamedResponse:
    def __init__(self, content: bytes) -> None:
        self._content = content

    async def stream_to_file(self, path: Path) -> None:
        Path(path).write_bytes(self._content)


class _FakeStreamingContextManager:
    def __init__(self, result_or_exc, capture: dict) -> None:
        self._result_or_exc = result_or_exc
        self._capture = capture

    async def __aenter__(self):
        if isinstance(self._result_or_exc, BaseException):
            raise self._result_or_exc
        return self._result_or_exc

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False


class _FakeStreamingResponseNamespace:
    def __init__(self, result_or_exc) -> None:
        self._result_or_exc = result_or_exc
        self.last_call_kwargs: dict | None = None

    def create(self, **kwargs):
        self.last_call_kwargs = kwargs
        return _FakeStreamingContextManager(self._result_or_exc, {})


class _FakeSpeech:
    def __init__(self, streaming_namespace: _FakeStreamingResponseNamespace) -> None:
        self.with_streaming_response = streaming_namespace


class _FakeAudio:
    def __init__(self, speech: _FakeSpeech) -> None:
        self.speech = speech


class _FakeClient:
    def __init__(self, result_or_exc) -> None:
        self._streaming_namespace = _FakeStreamingResponseNamespace(result_or_exc)
        self.audio = _FakeAudio(_FakeSpeech(self._streaming_namespace))


async def test_synthesize_writes_audio_to_out_path(tmp_path: Path) -> None:
    client = _FakeClient(_FakeStreamedResponse(_FAKE_WAV_BYTES))
    provider = OpenAITTSProvider(client, model="gpt-4o-mini-tts")  # type: ignore[arg-type]
    out_path = tmp_path / "intro.wav"

    result = await provider.synthesize("Good morning!", "intro", "alloy", out_path)

    assert result == out_path
    assert out_path.read_bytes() == _FAKE_WAV_BYTES
    kwargs = client._streaming_namespace.last_call_kwargs
    assert kwargs["model"] == "gpt-4o-mini-tts"
    assert kwargs["voice"] == "alloy"
    assert kwargs["input"] == "Good morning!"
    assert kwargs["response_format"] == "wav"


async def test_synthesize_passes_delivery_instructions(tmp_path: Path) -> None:
    client = _FakeClient(_FakeStreamedResponse(_FAKE_WAV_BYTES))
    provider = OpenAITTSProvider(
        client, delivery_instructions="Warm and calm."  # type: ignore[arg-type]
    )

    await provider.synthesize("Text", "outro", "alloy", tmp_path / "outro.wav")

    assert client._streaming_namespace.last_call_kwargs["instructions"] == "Warm and calm."


async def test_synthesize_omits_instructions_when_not_configured(tmp_path: Path) -> None:
    client = _FakeClient(_FakeStreamedResponse(_FAKE_WAV_BYTES))
    provider = OpenAITTSProvider(client)  # type: ignore[arg-type]

    await provider.synthesize("Text", "outro", "alloy", tmp_path / "outro.wav")

    assert client._streaming_namespace.last_call_kwargs["instructions"] is openai.omit


async def test_openai_error_is_wrapped_as_tts_generation_error(tmp_path: Path) -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/audio/speech")
    client = _FakeClient(openai.APIConnectionError(request=request))
    provider = OpenAITTSProvider(client)  # type: ignore[arg-type]

    with pytest.raises(TTSGenerationError, match="synthesis failed for section 'weather'"):
        await provider.synthesize("Text", "weather", "alloy", tmp_path / "weather.wav")


async def test_creates_parent_directory(tmp_path: Path) -> None:
    client = _FakeClient(_FakeStreamedResponse(_FAKE_WAV_BYTES))
    provider = OpenAITTSProvider(client)  # type: ignore[arg-type]
    out_path = tmp_path / "nested" / "dir" / "intro.wav"

    await provider.synthesize("Text", "intro", "alloy", out_path)

    assert out_path.exists()
