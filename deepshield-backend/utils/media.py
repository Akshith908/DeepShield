import mimetypes


IMAGE_EXTENSIONS = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".webp",
    ".avif",
}

VIDEO_EXTENSIONS = {
    ".mp4",
    ".webm",
    ".mov",
    ".avi",
    ".mkv",
}

AUDIO_EXTENSIONS = {
    ".mp3",
    ".wav",
    ".m4a",
    ".aac",
    ".ogg",
    ".flac",
    ".alac",
    ".mp2",
    ".mpeg",
}


def get_media_type(filename: str) -> str:
    """Return the best-effort media category for `filename`.

    Extension-based matching is intentionally ordered audio-first for
    ambiguous MPEG-family suffixes because several widely used audio formats
    share those suffixes with video formats (for example `.mpeg`, `.mpg`,
    `.mp2`). Where the extension alone cannot disambiguate, we prefer a safe
    classification that routes to the audio provider when the filename is a
    plausible audio asset, and we fail closed as "unknown" when we cannot
    decide.

    This function must never read the uploaded file bytes. It only inspects
    the filename extension and the standard `mimetypes` mapping.
    """
    filename = filename.lower()

    for extension in IMAGE_EXTENSIONS:
        if filename.endswith(extension):
            return "image"

    for extension in AUDIO_EXTENSIONS:
        if filename.endswith(extension):
            return "audio"

    for extension in VIDEO_EXTENSIONS:
        if filename.endswith(extension):
            return "video"

    mime_type, _ = mimetypes.guess_type(filename)

    if mime_type:
        if mime_type.startswith("image/"):
            return "image"

        if mime_type.startswith("audio/"):
            return "audio"

        if mime_type.startswith("video/"):
            return "video"

    return "unknown"
