#!/usr/bin/env python3
import curses
import curses.panel
import os
import sys
import locale
from typing import List, Dict, Optional, Tuple

# External dependency
try:
    from mutagen import File as MutagenFile
    from mutagen.id3 import ID3, APIC, ID3NoHeaderError
    from mutagen.flac import FLAC, Picture
    from mutagen.mp4 import MP4, MP4Cover
    from mutagen.oggvorbis import OggVorbis
    from mutagen.oggopus import OggOpus
    import base64
    import mimetypes
except Exception as e:
    MutagenFile = None  # type: ignore

SUPPORTED_EXTS = {
    ".mp3", ".flac", ".ogg", ".oga", ".opus", ".m4a", ".mp4", ".aac", ".wav", ".aiff", ".aif"
}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}

# Common, easy tag names we'll expose in the UI
DEFAULT_FIELDS = [
    ("title", "Title"),
    ("artist", "Artist"),
    ("album", "Album"),
    ("albumartist", "Album Artist"),
    ("tracknumber", "Track"),
    ("discnumber", "Disc"),
    ("date", "Year"),
    ("genre", "Genre"),
    ("comment", "Comment"),
]


def human_join(values: List[str]) -> str:
    return ", ".join(v for v in values if v)


def normalize_value(v):
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v]
    return [str(v)]


