from __future__ import annotations

import json
import threading
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

import youtube_script_app.gui as gui
from youtube_script_app.video import logo_config


class _ImmediateMaster:
    def after(self, _delay: int, callback, *args):
        callback(*args)


class _DummyVar:
    def __init__(self) -> None:
        self.value = ""

    def set(self, value: str) -> None:
        self.value = value

    def get(self) -> str:
        return self.value


class _DummyNumberVar:
    def __init__(self, value):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _DummyCanvas:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def yview_moveto(self, fraction: float) -> None:
        self.calls.append(("moveto", fraction))

    def yview_scroll(self, amount: int, unit: str) -> None:
        self.calls.append(("scroll", amount, unit))


class _DummyProgress:
    def __init__(self) -> None:
        self.options = {"value": 0.0, "maximum": 100.0}

    def configure(self, **kwargs) -> None:
        self.options.update(kwargs)


class _DummyEntry:
    def __init__(self, value: str) -> None:
        self.value = value
        self._placeholder_active = False

    def get(self) -> str:
        return self.value


class _DummyMoment:
    def __init__(self, minute_index: int, excerpt: str = "") -> None:
        self.minute_index = minute_index
        self.excerpt = excerpt


def _write_logo(path: Path, size: tuple[int, int] = (800, 320)) -> None:
    Image.new("RGBA", size, (255, 0, 0, 255)).save(path)


def test_logo_config_reports_decompression_bomb_as_too_large(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    logo_path = tmp_path / "logo.png"
    logo_path.write_bytes(b"fake")

    def _raise_decompression_bomb(_path):
        raise Image.DecompressionBombError("too many pixels")

    monkeypatch.setattr(logo_config.Image, "open", _raise_decompression_bomb)

    with pytest.raises(ValueError, match="Image logo trop grande"):
        logo_config.LogoConfig(
            path=logo_path,
            position="top-right",
            size_mode="relative",
            slider_value=30,
            opacity=1.0,
        )


def test_run_generation_handles_unexpected_exception(
    monkeypatch,
) -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.master = _ImmediateMaster()
    app.cancel_event = threading.Event()
    app.current_job_id = 1

    captured: dict[str, str] = {}

    app._should_ignore_result = lambda job_id: False  # type: ignore[attr-defined]
    app._handle_error = lambda message: captured.setdefault("message", message)  # type: ignore[attr-defined]

    def _raise(*args, **kwargs):
        raise RuntimeError("boom generation")

    monkeypatch.setattr(gui, "generate_transcript_with_format", _raise)

    app._run_generation(1, "https://youtu.be/dQw4w9WgXcQ", None, "text", False, 5)

    assert captured["message"] == "Erreur inattendue: boom generation"


def test_recover_stale_busy_state_resets_busy_flag() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.busy = True
    app.download_active = False
    app.generation_thread = None
    app.download_thread = None
    app.download_process = None
    app.status_var = _DummyVar()

    calls: list[tuple[str, bool]] = []

    def _set_status(message: str, *, busy: bool, error: bool = False, success: bool = False):
        calls.append((message, busy))
        app.busy = busy

    app._set_status = _set_status  # type: ignore[attr-defined]

    app._recover_stale_busy_state()

    assert app.busy is False
    assert calls == [("Prêt.", False)]


def test_scroll_helpers_move_on_main_canvas() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.main_canvas = _DummyCanvas()

    app.scroll_to_top()
    app.scroll_to_bottom()
    app._scroll_main_page(1)
    app._scroll_main_page(-1)

    assert app.main_canvas.calls == [
        ("moveto", 0.0),
        ("moveto", 1.0),
        ("scroll", 1, "pages"),
        ("scroll", -1, "pages"),
    ]


def test_generate_button_enables_after_url_write() -> None:
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Tk unavailable in this environment")

    app = gui.TranscriptApp(root)
    app.url_var.set("https://youtu.be/dQw4w9WgXcQ")
    root.update_idletasks()

    assert str(app.generate_button.cget("state")) == "normal"
    assert str(app.preview_video_button.cget("state")) == "normal"
    assert str(app.quick_transcribe_button.cget("state")) == "normal"
    assert str(app.quick_download_full_video_button.cget("state")) == "normal"
    assert str(app.quick_download_audio_button.cget("state")) == "normal"
    root.destroy()


def test_preview_video_opens_current_link(monkeypatch: pytest.MonkeyPatch) -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.url_entry = _DummyEntry("https://example.com/video")
    opened: list[str] = []

    monkeypatch.setattr(gui.webbrowser, "open", opened.append)

    app.preview_video()

    assert opened == ["https://example.com/video"]


def test_generate_non_youtube_guides_to_download_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.busy = False
    app.download_active = False
    app.url_entry = _DummyEntry("https://example.com/video")
    output_lines: list[str] = []
    statuses: list[str] = []
    dialogs: list[tuple[str, str]] = []
    app._append_output = output_lines.append  # type: ignore[attr-defined]
    app._set_status = lambda message, **_kwargs: statuses.append(message)  # type: ignore[attr-defined]
    monkeypatch.setattr(gui.messagebox, "showerror", lambda title, message: dialogs.append((title, message)))

    app.generate()

    assert dialogs[0][0] == "Transcription YouTube uniquement"
    assert "Télécharger vidéo" in dialogs[0][1]
    assert output_lines == ["Erreur: lien non compatible avec la transcription YouTube."]
    assert statuses == ["Choisis un lien YouTube pour transcrire, ou télécharge le média."]


def test_download_variant_suffix() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    assert app._download_variant_suffix(True, True) == "_shorts_logo"
    assert app._download_variant_suffix(True, False) == "_shorts_9x16"
    assert app._download_variant_suffix(False, True) == "_logo"
    assert (
        app._download_variant_suffix(False, False, has_lower_third=True)
        == "_lower-third"
    )
    assert (
        app._download_variant_suffix(
            False,
            False,
            has_intro_outro=True,
            has_progress_bar=True,
            has_watermark=True,
        )
        == "_intro-outro_progress_watermark"
    )
    assert app._download_variant_suffix(False, False) == ""


def test_download_variant_output_path_uses_mp4_for_processed_variants() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    source = Path("/tmp/clip.webm")

    shorts_logo = app._download_variant_output_path(source, True, True)
    shorts_only = app._download_variant_output_path(source, True, False)
    logo_only = app._download_variant_output_path(source, False, True)
    lower_only = app._download_variant_output_path(
        source,
        False,
        False,
        has_lower_third=True,
    )
    value_add = app._download_variant_output_path(
        source,
        False,
        False,
        has_intro_outro=True,
        has_progress_bar=True,
        has_watermark=True,
    )
    untouched = app._download_variant_output_path(source, False, False)

    assert shorts_logo.name == "clip_shorts_logo.mp4"
    assert shorts_only.name == "clip_shorts_9x16.mp4"
    assert logo_only.name == "clip_logo.mp4"
    assert lower_only.name == "clip_lower-third.mp4"
    assert value_add.name == "clip_intro-outro_progress_watermark.mp4"
    assert untouched.name == "clip.webm"


def test_download_variant_suffix_includes_subtitles_and_effect() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)

    suffix = app._download_variant_suffix(
        True,
        True,
        has_subtitles=True,
        video_effect="black_white",
        subtitle_style="modern",
    )

    assert suffix == "_shorts_logo_subs-modern_bw"


def test_cleanup_intermediate_download_removes_source_file(tmp_path) -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.master = _ImmediateMaster()
    app._append_download_log = lambda _line: None  # type: ignore[attr-defined]

    source = tmp_path / "clip_source.mp4"
    source.write_text("source", encoding="utf-8")
    final = tmp_path / "clip_shorts_9x16.mp4"
    final.write_text("final", encoding="utf-8")

    app._cleanup_intermediate_download(source, final)

    assert source.exists() is False


def test_cleanup_intermediate_download_keeps_source_when_same_path(tmp_path) -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.master = _ImmediateMaster()
    app._append_download_log = lambda _line: None  # type: ignore[attr-defined]

    source = tmp_path / "clip.mp4"
    source.write_text("source", encoding="utf-8")

    app._cleanup_intermediate_download(source, source)

    assert source.exists() is True


def test_build_media_download_command_for_full_video() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    cmd = app._build_media_download_command(
        {
            "kind": "full_video",
            "output_dir": "/tmp",
            "url": "https://youtu.be/demo",
            "yt_dlp_cmd": ["yt-dlp"],
            "format": "webm",
        }
    )

    assert "-f" in cmd
    assert gui.download_utils.BEST_VIDEO_FORMAT_SELECTOR in cmd
    assert "-S" in cmd
    assert gui.download_utils.BEST_VIDEO_SORT_ORDER in cmd
    assert "--merge-output-format" in cmd
    assert "webm" in cmd
    assert "%(title).120s_full.%(ext)s" in cmd


def test_build_media_download_command_for_audio() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    cmd = app._build_media_download_command(
        {
            "kind": "audio",
            "output_dir": "/tmp",
            "url": "https://youtu.be/demo",
            "yt_dlp_cmd": ["yt-dlp"],
            "format": "mp3",
        }
    )

    assert "--extract-audio" in cmd
    assert "--audio-format" in cmd
    assert "mp3" in cmd
    assert "%(title).120s_audio.%(ext)s" in cmd


def test_resolve_yt_dlp_cmd_uses_common_tool_dirs(tmp_path, monkeypatch) -> None:
    tool_dir = tmp_path / "bin"
    tool_dir.mkdir()
    yt_dlp = tool_dir / "yt-dlp"
    yt_dlp.write_text("#!/bin/sh\n", encoding="utf-8")
    yt_dlp.chmod(0o755)

    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setattr(gui.shutil, "which", lambda _name: None)
    monkeypatch.setattr(gui, "COMMON_TOOL_DIRS", (str(tool_dir),))

    app = gui.TranscriptApp.__new__(gui.TranscriptApp)

    assert app._resolve_yt_dlp_cmd() == [str(yt_dlp)]
    assert gui.os.environ["PATH"].split(gui.os.pathsep)[0] == str(tool_dir)


