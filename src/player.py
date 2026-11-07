"""Embed the installed VLC 3 video engine into a Win32 child window."""
import ctypes as c
import os
import threading
from pathlib import Path
from i18n import T


class _Track(c.Structure):
    pass


_Track._fields_ = [("id", c.c_int), ("name", c.c_char_p), ("next", c.POINTER(_Track))]


class Player:
    def __init__(self, hwnd):
        folder = Path(__file__).with_name("video")
        if not (folder / "libvlc.dll").is_file():
            raise ValueError(T("De ingebouwde videomotor ontbreekt."))
        self.dll_directory = os.add_dll_directory(str(folder))
        self.instance = self.player = None
        try:
            self.dll = c.CDLL(str(folder / "libvlc.dll"))
            p, i, ll, s = c.c_void_p, c.c_int, c.c_longlong, c.c_char_p
            for name, result, args in (
                ("new", p, [i, c.POINTER(s)]), ("release", None, [p]),
                ("media_new_location", p, [p, s]), ("media_release", None, [p]),
                ("media_player_new", p, [p]), ("media_player_release", None, [p]),
                ("media_player_set_media", None, [p, p]),
                ("media_player_set_hwnd", None, [p, p]),
                ("media_player_play", i, [p]), ("media_player_stop", None, [p]),
                ("media_player_pause", None, [p]), ("media_player_get_state", i, [p]),
                ("media_player_get_time", ll, [p]), ("media_player_get_length", ll, [p]),
                ("media_player_set_time", None, [p, ll]), ("audio_set_volume", i, [p, i]),
                ("media_player_is_seekable", i, [p]),
            ):
                fn = getattr(self.dll, "libvlc_" + name)
                fn.restype, fn.argtypes = result, args
                setattr(self, name, fn)
            self.extras = {}
            for name, result, args in (
                ("media_add_option", None, [p, s]),
                ("audio_get_track_description", c.POINTER(_Track), [p]),
                ("video_get_spu_description", c.POINTER(_Track), [p]),
                ("track_description_list_release", None, [c.POINTER(_Track)]),
                ("audio_get_track", i, [p]), ("audio_set_track", i, [p, i]),
                ("video_get_spu", i, [p]), ("video_set_spu", i, [p, i]),
                ("media_player_add_slave", i, [p, i, s, c.c_bool]),
                ("media_player_set_rate", i, [p, c.c_float]),
            ):
                try:
                    fn = getattr(self.dll, "libvlc_" + name)
                except AttributeError:
                    continue
                fn.restype, fn.argtypes = result, args
                self.extras[name] = fn
            arguments = (s * 2)(b"--no-video-title-show", b"--no-osd")
            self.instance = self.new(len(arguments), arguments)
            if not self.instance:
                raise ValueError(T("VLC kon zijn videomotor niet starten."))
            self.player = self.media_player_new(self.instance)
            if not self.player:
                raise ValueError(T("VLC kon de speler niet openen."))
            self.media_player_set_hwnd(self.player, hwnd)
            for name in ("libvlc_video_set_mouse_input", "libvlc_video_set_key_input"):
                try:
                    function = getattr(self.dll, name)
                    function.restype, function.argtypes = None, [p, c.c_uint]
                    function(self.player, 0)  # let Zono receive clicks and keys on the video
                except AttributeError:
                    pass
        except Exception:
            self.close()
            raise

    def open(self, url, options=()):
        media = self.media_new_location(self.instance, url.encode())
        if not media:
            raise ValueError(T("VLC kon de streamlink niet openen."))
        add = self.extras.get("media_add_option")
        if add:
            for option in options:
                add(media, option.encode())
        self.media_player_set_media(self.player, media)
        self.media_release(media)
        if self.media_player_play(self.player) != 0:
            raise ValueError(T("VLC kon het afspelen niet starten."))

    def set_window(self, hwnd):
        """Move the video to another window (used for picture-in-picture)."""
        if self.player:
            self.media_player_set_hwnd(self.player, hwnd)

    def tracks(self, kind):
        """List of (id, name) for "audio" or "subtitles"; empty when VLC does not know them yet."""
        getter = self.extras.get("audio_get_track_description" if kind == "audio" else "video_get_spu_description")
        release = self.extras.get("track_description_list_release")
        if not getter or not self.player:
            return []
        head = getter(self.player)
        result, node = [], head
        while node:
            track = node.contents
            result.append((track.id, (track.name or b"").decode("utf-8", "replace")))
            node = track.next
        if head and release:
            release(head)
        return result

    def current_track(self, kind):
        getter = self.extras.get("audio_get_track" if kind == "audio" else "video_get_spu")
        return getter(self.player) if getter and self.player else None

    def set_track(self, kind, track_id):
        setter = self.extras.get("audio_set_track" if kind == "audio" else "video_set_spu")
        if setter and self.player:
            setter(self.player, track_id)

    def set_rate(self, rate):
        setter = self.extras.get("media_player_set_rate")
        return bool(setter and self.player and setter(self.player, float(rate)) == 0)

    def add_subtitle(self, path):
        """Load a subtitle file (.srt, .ass, .vtt …) next to the current video and show it."""
        add = self.extras.get("media_player_add_slave")
        if not add or not self.player:
            return False
        from pathlib import Path
        return add(self.player, 0, Path(path).resolve().as_uri().encode("utf-8"), True) == 0

    def stop(self):
        if self.player:
            self.media_player_stop(self.player)

    def close(self):
        if self.player:
            self.media_player_stop(self.player)
            self.media_player_release(self.player)
            self.player = None
        if self.instance:
            self.release(self.instance)
            self.instance = None
        self.dll_directory.close()