class TagIO:
    """Thin wrapper around mutagen easy tags + cover art helpers."""

    def __init__(self, path: str):
        if MutagenFile is None:
            raise RuntimeError("mutagen is not installed. Please install requirements.txt")
        self.path = path
        self.audio = MutagenFile(path, easy=True)
        self.raw = MutagenFile(path)  # non-easy for cover art access
        self.format_name = type(self.audio).__name__ if self.audio else "Unknown"
        self.readonly = False

    def is_supported(self) -> bool:
        return self.audio is not None

    def get(self, key: str) -> List[str]:
        if not self.audio:
            return []
        try:
            v = self.audio.get(key)
        except Exception:
            v = None
        return normalize_value(v)

    def set(self, key: str, value: str):
        if not self.audio:
            return
        try:
            if value == "":
                # Empty value clears the tag
                if key in self.audio:
                    del self.audio[key]
            else:
                self.audio[key] = [value]
        except Exception:
            # Silently ignore unsupported keys for this format
            pass

    def save(self) -> Tuple[bool, Optional[str]]:
        if not self.audio:
            return False, "Unsupported file format"
        try:
            # Save both easy and raw tags if needed
            if self.raw is not None and self.raw is not self.audio:
                try:
                    self.raw.save()
                except Exception:
                    pass
            self.audio.save()
            return True, None
        except Exception as e:
            return False, str(e)

    # -------- Cover art helpers --------
    def has_cover(self) -> bool:
        info = self.get_cover_info()
        return info is not None

    def get_cover_info(self) -> Optional[str]:
        try:
            if isinstance(self.raw, FLAC):
                pics = getattr(self.raw, 'pictures', [])
                if pics:
                    p = pics[0]
                    size = len(p.data) if p.data else 0
                    return f"FLAC picture: {p.mime or 'image/*'} ({size} bytes)"
            elif isinstance(self.raw, MP4):
                covr = self.raw.tags.get('covr') if self.raw.tags else None
                if covr:
                    fmt = 'jpeg' if covr[0].imageformat == MP4Cover.FORMAT_JPEG else 'png'
                    size = len(bytes(covr[0]))
                    return f"MP4 cover: image/{fmt} ({size} bytes)"
            elif isinstance(self.raw, (OggVorbis, OggOpus)):
                tags = self.raw.tags
                if not tags:
                    return None
                mbp = tags.get('metadata_block_picture')
                if mbp:
                    try:
                        b = base64.b64decode(mbp[0])
                        size = len(b)
                        return f"Vorbis/Opus picture: ({size} bytes)"
                    except Exception:
                        return "Vorbis/Opus picture: (unreadable)"
                coverart = tags.get('coverart')
                if coverart:
                    try:
                        b = base64.b64decode(coverart[0])
                        mime = tags.get('coverartmime', ['image/jpeg'])[0]
                        return f"Vorbis/Opus coverart: {mime} ({len(b)} bytes)"
                    except Exception:
                        return "Vorbis/Opus coverart present"
            elif hasattr(self.raw, 'tags') and isinstance(self.raw.tags, ID3):
                id3 = self.raw.tags
                apics = id3.getall('APIC') if id3 else []
                if apics:
                    a = apics[0]
                    size = len(a.data) if a.data else 0
                    return f"ID3 APIC: {a.mime or 'image/*'} ({size} bytes)"
        except Exception:
            return None
        return None

    def clear_cover(self) -> Tuple[bool, Optional[str]]:
        try:
            if isinstance(self.raw, FLAC):
                self.raw.clear_pictures()
                self.raw.save()
                return True, None
            elif isinstance(self.raw, MP4):
                if self.raw.tags is None:
                    self.raw.add_tags()
                self.raw.tags['covr'] = []
                self.raw.save()
                return True, None
            elif isinstance(self.raw, (OggVorbis, OggOpus)):
                tags = self.raw.tags
                if tags is None:
                    return True, None
                for key in ['metadata_block_picture', 'coverart', 'coverartmime']:
                    if key in tags:
                        del tags[key]
                self.raw.save()
                return True, None
            elif hasattr(self.raw, 'tags'):
                try:
                    id3 = ID3(self.path)
                except ID3NoHeaderError:
                    return True, None
                for k in list(id3.keys()):
                    if k.startswith('APIC'):
                        del id3[k]
                id3.save(self.path)
                return True, None
        except Exception as e:
            return False, str(e)
        return False, "Unsupported format for cover removal"

    def set_cover(self, image_path: str) -> Tuple[bool, Optional[str]]:
        try:
            with open(image_path, 'rb') as f:
                data = f.read()
            mime, _ = mimetypes.guess_type(image_path)
            if not mime or not mime.startswith('image/'):
                # default to jpeg
                mime = 'image/jpeg'

            if isinstance(self.raw, FLAC):
                pic = Picture()
                pic.type = 3  # front cover
                pic.mime = mime
                pic.desc = 'cover'
                pic.data = data
                # Clearing existing pictures and adding one
                self.raw.clear_pictures()
                self.raw.add_picture(pic)
                self.raw.save()
                return True, None
            elif isinstance(self.raw, MP4):
                if self.raw.tags is None:
                    self.raw.add_tags()
                fmt = MP4Cover.FORMAT_JPEG
                if mime == 'image/png':
                    fmt = MP4Cover.FORMAT_PNG
                self.raw.tags['covr'] = [MP4Cover(data, imageformat=fmt)]
                self.raw.save()
                return True, None
            elif isinstance(self.raw, (OggVorbis, OggOpus)):
                # Use METADATA_BLOCK_PICTURE with embedded FLAC picture structure
                pic = Picture()
                pic.type = 3
                pic.mime = mime
                pic.desc = 'cover'
                pic.data = data
                b64 = base64.b64encode(pic.write()).decode('ascii')
                tags = self.raw.tags
                if tags is None:
                    self.raw.add_tags()
                    tags = self.raw.tags
                if 'coverart' in tags:
                    del tags['coverart']
                if 'coverartmime' in tags:
                    del tags['coverartmime']
                tags['metadata_block_picture'] = [b64]
                self.raw.save()
                return True, None
            else:
                # Try ID3 fallback for MP3/others
                try:
                    try:
                        id3 = ID3(self.path)
                    except ID3NoHeaderError:
                        id3 = ID3()
                    # remove existing APICs
                    for k in list(id3.keys()):
                        if k.startswith('APIC'):
                            del id3[k]
                    id3.add(APIC(encoding=3, mime=mime, type=3, desc='cover', data=data))
                    id3.save(self.path)
                    return True, None
                except Exception:
                    pass
        except Exception as e:
            return False, str(e)
        return False, "Unsupported format for cover setting"

class FileBrowser:
    def __init__(self, root: str, exts: Optional[set] = None):
        self.root = os.path.abspath(root)
        self.entries: List[str] = []
        self.selection = 0
        self.exts = exts or SUPPORTED_EXTS
        self.refresh()

    def refresh(self):
        items = []
        try:
            for name in os.listdir(self.root):
                path = os.path.join(self.root, name)
                if os.path.isdir(path):
                    items.append(name + "/")
                else:
                    ext = os.path.splitext(name)[1].lower()
                    if ext in self.exts:
                        items.append(name)
        except FileNotFoundError:
            items = []
        items.sort(key=lambda n: (not n.endswith("/"), n.lower()))
        self.entries = items
        if self.selection >= len(self.entries):
            self.selection = max(0, len(self.entries) - 1)

    def enter(self) -> Optional[str]:
        if not self.entries:
            return None
        name = self.entries[self.selection]
        path = os.path.join(self.root, name.rstrip("/"))
        if name.endswith("/"):
            self.root = os.path.abspath(path)
            self.selection = 0
            self.refresh()
            return None
        return path

    def up(self):
        self.selection = (self.selection - 1) % max(1, len(self.entries))

    def down(self):
        self.selection = (self.selection + 1) % max(1, len(self.entries))

    def parent(self):
        parent = os.path.dirname(self.root)
        if parent and parent != self.root:
            self.root = parent
            self.selection = 0
            self.refresh()


