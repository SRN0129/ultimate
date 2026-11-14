"""Inference and Speech-to-Text engine modules for ULTIMATE."""

from ultimate.engine.groq_failover import GroqFailoverEngine, transcribe_audio_bytes

__all__ = ["GroqFailoverEngine", "transcribe_audio_bytes"]