class Headless:
    """A VLC instance without a window that runs a stream-output chain (convert, record)."""

    def __init__(self, url, chain, options=()):
        vlc = Path(__file__).with_name("video")
        if not (vlc / "libvlc.dll").is_file():
            raise ValueError(T("De ingebouwde videomotor ontbreekt."))
        self.dll_directory = os.add_dll_directory(str(vlc))
        self.instance = self.player = None
        p, i, s = c.c_void_p, c.c_int, c.c_char_p
        dll = c.CDLL(str(vlc / "libvlc.dll"))
        self.fn = {}
        for name, result, args in (
            ("new", p, [i, c.POINTER(s)]), ("release", None, [p]),
            ("media_new_location", p, [p, s]), ("media_release", None, [p]), ("media_add_option", None, [p, s]),
            ("media_player_new", p, [p]), ("media_player_release", None, [p]),
            ("media_player_set_media", None, [p, p]), ("media_player_play", i, [p]),
            ("media_player_stop", None, [p]), ("media_player_get_state", i, [p]),
        ):
            function = getattr(dll, "libvlc_" + name)
            function.restype, function.argtypes = result, args
            self.fn[name] = function
        arguments = (s * 3)(b"--no-video-title-show", b"--no-osd", b"--no-stats")
        self.instance = self.fn["new"](len(arguments), arguments)
        if not self.instance:
            raise ValueError(T("VLC kon niet starten."))
        media = self.fn["media_new_location"](self.instance, url.encode("utf-8"))
        if not media:
            self.close()
            raise ValueError(T("VLC kon de streamlink niet openen."))
        for option in (":sout=" + chain, ":sout-keep", ":no-sout-all", ":network-caching=2000", ":http-reconnect",
                       *options):
            self.fn["media_add_option"](media, option.encode("utf-8"))
        self.player = self.fn["media_player_new"](self.instance)
        self.fn["media_player_set_media"](self.player, media)
        self.fn["media_release"](media)
        if self.fn["media_player_play"](self.player) != 0:
            self.close()
            raise ValueError(T("Starten mislukt."))

    def state(self):
        return self.fn["media_player_get_state"](self.player) if self.player else 5

    def failed(self):
        return self.state() == 7  # libvlc_Error

    def close(self):
        if self.player:
            self.fn["media_player_stop"](self.player)
            self.fn["media_player_release"](self.player)
            self.player = None
        if self.instance:
            self.fn["release"](self.instance)
            self.instance = None
        try:
            self.dll_directory.close()
        except Exception:
            pass


def buffer_chain(folder, seconds, seglen=4):
    """Stream-output that shows the video and also keeps the last `seconds` as small files (live pause/rewind)."""
    folder = Path(folder).as_posix()
    count = max(4, int(seconds / seglen))
    return (f"#duplicate{{dst=display,dst=std{{access=livehttp{{seglen={seglen},delsegs=true,numsegs={count},"
            f"index='{folder}/index.m3u8',index-url=seg-########.ts}},mux=ts{{use-key-frames}},"
            f"dst='{folder}/seg-########.ts'}}}}")


