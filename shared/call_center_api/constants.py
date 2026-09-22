"""Shared literals for reference and Pixeltable backend parity."""

EMBED_DIM = 768

ALLOWED_AUDIO_EXTENSIONS = frozenset({".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm"})
ALLOWED_VIDEO_EXTENSIONS = frozenset({".mp4", ".mov", ".mkv"})
ALLOWED_UPLOAD_EXTENSIONS = ALLOWED_AUDIO_EXTENSIONS | ALLOWED_VIDEO_EXTENSIONS

FLAGGED_SENTIMENT_THRESHOLD = 0.4
