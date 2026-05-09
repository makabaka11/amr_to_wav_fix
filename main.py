import asyncio
import os
import shutil
import uuid

from astrbot.api import logger
from astrbot.api.star import Context, Star, register


AMR_MAGIC = b"#!AMR\n"


def _is_amr_file(file_path: str) -> bool:
    """Check if a file is AMR format by reading its magic bytes."""
    try:
        with open(file_path, "rb") as f:
            header = f.read(8)
        return header[:6] == AMR_MAGIC
    except (OSError, IOError):
        return False


async def _convert_amr_to_wav(input_path: str, output_path: str) -> bool:
    """Convert AMR file to WAV (16kHz mono PCM) using ffmpeg.

    Returns True on success, False on failure.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-y",
            "-i", input_path,
            "-ar", "16000",
            "-ac", "1",
            "-c:a", "pcm_s16le",
            output_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await proc.communicate()
        if proc.returncode == 0 and os.path.exists(output_path):
            return True
        else:
            logger.error(
                f"[AMR2WAV] ffmpeg conversion failed (rc={proc.returncode}): "
                f"{stderr.decode(errors='replace')}"
            )
            return False
    except FileNotFoundError:
        logger.error("[AMR2WAV] ffmpeg not found. Please install ffmpeg.")
        return False
    except Exception as e:
        logger.error(f"[AMR2WAV] Unexpected error during conversion: {e}")
        return False


async def _resolve_record_to_local_path(record) -> str | None:
    """Resolve a Record component's file reference to a local file path.

    Handles file:///, http(s)://, base64://, raw local paths,
    and falls back to record.url when record.file is just a filename.
    Returns None if resolution fails.
    """
    file_ref = record.file or ""

    # file:///path/to/file.amr
    if file_ref.startswith("file:///"):
        path = file_ref[8:]  # strip "file:///"
        if os.path.isfile(path):
            return path

    # http(s)://... in file field -> download
    if file_ref.startswith("http://") or file_ref.startswith("https://"):
        try:
            from astrbot.core.utils.io import download_image_by_url
            path = await download_image_by_url(file_ref)
            if path and os.path.isfile(path):
                return os.path.abspath(path)
        except Exception as e:
            logger.warning(f"[AMR2WAV] Failed to download voice file: {e}")
        return None

    # base64://...
    if file_ref.startswith("base64://"):
        try:
            import base64
            from astrbot.core.utils.shared import get_astrbot_temp_path
            bs64_data = file_ref.removeprefix("base64://")
            audio_bytes = base64.b64decode(bs64_data)
            path = os.path.join(
                get_astrbot_temp_path(), f"amr2wav_seg_{uuid.uuid4().hex}"
            )
            with open(path, "wb") as f:
                f.write(audio_bytes)
            return path
        except Exception as e:
            logger.warning(f"[AMR2WAV] Failed to decode base64 voice: {e}")
        return None

    # raw local path
    if file_ref and os.path.isfile(file_ref):
        return os.path.abspath(file_ref)

    # Fallback: NapCat sends file=filename, url=http://download_url
    # convert_to_file_path() ignores url, so we handle it here
    url_ref = getattr(record, "url", None) or ""
    if url_ref.startswith("http://") or url_ref.startswith("https://"):
        try:
            from astrbot.core.utils.io import download_image_by_url
            path = await download_image_by_url(url_ref)
            if path and os.path.isfile(path):
                logger.info(
                    f"[AMR2WAV] Downloaded voice via record.url: {url_ref} -> {path}"
                )
                return os.path.abspath(path)
        except Exception as e:
            logger.warning(f"[AMR2WAV] Failed to download voice via url: {e}")

    return None


@register(
    "amr_to_wav_fix",
    "makabaka11",
    "修复 NapCat AMR 语音无法被 STT 识别的问题，自动使用 ffmpeg 转换为 WAV",
    "1.0.0",
)
class AmrToWavFix(Star):
    """Wraps PreProcessStage.process to convert AMR voice files to WAV before STT."""

    def __init__(self, context: Context):
        super().__init__(context)
        self._temp_dir = os.path.join("data", "plugins", "amr_to_wav_fix", "temp")
        self._original_process = None
        self._patched = False

    async def initialize(self):
        """Called when plugin is activated. Sets up temp dir, checks ffmpeg, patches process."""
        os.makedirs(self._temp_dir, exist_ok=True)
        self._cleanup_temp_files()

        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            logger.warning(
                "[AMR2WAV] ffmpeg not found in PATH. "
                "Install ffmpeg: apt install ffmpeg / brew install ffmpeg"
            )
            return

        logger.info(f"[AMR2WAV] ffmpeg found at: {ffmpeg_path}")
        self._patch_preprocess_stage()

    def _patch_preprocess_stage(self):
        """Monkey-patch PreProcessStage.process to handle AMR before the original logic."""
        try:
            from astrbot.core.pipeline.preprocess_stage.stage import PreProcessStage
        except ImportError:
            logger.error("[AMR2WAV] Cannot import PreProcessStage")
            return

        original_process = PreProcessStage.process
        if original_process is None:
            logger.error("[AMR2WAV] PreProcessStage.process not found")
            return

        self._original_process = original_process
        temp_dir = self._temp_dir

        async def patched_process(self_inner, event):
            """Wraps original process: converts AMR records to WAV first,
            then delegates to the original process method."""
            from astrbot.core.message.components import Record

            message_chain = event.get_messages()
            for idx, component in enumerate(message_chain):
                if not isinstance(component, Record):
                    continue

                local_path = await _resolve_record_to_local_path(component)
                if local_path is None:
                    continue

                if not _is_amr_file(local_path):
                    continue

                wav_path = os.path.join(temp_dir, f"{uuid.uuid4().hex}.wav")
                logger.info(
                    f"[AMR2WAV] AMR detected: {os.path.basename(local_path)} "
                    f"-> {os.path.basename(wav_path)}"
                )

                success = await _convert_amr_to_wav(local_path, wav_path)
                if success:
                    logger.info(
                        f"[AMR2WAV] Conversion succeeded: "
                        f"{os.path.getsize(wav_path)} bytes"
                    )
                    component.file = wav_path
                    component.path = wav_path
                    message_chain[idx] = component
                    event.track_temporary_local_file(wav_path)
                else:
                    logger.warning(
                        "[AMR2WAV] Conversion failed, keeping original file"
                    )

            return await original_process(self_inner, event)

        PreProcessStage.process = patched_process
        self._patched = True
        logger.info("[AMR2WAV] Patched PreProcessStage.process successfully")

    def _cleanup_temp_files(self):
        """Remove stale WAV files from previous runs."""
        if not os.path.isdir(self._temp_dir):
            return
        count = 0
        for fname in os.listdir(self._temp_dir):
            if fname.endswith(".wav"):
                fpath = os.path.join(self._temp_dir, fname)
                try:
                    os.remove(fpath)
                    count += 1
                except OSError:
                    pass
        if count:
            logger.info(f"[AMR2WAV] Cleaned up {count} stale temp file(s)")

    async def terminate(self):
        """Called when plugin is disabled. Restores original process and cleans up."""
        if self._patched and self._original_process:
            try:
                from astrbot.core.pipeline.preprocess_stage.stage import PreProcessStage
                PreProcessStage.process = self._original_process
                logger.info("[AMR2WAV] Restored original PreProcessStage.process")
            except ImportError:
                pass

        self._cleanup_temp_files()
        logger.info("[AMR2WAV] Plugin terminated")