def test_set_download_summary_supports_full_video_and_audio() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.download_summary_var = _DummyVar()
    app.download_phase_var = _DummyVar()

    app._set_download_summary(
        1,
        2,
        0,
        0,
        "mp4",
        "Titre test",
        item_kind="full_video",
    )
    assert "vidéo entière" in app.download_summary_var.value

    app._set_download_summary(
        2,
        2,
        0,
        0,
        "mp3",
        "Titre test",
        item_kind="audio",
    )
    assert "piste audio" in app.download_summary_var.value


def test_download_full_video_enqueues_media_request() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.last_url = "https://youtu.be/demo"
    app._resolve_yt_dlp_cmd = lambda: ["yt-dlp"]  # type: ignore[attr-defined]
    app._pick_download_dir = lambda: "/tmp"  # type: ignore[attr-defined]
    app._get_video_format = lambda: "webm"  # type: ignore[attr-defined]
    captured: dict[str, object] = {}

    def _capture_enqueue(**kwargs) -> None:
        captured.update(kwargs)

    app._enqueue_media_download = _capture_enqueue  # type: ignore[attr-defined]

    app.download_full_video()

    assert captured["kind"] == "full_video"
    assert captured["video_format"] == "webm"


def test_download_full_video_prefers_current_generic_link() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.last_url = "https://youtu.be/old"
    app.url_entry = object()
    app._get_entry_value = lambda _entry: "https://www.tiktok.com/@demo/video/123"  # type: ignore[attr-defined]
    app._resolve_yt_dlp_cmd = lambda: ["yt-dlp"]  # type: ignore[attr-defined]
    app._pick_download_dir = lambda: "/tmp"  # type: ignore[attr-defined]
    app._get_video_format = lambda: "mp4"  # type: ignore[attr-defined]
    captured: dict[str, object] = {}
    app._enqueue_media_download = lambda **kwargs: captured.update(kwargs)  # type: ignore[attr-defined]

    app.download_full_video()

    assert captured["url"] == "https://www.tiktok.com/@demo/video/123"
    assert captured["kind"] == "full_video"


def test_download_full_video_enqueues_logo_options() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.last_url = "https://youtu.be/demo"
    app._resolve_yt_dlp_cmd = lambda: ["yt-dlp"]  # type: ignore[attr-defined]
    app._resolve_system_tool = lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None  # type: ignore[attr-defined]
    app._pick_download_dir = lambda: "/tmp"  # type: ignore[attr-defined]
    app._get_video_format = lambda: "mp4"  # type: ignore[attr-defined]
    app.download_logo_enabled_var = _DummyNumberVar(True)
    app._build_logo_config = lambda: SimpleNamespace(  # type: ignore[attr-defined]
        path=Path("/tmp/logo.png"),
        position="bottom",
        size_mode="relative",
        slider_value=42,
        opacity=0.76,
        original_width=800,
        original_height=320,
    )
    app._get_download_logo_width_ratio = lambda: 0.144  # type: ignore[attr-defined]
    app._get_download_logo_x_ratio = lambda: 0.5  # type: ignore[attr-defined]
    app._get_download_logo_y_ratio = lambda: 0.87  # type: ignore[attr-defined]
    app.download_logo_position_var = _DummyVar()
    app.download_logo_position_lookup = {}
    app._selected_download_logo_position = lambda: "bottom"  # type: ignore[attr-defined]
    app.download_logo_size_mode_var = _DummyVar()
    app.download_logo_size_mode_lookup = {}
    app._selected_download_logo_size_mode = lambda: "relative"  # type: ignore[attr-defined]
    app.download_logo_size_var = _DummyNumberVar(58)
    app._get_download_logo_scale_percent = lambda: 42  # type: ignore[attr-defined]
    app.download_logo_opacity_var = _DummyNumberVar(100)
    app._get_download_logo_opacity_percent = lambda: 76  # type: ignore[attr-defined]
    captured: dict[str, object] = {}
    app._enqueue_media_download = lambda **kwargs: captured.update(kwargs)  # type: ignore[attr-defined]

    app.download_full_video()

    assert captured["kind"] == "full_video"
    assert captured["logo_enabled"] is True
    assert captured["logo_path"] == "/tmp/logo.png"
    assert captured["logo_position"] == "bottom"
    assert captured["logo_size_mode"] == "relative"
    assert captured["logo_scale_percent"] == 42
    assert captured["logo_opacity_percent"] == 76
    assert captured["logo_original_width"] == 800
    assert captured["logo_original_height"] == 320


def test_download_full_video_enqueues_shorts_mode() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.last_url = "https://youtu.be/demo"
    app._resolve_yt_dlp_cmd = lambda: ["yt-dlp"]  # type: ignore[attr-defined]
    app._resolve_system_tool = lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None  # type: ignore[attr-defined]
    app._pick_download_dir = lambda: "/tmp"  # type: ignore[attr-defined]
    app._get_video_format = lambda: "mp4"  # type: ignore[attr-defined]
    app.download_aspect_ratio_lookup = {"Short 9:16": "shorts"}
    app.download_aspect_ratio_var = _DummyVar()
    app.download_aspect_ratio_var.set("Short 9:16")
    app.download_logo_enabled_var = _DummyNumberVar(False)
    app.download_lower_third_enabled_var = _DummyNumberVar(False)
    app.download_subtitles_enabled_var = _DummyNumberVar(False)
    app.download_video_effect_lookup = {"Aucun": "none"}
    app.download_video_effect_var = _DummyVar()
    app.download_video_effect_var.set("Aucun")
    captured: dict[str, object] = {}
    app._enqueue_media_download = lambda **kwargs: captured.update(kwargs)  # type: ignore[attr-defined]

    app.download_full_video()

    assert captured["kind"] == "full_video"
    assert captured["shorts_mode"] is True


def test_download_full_video_requires_logo_when_logo_enabled(monkeypatch) -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.last_url = "https://youtu.be/demo"
    app._resolve_yt_dlp_cmd = lambda: ["yt-dlp"]  # type: ignore[attr-defined]
    app.download_logo_enabled_var = _DummyNumberVar(True)
    app._validated_download_logo_path = lambda: ""  # type: ignore[attr-defined]
    warnings: list[str] = []
    app._pick_download_dir = lambda: warnings.append("picked") or "/tmp"  # type: ignore[attr-defined]
    app._enqueue_media_download = lambda **_kwargs: warnings.append("enqueued")  # type: ignore[attr-defined]

    monkeypatch.setattr(
        gui.messagebox,
        "showwarning",
        lambda _title, message: warnings.append(message),
    )

    app.download_full_video()

    assert any("logo" in message for message in warnings)
    assert "picked" not in warnings
    assert "enqueued" not in warnings


def test_download_audio_only_requires_ffmpeg(monkeypatch) -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.last_url = "https://youtu.be/demo"
    app._resolve_yt_dlp_cmd = lambda: ["yt-dlp"]  # type: ignore[attr-defined]
    app._pick_download_dir = lambda: "/tmp"  # type: ignore[attr-defined]
    app._get_video_format = lambda: "mp4"  # type: ignore[attr-defined]
    errors: list[str] = []
    app._enqueue_media_download = lambda **kwargs: errors.append("enqueued")  # type: ignore[attr-defined]

    monkeypatch.setattr(gui.shutil, "which", lambda name: None if name == "ffmpeg" else "/usr/bin/tool")
    monkeypatch.setattr(gui, "COMMON_TOOL_DIRS", ())
    monkeypatch.setattr(
        gui.messagebox,
        "showerror",
        lambda _title, message: errors.append(message),
    )

    app.download_audio_only()

    assert any("ffmpeg" in message for message in errors)
    assert "enqueued" not in errors


def test_download_media_item_generates_logo_variant_for_full_video(monkeypatch, tmp_path) -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.master = _ImmediateMaster()
    app.download_cancel = threading.Event()
    app.download_process = None
    app.download_last_size = ""
    app._build_media_download_command = lambda _item: ["yt-dlp"]  # type: ignore[attr-defined]
    downloaded = tmp_path / "demo_full.mp4"
    downloaded.write_text("video", encoding="utf-8")
    final = tmp_path / "demo_full_logo.mp4"
    app._resolve_downloaded_path = lambda **_kwargs: downloaded  # type: ignore[attr-defined]
    app._update_download_progress = lambda *_args: None  # type: ignore[attr-defined]
    app._log_download_percent_steps = lambda *_args: None  # type: ignore[attr-defined]
    app._set_download_phase = lambda _phase: None  # type: ignore[attr-defined]
    app.download_detail_var = _DummyVar()
    app._append_download_log = lambda _line: None  # type: ignore[attr-defined]
    recorded: list[Path] = []
    app._record_download_history = lambda _item, path: recorded.append(path)  # type: ignore[attr-defined]
    app._cleanup_intermediate_download = lambda _source, _path: None  # type: ignore[attr-defined]
    variant_calls: list[dict] = []

    def _variant(path: Path, **kwargs) -> Path:
        variant_calls.append({"path": path, **kwargs})
        return final

    app._build_download_variant = _variant  # type: ignore[attr-defined]

    class _FakePopen:
        stderr = iter(())

        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def wait(self) -> int:
            return 0

    monkeypatch.setattr(gui.subprocess, "Popen", _FakePopen)

    success, error = app._download_media_item(
        {
            "kind": "full_video",
            "url": "https://youtu.be/demo",
            "output_dir": str(tmp_path),
            "format": "mp4",
            "logo_enabled": True,
            "logo_path": "/tmp/logo.png",
            "logo_position": "top",
            "logo_size_mode": "original",
            "logo_scale_percent": 55,
            "logo_opacity_percent": 80,
        }
    )

    assert (success, error) == (True, "")
    assert recorded == [final]
    assert app.last_downloaded_file == str(final)
    assert variant_calls == [
        {
            "path": downloaded,
            "to_shorts": False,
            "logo_path": "/tmp/logo.png",
            "logo_position": "top",
            "logo_size_mode": "original",
            "logo_scale_percent": 55,
            "logo_opacity_percent": 80,
            "logo_display_duration": None,
            "shorts_blur_bg": True,
            "lower_third_config": None,
            "intro_outro_enabled": False,
            "intro_outro_channel_name": "",
            "intro_outro_hold_duration": 1.5,
            "intro_outro_bg_color": "0x000000@0.75",
            "intro_outro_text_color": "#FFFFFF",
            "progress_bar_enabled": False,
            "animated_watermark_enabled": False,
            "watermark_logo_path": "",
            "logo_width_ratio": 0.17,
            "logo_x_ratio": 0.5,
            "logo_y_ratio": 0.05,
            "lower_third_interval": 20,
            "lower_third_display_duration": 4,
        }
    ]


