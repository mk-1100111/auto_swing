# -*- coding: utf-8 -*-
"""Swing UIA Inspector - pywinauto + tkinter, Windows only for live scanning."""
from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
import os
import queue
import re
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

APP_TITLE = "Swing UIA Inspector"
APP_VERSION = "1.2.0"
DEFAULT_WINDOW_RE = r"^Swing$"
MAX_DOCUMENT_CHARS = 500
MAX_FIELD_CHARS = 6000


def normalized(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def clipped(value: str, limit: int) -> str:
    return value if len(value) <= limit else value[:limit] + f" ... [생략 {len(value)-limit:,}자]"


@dataclass(frozen=True)
class ControlRecord:
    number: int
    control_type: str
    auto_id: str = ""
    name: str = ""
    window_text: str = ""
    value: str = ""
    rect: str = ""
    class_name: str = ""
    source: str = "Swing"
    match_index: int = 0
    match_count: int = 1

    @property
    def text(self) -> str:
        parts = []
        for item in (self.window_text, self.name, self.value):
            if item and item not in parts:
                parts.append(item)
        return " | ".join(parts)


def record_key(rec: ControlRecord) -> tuple[str, str, str]:
    """Used to count controls with the same visible locator in the scan."""
    if rec.auto_id:
        return ("id", rec.control_type, rec.auto_id)
    if rec.name:
        return ("name", rec.control_type, rec.name)
    if rec.window_text:
        return ("text", rec.control_type, rec.window_text)
    return ("none", rec.control_type, "")


def add_duplicate_info(records: list[ControlRecord]) -> list[ControlRecord]:
    totals: dict[tuple[str, str, str], int] = {}
    for item in records:
        key = record_key(item)
        totals[key] = totals.get(key, 0) + 1
    seen: dict[tuple[str, str, str], int] = {}
    output = []
    for item in records:
        key = record_key(item)
        index = seen.get(key, 0)
        seen[key] = index + 1
        output.append(replace(item, match_index=index, match_count=totals[key]))
    return output


def read_live(window_re: str) -> tuple[list[ControlRecord], int]:
    """Executed in a worker thread; initializes COM in *that* thread."""
    if sys.platform != "win32":
        raise RuntimeError("Swing 실시간 조회는 Windows에서만 실행할 수 있습니다.")

    # Must initialize COM separately in each thread that makes UIA requests.
    # Align COM threading model with pywinauto default (MTA).
    sys.coinit_flags = 0
    import comtypes
    comtypes.CoInitializeEx(0)
    try:
        from pywinauto.application import Application
        from pywinauto import findwindows
        try:
            handles = findwindows.find_windows(title_re=window_re, backend="uia")
        except re.error as exc:
            raise RuntimeError(f"창 제목 정규식이 잘못되었습니다: {exc}") from exc
        if not handles:
            raise RuntimeError("Swing 창을 찾지 못했습니다. Swing 실행 상태와 창 제목을 확인하세요.")
        hwnd = handles[0]
        app = Application(backend="uia").connect(handle=hwnd, timeout=5)
        dlg = app.window(handle=hwnd)
        records: list[ControlRecord] = []

        for widget in dlg.descendants():
            try:
                if not widget.is_visible():
                    continue
                rc = widget.rectangle()
                if rc.width() <= 1 or rc.height() <= 1:
                    continue
                info = widget.element_info
                control_type = normalized(getattr(info, "control_type", ""))
                auto_id = normalized(getattr(info, "automation_id", ""))
                name = normalized(getattr(info, "name", ""))
                class_name = normalized(getattr(info, "class_name", ""))

                window_text = ""
                try:
                    window_text = normalized(widget.window_text())
                except Exception:
                    pass

                value = ""
                # Same ValuePattern collection behavior as the original script.
                try:
                    if hasattr(widget, "get_value"):
                        value = normalized(widget.get_value())
                except Exception:
                    pass

                # Empty decorative elements add little value. Keep unlabeled
                # controls when their AutomationId is present.
                if not (auto_id or name or window_text or value):
                    continue
                if control_type == "Document":
                    window_text = clipped(window_text, MAX_DOCUMENT_CHARS)
                    name = clipped(name, MAX_DOCUMENT_CHARS)
                else:
                    window_text = clipped(window_text, MAX_FIELD_CHARS)
                    name = clipped(name, MAX_FIELD_CHARS)
                    value = clipped(value, MAX_FIELD_CHARS)
                records.append(ControlRecord(
                    number=len(records)+1,
                    control_type=control_type,
                    auto_id=auto_id,
                    name=name,
                    window_text=window_text,
                    value=value,
                    rect=f"{rc.left}, {rc.top}, {rc.right}, {rc.bottom}",
                    class_name=class_name,
                ))
            except Exception:
                # A UIA element may disappear mid-scan due to page refresh.
                continue
        return add_duplicate_info(records), hwnd
    finally:
        comtypes.CoUninitialize()


# Log import supports the output of the user's existing autoid.py.
LOG_RE = re.compile(r"^\[(?P<kind>[^\]]{1,24})\]\s+ID=(?P<id>.*?)\s+TEXT=(?P<text>.*)$")


def parse_console_log(contents: str) -> list[ControlRecord]:
    raw: list[dict[str, str]] = []
    for line in contents.splitlines():
        match = LOG_RE.match(line)
        if match:
            raw.append({
                "kind": match.group("kind").strip(),
                "id": match.group("id").strip(),
                "text": match.group("text").strip(),
            })
        elif raw and line.strip() and not line.startswith("PS "):
            # A multiline Document prints line breaks without new [Type] tags.
            if raw[-1]["kind"] == "Document":
                raw[-1]["text"] += "\n" + line.strip()
    records = [ControlRecord(
        number=i+1,
        control_type=x["kind"],
        auto_id=x["id"],
        name=clipped(x["text"], MAX_DOCUMENT_CHARS if x["kind"] == "Document" else MAX_FIELD_CHARS),
        source="TXT 로그",
    ) for i, x in enumerate(raw)]
    return add_duplicate_info(records)


def locator_code(rec: ControlRecord, title_re: str = DEFAULT_WINDOW_RE,
                 action: str = "find") -> str:
    """Produce copyable Python; never executes any action in Swing."""
    prefix = (
        "from pywinauto.application import Application\n"
        "from pywinauto import findwindows\n\n"
        f"handles = findwindows.find_windows(title_re={title_re!r}, backend='uia')\n"
        "if not handles:\n"
        "    raise RuntimeError('Swing 창을 찾지 못했습니다.')\n"
        "app = Application(backend='uia').connect(handle=handles[0], timeout=5)\n"
        "dlg = app.window(handle=handles[0])\n"
    )
    typ = rec.control_type
    if rec.source == "TXT 로그" and rec.control_type == "Document" and not rec.auto_id:
        return prefix + "\n# 로그에서 잘린 Document 텍스트는 재탐색 조건으로 사용할 수 없습니다.\n"
    if rec.auto_id and rec.match_count == 1:
        selector = f"target = dlg.child_window(auto_id={rec.auto_id!r}, control_type={typ!r})\n"
    else:
        if rec.auto_id:
            criterion = "(w.element_info.automation_id or '') == " + repr(rec.auto_id)
        elif rec.name:
            criterion = ("(w.element_info.automation_id or '') == '' "
                         "and (w.element_info.name or '') == " + repr(rec.name))
        elif rec.window_text:
            criterion = ("(w.element_info.automation_id or '') == '' "
                         "and (w.window_text() or '') == " + repr(rec.window_text))
        else:
            return prefix + "\n# 이 컨트롤에는 재조회에 필요한 ID/Name/Text가 없습니다.\n"
        selector = (
            "# ID가 중복되거나 없어서 같은 조건의 visible 컨트롤 중 순번으로 선택합니다.\n"
            "# 화면 구조가 바뀌면 순번이 달라질 수 있습니다.\n"
            "candidates = [\n"
            "    w for w in dlg.descendants()\n"
            "    if w.is_visible()\n"
            f"    and w.element_info.control_type == {typ!r}\n"
            f"    and {criterion}\n"
            "]\n"
            f"if len(candidates) <= {rec.match_index}:\n"
            "    raise RuntimeError('일치하는 컨트롤을 찾지 못했습니다.')\n"
            f"target = candidates[{rec.match_index}]\n"
        )
    suffix = "\n# 찾은 컨트롤 정보\nprint(target.window_text())\n"
    if action == "click":
        suffix = "\n# 실제 클릭 (의도한 대상인지 확인한 다음 실행하세요)\ntarget.click_input()\n"
    elif action == "input":
        if typ != "Edit":
            suffix = "\n# 입력 코드는 Edit 컨트롤에서만 제공합니다.\n"
        else:
            suffix = "\n# 입력값 수정: 아래 문자열을 바꾼 뒤 실행하세요.\ntarget.set_edit_text('입력할 값')\n"
    return prefix + "\n" + selector + suffix


def rectangle_center(rect: str) -> tuple[int, int] | None:
    """Convert a captured UIA LTRB rectangle into its on-screen center."""
    try:
        values = [int(part.strip()) for part in rect.split(",")]
    except (AttributeError, TypeError, ValueError):
        return None
    if len(values) != 4:
        return None
    left, top, right, bottom = values
    if left >= right or top >= bottom:
        return None
    # Negative coordinates are supported for monitors left/above the primary one.
    return ((left + right) // 2, (top + bottom) // 2)


def move_cursor(x: int, y: int) -> None:
    """Move the Windows mouse pointer, without a click or keyboard input."""
    if sys.platform != "win32":
        raise RuntimeError("마우스 좌표 이동 기능은 Windows에서만 사용할 수 있습니다.")
    import ctypes
    if not ctypes.windll.user32.SetCursorPos(x, y):
        raise ctypes.WinError()


class Inspector(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"{APP_TITLE} v{APP_VERSION}")
        self.geometry("1450x850")
        self.minsize(1010, 620)
        self.configure(bg="#f4f7fb")
        self.records: list[ControlRecord] = []
        self.displayed: dict[str, ControlRecord] = {}
        self.events: queue.Queue = queue.Queue()
        self.scanning = False
        self.source_label = ""
        self.window_regex = tk.StringVar(value=DEFAULT_WINDOW_RE)
        self.search_var = tk.StringVar()
        self.type_var = tk.StringVar(value="전체")
        self.ids_only_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Swing 실행 후 [새로고침]을 누르거나 기존 TXT 로그를 불러오세요.")
        self.metrics_var = tk.StringVar(value="0개 컨트롤")
        self.detail_var = tk.StringVar(value="컨트롤을 선택하면 상세 정보가 표시됩니다.")
        self.note_file = self._note_path()
        self._note_job: str | None = None
        self._filter_job: str | None = None
        self._closed = False
        self._style()
        self._build()
        self._load_notes()
        self.search_var.trace_add("write", lambda *_: self._queue_filter())
        self.type_var.trace_add("write", lambda *_: self._queue_filter())
        self.ids_only_var.trace_add("write", lambda *_: self._queue_filter())
        self.bind("<F5>", lambda _event: self.refresh())
        self.bind("<Control-f>", self._focus_search)
        self.bind("<Control-s>", lambda _event: self.save_notes())
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._drain_events)

    @staticmethod
    def _note_path() -> Path:
        # Keep notes in an app-data directory instead of mixing with Swing data.
        base = os.getenv("LOCALAPPDATA")
        if base:
            return Path(base) / "Swing_UIA_Inspector" / "notes.txt"
        return Path.home() / ".swing_uia_inspector" / "notes.txt"

    def _style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("App.TFrame", background="#f4f7fb")
        style.configure("Panel.TFrame", background="#ffffff")
        style.configure("Title.TLabel", background="#f4f7fb", foreground="#14213d",
                        font=("맑은 고딕", 16, "bold"))
        style.configure("Sub.TLabel", background="#f4f7fb", foreground="#53647b",
                        font=("맑은 고딕", 9))
        style.configure("PanelTitle.TLabel", background="#ffffff", foreground="#14213d",
                        font=("맑은 고딕", 11, "bold"))
        style.configure("Panel.TLabel", background="#ffffff", foreground="#394960",
                        font=("맑은 고딕", 9))
        style.configure("TButton", font=("맑은 고딕", 9), padding=(10, 6))
        style.configure("Accent.TButton", background="#2563eb", foreground="#ffffff")
        style.map("Accent.TButton", background=[("active", "#1d4ed8"), ("disabled", "#a9bce0")])
        style.configure("Treeview", font=("맑은 고딕", 9), rowheight=27,
                        background="#ffffff", fieldbackground="#ffffff", foreground="#26354b")
        style.configure("Treeview.Heading", font=("맑은 고딕", 9, "bold"),
                        background="#eaf0f9", foreground="#253858")
        style.map("Treeview", background=[("selected", "#cfe0ff")],
                  foreground=[("selected", "#13294b")])
        style.configure("TCombobox", font=("맑은 고딕", 9))

    def _build(self) -> None:
        outer = ttk.Frame(self, style="App.TFrame", padding=14)
        outer.pack(fill="both", expand=True)
        heading = ttk.Frame(outer, style="App.TFrame")
        heading.pack(fill="x", pady=(0, 10))
        ttk.Label(heading, text="Swing UIA Inspector", style="Title.TLabel").pack(side="left")
        ttk.Label(heading, text="컨트롤 검색 · Auto ID 복사 · 코드 생성 · 로컬 메모",
                  style="Sub.TLabel").pack(side="left", padx=(18, 0), pady=(7, 0))

        tools = ttk.Frame(outer, style="App.TFrame")
        tools.pack(fill="x", pady=(0, 8))
        ttk.Label(tools, text="창 제목", style="Sub.TLabel").pack(side="left")
        ttk.Entry(tools, textvariable=self.window_regex, width=18).pack(side="left", padx=(7, 9))
        self.refresh_button = ttk.Button(tools, text="↻  새로고침  F5", style="Accent.TButton",
                                         command=self.refresh)
        self.refresh_button.pack(side="left", padx=(0, 7))
        ttk.Button(tools, text="TXT 로그 불러오기", command=self.open_log).pack(side="left", padx=(0, 7))
        ttk.Button(tools, text="CSV 내보내기", command=self.export_csv).pack(side="left")
        self.spinner = ttk.Progressbar(tools, mode="indeterminate", length=90)
        self.spinner.pack(side="right", padx=(8, 0))

        filters = ttk.Frame(outer, style="App.TFrame")
        filters.pack(fill="x", pady=(0, 10))
        ttk.Label(filters, text="검색 (ID / 텍스트 / 값)", style="Sub.TLabel").pack(side="left")
        self.search = ttk.Entry(filters, textvariable=self.search_var, width=46)
        self.search.pack(side="left", fill="x", expand=True, padx=(8, 10))
        ttk.Label(filters, text="유형", style="Sub.TLabel").pack(side="left")
        self.type_box = ttk.Combobox(filters, width=15, textvariable=self.type_var,
                                     state="readonly", values=["전체"])
        self.type_box.pack(side="left", padx=(7, 14))
        ttk.Checkbutton(filters, text="Auto ID 있는 항목만", variable=self.ids_only_var).pack(side="left")

        panes = ttk.Panedwindow(outer, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left = ttk.Frame(panes, style="Panel.TFrame", padding=9)
        right = ttk.Frame(panes, style="Panel.TFrame", padding=9)
        panes.add(left, weight=7)
        panes.add(right, weight=4)

        left_header = ttk.Frame(left, style="Panel.TFrame")
        left_header.pack(fill="x", pady=(0, 6))
        ttk.Label(left_header, text="컨트롤 목록", style="PanelTitle.TLabel").pack(side="left")
        ttk.Label(left_header, textvariable=self.metrics_var, style="Panel.TLabel").pack(side="right")
        tree_frame = ttk.Frame(left, style="Panel.TFrame")
        tree_frame.pack(fill="both", expand=True)
        columns = ("no", "kind", "id", "text", "rect")
        self.tree = ttk.Treeview(tree_frame, columns=columns, show="headings", selectmode="browse")
        defs = {
            "no": ("번호", 56, "center", False),
            "kind": ("유형", 113, "w", False),
            "id": ("Auto ID", 260, "w", True),
            "text": ("텍스트 / 값", 365, "w", True),
            "rect": ("좌표 (LTRB) · 더블클릭 이동", 215, "w", False),
        }
        for field, (label, width, anchor, stretch) in defs.items():
            self.tree.heading(field, text=label)
            self.tree.column(field, width=width, minwidth=40, anchor=anchor, stretch=stretch)
        vs = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        hs = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        hs.grid(row=1, column=0, sticky="ew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", lambda _event: self._selection_changed())
        self.tree.bind("<Control-c>", self._copy_tree_id)
        self.tree.bind("<Double-1>", self._tree_double_click)
        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="Auto ID 복사", command=lambda: self.copy_field("auto_id"))
        self.menu.add_command(label="텍스트 복사", command=lambda: self.copy_field("text"))
        self.menu.add_command(label="값 복사", command=lambda: self.copy_field("value"))
        self.menu.add_command(label="좌표로 마우스 이동", command=self.move_to_selected_coordinates)
        self.menu.add_separator()
        self.menu.add_command(label="요소 찾기 코드 복사", command=lambda: self.copy_code("find"))
        self.menu.add_command(label="메모에 추가", command=self.append_to_notes)
        self.tree.bind("<Button-3>", self._open_context_menu)

        right_panes = ttk.Panedwindow(right, orient="vertical")
        right_panes.pack(fill="both", expand=True)
        detail_frame = ttk.Frame(right_panes, style="Panel.TFrame", padding=(4, 2))
        note_frame = ttk.Frame(right_panes, style="Panel.TFrame", padding=(4, 2))
        right_panes.add(detail_frame, weight=5)
        right_panes.add(note_frame, weight=4)

        ttk.Label(detail_frame, text="선택 항목 상세", style="PanelTitle.TLabel").pack(anchor="w", pady=(0, 6))
        details_container = ttk.Frame(detail_frame, style="Panel.TFrame")
        details_container.pack(fill="both", expand=True)
        self.detail_text = tk.Text(details_container, wrap="word", borderwidth=1, relief="solid",
                                   bg="#f9fbff", fg="#213047", font=("Consolas", 10),
                                   padx=10, pady=8, state="disabled", height=9)
        detail_scroll = ttk.Scrollbar(details_container, orient="vertical", command=self.detail_text.yview)
        self.detail_text.configure(yscrollcommand=detail_scroll.set)
        self.detail_text.pack(side="left", fill="both", expand=True)
        detail_scroll.pack(side="right", fill="y")
        actions = ttk.Frame(detail_frame, style="Panel.TFrame")
        actions.pack(fill="x", pady=(7, 0))
        for label, cb in (
            ("ID 복사", lambda: self.copy_field("auto_id")),
            ("텍스트 복사", lambda: self.copy_field("text")),
            ("값 복사", lambda: self.copy_field("value")),
            ("좌표 복사", lambda: self.copy_field("rect")),
        ):
            ttk.Button(actions, text=label, command=cb).pack(side="left", padx=(0, 5))
        ttk.Button(actions, text="좌표로 이동", command=self.move_to_selected_coordinates).pack(
            side="left", padx=(0, 5))
        code_actions = ttk.Frame(detail_frame, style="Panel.TFrame")
        code_actions.pack(fill="x", pady=(5, 0))
        for label, action in (("찾기 코드 복사", "find"), ("클릭 코드 복사", "click"),
                              ("입력 코드 복사", "input")):
            ttk.Button(code_actions, text=label, command=lambda a=action: self.copy_code(a)).pack(
                side="left", padx=(0, 5))

        note_title = ttk.Frame(note_frame, style="Panel.TFrame")
        note_title.pack(fill="x", pady=(6, 5))
        ttk.Label(note_title, text="자동화 메모장", style="PanelTitle.TLabel").pack(side="left")
        ttk.Button(note_title, text="선택 항목 추가", command=self.append_to_notes).pack(side="right")
        notes_container = ttk.Frame(note_frame, style="Panel.TFrame")
        notes_container.pack(fill="both", expand=True)
        self.notes = tk.Text(notes_container, wrap="word", borderwidth=1, relief="solid",
                             bg="#ffffff", fg="#213047", padx=10, pady=8,
                             font=("맑은 고딕", 10), undo=True, height=7)
        nscroll = ttk.Scrollbar(notes_container, orient="vertical", command=self.notes.yview)
        self.notes.configure(yscrollcommand=nscroll.set)
        self.notes.pack(side="left", fill="both", expand=True)
        nscroll.pack(side="right", fill="y")
        self.notes.bind("<<Modified>>", self._notes_modified)
        note_bottom = ttk.Frame(note_frame, style="Panel.TFrame")
        note_bottom.pack(fill="x", pady=(5, 0))
        ttk.Label(note_bottom, text="자동 저장 · PC 로컬 저장", style="Panel.TLabel").pack(side="left")
        ttk.Button(note_bottom, text="메모 저장  Ctrl+S", command=self.save_notes).pack(side="right")

        foot = ttk.Frame(outer, style="App.TFrame")
        foot.pack(fill="x", pady=(7, 0))
        ttk.Label(foot, textvariable=self.status_var, style="Sub.TLabel").pack(side="left", fill="x", expand=True)
        ttk.Label(foot, text="F5 새로고침   ·   좌표 열 더블클릭 → 커서 이동 (클릭 없음)",
                  style="Sub.TLabel").pack(side="right")

    def _focus_search(self, _event=None):
        self.search.focus_set()
        self.search.select_range(0, "end")
        return "break"

    def refresh(self) -> None:
        if self.scanning:
            return
        title_re = self.window_regex.get().strip() or DEFAULT_WINDOW_RE
        try:
            re.compile(title_re)
        except re.error as exc:
            messagebox.showerror("창 제목 오류", str(exc))
            return
        self.scanning = True
        self.refresh_button.configure(state="disabled")
        self.spinner.start(12)
        self.status_var.set("Swing의 현재 화면을 읽는 중입니다. UI는 계속 사용할 수 있습니다.")
        def worker():
            try:
                records, hwnd = read_live(title_re)
                self.events.put(("data", records, f"Swing 실시간 (HWND {hwnd})"))
            except Exception as exc:
                self.events.put(("error", str(exc)))
        threading.Thread(target=worker, daemon=True, name="SwingUIAScanner").start()

    def _drain_events(self) -> None:
        if self._closed:
            return
        try:
            while True:
                event = self.events.get_nowait()
                self.scanning = False
                self.refresh_button.configure(state="normal")
                self.spinner.stop()
                if event[0] == "error":
                    self.status_var.set(event[1])
                    messagebox.showerror("조회 실패", event[1])
                elif event[0] == "data":
                    self._set_records(event[1], event[2])
        except queue.Empty:
            pass
        self.after(120, self._drain_events)

    def _set_records(self, records: list[ControlRecord], source_label: str) -> None:
        self.records = records
        self.source_label = source_label
        options = ["전체"] + sorted({r.control_type for r in records})
        self.type_box.configure(values=options)
        if self.type_var.get() not in options:
            self.type_var.set("전체")
        self._apply_filter()
        self.status_var.set(f"{source_label} · {datetime.now():%Y-%m-%d %H:%M:%S} · {len(records):,}개 읽기 완료")

    def open_log(self) -> None:
        filename = filedialog.askopenfilename(
            title="autoid.py 출력 TXT 선택",
            filetypes=[("텍스트 로그", "*.txt *.log"), ("모든 파일", "*.*")],
        )
        if not filename:
            return
        try:
            contents = Path(filename).read_text(encoding="utf-8-sig")
            records = parse_console_log(contents)
            if not records:
                raise ValueError("'[Button] ID=... TEXT=...' 형식의 항목을 찾지 못했습니다.")
            self._set_records(records, f"TXT 로그 ({Path(filename).name})")
        except Exception as exc:
            messagebox.showerror("로그 읽기 실패", str(exc))

    def _queue_filter(self) -> None:
        if self._filter_job is not None:
            self.after_cancel(self._filter_job)
        self._filter_job = self.after(150, self._apply_filter)

    def _apply_filter(self) -> None:
        self._filter_job = None
        old = self.tree.selection()
        old_no = self.displayed[old[0]].number if old and old[0] in self.displayed else None
        self.tree.delete(*self.tree.get_children())
        self.displayed.clear()
        word = self.search_var.get().casefold().strip()
        typ = self.type_var.get()
        filtered = []
        for item in self.records:
            if typ != "전체" and item.control_type != typ:
                continue
            if self.ids_only_var.get() and not item.auto_id:
                continue
            if word and word not in " ".join((item.auto_id, item.text, item.control_type,
                                              item.class_name, item.rect)).casefold():
                continue
            filtered.append(item)

        for item in filtered:
            iid = f"control-{item.number}"
            self.tree.insert("", "end", iid=iid, values=(
                item.number,
                item.control_type,
                item.auto_id or "(없음)",
                clipped(item.text.replace("\n", " "), 130),
                item.rect,
            ))
            self.displayed[iid] = item
        id_count = sum(bool(x.auto_id) for x in self.records)
        self.metrics_var.set(f"표시 {len(filtered):,} / 전체 {len(self.records):,} · ID {id_count:,}")
        if old_no is not None and f"control-{old_no}" in self.displayed:
            self.tree.selection_set(f"control-{old_no}")
        elif filtered:
            self.tree.selection_set(f"control-{filtered[0].number}")
        else:
            self._show_detail(None)

    def _selected(self) -> ControlRecord | None:
        selection = self.tree.selection()
        if not selection:
            return None
        return self.displayed.get(selection[0])

    def _selection_changed(self) -> None:
        self._show_detail(self._selected())

    def _show_detail(self, item: ControlRecord | None) -> None:
        if item is None:
            value = "컨트롤을 선택하세요."
        else:
            ambiguity = (f"{item.match_count}개 일치 · 그중 {item.match_index+1}번째"
                         if item.match_count > 1 else "유일한 조건")
            value = (
                f"번호       : {item.number}\n"
                f"유형       : {item.control_type}\n"
                f"Auto ID    : {item.auto_id or '(없음)'}\n"
                f"Name       : {item.name or '(없음)'}\n"
                f"Value      : {item.value or '(없음/미수집)'}\n"
                f"Window Text: {item.window_text or '(없음/미수집)'}\n"
                f"클래스     : {item.class_name or '(로그에는 없음)'}\n"
                f"좌표 LTRB  : {item.rect or '(로그에는 없음)'}\n"
                f"매칭 상태  : {ambiguity}\n"
                f"데이터 출처: {item.source}\n"
            )
            if not item.auto_id:
                value += "\n주의: Auto ID가 없어 Name/Text로 탐색하며, 중복 시 선택 순서가 바뀔 수 있습니다.\n"
            if item.control_type == "Document":
                value += "\n주의: Document에 여러 자식 텍스트가 합쳐져 표시될 수 있습니다.\n"
        self.detail_text.configure(state="normal")
        self.detail_text.delete("1.0", "end")
        self.detail_text.insert("1.0", value)
        self.detail_text.configure(state="disabled")

    def _clipboard(self, value: str, kind: str) -> None:
        if not value:
            self.status_var.set(f"선택 항목에는 복사할 {kind}가 없습니다.")
            return
        self.clipboard_clear()
        self.clipboard_append(value)
        self.update_idletasks()
        self.status_var.set(f"{kind} 클립보드에 복사했습니다.")

    def copy_field(self, field: str) -> None:
        item = self._selected()
        if item is None:
            self.status_var.set("먼저 컨트롤을 선택하세요.")
            return
        self._clipboard(getattr(item, field),
                        {"auto_id": "Auto ID", "text": "텍스트", "value": "Value", "rect": "좌표"}.get(field, field))

    def copy_code(self, action: str) -> None:
        item = self._selected()
        if item is None:
            self.status_var.set("먼저 컨트롤을 선택하세요.")
            return
        if action == "input" and item.control_type != "Edit":
            messagebox.showinfo("입력 불가", "입력 코드는 Edit 컨트롤에서만 생성할 수 있습니다.")
            return
        code = locator_code(item, self.window_regex.get().strip() or DEFAULT_WINDOW_RE, action)
        self._clipboard(code, "Python 자동화 코드")

    def move_to_selected_coordinates(self) -> None:
        """Move pointer to center of selected control; never activate/click it."""
        item = self._selected()
        if item is None:
            self.status_var.set("먼저 컨트롤을 선택하세요.")
            return
        center = rectangle_center(item.rect)
        if center is None:
            self.status_var.set("유효한 좌표가 없습니다. TXT 로그에는 좌표가 없으므로 Swing을 새로고침하세요.")
            return
        try:
            move_cursor(*center)
        except Exception as exc:
            self.status_var.set(f"마우스 이동 실패: {exc}")
            return
        self.status_var.set(f"{item.control_type} #{item.number} 중심 좌표 {center}로 마우스 이동 완료 (클릭 없음)")

    def _tree_double_click(self, event):
        """Double-clicking the coordinate column moves cursor; others copy ID."""
        row = self.tree.identify_row(event.y)
        if not row or row not in self.displayed:
            return "break"
        if self.tree.identify_region(event.x, event.y) != "cell":
            return "break"
        self.tree.selection_set(row)
        self.tree.focus(row)
        if self.tree.identify_column(event.x) == "#5":
            self.move_to_selected_coordinates()
        else:
            self.copy_field("auto_id")
        return "break"

    def _copy_tree_id(self, _event=None):
        self.copy_field("auto_id")
        return "break"

    def _open_context_menu(self, event):
        row_id = self.tree.identify_row(event.y)
        if row_id:
            self.tree.selection_set(row_id)
            self.tree.focus(row_id)
            try:
                self.menu.tk_popup(event.x_root, event.y_root)
            finally:
                self.menu.grab_release()

    def append_to_notes(self) -> None:
        item = self._selected()
        if item is None:
            self.status_var.set("먼저 컨트롤을 선택하세요.")
            return
        note = (f"\n[{datetime.now():%Y-%m-%d %H:%M}] {item.control_type}\n"
                f"Auto ID: {item.auto_id or '(없음)'}\n"
                f"TEXT: {clipped(item.text.replace(chr(10), ' '), 250)}\n"
                f"좌표: {item.rect or '(정보 없음)'}\n")
        self.notes.insert("end", note)
        self.notes.see("end")
        self._schedule_save_notes()
        self.status_var.set("선택 항목을 메모장에 추가했습니다.")

    def _notes_modified(self, _event=None) -> None:
        if self.notes.edit_modified():
            self.notes.edit_modified(False)
            self._schedule_save_notes()

    def _schedule_save_notes(self) -> None:
        if self._note_job:
            self.after_cancel(self._note_job)
        self._note_job = self.after(950, self.save_notes)

    def save_notes(self) -> None:
        if self._note_job is not None:
            self.after_cancel(self._note_job)
            self._note_job = None
        try:
            self.note_file.parent.mkdir(parents=True, exist_ok=True)
            content = self.notes.get("1.0", "end-1c")
            tmp_file = self.note_file.with_name("notes.tmp")
            tmp_file.write_text(content, encoding="utf-8")
            tmp_file.replace(self.note_file)
            self.status_var.set(f"메모 저장 완료: {self.note_file}")
        except Exception as exc:
            self.status_var.set(f"메모 저장 실패: {exc}")

    def _load_notes(self) -> None:
        if self.note_file.exists():
            try:
                self.notes.insert("1.0", self.note_file.read_text(encoding="utf-8"))
                self.notes.edit_modified(False)
            except OSError as exc:
                self.status_var.set(f"메모 불러오기 실패: {exc}")

    def export_csv(self) -> None:
        if not self.records:
            messagebox.showinfo("내보내기", "먼저 Swing을 읽거나 TXT 로그를 불러오세요.")
            return
        filename = filedialog.asksaveasfilename(
            title="컨트롤 데이터를 CSV로 내보내기", defaultextension=".csv",
            initialfile=f"swing_controls_{datetime.now():%Y%m%d_%H%M%S}.csv",
            filetypes=[("CSV 파일", "*.csv")],
        )
        if not filename:
            return
        try:
            with open(filename, "w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["번호", "유형", "Auto ID", "Name", "Window Text",
                                 "Value", "좌표 LTRB", "클래스", "중복 개수", "선택 순번"])
                for item in self.records:
                    writer.writerow([item.number, item.control_type, item.auto_id,
                                     item.name, item.window_text, item.value,
                                     item.rect, item.class_name,
                                     item.match_count, item.match_index+1])
            self.status_var.set(f"CSV 저장 완료: {filename} (고객정보 취급 주의)")
        except Exception as exc:
            messagebox.showerror("CSV 저장 실패", str(exc))

    def _on_close(self) -> None:
        self.save_notes()
        self._closed = True
        self.destroy()


def main() -> None:
    Inspector().mainloop()


if __name__ == "__main__":
    main()