def _segments_chain(folder, seconds, seglen=4):
    folder = Path(folder).as_posix()
    count = max(4, int(seconds / seglen))
    # delsegs=false: VLC would delete every piece when the player stops; Zono removes old pieces itself
    return (f"#std{{access=livehttp{{seglen={seglen},delsegs=false,numsegs={count},"
            f"index='{folder}/index.m3u8',index-url=seg-########.ts}},mux=ts{{use-key-frames}},"
            f"dst='{folder}/seg-########.ts'}}")


class LiveBuffer:
    """Keeps the last minutes of a live channel on disk, with only one connection to the provider.

    While you watch live, the player itself saves small pieces (part 0). The first time you pause or rewind,
    the player switches to playing those pieces from disk and a small background recorder (part 1, 2 …) takes
    over the connection. A combined playlist (index.m3u8) ties all parts together, so you can seek anywhere
    in the window and go back to (almost) live."""

    def __init__(self, url, root, seconds, seglen=4):
        self.url, self.root, self.seconds, self.seglen = url, Path(root), int(seconds), seglen
        self.root.mkdir(parents=True, exist_ok=True)
        self.parts, self.recorder = [], None
        self.sequence, self.numbers = 0, {}
        self.dropped_breaks = 0
        self.lock = threading.Lock()
        self.running = True
        self.local = False
        self.kept = None
        threading.Thread(target=self._writer, daemon=True).start()

    def _new_part(self):
        folder = self.root / f"p{len(self.parts)}"
        folder.mkdir(parents=True, exist_ok=True)
        self.parts.append(folder)
        return folder

    def display_chain(self):
        """Stream output for the visible player: show the picture and save part 0."""
        folder = self._new_part()
        return "#duplicate{dst=display,dst=" + _segments_chain(folder, self.seconds, self.seglen)[1:] + "}"

    def keep_parts(self):
        """VLC deletes its pieces when a player stops. Call this just before: hard links (instant, no extra disk
        space) keep the pieces of the running part."""
        if not self.parts:
            return
        folder = self.parts[-1]
        kept = folder.with_name(folder.name + "k")
        kept.mkdir(parents=True, exist_ok=True)
        try:
            text = (folder / "index.m3u8").read_text(encoding="utf-8", errors="replace")
        except OSError:
            return
        for line in text.splitlines():
            name = line.strip()
            if name and not name.startswith("#"):
                source, target = folder / name, kept / name
                if source.is_file() and not target.exists():
                    try:
                        os.link(source, target)
                    except OSError:
                        import shutil
                        shutil.copy2(source, target)
        (kept / "index.m3u8").write_text(text, encoding="utf-8")
        with self.lock:
            self.parts[-1] = kept
            try:
                self.write_index()
            except OSError:
                pass

    def start_recorder(self):
        """Keep saving after the visible player stopped reading from the provider."""
        if self.recorder is not None:
            try:
                self.recorder.close()
            except Exception:
                pass
        folder = self._new_part()
        self.recorder = Headless(self.url, _segments_chain(folder, self.seconds, self.seglen))
        self.local = True

    def recorder_failed(self):
        return self.recorder is not None and self.recorder.state() in (6, 7)

    def entries(self):
        """[(part index, duration, file)] of every saved piece, oldest first."""
        found = []
        for index, folder in enumerate(list(self.parts)):
            try:
                text = (folder / "index.m3u8").read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            duration = None
            for line in text.splitlines():
                if line.startswith("#EXTINF:"):
                    try:
                        duration = float(line[8:].split(",", 1)[0])
                    except ValueError:
                        duration = None
                elif line and not line.startswith("#") and duration is not None:
                    found.append((index, duration, line.strip()))
                    duration = None
        return found

    def seconds_kept(self, fresh=False):
        """Seconds saved. Uses the figure of the background writer (no disk work on the screen) unless `fresh`."""
        if fresh or self.kept is None:
            return sum(d for _, d, _ in self.entries())
        return self.kept

    def write_index(self):
        found = self.entries()
        self.kept = sum(d for _, d, _ in found)
        total, keep = 0.0, []
        for entry in reversed(found):  # newest first, until the window is full
            if total >= self.seconds:
                break
            keep.append(entry)
            total += entry[1]
        keep.reverse()
        if not keep:
            return False
        for part, _, name in keep:
            key = (part, name)
            if key not in self.numbers:
                self.numbers[key] = self.sequence
                self.sequence += 1
        first = self.numbers[(keep[0][0], keep[0][2])]
        breaks_before = len({p for p, _, _ in found if p < keep[0][0]})
        lines = ["#EXTM3U", "#EXT-X-VERSION:3",
                 f"#EXT-X-TARGETDURATION:{int(max(d for _, d, _ in keep) + 0.999)}",
                 f"#EXT-X-MEDIA-SEQUENCE:{first}", f"#EXT-X-DISCONTINUITY-SEQUENCE:{breaks_before}"]
        previous = keep[0][0]
        for part, duration, name in keep:
            if part != previous:
                lines.append("#EXT-X-DISCONTINUITY")
                previous = part
            lines += [f"#EXTINF:{duration:.3f},", f"{self.parts[part].name}/{name}"]
        kept_files = {(part, name) for part, _, name in keep}
        for part, folder in enumerate(list(self.parts)):  # free disk space: pieces older than the window
            try:
                for file in folder.glob("seg-*.ts"):
                    older = part < keep[0][0] or (part == keep[0][0] and file.name < keep[0][2])
                    if older and (part, file.name) not in kept_files:
                        file.unlink(missing_ok=True)
            except OSError:
                pass
        temporary = self.root / "index.tmp"
        temporary.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(temporary, self.root / "index.m3u8")
        return True

    def index_uri(self):
        return (self.root / "index.m3u8").as_uri()

    def _writer(self):
        import time
        while self.running:
            try:
                with self.lock:
                    self.write_index()
            except OSError:
                pass
            time.sleep(1)

    def close(self):
        self.running = False
        if self.recorder is not None:
            try:
                self.recorder.close()
            except Exception:
                pass
            self.recorder = None
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)