def test_download_media_item_applies_shorts_to_full_video(monkeypatch, tmp_path) -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.master = _ImmediateMaster()
    app.download_cancel = threading.Event()
    app.download_process = None
    app.download_last_size = ""
    app._build_media_download_command = lambda _item: ["yt-dlp"]  # type: ignore[attr-defined]
    downloaded = tmp_path / "demo_full.mp4"
    downloaded.write_text("video", encoding="utf-8")
    final = tmp_path / "demo_full_shorts_9x16.mp4"
    app._resolve_downloaded_path = lambda **_kwargs: downloaded  # type: ignore[attr-defined]
    app._update_download_progress = lambda *_args: None  # type: ignore[attr-defined]
    app._log_download_percent_steps = lambda *_args: None  # type: ignore[attr-defined]
    app._set_download_phase = lambda _phase: None  # type: ignore[attr-defined]
    app.download_detail_var = _DummyVar()
    app._append_download_log = lambda _line: None  # type: ignore[attr-defined]
    app._record_download_history = lambda _item, _path: None  # type: ignore[attr-defined]
    app._cleanup_intermediate_download = lambda _source, _path: None  # type: ignore[attr-defined]
    variant_calls: list[dict] = []

    def _variant(path: Path, **kwargs) -> Path:
        variant_calls.append({"path": path, **kwargs})
        return final

    app._build_download_variant = _variant  # type: ignore[attr-defined]

    class _FakePopen:
        stderr = iter(())

        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def wait(self) -> int:
            return 0

    monkeypatch.setattr(gui.subprocess, "Popen", _FakePopen)

    success, error = app._download_media_item(
        {
            "kind": "full_video",
            "url": "https://youtu.be/demo",
            "output_dir": str(tmp_path),
            "format": "mp4",
            "shorts": True,
            "logo_enabled": False,
            "video_effect": "none",
        }
    )

    assert (success, error) == (True, "")
    assert variant_calls[0]["to_shorts"] is True


def test_render_preview_clip_generates_temporary_variant(monkeypatch, tmp_path) -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.master = _ImmediateMaster()
    app.cancel_event = threading.Event()
    app.download_process = None
    app._set_download_phase = lambda _phase: None  # type: ignore[attr-defined]
    app._append_download_log = lambda _line: None  # type: ignore[attr-defined]
    downloaded = tmp_path / "preview.mp4"
    downloaded.write_text("video", encoding="utf-8")
    final = tmp_path / "preview_subs-impact_bw.mp4"
    app._resolve_downloaded_path = lambda **_kwargs: downloaded  # type: ignore[attr-defined]
    variant_calls: list[dict] = []

    def _variant(path: Path, **kwargs) -> Path:
        variant_calls.append({"path": path, **kwargs})
        return final

    app._build_download_variant = _variant  # type: ignore[attr-defined]

    class _FakePopen:
        def __init__(self, *_args, **_kwargs) -> None:
            self.stderr = iter(())

        def wait(self) -> int:
            return 0

    monkeypatch.setattr(gui.subprocess, "Popen", _FakePopen)

    result = app._render_preview_clip(
        {
            "url": "https://youtu.be/demo",
            "output_dir": str(tmp_path),
            "start": 60,
            "duration": 8,
            "format": "mp4",
            "yt_dlp_cmd": ["yt-dlp"],
            "shorts": True,
            "logo_enabled": False,
            "logo_path": "",
            "logo_position": "center",
            "logo_size_mode": "relative",
            "logo_scale_percent": 58,
            "logo_opacity_percent": 100,
            "subtitles_enabled": True,
            "subtitle_chunks": [
                {"text": "Preview", "start": 62.0, "duration": 3.0},
            ],
            "subtitle_style": "impact",
            "video_effect": "black_white",
        }
    )

    assert result == final
    assert variant_calls == [
        {
            "path": downloaded,
            "to_shorts": True,
            "logo_path": "",
            "logo_position": "center",
            "logo_size_mode": "relative",
            "logo_scale_percent": 58,
            "logo_opacity_percent": 100,
            "logo_display_duration": None,
            "shorts_blur_bg": True,
            "logo_width_ratio": 0.176,
            "logo_x_ratio": 0.5,
            "logo_y_ratio": 0.46,
            "subtitle_chunks": [
                {"text": "Preview", "start": 62.0, "duration": 3.0},
            ],
            "subtitle_start": 60.0,
            "subtitle_duration": 8.0,
            "subtitle_offset_ms": 0,
            "subtitle_style": "impact",
            "video_effect": "black_white",
            "lower_third_config": None,
            "clip_duration": 8.0,
            "intro_outro_enabled": False,
            "intro_outro_channel_name": "",
            "intro_outro_hold_duration": 1.5,
            "intro_outro_bg_color": "0x000000@0.75",
            "intro_outro_text_color": "#FFFFFF",
            "progress_bar_enabled": False,
            "animated_watermark_enabled": False,
            "watermark_logo_path": "",
            "lower_third_interval": 20,
            "lower_third_display_duration": 4,
            "preview_width": 1080,
        }
    ]


def test_load_gui_settings_returns_default_when_missing(tmp_path) -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.gui_settings_path = tmp_path / "gui_settings.json"

    settings = app._load_gui_settings()

    assert settings == {
        "version": 7,
        "download_aspect_mode": "landscape",
        "video_format": "mp4",
        "clip_duration": 60,
        "download_logo_enabled": True,
        "download_logo_path": "",
        "download_logo_position": "top-right",
        "download_logo_size_mode": "relative",
        "download_logo_scale_percent": 30,
        "download_logo_opacity_percent": 100,
        "download_logo_duration": 0,
        "download_logo_width_ratio": 0.12,
        "download_logo_x_ratio": 0.95,
        "download_logo_y_ratio": 0.05,
        "download_subtitles_enabled": True,
        "download_subtitle_style": "impact",
        "download_video_effect": "none",
        "download_intro_outro_enabled": False,
        "download_progress_bar_enabled": False,
        "download_animated_watermark_enabled": False,
        "download_lower_third_enabled": False,
        "download_lower_third_name": "",
        "download_lower_third_tagline": "",
        "download_lower_third_subscribe": True,
        "download_lower_third_bg_color": "#F5F0E8",
        "download_lower_third_accent_color": "#E85D3A",
        "download_lower_third_interval": 20,
        "download_lower_third_display_duration": 4,
        "download_preset": "custom",
    }