class Tui:
    def __init__(self, stdscr, start_path: str):
        self.stdscr = stdscr
        self.browser = FileBrowser(start_path, SUPPORTED_EXTS)
        self.current_path: Optional[str] = None
        self.tags: Dict[str, str] = {}
        self.cursor_field = 0
        self.status_msg = "Press [h] for help"
        self.dirty = False
        self.focus = "browser"  # browser, tags, or cover
        self.last_error: Optional[str] = None
        self.cover_info: Optional[str] = None
        self.theme = None  # set later

    def load_current(self):
        if self.current_path is None:
            self.tags = {k: "" for k, _ in DEFAULT_FIELDS}
            self.cover_info = None
            return
        try:
            io = TagIO(self.current_path)
            if not io.is_supported():
                self.status_msg = "Unsupported file"
                self.tags = {k: "" for k, _ in DEFAULT_FIELDS}
                self.cover_info = None
                return
            new_tags = {}
            for k, _ in DEFAULT_FIELDS:
                new_tags[k] = human_join(io.get(k))
            self.tags = new_tags
            self.cover_info = io.get_cover_info()
            self.dirty = False
            self.last_error = None
        except Exception as e:
            self.tags = {k: "" for k, _ in DEFAULT_FIELDS}
            self.cover_info = None
            self.last_error = str(e)
            self.status_msg = f"Error: {e}"

    def save_current(self):
        if self.current_path is None:
            return
        try:
            io = TagIO(self.current_path)
            if not io.is_supported():
                self.status_msg = "Unsupported file"
                return
            for k, _ in DEFAULT_FIELDS:
                io.set(k, self.tags.get(k, ""))
            ok, err = io.save()
            if ok:
                self.status_msg = "Saved"
                self.dirty = False
            else:
                self.status_msg = f"Save failed: {err}"
        except Exception as e:
            self.status_msg = f"Save failed: {e}"

    def edit_field(self, idx: int):
        if idx < 0 or idx >= len(DEFAULT_FIELDS):
            return
        key, label = DEFAULT_FIELDS[idx]
        prompt = f"{label}: "
        value = self.tags.get(key, "")
        new_val = self.prompt_input(prompt, value)
        if new_val is not None and new_val != value:
            self.tags[key] = new_val
            self.dirty = True

    def draw(self):
        self.stdscr.clear()
        h, w = self.stdscr.getmaxyx()
        
        current_line = 0
        
        # ASCII Logo
        logo = [
            "_________  ____ ________________________________________    ________ ",
            r"\_   ___ \|    |   \______   \_   _____/\__    ___/  _  \  /  _____/ ",
            r"/    \  \/|    |   /|    |  _/|    __)_   |    | /  /_\  \/   \  ___ ",
            r"\     \___|    |  / |    |   \|        \  |    |/    |    \    \_\  \ ",
            r" \______  /______/  |______  /_______  /  |____|\____|__  /\______  /",
            r"        \/                 \/        \/                 \/        \/ ",
        ]
        for i, line in enumerate(logo):
            try:
                self.stdscr.addnstr(current_line, 0, line[: w], w, curses.A_BOLD)
                current_line += 1
            except curses.error:
                pass
        
        try:
            self.stdscr.addnstr(current_line, 0, "─" * w, w)
            current_line += 1
        except curses.error:
            pass
        
        # Current file info
        if self.current_path:
            filename = os.path.basename(self.current_path)
            status = "[MODIFIED]" if self.dirty else "[SAVED]"
            try:
                self.stdscr.addnstr(current_line, 0, f"File: {filename} {status}"[: w], w)
                current_line += 1
            except curses.error:
                pass
        else:
            try:
                self.stdscr.addnstr(current_line, 0, "No file selected - press [o] to open"[: w], w, curses.A_DIM)
                current_line += 1
            except curses.error:
                pass
        
        try:
            self.stdscr.addnstr(current_line, 0, "─" * w, w)
            current_line += 1
        except curses.error:
            pass
        
        # Calculate available space
        footer_lines = 3
        available = h - current_line - footer_lines
        
        # Split screen: browser on left, tags on right
        # Left panel: 0 to split_x-2, divider at split_x-1, right panel: split_x to w-1
        split_x = w // 2
        
        # LEFT: File Browser with border
        left_width = split_x
        try:
            # Top border: ┌─ FILES ─────┐
            top_line = "┌─ FILES " + "─" * max(0, left_width - 10) + "┐"
            self.stdscr.addnstr(current_line, 0, top_line[: left_width], left_width, curses.A_BOLD)
        except curses.error:
            pass
        
        browser_start = current_line + 1
        browser_height = available - 1
        
        # Draw file list with borders
        try:
            dir_line = f"Dir: {self.browser.root}"
            content = "│ " + dir_line
            # Pad to fit and add right border
            padded = content + " " * max(0, left_width - len(content) - 1) + "│"
            self.stdscr.addnstr(browser_start, 0, padded[: left_width], left_width, curses.A_DIM)
        except curses.error:
            pass
        
        start_idx = max(0, self.browser.selection - browser_height + 3)
        for i in range(start_idx, min(len(self.browser.entries), start_idx + browser_height - 2)):
            line_y = browser_start + 1 + (i - start_idx)
            if line_y >= h - footer_lines:
                break
            name = self.browser.entries[i]
            marker = "►" if (i == self.browser.selection and self.focus == "browser") else " "
            content = f"│{marker} {name}"
            padded = content + " " * max(0, left_width - len(content) - 1) + "│"
            try:
                self.stdscr.addnstr(line_y, 0, padded[: left_width], left_width)
            except curses.error:
                pass
        
        # Fill remaining lines in left panel with borders
        for line_y in range(browser_start + 1 + min(len(self.browser.entries), browser_height - 2), h - footer_lines):
            try:
                filler = "│" + " " * (left_width - 2) + "│"
                self.stdscr.addnstr(line_y, 0, filler[: left_width], left_width)
            except curses.error:
                pass
        
        # Bottom border for left panel
        try:
            bottom = "└" + "─" * max(0, left_width - 2) + "┘"
            self.stdscr.addnstr(h - footer_lines, 0, bottom[: left_width], left_width)
        except curses.error:
            pass
        
        # RIGHT: Tags with border
        try:
            top_line = "┌─ TAGS " + "─" * max(0, w - split_x - 10) + "┐"
            self.stdscr.addnstr(current_line, split_x, top_line[: w - split_x], w - split_x, curses.A_BOLD)
        except curses.error:
            pass
        
        tags_start = current_line + 1
        tags_height = available - 1
        
        if self.current_path:
            # Draw tags with borders
            start_idx = max(0, self.cursor_field - tags_height // 3)
            current_y = tags_start
            for i in range(start_idx, len(DEFAULT_FIELDS)):
                if current_y >= h - footer_lines - 2:
                    break
                key, label = DEFAULT_FIELDS[i]
                value = self.tags.get(key, "")
                is_sel = (self.focus == "tags" and i == self.cursor_field)
                
                # Draw tag (3 lines with proper padding)
                marker = "►" if is_sel else " "
                right_width = w - split_x
                try:
                    # Label line
                    label_content = f"│{marker} {label}:"
                    label_padded = label_content + " " * max(0, right_width - 2 - len(label_content)) + "│"
                    self.stdscr.addnstr(current_y, split_x, label_padded[: right_width], right_width, curses.A_BOLD if is_sel else 0)
                    current_y += 1
                    # Value line
                    value_content = f"│  {value}"
                    value_padded = value_content + " " * max(0, right_width - 2 - len(value_content)) + "│"
                    self.stdscr.addnstr(current_y, split_x, value_padded[: right_width], right_width)
                    current_y += 1
                    # Separator
                    if not is_sel:
                        sep_content = "│  " + "·" * max(0, right_width - 4) + "│"
                        self.stdscr.addnstr(current_y, split_x, sep_content[: right_width], right_width, curses.A_DIM)
                    else:
                        sep_padded = "│" + " " * (right_width - 2) + "│"
                        self.stdscr.addnstr(current_y, split_x, sep_padded[: right_width], right_width)
                    current_y += 1
                except curses.error:
                    break
            
            # Fill remaining space with borders
            for line_y in range(current_y, h - footer_lines):
                try:
                    filler = "│" + " " * (right_width - 2) + "│"
                    self.stdscr.addnstr(line_y, split_x, filler[: right_width], right_width)
                except curses.error:
                    pass
        else:
            right_width = w - split_x
            try:
                msg_content = "│ Open a file to edit tags"
                msg_padded = msg_content + " " * max(0, right_width - 2 - len(msg_content)) + "│"
                self.stdscr.addnstr(tags_start, split_x, msg_padded[: right_width], right_width, curses.A_DIM)
            except curses.error:
                pass
            # Fill space with borders
            for line_y in range(tags_start + 1, h - footer_lines):
                try:
                    filler = "│" + " " * (right_width - 2) + "│"
                    self.stdscr.addnstr(line_y, split_x, filler[: right_width], right_width)
                except curses.error:
                    pass
        
        # Bottom border for right panel
        try:
            right_width = w - split_x
            bottom = "└" + "─" * max(0, right_width - 2) + "┘"
            self.stdscr.addnstr(h - footer_lines, split_x, bottom[: right_width], right_width)
        except curses.error:
            pass
        
        # Footer
        try:
            self.stdscr.addnstr(h - 3, 0, "═" * w, w)
            footer1 = "[↑↓] Navigate  [Tab] Switch  [Enter/e] Edit  [o] Open  [s] Save  [r] Reload"
            footer2 = "[c] Set Cover  [C] Clear Cover  [h] Help  [q] Quit"
            self.stdscr.addnstr(h - 2, 0, footer1[: w], w)
            self.stdscr.addnstr(h - 1, 0, footer2[: w], w)
        except curses.error:
            pass
        
        self.stdscr.refresh()

    def draw_panel(self, y, x, h, w, title=""):
        """Draw panel with Cubeplayer-style border and centered title"""
        try:
            win = curses.newwin(h, w, y, x)
            # Top border with centered title
            if title:
                title_str = f" {title} "
                pad_len = (w - len(title_str) - 2) // 2
                top_line = "┌" + "─" * pad_len + title_str + "─" * (w - pad_len - len(title_str) - 2) + "┐"
            else:
                top_line = "┌" + "─" * (w - 2) + "┐"
            win.addnstr(0, 0, top_line[: w], w)
            
            # Side borders
            for i in range(1, h - 1):
                try:
                    win.addch(i, 0, "│")
                    win.addch(i, w - 1, "│")
                except curses.error:
                    pass
            
            # Bottom border
            bottom_line = "└" + "─" * (w - 2) + "┘"
            win.addnstr(h - 1, 0, bottom_line[: w], w)
            
            win.noutrefresh()
        except curses.error:
            pass

    def draw_current_file_info(self, y, x, h, w):
        """Draw current file info (like 'Now Playing' in Cubeplayer)"""
        try:
            win = curses.newwin(h, w, y, x)
            if self.current_path:
                filename = os.path.basename(self.current_path)
                # Line 1: filename
                win.addnstr(0, 0, f"File: {filename}"[: w - 1], w - 1)
                # Line 2: status (modified/saved)
                status = "Modified" if self.dirty else "Saved"
                win.addnstr(1, 0, f"Status: {status}"[: w - 1], w - 1)
            else:
                win.addnstr(0, 0, "No file selected"[: w - 1], w - 1)
            win.noutrefresh()
        except curses.error:
            pass

    def draw_files(self, y, x, h, w):
        try:
            win = curses.newwin(h, w, y, x)
            # Current directory header
            header = f"Dir: {self.browser.root}"
            win.addnstr(0, 0, header[: w - 1], w - 1, curses.A_DIM)
            max_rows = h - 1
            start = 0
            if self.browser.selection >= max_rows:
                start = self.browser.selection - max_rows + 1
            for i in range(start, min(len(self.browser.entries), start + max_rows)):
                name = self.browser.entries[i]
                # Cubeplayer-style marker for selected item
                marker = ">> " if (i == self.browser.selection and self.focus == "browser") else "   "
                line = f"{marker}{name}"
                win.addnstr(1 + i - start, 0, line[: w - 1], w - 1)
            win.noutrefresh()
        except curses.error:
            pass

    def draw_cover(self, y, x, h, w):
        try:
            win = curses.newwin(h, w, y, x)
            # Cover info
            if self.cover_info:
                win.addnstr(0, 0, f"Status: {self.cover_info}"[: w - 1], w - 1)
            else:
                win.addnstr(0, 0, "Status: No cover"[: w - 1], w - 1)
            
            # ASCII preview placeholder (future: actual cover to ASCII conversion)
            for i in range(1, min(h - 1, 6)):
                preview = "[  Cover Preview Here  ]" if i == 2 else ""
                try:
                    win.addnstr(i, 0, preview[: w - 1], w - 1, curses.A_DIM)
                except curses.error:
                    pass
            
            # Controls hint
            hint = "[c] Set Cover   [C] Clear Cover"
            try:
                win.addnstr(h - 1, 0, hint[: w - 1], w - 1, curses.A_DIM)
            except curses.error:
                pass
            win.noutrefresh()
        except curses.error:
            pass

    def draw_tags(self, y, x, h, w):
        try:
            win = curses.newwin(h, w, y, x)
            if not self.current_path:
                win.addnstr(0, 0, "Select a file to edit tags", w - 1, curses.A_DIM)
                win.noutrefresh()
                return
            
            # Calculate scrolling: show tags around the selected one
            box_h = 3  # height per tag box
            visible_tags = h // box_h  # how many tags fit in the view
            
            # Determine scroll offset to keep selected tag visible
            start_idx = 0
            if self.cursor_field >= visible_tags:
                start_idx = self.cursor_field - visible_tags + 1
            
            # Draw each tag in a mini-box with scrolling
            current_y = 0
            for i in range(start_idx, len(DEFAULT_FIELDS)):
                if current_y + box_h > h:
                    break
                
                key, label = DEFAULT_FIELDS[i]
                value = self.tags.get(key, "")
                is_sel = (self.focus == "tags" and i == self.cursor_field)
                
                # Draw mini-box
                box_w = w
                # Top border
                if is_sel:
                    top_line = "┌─» " + label + " «" + "─" * max(0, box_w - len(label) - 7) + "┐"
                else:
                    top_line = "┌─ " + label + " " + "─" * max(0, box_w - len(label) - 5) + "┐"
                try:
                    win.addnstr(current_y, 0, top_line[: box_w], box_w)
                except curses.error:
                    pass
                
                # Content line
                content = f"│ {value}" + " " * max(0, box_w - len(value) - 3) + "│"
                try:
                    win.addnstr(current_y + 1, 0, content[: box_w], box_w)
                except curses.error:
                    pass
                
                # Bottom border
                bottom_line = "└" + "─" * (box_w - 2) + "┘"
                try:
                    win.addnstr(current_y + 2, 0, bottom_line[: box_w], box_w)
                except curses.error:
                    pass
                
                current_y += box_h
            
            win.noutrefresh()
        except curses.error:
            pass

    def prompt_input(self, prompt: str, initial: str = "") -> Optional[str]:
        h, w = self.stdscr.getmaxyx()
        win_h = 3
        win_w = min(max(30, len(prompt) + 10), w - 4)
        win_y = h // 2 - win_h // 2
        win_x = w // 2 - win_w // 2
        win = curses.newwin(win_h, win_w, win_y, win_x)
        win.keypad(True)
        win.box()
        curses.curs_set(1)
        buffer = list(initial)
        pos = len(buffer)
        while True:
            # Render
            win.erase()
            win.box()
            win.addnstr(0, 2, f" {prompt.strip()} ", win_w - 4)
            visible = "".join(buffer)
            field_w = win_w - 4
            # Calculate display position accounting for wide chars
            display_text = visible
            if len(display_text) > field_w - 1:
                # Simple truncation for now
                start = max(0, len(display_text) - field_w + 1)
                display_text = display_text[start:]
            win.addnstr(1, 2, " " * (field_w), field_w)
            try:
                win.addstr(1, 2, display_text[: field_w - 1])
            except curses.error:
                pass
            # Place cursor at end
            try:
                cursor_pos = min(len(display_text), field_w - 1)
                win.move(1, 2 + cursor_pos)
            except curses.error:
                pass
            win.refresh()

            # Use get_wch for proper unicode support
            try:
                ch = win.get_wch()
            except curses.error:
                continue
            
            # Handle special keys (returned as integers)
            if isinstance(ch, int):
                if ch in (curses.KEY_ENTER, 10, 13):
                    curses.curs_set(0)
                    return "".join(buffer)
                elif ch == 27:  # ESC
                    curses.curs_set(0)
                    return None
                elif ch == curses.KEY_LEFT:
                    if pos > 0:
                        pos -= 1
                elif ch == curses.KEY_RIGHT:
                    if pos < len(buffer):
                        pos += 1
                elif ch in (curses.KEY_BACKSPACE, 127, 8):
                    if pos > 0:
                        buffer.pop(pos - 1)
                        pos -= 1
                elif ch == curses.KEY_DC:  # Delete
                    if pos < len(buffer):
                        buffer.pop(pos)
                elif ch == curses.KEY_HOME:
                    pos = 0
                elif ch == curses.KEY_END:
                    pos = len(buffer)
            # Handle regular characters (returned as strings)
            elif isinstance(ch, str):
                if ch == '\n' or ch == '\r':
                    curses.curs_set(0)
                    return "".join(buffer)
                elif ch == '\x1b':  # ESC
                    curses.curs_set(0)
                    return None
                elif ch == '\x7f' or ch == '\b':  # Backspace
                    if pos > 0:
                        buffer.pop(pos - 1)
                        pos -= 1
                elif ch.isprintable():
                    buffer.insert(pos, ch)
                    pos += 1

    def file_picker(self, title: str, exts: set) -> Optional[str]:
        # Modal file picker constrained to exts
        h, w = self.stdscr.getmaxyx()
        win_h = max(12, min(30, h - 4))
        win_w = max(40, min(100, w - 4))
        y = h // 2 - win_h // 2
        x = w // 2 - win_w // 2
        win = curses.newwin(win_h, win_w, y, x)
        win.keypad(True)
        browser = FileBrowser(self.browser.root, exts)
        while True:
            win.erase()
            win.box()
            header = f" {title} "
            path_line = browser.root
            try:
                win.addnstr(0, 2, header[: win_w - 4], win_w - 4)
                win.addnstr(1, 2, path_line[: win_w - 4], win_w - 4, curses.A_BOLD)
            except curses.error:
                pass
            # entries
            max_rows = win_h - 5
            start = 0
            if browser.selection >= max_rows:
                start = browser.selection - max_rows + 1
            for i in range(start, min(len(browser.entries), start + max_rows)):
                name = browser.entries[i]
                attr = curses.A_REVERSE if i == browser.selection else 0
                try:
                    win.addnstr(2 + i - start, 2, name[: win_w - 4], win_w - 4, attr)
                except curses.error:
                    pass
            # footer/help
            help_line = "Enter: open/select  Backspace: up  ESC: cancel"
            try:
                win.addnstr(win_h - 2, 2, help_line[: win_w - 4], win_w - 4, curses.A_DIM)
            except curses.error:
                pass
            win.refresh()

            ch = win.getch()
            if ch in (27,):
                return None
            elif ch == curses.KEY_UP:
                browser.up()
            elif ch == curses.KEY_DOWN:
                browser.down()
            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                browser.parent()
            elif ch in (curses.KEY_ENTER, 10, 13):
                # Enter: enter dir or select file
                name = browser.entries[browser.selection] if browser.entries else None
                if not name:
                    continue
                if name.endswith('/'):
                    browser.enter()
                else:
                    return os.path.join(browser.root, name)

    def help(self):
        h, w = self.stdscr.getmaxyx()
        text = [
            "ytx-tag help",
            "",
            "Navigation:",
            "  ↑/↓        Move in file list or fields",
            "  ←/→, Tab   Switch between files and tags panes",
            "  Enter      Open dir/file (left) or edit field (right)",
            "  Backspace  Up to parent dir",
            "  o          Open music file via modal picker",
            "",
            "Editing:",
            "  s          Save tags",
            "  r          Reload tags from file",
            "  c / C      Set cover (choose image) / Clear cover",
            "",
            "File picker (modal):",
            "  ↑/↓        Move",
            "  Enter      Enter directory / select file",
            "  Backspace  Go to parent directory",
            "  ESC        Cancel",
            "",
            "Other:",
            "  q          Quit",
            "  h or ?     Show this help",
        ]
        win_h = min(len(text) + 4, max(10, h - 4))
        win_w = min(max(len(max(text, key=len)) + 4, 40), w - 4)
        y = h // 2 - win_h // 2
        x = w // 2 - win_w // 2
        win = curses.newwin(win_h, win_w, y, x)
        win.box()
        for i, line in enumerate(text[: win_h - 2]):
            win.addnstr(1 + i, 2, line[: win_w - 4], win_w - 4)
        win.addnstr(win_h - 1, 2, "Press any key to close", win_w - 4, curses.A_DIM)
        win.refresh()
        win.getch()

    def loop(self):
        curses.curs_set(0)
        self.draw()
        while True:
            try:
                ch = self.stdscr.getch()
            except KeyboardInterrupt:
                break

            # Global hotkeys
            if ch in (ord('o'),):
                # modal open music file
                picked = self.file_picker("Open music file", SUPPORTED_EXTS)
                if picked:
                    self.current_path = picked
                    # sync browser to the file's directory
                    self.browser.root = os.path.dirname(picked)
                    self.browser.refresh()
                    # set selection to file
                    base = os.path.basename(picked)
                    if base in self.browser.entries:
                        self.browser.selection = self.browser.entries.index(base)
                    self.load_current()
                    self.focus = 'tags'
                    self.draw()
                continue

            if ch in (ord('q'), ord('Q')):
                if self.dirty:
                    # Confirm discard
                    ans = self.prompt_input("Unsaved changes, type 'yes' to quit: ", "")
                    if ans != 'yes':
                        self.draw()
                        continue
                break

            if ch in (ord('h'), ord('?')):
                self.help()
                self.draw()
                continue

            # Navigation keys
            if ch == curses.KEY_UP:
                if self.focus == "browser":
                    self.browser.up()
                    self.draw()
                elif self.focus == "tags":
                    self.cursor_field = (self.cursor_field - 1) % len(DEFAULT_FIELDS)
                    self.draw()
            elif ch == curses.KEY_DOWN:
                if self.focus == "browser":
                    self.browser.down()
                    self.draw()
                elif self.focus == "tags":
                    self.cursor_field = (self.cursor_field + 1) % len(DEFAULT_FIELDS)
                    self.draw()
            elif ch in (curses.KEY_BACKSPACE, 127, 8):
                if self.focus == "browser":
                    self.browser.parent()
                    self.current_path = None
                    self.load_current()
                    self.draw()
            
            # Enter key
            elif ch in (curses.KEY_ENTER, 10, 13, ord('e')):
                if self.focus == "browser":
                    path = self.browser.enter()
                    if path:
                        self.current_path = path
                        self.load_current()
                        self.focus = "tags"  # switch to tags after opening file
                    self.draw()
                elif self.focus == "tags":
                    self.edit_field(self.cursor_field)
                    self.draw()
            
            # Tab to switch panels
            elif ch in (9, curses.KEY_BTAB):
                # Cycle: browser -> tags -> browser
                if self.focus == "browser":
                    self.focus = "tags"
                elif self.focus == "tags":
                    self.focus = "browser"
                self.draw()
            
            # Tag editing shortcuts (work in any panel if file selected)
            elif ch in (ord('s'), ord('S')):
                self.save_current()
                self.draw()
            elif ch in (ord('r'), ord('R')):
                self.load_current()
                self.draw()
            elif ch == ord('C'):
                if self.current_path:
                    io = TagIO(self.current_path)
                    ok, err = io.clear_cover()
                    if ok:
                        self.status_msg = "Cover cleared"
                    else:
                        self.status_msg = f"Cover clear failed: {err}"
                    self.cover_info = io.get_cover_info()
                    self.draw()
            elif ch in (ord('c'),):
                # choose image and set as cover
                img = self.file_picker("Select image for cover", IMAGE_EXTS)
                if img and self.current_path:
                    io = TagIO(self.current_path)
                    ok, err = io.set_cover(img)
                    if ok:
                        self.status_msg = "Cover set"
                    else:
                        self.status_msg = f"Cover set failed: {err}"
                    self.cover_info = io.get_cover_info()
                    self.draw()
            

# ---- Theming ----
class Theme:
    def __init__(self):
        self.color_header = curses.color_pair(1) | curses.A_BOLD
        self.color_status = curses.color_pair(2)
        self.color_help = curses.color_pair(3)
        self.color_panel_title = curses.color_pair(4) | curses.A_BOLD
        self.color_focus = curses.color_pair(5)
        self.color_dim = curses.A_DIM


def init_colors():
    if not curses.has_colors():
        return
    curses.start_color()
    try:
        curses.use_default_colors()
    except Exception:
        pass
    # pair: (fg, bg) try to be readable in most terminals
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)     # header
    curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_WHITE)    # status
    curses.init_pair(3, curses.COLOR_CYAN, -1)                     # help text
    curses.init_pair(4, curses.COLOR_YELLOW, -1)                   # panel title
    curses.init_pair(5, curses.COLOR_BLACK, curses.COLOR_YELLOW)   # selection focus


def main(stdscr, start_path: str):
    init_colors()
    stdscr.keypad(True)
    app = Tui(stdscr, start_path)
    app.theme = Theme()
    app.draw()
    app.loop()


if __name__ == "__main__":
    locale.setlocale(locale.LC_ALL, "")
    start = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    if not os.path.isdir(start):
        print(f"Start path must be a directory: {start}")
        sys.exit(1)
    if MutagenFile is None:
        print("This tool requires mutagen. Install with: pip install -r requirements.txt")
        sys.exit(2)
    curses.wrapper(main, start)