class BufferTap:
    """Records the channel you are watching from its live buffer: no second connection to the provider.
    New pieces are appended to the recording file as they arrive."""

    def __init__(self, buffer, path):
        self.buffer, self.path = buffer, Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_bytes(b"")
        self.done = {(part, name) for part, _, name in buffer.entries()}  # what was there before you pressed R
        self.closed = False
        self.lock = threading.Lock()
        threading.Thread(target=self._run, daemon=True).start()

    def flush(self):
        with self.lock:
            if not self.buffer.running:
                return
            for part, _, name in self.buffer.entries():
                if (part, name) in self.done:
                    continue
                try:
                    data = (self.buffer.parts[part] / name).read_bytes()
                except (OSError, IndexError):
                    continue
                with self.path.open("ab") as output:
                    output.write(data)
                self.done.add((part, name))

    def _run(self):
        import time
        while not self.closed:
            try:
                self.flush()
            except OSError:
                pass
            time.sleep(2)

    def state(self):
        return 3 if not self.closed and self.buffer.running else 6

    def close(self):
        try:
            self.flush()
        except OSError:
            pass
        self.closed = True


class Recorder(Headless):
    """Save a live channel to a .ts file, unchanged (no quality loss, little work for the PC)."""

    def __init__(self, url, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        super().__init__(url, f"#std{{access=file,mux=ts,dst='{self.path.as_posix()}'}}")


class Transcoder(Headless):
    """Re-encode a stream into H.264/AAC HLS files in `folder`.

    Used for phones: an iPhone cannot show HEVC (4K) or interlaced pictures from many IPTV streams, nor play MKV
    files, and then plays sound over a black picture. The PC converts the stream so every phone can show it."""

    def __init__(self, url, folder, live=True):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        index = (self.folder / "index.m3u8").as_posix()
        segments = (self.folder / "seg-########.ts").as_posix()
        keep = "delsegs=true,numsegs=10" if live else "delsegs=false,numsegs=0"
        chain = ("#transcode{vcodec=h264,venc=x264{preset=veryfast,profile=main,level=4.0,keyint=50,min-keyint=25},"
                 "vb=2800,maxwidth=1280,maxheight=720,deinterlace,"
                 "acodec=mp4a,ab=128,channels=2,samplerate=48000}"
                 f":std{{access=livehttp{{seglen=4,{keep},index='{index}',index-url=seg-########.ts}},"
                 f"mux=ts{{use-key-frames}},dst='{segments}'}}")
        super().__init__(url, chain)

    def close(self):
        super().close()
        import shutil
        shutil.rmtree(self.folder, ignore_errors=True)