def test_load_gui_settings_normalizes_invalid_mode(tmp_path) -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.gui_settings_path = tmp_path / "gui_settings.json"
    app.gui_settings_path.write_text(
        json.dumps(
            {
                "version": 1,
                "download_aspect_mode": "invalid",
                "video_format": "avi",
                "clip_duration": "999",
                "download_logo_enabled": "off",
                "download_logo_path": gui.DOWNLOAD_LOGO_PLACEHOLDER,
                "download_logo_position": "left",
                "download_logo_size_mode": "invalid",
                "download_logo_scale_percent": 400,
                "download_logo_opacity_percent": 1,
                "download_subtitles_enabled": "off",
                "download_subtitle_style": "unknown",
                "download_video_effect": "unknown",
                "download_intro_outro_enabled": "yes",
                "download_progress_bar_enabled": "on",
                "download_animated_watermark_enabled": "off",
                "download_lower_third_enabled": "yes",
                "download_lower_third_name": "  MindShift   Daily  ",
                "download_lower_third_tagline": "  daily ideas  ",
                "download_lower_third_subscribe": "off",
                "download_lower_third_bg_color": "bad",
                "download_lower_third_accent_color": "#123ABC",
                "download_lower_third_interval": "999",
                "download_lower_third_display_duration": "999",
                "download_preset": "unknown",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    settings = app._load_gui_settings()

    assert settings["download_aspect_mode"] == "landscape"
    assert settings["video_format"] == "mp4"
    assert settings["clip_duration"] == 300
    assert settings["download_logo_enabled"] is False
    assert settings["download_logo_path"] == ""
    assert settings["download_logo_position"] == "top-right"
    assert settings["download_logo_size_mode"] == "relative"
    assert settings["download_logo_scale_percent"] == 80
    assert settings["download_logo_width_ratio"] == pytest.approx(0.22)
    assert settings["download_logo_x_ratio"] == pytest.approx(0.95)
    assert settings["download_logo_y_ratio"] == pytest.approx(0.05)
    assert settings["download_logo_opacity_percent"] == 10
    assert settings["download_subtitles_enabled"] is False
    assert settings["download_subtitle_style"] == "impact"
    assert settings["download_video_effect"] == "none"
    assert settings["download_intro_outro_enabled"] is True
    assert settings["download_progress_bar_enabled"] is True
    assert settings["download_animated_watermark_enabled"] is False
    assert settings["download_lower_third_enabled"] is True
    assert settings["download_lower_third_name"] == "MindShift Daily"
    assert settings["download_lower_third_tagline"] == "daily ideas"
    assert settings["download_lower_third_subscribe"] is False
    assert settings["download_lower_third_bg_color"] == "#F5F0E8"
    assert settings["download_lower_third_accent_color"] == "#123ABC"
    assert settings["download_lower_third_interval"] == 30
    assert settings["download_lower_third_display_duration"] == 30
    assert settings["download_preset"] == "custom"


def test_load_gui_settings_migrates_legacy_corner_logo_position(tmp_path) -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.gui_settings_path = tmp_path / "gui_settings.json"
    app.gui_settings_path.write_text(
        json.dumps(
            {
                "version": 2,
                "download_logo_position": "bottom-right",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    settings = app._load_gui_settings()

    assert settings["version"] == 7
    assert settings["download_logo_position"] == "top-right"
    assert settings["download_logo_width_ratio"] == pytest.approx(0.12)
    assert settings["download_logo_x_ratio"] == pytest.approx(0.95)
    assert settings["download_logo_y_ratio"] == pytest.approx(0.05)


def test_current_download_logo_path_ignores_placeholder_value() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.download_logo_var = _DummyVar()
    app.download_logo_var.set(gui.DOWNLOAD_LOGO_PLACEHOLDER)

    assert app._current_download_logo_path() == ""


def test_save_gui_settings_writes_download_preferences(tmp_path) -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.gui_settings_path = tmp_path / "gui_settings.json"
    app.download_aspect_ratio_lookup = {
        "Normal 16:9": "landscape",
        "Short 9:16": "shorts",
    }
    app.download_aspect_ratio_var = _DummyVar()
    app.download_aspect_ratio_var.set("Short 9:16")
    app.video_format_var = _DummyVar()
    app.video_format_var.set("webm")
    app.clip_duration_var = _DummyNumberVar(45)
    app.download_logo_enabled_var = _DummyNumberVar(False)
    app.download_logo_var = _DummyVar()
    app.download_logo_var.set("/tmp/logo.png")
    app.download_logo_position_lookup = {
        "Haut gauche": "top-left",
        "Haut centre": "top",
        "Haut droit": "top-right",
        "Centre gauche": "center-left",
        "Centre": "center",
        "Centre droit": "center-right",
        "Bas gauche": "bottom-left",
        "Bas centre": "bottom",
        "Bas droit": "bottom-right",
    }
    app.download_logo_position_var = _DummyVar()
    app.download_logo_position_var.set("Centre")
    app.download_logo_size_mode_lookup = {
        "Taille relative": "relative",
        "Taille originale (max 30%)": "original",
    }
    app.download_logo_size_mode_var = _DummyVar()
    app.download_logo_size_mode_var.set("Taille relative")
    app.download_logo_size_var = _DummyNumberVar(63)
    app.download_logo_opacity_var = _DummyNumberVar(82)
    app.download_subtitles_enabled_var = _DummyNumberVar(True)
    app.download_subtitle_style_lookup = {
        "Impact TikTok": "impact",
        "Moderne blanc": "modern",
    }
    app.download_subtitle_style_var = _DummyVar()
    app.download_subtitle_style_var.set("Moderne blanc")
    app.download_video_effect_lookup = {
        "Aucun": "none",
        "Noir et blanc": "black_white",
    }
    app.download_video_effect_var = _DummyVar()
    app.download_video_effect_var.set("Noir et blanc")
    app.download_intro_outro_enabled_var = _DummyNumberVar(True)
    app.download_progress_bar_enabled_var = _DummyNumberVar(True)
    app.download_animated_watermark_enabled_var = _DummyNumberVar(False)
    app.download_lower_third_enabled_var = _DummyNumberVar(True)
    app.download_lower_third_name_var = _DummyVar()
    app.download_lower_third_name_var.set("MindShift Daily")
    app.download_lower_third_tagline_var = _DummyVar()
    app.download_lower_third_tagline_var.set("Idées claires")
    app.download_lower_third_subscribe_var = _DummyNumberVar(False)
    app.download_lower_third_bg_color_var = _DummyVar()
    app.download_lower_third_bg_color_var.set("#101820")
    app.download_lower_third_accent_color_var = _DummyVar()
    app.download_lower_third_accent_color_var.set("#E85D3A")
    app.download_lower_third_interval_var = _DummyNumberVar(24)
    app.download_lower_third_display_duration_var = _DummyNumberVar(5)
    app.download_preset_lookup = {
        "Personnalisé": "custom",
        "TikTok Viral": "tiktok_viral",
    }
    app.download_preset_var = _DummyVar()
    app.download_preset_var.set("TikTok Viral")

    app._save_gui_settings()

    payload = json.loads(app.gui_settings_path.read_text(encoding="utf-8"))
    assert payload == {
        "version": 7,
        "download_aspect_mode": "shorts",
        "video_format": "webm",
        "clip_duration": 45,
        "download_logo_enabled": False,
        "download_logo_path": "/tmp/logo.png",
        "download_logo_position": "center",
        "download_logo_size_mode": "relative",
        "download_logo_scale_percent": 63,
        "download_logo_opacity_percent": 82,
        "download_logo_duration": 0,
        "download_logo_width_ratio": 0.186,
        "download_logo_x_ratio": 0.5,
        "download_logo_y_ratio": 0.46,
        "download_subtitles_enabled": True,
        "download_subtitle_style": "modern",
        "download_video_effect": "black_white",
        "download_intro_outro_enabled": True,
        "download_progress_bar_enabled": True,
        "download_animated_watermark_enabled": False,
        "download_lower_third_enabled": True,
        "download_lower_third_name": "MindShift Daily",
        "download_lower_third_tagline": "Idées claires",
        "download_lower_third_subscribe": False,
        "download_lower_third_bg_color": "#101820",
        "download_lower_third_accent_color": "#E85D3A",
        "download_lower_third_interval": 24,
        "download_lower_third_display_duration": 5,
        "download_preset": "tiktok_viral",
    }


def test_apply_gui_settings_sets_download_preferences() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.download_aspect_ratio_lookup = {
        "Normal 16:9": "landscape",
        "Short 9:16": "shorts",
    }
    app.download_aspect_ratio_var = _DummyVar()
    app.video_format_var = _DummyVar()
    app.clip_duration_var = _DummyNumberVar(60)
    app.download_logo_enabled_var = _DummyNumberVar(True)
    app.download_logo_var = _DummyVar()
    app.download_logo_position_lookup = {
        "Haut gauche": "top-left",
        "Haut centre": "top",
        "Haut droit": "top-right",
        "Centre gauche": "center-left",
        "Centre": "center",
        "Centre droit": "center-right",
        "Bas gauche": "bottom-left",
        "Bas centre": "bottom",
        "Bas droit": "bottom-right",
    }
    app.download_logo_position_var = _DummyVar()
    app.download_logo_size_mode_lookup = {
        "Taille relative": "relative",
        "Taille originale (max 30%)": "original",
    }
    app.download_logo_size_mode_var = _DummyVar()
    app.download_logo_size_var = _DummyNumberVar(58)
    app.download_logo_size_label_var = _DummyVar()
    app.download_logo_opacity_var = _DummyNumberVar(100)
    app.download_logo_opacity_label_var = _DummyVar()
    app.download_subtitles_enabled_var = _DummyNumberVar(True)
    app.download_subtitle_style_lookup = {
        "Impact TikTok": "impact",
        "Moderne blanc": "modern",
    }
    app.download_subtitle_style_var = _DummyVar()
    app.download_video_effect_lookup = {
        "Aucun": "none",
        "Noir et blanc": "black_white",
    }
    app.download_video_effect_var = _DummyVar()
    app.download_intro_outro_enabled_var = _DummyNumberVar(False)
    app.download_progress_bar_enabled_var = _DummyNumberVar(False)
    app.download_animated_watermark_enabled_var = _DummyNumberVar(False)
    app.download_lower_third_interval_var = _DummyNumberVar(20)
    app.download_lower_third_interval_label_var = _DummyVar()
    app.download_lower_third_display_duration_var = _DummyNumberVar(4)
    app.download_lower_third_display_duration_label_var = _DummyVar()
    app.download_preset_lookup = {
        "Personnalisé": "custom",
        "TikTok Viral": "tiktok_viral",
    }
    app.download_preset_var = _DummyVar()
    app.busy = False

    app._apply_gui_settings(
        {
            "download_aspect_mode": "shorts",
            "video_format": "webm",
            "clip_duration": 70,
            "download_logo_enabled": False,
            "download_logo_path": "/tmp/logo.png",
            "download_logo_position": "top-right",
            "download_logo_size_mode": "relative",
            "download_logo_scale_percent": 44,
            "download_logo_opacity_percent": 77,
            "download_subtitles_enabled": False,
            "download_subtitle_style": "modern",
            "download_video_effect": "black_white",
            "download_intro_outro_enabled": True,
            "download_progress_bar_enabled": True,
            "download_animated_watermark_enabled": False,
            "download_lower_third_interval": 18,
            "download_lower_third_display_duration": 5,
            "download_preset": "tiktok_viral",
        }
    )
    assert app.download_aspect_ratio_var.get() == "Short 9:16"
    assert app.video_format_var.get() == "webm"
    assert app.clip_duration_var.get() == 70
    assert app.download_logo_enabled_var.get() is False
    assert app.download_logo_var.get() == "/tmp/logo.png"
    assert app.download_logo_position_var.get() == "Haut droit"
    assert app.download_logo_size_mode_var.get() == "Taille relative"
    assert app.download_logo_size_var.get() == 44
    assert app.download_logo_size_label_var.value == "44% · 15% vidéo"
    assert app.download_logo_opacity_var.get() == 77
    assert app.download_logo_opacity_label_var.value == "77%"
    assert app.download_subtitles_enabled_var.get() is False
    assert app.download_subtitle_style_var.get() == "Moderne blanc"
    assert app.download_video_effect_var.get() == "Noir et blanc"
    assert app.download_intro_outro_enabled_var.get() is True
    assert app.download_progress_bar_enabled_var.get() is True
    assert app.download_animated_watermark_enabled_var.get() is False
    assert app.download_lower_third_interval_var.get() == 18
    assert app.download_lower_third_interval_label_var.value == "18s"
    assert app.download_lower_third_display_duration_var.get() == 5
    assert app.download_lower_third_display_duration_label_var.value == "5s"
    assert app.download_preset_var.get() == "TikTok Viral"

    app._apply_gui_settings({"download_aspect_mode": "invalid", "video_format": "avi"})
    assert app.download_aspect_ratio_var.get() == "Normal 16:9"
    assert app.video_format_var.get() == "mp4"
    assert app.download_logo_size_mode_var.get() == "Taille relative"


def test_get_download_logo_scale_percent_clamps_values() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.download_logo_size_var = _DummyNumberVar(5)
    assert app._get_download_logo_scale_percent() == 20

    app.download_logo_size_var = _DummyNumberVar(95)
    assert app._get_download_logo_scale_percent() == 80

    app.download_logo_size_var = _DummyNumberVar(47)
    assert app._get_download_logo_scale_percent() == 47


def test_selected_download_logo_size_mode_maps_ui_labels() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.download_logo_size_mode_lookup = {
        "Taille relative": "relative",
        "Taille originale (max 30%)": "original",
    }
    app.download_logo_size_mode_var = _DummyVar()

    app.download_logo_size_mode_var.set("Taille originale (max 30%)")
    assert app._selected_download_logo_size_mode() == "original"

    app.download_logo_size_mode_var.set("Taille relative")
    assert app._selected_download_logo_size_mode() == "relative"

    app.download_logo_size_mode_var.set("Inconnu")
    assert app._selected_download_logo_size_mode() == "relative"


def test_on_logo_size_change_updates_label_and_value() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.download_logo_size_var = _DummyNumberVar(58)
    app.download_logo_size_label_var = _DummyVar()

    app._on_logo_size_change("73.2")
    assert app.download_logo_size_var.get() == 73
    assert app.download_logo_size_label_var.value == "73% · 21% vidéo"


def test_build_download_variant_caps_original_logo_size(monkeypatch, tmp_path) -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app._resolve_system_tool = lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None  # type: ignore[attr-defined]
    input_path = tmp_path / "clip.mp4"
    logo_path = tmp_path / "logo.png"
    input_path.write_text("video", encoding="utf-8")
    _write_logo(logo_path)
    commands: list[list[str]] = []

    def _capture_run(cmd, **_kwargs):
        commands.append(cmd)

    monkeypatch.setattr(gui.subprocess, "run", _capture_run)

    output_path = app._build_download_variant(
        input_path,
        to_shorts=False,
        logo_path=str(logo_path),
        logo_size_mode="original",
        logo_scale_percent=80,
    )

    assert output_path.name == "clip_logo.mp4"
    filter_complex = commands[0][commands[0].index("-filter_complex") + 1]
    assert "scale2ref" not in filter_complex
    assert "scale=576:-1" in filter_complex
    assert "overlay=1248:54" in filter_complex
    assert "[with_shadow][logo_fg]overlay" in filter_complex


def test_build_download_variant_scales_logo_from_video_frame(monkeypatch, tmp_path) -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app._resolve_system_tool = lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None  # type: ignore[attr-defined]
    input_path = tmp_path / "clip.mp4"
    logo_path = tmp_path / "logo.png"
    input_path.write_text("video", encoding="utf-8")
    _write_logo(logo_path)
    commands: list[list[str]] = []

    def _capture_run(cmd, **_kwargs):
        commands.append(cmd)

    monkeypatch.setattr(gui.subprocess, "run", _capture_run)

    app._build_download_variant(
        input_path,
        to_shorts=False,
        logo_path=str(logo_path),
        logo_size_mode="relative",
        logo_scale_percent=20,
    )

    filter_complex = commands[0][commands[0].index("-filter_complex") + 1]
    assert "scale=192:-1" in filter_complex
    assert "overlay=1632:54" in filter_complex
    assert "[with_shadow][logo_fg]overlay" in filter_complex


def test_build_download_variant_preserves_source_resolution(
    monkeypatch,
    tmp_path,
) -> None:
    # Forced upscale is disabled (MIN_FULL_HD_SHORT_EDGE=0): video keeps its
    # original resolution instead of being stretched to 1920x1080.
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app._resolve_system_tool = lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None  # type: ignore[attr-defined]
    input_path = tmp_path / "clip.mp4"
    logo_path = tmp_path / "logo.png"
    input_path.write_text("video", encoding="utf-8")
    _write_logo(logo_path)
    commands: list[list[str]] = []

    def _capture_run(cmd, **_kwargs):
        commands.append(cmd)

    def _fake_probe(cmd, **_kwargs):
        return gui.subprocess.CompletedProcess(
            cmd,
            0,
            stdout='{"streams":[{"width":1280,"height":720}]}',
        )

    monkeypatch.setattr(gui.subprocess, "run", _capture_run)
    monkeypatch.setattr(gui.video_renderer, "_ffprobe_path", lambda _path: "/usr/bin/ffprobe")
    monkeypatch.setattr(gui.video_renderer, "_SUBPROCESS_RUN", _fake_probe)

    app._build_download_variant(
        input_path,
        to_shorts=False,
        logo_path=str(logo_path),
        logo_width_ratio=0.12,
        logo_x_ratio=0.95,
        logo_y_ratio=0.05,
    )

    filter_complex = commands[0][commands[0].index("-filter_complex") + 1]
    # No forced upscale to 1920x1080 — source resolution (1280x720) is kept
    assert "scale=1920:1080" not in filter_complex
    assert "unsharp=5:5:0.45:5:5:0.0" in filter_complex
    # Logo scaled for 1280px-wide frame: int(1280 * 0.12) = 153px
    assert "scale=153:-1" in filter_complex
    assert filter_complex.index("unsharp=") < filter_complex.index("[logo_fg]")


def test_build_download_variant_does_not_upscale_full_hd_source(
    monkeypatch,
    tmp_path,
) -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app._resolve_system_tool = lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None  # type: ignore[attr-defined]
    input_path = tmp_path / "clip.mp4"
    input_path.write_text("video", encoding="utf-8")
    commands: list[list[str]] = []

    def _capture_run(cmd, **_kwargs):
        commands.append(cmd)

    def _fake_probe(cmd, **_kwargs):
        return gui.subprocess.CompletedProcess(
            cmd,
            0,
            stdout='{"streams":[{"width":1920,"height":1080}]}',
        )

    monkeypatch.setattr(gui.subprocess, "run", _capture_run)
    monkeypatch.setattr(gui.video_renderer, "_ffprobe_path", lambda _path: "/usr/bin/ffprobe")
    monkeypatch.setattr(gui.video_renderer, "_SUBPROCESS_RUN", _fake_probe)

    app._build_download_variant(
        input_path,
        to_shorts=False,
        logo_path="",
        video_effect="black_white",
    )

    filter_complex = commands[0][commands[0].index("-filter_complex") + 1]
    assert "scale=1920:1080" not in filter_complex
    assert "unsharp=5:5:0.45:5:5:0.0" in filter_complex


def test_build_download_variant_boosts_logo_for_portrait_output(
    monkeypatch,
    tmp_path,
) -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app._resolve_system_tool = lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None  # type: ignore[attr-defined]
    input_path = tmp_path / "clip.mp4"
    logo_path = tmp_path / "logo.png"
    input_path.write_text("video", encoding="utf-8")
    _write_logo(logo_path)
    commands: list[list[str]] = []

    def _capture_run(cmd, **_kwargs):
        commands.append(cmd)

    def _fake_probe(cmd, **_kwargs):
        return gui.subprocess.CompletedProcess(
            cmd,
            0,
            stdout='{"streams":[{"width":1080,"height":1920}]}',
        )

    monkeypatch.setattr(gui.subprocess, "run", _capture_run)
    monkeypatch.setattr(gui.video_renderer, "_ffprobe_path", lambda _path: "/usr/bin/ffprobe")
    monkeypatch.setattr(gui.video_renderer, "_SUBPROCESS_RUN", _fake_probe)

    app._build_download_variant(
        input_path,
        to_shorts=False,
        logo_path=str(logo_path),
        logo_position="bottom",
        logo_width_ratio=0.12,
        logo_x_ratio=0.56,
        logo_y_ratio=0.87,
    )

    filter_complex = commands[0][commands[0].index("-filter_complex") + 1]
    assert "scale=259:-1" in filter_complex
    assert "overlay=604:1670" in filter_complex


def test_build_download_variant_adds_subtitles_and_effect(monkeypatch, tmp_path) -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app._resolve_system_tool = lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None  # type: ignore[attr-defined]
    input_path = tmp_path / "clip.mp4"
    input_path.write_text("video", encoding="utf-8")
    commands: list[list[str]] = []

    def _capture_run(cmd, **_kwargs):
        commands.append(cmd)

    monkeypatch.setattr(gui.subprocess, "run", _capture_run)

    output_path = app._build_download_variant(
        input_path,
        to_shorts=False,
        logo_path="",
        subtitle_chunks=[
            {"text": "Texte sous-titré", "start": 62.0, "duration": 3.0},
        ],
        subtitle_start=60.0,
        subtitle_duration=30.0,
        subtitle_style="box",
        video_effect="black_white",
    )

    assert output_path.name == "clip_subs-box_bw.mp4"
    filter_complex = commands[0][commands[0].index("-filter_complex") + 1]
    assert "hue=s=0" in filter_complex
    assert "subtitles=filename=" in filter_complex
    marker = "subtitles=filename='"
    subtitle_path_start = filter_complex.index(marker) + len(marker)
    subtitle_path_end = filter_complex.index("'", subtitle_path_start)
    assert not Path(filter_complex[subtitle_path_start:subtitle_path_end]).exists()


def test_build_download_variant_preview_uses_high_quality_scale(monkeypatch, tmp_path) -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app._resolve_system_tool = lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None  # type: ignore[attr-defined]
    input_path = tmp_path / "clip.mp4"
    input_path.write_text("video", encoding="utf-8")
    commands: list[list[str]] = []

    def _capture_run(cmd, **_kwargs):
        commands.append(cmd)

    monkeypatch.setattr(gui.subprocess, "run", _capture_run)

    app._build_download_variant(
        input_path,
        to_shorts=False,
        logo_path="",
        video_effect="black_white",
        preview_width=1080,
    )

    filter_complex = commands[0][commands[0].index("-filter_complex") + 1]
    assert "hue=s=0" in filter_complex
    assert (
        "scale=1080:-2:flags=lanczos+accurate_rnd+full_chroma_int"
        in filter_complex
    )
    assert "unsharp=5:5:0.45:5:5:0.0" in filter_complex
    assert commands[0][commands[0].index("-preset") + 1] == "slow"
    assert commands[0][commands[0].index("-crf") + 1] == "14"
    assert commands[0][commands[0].index("-b:a") + 1] == "256k"


def test_build_download_variant_adds_lower_third(monkeypatch, tmp_path) -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app._resolve_system_tool = lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None  # type: ignore[attr-defined]
    input_path = tmp_path / "clip.mp4"
    input_path.write_text("video", encoding="utf-8")
    commands: list[list[str]] = []

    def _capture_run(cmd, **_kwargs):
        commands.append(cmd)

    monkeypatch.setattr(gui.subprocess, "run", _capture_run)

    output_path = app._build_download_variant(
        input_path,
        to_shorts=False,
        logo_path="",
        lower_third_config=gui.lower_third.config_from_hex(
            channel_name="MindShift Daily",
            tagline="Daily ideas",
            bg_color="#101820",
            accent_color="#E85D3A",
        ),
    )

    assert output_path.name == "clip_lower-third.mp4"
    cmd = commands[0]
    filter_complex = cmd[cmd.index("-filter_complex") + 1]
    assert "format=rgba[lowerthird]" in filter_complex
    assert (
        "overlay=x='if(lt(mod(t,20),4),if(lt(mod(t,20),0.4),"
        "-W+mod(t,20)*(W/0.4),if(gt(mod(t,20),3.6),"
        "-(mod(t,20)-3.6)*(W/0.4),0)),-W)':y=H-h:format=auto"
        "[withlowerthird]"
    ) in filter_complex
    assert not Path(cmd[5]).exists()


def test_build_download_variant_uses_custom_periodic_lower_third_timing(
    monkeypatch,
    tmp_path,
) -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app._resolve_system_tool = lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None  # type: ignore[attr-defined]
    input_path = tmp_path / "clip.mp4"
    input_path.write_text("video", encoding="utf-8")
    commands: list[list[str]] = []

    def _capture_run(cmd, **_kwargs):
        commands.append(cmd)

    monkeypatch.setattr(gui.subprocess, "run", _capture_run)

    app._build_download_variant(
        input_path,
        to_shorts=False,
        logo_path="",
        lower_third_config=gui.lower_third.config_from_hex(
            channel_name="MindShift Daily",
            tagline="Daily ideas",
            bg_color="#101820",
            accent_color="#E85D3A",
        ),
        clip_duration=8.0,
        lower_third_interval=12,
        lower_third_display_duration=5,
    )

    filter_complex = commands[0][commands[0].index("-filter_complex") + 1]
    assert (
        "overlay=x='if(lt(mod(t,12),5),if(lt(mod(t,12),0.4),"
        "-W+mod(t,12)*(W/0.4),if(gt(mod(t,12),4.6),"
        "-(mod(t,12)-4.6)*(W/0.4),0)),-W)'"
        ":y=H-h:format=auto[withlowerthird]"
    ) in filter_complex


def test_build_download_variant_adds_intro_progress_and_watermark(
    monkeypatch,
    tmp_path,
) -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app._resolve_system_tool = lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None  # type: ignore[attr-defined]
    input_path = tmp_path / "clip.mp4"
    input_path.write_text("video", encoding="utf-8")
    logo_path = tmp_path / "logo.png"
    logo_path.write_text("logo", encoding="utf-8")
    commands: list[list[str]] = []

    def _capture_run(cmd, **_kwargs):
        commands.append(cmd)

    monkeypatch.setattr(gui.subprocess, "run", _capture_run)

    output_path = app._build_download_variant(
        input_path,
        to_shorts=False,
        logo_path="",
        clip_duration=8.0,
        intro_outro_enabled=True,
        intro_outro_channel_name="MindShift Daily",
        progress_bar_enabled=True,
        animated_watermark_enabled=True,
        watermark_logo_path=str(logo_path),
    )

    assert output_path.name == "clip_intro-outro_progress_watermark.mp4"
    cmd = commands[0]
    assert str(logo_path) in cmd
    filter_complex = cmd[cmd.index("-filter_complex") + 1]
    assert "fade=t=in:st=0:d=0.5" in filter_complex
    assert "fade=t=out:st=7.5:d=0.5" in filter_complex
    assert "drawtext=text='MindShift Daily'" in filter_complex
    assert "color=c=0xE85D3A@1.0:s=1920x8:d=9.0000[progressbar]" in filter_complex
    assert (
        "[progressbar]overlay=x='max(-w,min(0,-w+w*t/8.0000))':"
        "y=H-h:format=auto:eval=frame[progress]"
    ) in filter_complex
    assert (
        "scale=230:-1:flags=lanczos+accurate_rnd+full_chroma_int"
        in filter_complex
    )
    assert (
        "geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
        "a='alpha(X,Y)*(0.50+0.25*sin(T*1.0))'"
    ) in filter_complex
    assert "[watermark]overlay=1594:54:format=auto" in filter_complex


def test_lower_third_png_keeps_transparent_canvas(tmp_path) -> None:
    output = tmp_path / "lower.png"
    config = gui.lower_third.config_from_hex(
        channel_name="MindShift Daily",
        tagline="Daily ideas",
        bg_color="#101820",
        accent_color="#E85D3A",
    )

    result = gui.lower_third.generate_lower_third(config, 640, 360, str(output))

    assert result == str(output)
    image = Image.open(output).convert("RGBA")
    assert image.size == (640, 360)
    assert image.getpixel((10, 10))[3] == 0
    assert image.getpixel((10, 350))[3] > 0


def test_subtitle_renderer_clips_entries_to_window() -> None:
    entries = gui.subtitle_renderer.build_subtitle_entries(
        [
            {"text": "Avant", "start": 10.0, "duration": 2.0},
            {"text": "Dans le clip", "start": 62.0, "duration": 4.0},
        ],
        clip_start=60.0,
        clip_duration=20.0,
    )

    assert entries == [{"start": 2.0, "end": 5.0, "text": "Dans le clip"}]


def test_subtitle_renderer_merges_overlapping_entries() -> None:
    entries = gui.subtitle_renderer.build_subtitle_entries(
        [
            {"text": "Premier", "start": 10.0, "duration": 2.0},
            {"text": "Deuxieme", "start": 11.0, "duration": 1.0},
            {"text": "Troisieme", "start": 14.0, "duration": 1.0},
        ],
        clip_start=10.0,
        clip_duration=10.0,
    )

    assert entries == [
        {"start": 0.0, "end": 2.0, "text": "Premier Deuxieme"},
        {"start": 4.0, "end": 5.0, "text": "Troisieme"},
    ]


def test_subtitle_renderer_does_not_merge_into_full_screen_block() -> None:
    chunks = gui.subtitle_renderer.rechunk_blocks(
        [
            {"text": "un deux", "start": 0.0, "duration": 1.0},
            {"text": "trois quatre", "start": 1.0, "duration": 1.0},
            {"text": "cinq six", "start": 2.0, "duration": 1.0},
            {"text": "sept huit", "start": 3.0, "duration": 1.0},
        ],
        "9:16",
        clip_start=0.0,
        clip_duration=10.0,
    )

    assert chunks == [
        {"text": "un deux trois quatre", "start": 0.0, "duration": 2.0},
        {"text": "cinq six sept huit", "start": 2.0, "duration": 2.0},
    ]


def test_subtitle_renderer_applies_minimum_duration() -> None:
    entries = gui.subtitle_renderer.build_subtitle_entries(
        [
            {"text": "Zero duration", "start": 10.0, "duration": 0.0},
            {"text": "Very short", "start": 12.0, "duration": 0.1},
        ],
        clip_start=10.0,
        clip_duration=10.0,
    )

    assert entries == [{"start": 2.0, "end": 2.5, "text": "Very short"}]


def test_subtitle_renderer_skips_empty_and_invalid_entries() -> None:
    entries = gui.subtitle_renderer.build_subtitle_entries(
        [
            {"text": "   \n  ", "start": 10.0, "duration": 1.0},
            {"text": "Invalid timing", "start": "bad", "duration": 1.0},
            {"text": "Valid", "start": 11.0, "duration": 1.0},
        ],
        clip_start=10.0,
        clip_duration=10.0,
    )

    assert entries == [{"start": 1.0, "end": 2.0, "text": "Valid"}]


def test_subtitle_renderer_rechunks_long_blocks_for_shorts() -> None:
    chunks = gui.subtitle_renderer.rechunk_blocks(
        [
            {
                "text": "Un deux trois quatre cinq six sept huit neuf dix",
                "start": 60.0,
                "duration": 10.0,
            },
        ],
        "9:16",
        clip_start=60.0,
        clip_duration=30.0,
    )

    assert chunks == [
        {"text": "Un deux trois quatre cinq", "start": 0.0, "duration": 3.0},
        {"text": "six sept huit neuf dix", "start": 5.0, "duration": 3.0},
    ]


def test_subtitle_renderer_builds_dynamic_ass_resolution() -> None:
    document = gui.subtitle_renderer.build_ass_file(
        [{"text": "Bonjour\nKinshasa", "start": 1.0, "duration": 2.0}],
        "impact",
        640,
        360,
        "16:9",
    )

    assert "PlayResX: 640" in document
    assert "PlayResY: 360" in document
    assert "Style: Default,Arial Black,17" in document
    assert "Dialogue: 0,0:00:01.00,0:00:03.00" in document
    assert r"Bonjour\NKinshasa" in document


def test_temporary_ass_file_deletes_file_after_context() -> None:
    with gui.subtitle_renderer.temporary_ass_file("content") as ass_path:
        path = Path(ass_path)
        assert path.exists()

    assert not path.exists()


def test_generate_subtitle_preview_uses_active_chunk(tmp_path) -> None:
    frame = tmp_path / "frame.jpg"
    output = tmp_path / "preview.jpg"
    Image.new("RGB", (320, 180), (20, 20, 20)).save(frame)

    result = gui.subtitle_renderer.generate_subtitle_preview(
        str(frame),
        [{"text": "Preview", "start": 1.0, "duration": 2.0}],
        1.5,
        "modern",
        320,
        180,
        "16:9",
        output_path=str(output),
    )

    assert result == str(output)
    assert output.exists()


def test_get_download_logo_opacity_percent_clamps_values() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.download_logo_opacity_var = _DummyNumberVar(3)
    assert app._get_download_logo_opacity_percent() == 10

    app.download_logo_opacity_var = _DummyNumberVar(140)
    assert app._get_download_logo_opacity_percent() == 100

    app.download_logo_opacity_var = _DummyNumberVar(64)
    assert app._get_download_logo_opacity_percent() == 64


def test_on_logo_opacity_change_updates_label_and_value() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.download_logo_opacity_var = _DummyNumberVar(100)
    app.download_logo_opacity_label_var = _DummyVar()

    app._on_logo_opacity_change("46.8")
    assert app.download_logo_opacity_var.get() == 47
    assert app.download_logo_opacity_label_var.value == "47%"


def test_logo_opacity_ratio_clamps_and_defaults() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    assert app._logo_opacity_ratio(5) == pytest.approx(0.10)
    assert app._logo_opacity_ratio(55) == pytest.approx(0.55)
    assert app._logo_opacity_ratio(180) == pytest.approx(1.0)
    assert app._logo_opacity_ratio("invalid") == pytest.approx(1.0)


def test_update_download_progress_uses_global_percentage() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.download_total = 4
    app.download_completed = 1
    app.download_overall_progress = _DummyProgress()
    app.download_current_progress = _DummyProgress()
    app.download_detail_var = _DummyVar()

    app._update_download_progress(50.0, "", "", "")

    assert app.download_current_progress.options["value"] == 50.0
    assert app.download_overall_progress.options["value"] == pytest.approx(37.5)
    assert "Global 37.5%" in app.download_detail_var.value


def test_format_download_size_progress_estimates_downloaded_bytes() -> None:
    result = gui.TranscriptApp._format_download_size_progress(25.0, "20.0MiB")
    assert result == "5.0 MiB / 20.0 MiB"


def test_log_download_percent_steps_logs_each_integer_percent() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.download_last_percent_logged = -1
    app.download_last_size = ""
    lines: list[str] = []
    app._append_download_log = lambda line: lines.append(line)  # type: ignore[attr-defined]

    app._log_download_percent_steps(2.7, "10.0MiB", "2.0MiB/s", "00:05")
    app._log_download_percent_steps(4.1, "10.0MiB", "", "")

    assert lines[0].startswith("[progress] 0%")
    assert lines[1].startswith("[progress] 1%")
    assert lines[2].startswith("[progress] 2%")
    assert any(line.startswith("[progress] 3%") for line in lines)
    assert any(line.startswith("[progress] 4%") for line in lines)
    assert sum(1 for line in lines if line.startswith("[progress] 2%")) == 1


def test_enqueue_downloads_updates_total_when_queue_is_active() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.download_queue = [{"url": "existing"}]
    app.download_active = True
    app.download_completed = 1
    app.download_total = 3
    app.download_overall_progress = _DummyProgress()
    app.master = _ImmediateMaster()
    app._append_download_log = lambda _line: None  # type: ignore[attr-defined]
    app._build_moment_filename_label = lambda _moment: "clip"  # type: ignore[attr-defined]

    moment = _DummyMoment(minute_index=2, excerpt="x")
    app._enqueue_downloads(
        [moment],
        "https://youtu.be/demo",
        "/tmp",
        60,
        "mp4",
        ["yt-dlp"],
        shorts_mode=False,
        logo_enabled=False,
        logo_path="",
        logo_position="center",
        logo_size_mode="original",
        logo_scale_percent=58,
        logo_opacity_percent=100,
    )

    assert app.download_total == 4


def test_enqueue_downloads_snapshots_subtitle_chunks() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.download_queue = []
    app.download_active = True
    app.download_completed = 0
    app.download_total = 0
    app.download_overall_progress = _DummyProgress()
    app.master = _ImmediateMaster()
    app.video_title_cache = {}
    app.last_url = "https://youtu.be/demo"
    app.last_transcript_chunks = [
        {"text": "Original", "start": 60.0, "duration": 2.0},
    ]
    app._append_download_log = lambda _line: None  # type: ignore[attr-defined]
    app._build_moment_filename_label = lambda _moment: "clip"  # type: ignore[attr-defined]

    app._enqueue_downloads(
        [_DummyMoment(minute_index=1, excerpt="x")],
        "https://youtu.be/demo",
        "/tmp",
        60,
        "mp4",
        ["yt-dlp"],
        shorts_mode=False,
        logo_enabled=False,
        logo_path="",
        logo_position="center",
        logo_size_mode="relative",
        logo_scale_percent=58,
        logo_opacity_percent=100,
        subtitles_enabled=True,
    )

    app.last_transcript_chunks[0]["text"] = "Modifie"

    assert app.download_queue[-1]["subtitle_chunks"] == [
        {"text": "Original", "start": 60.0, "duration": 2.0},
    ]


def test_enqueue_downloads_rejects_stale_subtitle_url() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.download_queue = []
    app.download_active = True
    app.download_completed = 0
    app.download_total = 0
    app.download_overall_progress = _DummyProgress()
    app.master = _ImmediateMaster()
    app.video_title_cache = {}
    app.last_url = "https://youtu.be/old"
    app.last_transcript_chunks = [
        {"text": "Ancienne video", "start": 60.0, "duration": 2.0},
    ]
    app._append_download_log = lambda _line: None  # type: ignore[attr-defined]
    app._build_moment_filename_label = lambda _moment: "clip"  # type: ignore[attr-defined]

    app._enqueue_downloads(
        [_DummyMoment(minute_index=1, excerpt="x")],
        "https://youtu.be/new",
        "/tmp",
        60,
        "mp4",
        ["yt-dlp"],
        shorts_mode=False,
        logo_enabled=False,
        logo_path="",
        logo_position="center",
        logo_size_mode="relative",
        logo_scale_percent=58,
        logo_opacity_percent=100,
        subtitles_enabled=True,
    )

    assert app.download_queue[-1]["subtitles_enabled"] is False
    assert app.download_queue[-1]["subtitle_chunks"] == []


def test_record_download_history_groups_entries_by_same_link(tmp_path) -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.master = _ImmediateMaster()
    app.download_history_lock = threading.Lock()
    app.download_history_path = tmp_path / "download_history.json"
    app.download_history = {"version": 1, "links": {}}
    app.video_title_cache = {}
    app._refresh_download_history_view = lambda: None  # type: ignore[attr-defined]

    item = {
        "url": "https://youtu.be/dQw4w9WgXcQ",
        "start": 60,
        "duration": 30,
        "format": "mp4",
        "shorts": True,
        "logo_enabled": False,
        "logo_path": "",
        "video_title": "Titre test",
    }
    app._record_download_history(item, Path("/tmp/clip_1.mp4"))
    app._record_download_history(item, Path("/tmp/clip_2.mp4"))

    links = app.download_history["links"]
    assert len(links) == 1
    first_key = next(iter(links))
    assert first_key.startswith("video:")
    assert len(links[first_key]["downloads"]) == 2

    payload = json.loads(app.download_history_path.read_text(encoding="utf-8"))
    assert len(payload["links"]) == 1


def test_format_download_history_lines_includes_title_url_and_total() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.download_history_lock = threading.Lock()
    app.download_history = {
        "version": 1,
        "links": {
            "video:dQw4w9WgXcQ": {
                "url": "https://youtu.be/dQw4w9WgXcQ",
                "video_id": "dQw4w9WgXcQ",
                "title": "Ma vidéo",
                "first_downloaded_at": "2026-02-10T10:00:00+00:00",
                "last_downloaded_at": "2026-02-10T11:00:00+00:00",
                "downloads": [
                    {
                        "downloaded_at": "2026-02-10T11:00:00+00:00",
                        "output_file": "/tmp/clip_2.mp4",
                        "output_name": "clip_2.mp4",
                        "start_seconds": 120,
                        "end_seconds": 180,
                        "format": "mp4",
                        "shorts": True,
                        "logo": False,
                    },
                    {
                        "downloaded_at": "2026-02-10T10:00:00+00:00",
                        "output_file": "/tmp/clip_1.mp4",
                        "output_name": "clip_1.mp4",
                        "start_seconds": 60,
                        "end_seconds": 90,
                        "format": "mp4",
                        "shorts": False,
                        "logo": True,
                    },
                ],
            }
        },
    }

    lines = app._format_download_history_lines()
    assert any("Ma vidéo" in line for line in lines)
    assert any("URL: https://youtu.be/dQw4w9WgXcQ" in line for line in lines)
    assert any("Total: 2" in line for line in lines)


def test_format_download_history_lines_includes_full_video_and_audio_kinds() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.download_history_lock = threading.Lock()
    app.download_history = {
        "version": 1,
        "links": {
            "video:demo": {
                "url": "https://youtu.be/demo",
                "video_id": "demo",
                "title": "Démo",
                "first_downloaded_at": "2026-02-10T10:00:00+00:00",
                "last_downloaded_at": "2026-02-10T11:00:00+00:00",
                "downloads": [
                    {
                        "downloaded_at": "2026-02-10T11:00:00+00:00",
                        "output_file": "/tmp/demo_audio.mp3",
                        "output_name": "demo_audio.mp3",
                        "start_seconds": 0,
                        "end_seconds": 0,
                        "format": "mp3",
                        "kind": "audio",
                        "shorts": False,
                        "logo": False,
                    },
                    {
                        "downloaded_at": "2026-02-10T10:00:00+00:00",
                        "output_file": "/tmp/demo_full.mp4",
                        "output_name": "demo_full.mp4",
                        "start_seconds": 0,
                        "end_seconds": 0,
                        "format": "mp4",
                        "kind": "full_video",
                        "shorts": False,
                        "logo": False,
                    },
                ],
            }
        },
    }

    lines = app._format_download_history_lines()

    assert any("audio seul" in line for line in lines)
    assert any("vidéo entière" in line for line in lines)


def test_resolve_video_title_uses_cached_value() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.video_title_cache = {"https://youtu.be/dQw4w9WgXcQ": "Titre en cache"}

    title = app._resolve_video_title("https://youtu.be/dQw4w9WgXcQ", [])

    assert title == "Titre en cache"


def test_update_download_ui_sets_100_percent_when_complete() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.download_overall_progress = _DummyProgress()
    app.download_current_progress = _DummyProgress()
    app.download_detail_var = _DummyVar()
    app.download_summary_var = _DummyVar()

    app._update_download_ui(3, 3)

    assert app.download_overall_progress.options["value"] == pytest.approx(100.0)
    assert "100%" in app.download_summary_var.value


def test_selected_download_logo_position_maps_ui_labels() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.download_logo_position_lookup = {
        "Haut gauche": "top-left",
        "Haut centre": "top",
        "Haut droit": "top-right",
        "Centre gauche": "center-left",
        "Centre": "center",
        "Centre droit": "center-right",
        "Bas gauche": "bottom-left",
        "Bas centre": "bottom",
        "Bas droit": "bottom-right",
    }
    app.download_logo_position_var = _DummyVar()

    app.download_logo_position_var.set("Haut droit")
    assert app._selected_download_logo_position() == "top-right"

    app.download_logo_position_var.set("Centre gauche")
    assert app._selected_download_logo_position() == "center-left"

    app.download_logo_position_var.set("Inconnu")
    assert app._selected_download_logo_position() == "top-right"


def test_selected_download_aspect_mode_maps_ui_labels() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.download_aspect_ratio_lookup = {
        "Normal 16:9": "landscape",
        "Short 9:16": "shorts",
    }
    app.download_aspect_ratio_var = _DummyVar()

    app.download_aspect_ratio_var.set("Short 9:16")
    assert app._selected_download_aspect_mode() == "shorts"

    app.download_aspect_ratio_var.set("Normal 16:9")
    assert app._selected_download_aspect_mode() == "landscape"

    app.download_aspect_ratio_var.set("Inconnu")
    assert app._selected_download_aspect_mode() == "landscape"


def test_download_preset_applies_creative_options(tmp_path) -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.gui_settings_path = tmp_path / "gui_settings.json"
    app.download_preset_lookup = {
        "Personnalisé": "custom",
        "TikTok Viral": "tiktok_viral",
    }
    app.download_preset_var = _DummyVar()
    app.download_preset_var.set("TikTok Viral")
    app.download_aspect_ratio_lookup = {
        "Normal 16:9": "landscape",
        "Short 9:16": "shorts",
    }
    app.download_aspect_ratio_var = _DummyVar()
    app.video_format_var = _DummyVar()
    app.video_format_var.set("mp4")
    app.clip_duration_var = _DummyNumberVar(60)
    app.download_logo_enabled_var = _DummyNumberVar(False)
    app.download_logo_var = _DummyVar()
    app.download_logo_position_lookup = {
        "Haut gauche": "top-left",
        "Haut centre": "top",
        "Haut droit": "top-right",
        "Centre gauche": "center-left",
        "Centre": "center",
        "Centre droit": "center-right",
        "Bas gauche": "bottom-left",
        "Bas centre": "bottom",
        "Bas droit": "bottom-right",
    }
    app.download_logo_position_var = _DummyVar()
    app.download_logo_position_var.set("Centre")
    app.download_logo_size_mode_lookup = {
        "Taille relative": "relative",
        "Taille originale (max 30%)": "original",
    }
    app.download_logo_size_mode_var = _DummyVar()
    app.download_logo_size_mode_var.set("Taille relative")
    app.download_logo_size_var = _DummyNumberVar(58)
    app.download_logo_opacity_var = _DummyNumberVar(100)
    app.download_subtitles_enabled_var = _DummyNumberVar(False)
    app.download_subtitle_style_lookup = {
        "Impact TikTok": "impact",
        "Boîte noire": "box",
    }
    app.download_subtitle_style_var = _DummyVar()
    app.download_video_effect_lookup = {
        "Aucun": "none",
        "Contraste fort": "contrast",
    }
    app.download_video_effect_var = _DummyVar()

    app._on_download_preset_change()

    assert app.download_aspect_ratio_var.get() == "Short 9:16"
    assert app.download_subtitles_enabled_var.get() is True
    assert app.download_subtitle_style_var.get() == "Impact TikTok"
    assert app.download_video_effect_var.get() == "Contraste fort"
    assert app.clip_duration_var.get() == 45


def test_logo_overlay_expr() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    assert app._logo_overlay_x_expr("top-left", margin=30) == "30"
    assert app._logo_overlay_x_expr("center", margin=30) == "(W-w)/2"
    assert app._logo_overlay_x_expr("bottom-right", margin=30) == "W-w-30"
    assert app._logo_overlay_y_expr("top-left", margin=30) == "30"
    assert app._logo_overlay_y_expr("center-left", margin=30) == "(H-h)/2"
    assert app._logo_overlay_y_expr("bottom-right", margin=30) == "H-h-30"


def test_logo_preview_boosts_logo_for_shorts() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.download_aspect_ratio_lookup = {"Short 9:16": "shorts"}
    app.download_aspect_ratio_var = _DummyVar()
    app.download_aspect_ratio_var.set("Short 9:16")
    app.download_logo_position_lookup = {"Bas centre": "bottom"}
    app.download_logo_position_var = _DummyVar()
    app.download_logo_position_var.set("Bas centre")
    app.download_logo_width_ratio_var = _DummyNumberVar(0.12)
    app.download_logo_x_ratio_var = _DummyNumberVar(0.56)
    app.download_logo_y_ratio_var = _DummyNumberVar(0.87)

    assert app._logo_preview_bounds(158, 280) == (88, 243, 37, 13)


def test_build_moment_clip_text_uses_matching_transcript_chunks() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.last_transcript_chunks = [
        {"text": "Intro", "start": 5.0, "duration": 3.0},
        {"text": "Point A", "start": 62.0, "duration": 4.0},
        {"text": "Point B", "start": 80.0, "duration": 4.0},
        {"text": "Outro", "start": 140.0, "duration": 3.0},
    ]
    app._get_clip_duration = lambda: 30  # type: ignore[attr-defined]

    text = app._build_moment_clip_text(_DummyMoment(minute_index=1, excerpt="fallback"))

    assert text == "Point A\nPoint B"


def test_build_moment_clip_text_falls_back_to_excerpt() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.last_transcript_chunks = []
    app._get_clip_duration = lambda: 30  # type: ignore[attr-defined]

    text = app._build_moment_clip_text(
        _DummyMoment(minute_index=3, excerpt="Extrait de secours")
    )

    assert text == "Extrait de secours"


def test_sanitize_filename_text_removes_invalid_chars_and_limits_length() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    sanitized = app._sanitize_filename_text('  Salut / monde: "test"?  ')
    assert sanitized == "Salut monde test"

    too_long = "a" * 140
    truncated = app._sanitize_filename_text(too_long, max_length=50)
    assert len(truncated) == 50


def test_build_moment_filename_label_uses_clip_text() -> None:
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.last_transcript_chunks = [
        {"text": "Nom / extrait ??", "start": 60.0, "duration": 5.0},
    ]
    app._get_clip_duration = lambda: 30  # type: ignore[attr-defined]

    label = app._build_moment_filename_label(_DummyMoment(minute_index=1, excerpt="fallback"))

    assert label == "Nom extrait"
