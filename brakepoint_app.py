#!/usr/bin/env python3
"""BrakePoint desktop app: record laps and open reports from one window.

This is what BrakePoint.exe runs. Sessions and reports are saved in folders
next to the .exe (or next to this file when run with Python).
"""
import json
import os
import pathlib
import queue
import sys
import threading
import tkinter as tk
import traceback
import webbrowser
from tkinter import messagebox, ttk

import analyze
from laps import fmt_time
from recorder import Recorder

VERSION = "1.1"

if getattr(sys, "frozen", False):          # running as BrakePoint.exe
    BASE = pathlib.Path(sys.executable).parent
else:
    BASE = pathlib.Path(__file__).parent
SESSIONS = BASE / "sessions"
REPORTS = BASE / "reports"

BG, PANEL, LINE = "#0d0f12", "#15191e", "#242a32"
TEXT, MUTE, ACCENT, GOOD = "#e9ecef", "#87909b", "#ff5a36", "#3ddc97"


def open_path(p):
    p = pathlib.Path(p)
    p.mkdir(parents=True, exist_ok=True) if not p.suffix else None
    if sys.platform == "win32":
        os.startfile(p)  # noqa: S606 - opening our own folder
    else:
        webbrowser.open(p.resolve().as_uri())


class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.stop = None
        self.thread = None
        self.sessions = {}      # display name -> path
        self.session = None     # loaded session dict
        self.lap_opts = {}      # display text -> lap dict

        root.title("BrakePoint")
        root.configure(bg=BG)
        root.minsize(520, 600)
        self._style()
        self._build()
        self.refresh_sessions()
        root.after(100, self.poll)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ---------- look ----------
    def _style(self):
        s = ttk.Style()
        s.theme_use("clam")
        s.configure(".", background=BG, foreground=TEXT, fieldbackground=PANEL, bordercolor=LINE,
                    font=("Segoe UI", 10))
        s.configure("Card.TFrame", background=PANEL, relief="flat")
        s.configure("Card.TLabel", background=PANEL, foreground=TEXT)
        s.configure("Mute.TLabel", background=PANEL, foreground=MUTE, font=("Segoe UI", 9))
        s.configure("H.TLabel", background=PANEL, foreground=MUTE, font=("Segoe UI", 9, "bold"))
        s.configure("Status.TLabel", background=PANEL, foreground=TEXT, font=("Segoe UI", 13, "bold"))
        s.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 18, "bold"))
        s.configure("Accent.TButton", background=ACCENT, foreground="#ffffff", borderwidth=0,
                    font=("Segoe UI", 11, "bold"), padding=(14, 9))
        s.map("Accent.TButton", background=[("active", "#ff7452"), ("disabled", "#5a3a33")])
        s.configure("TButton", background=PANEL, foreground=TEXT, bordercolor=LINE, padding=(10, 6))
        s.map("TButton", background=[("active", "#1d2228")])
        s.configure("TCombobox", foreground=TEXT, background=PANEL, arrowcolor=TEXT, padding=5)
        s.map("TCombobox", fieldbackground=[("readonly", PANEL)], foreground=[("readonly", TEXT)])
        self.root.option_add("*TCombobox*Listbox.background", PANEL)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)

    def _card(self, parent, title):
        f = ttk.Frame(parent, style="Card.TFrame", padding=16)
        f.pack(fill="x", padx=16, pady=(0, 12))
        ttk.Label(f, text=title.upper(), style="H.TLabel").pack(anchor="w", pady=(0, 8))
        return f

    def _build(self):
        head = tk.Frame(self.root, bg=BG)
        head.pack(fill="x", padx=16, pady=(14, 12))
        tk.Label(head, text="BRAKE", bg=BG, fg=TEXT, padx=0, bd=0, font=("Segoe UI", 18, "bold")).pack(side="left")
        tk.Label(head, text="POINT", bg=BG, fg=ACCENT, padx=0, bd=0, font=("Segoe UI", 18, "bold")).pack(side="left")
        tk.Label(head, text=f"v{VERSION}", bg=BG, fg=MUTE, font=("Segoe UI", 9)).pack(side="left", padx=8, pady=(8, 0))

        # record
        rec = self._card(self.root, "Record")
        self.status = ttk.Label(rec, text="Ready. Start recording, then drive in ACC.", style="Status.TLabel")
        self.status.pack(anchor="w")
        row = ttk.Frame(rec, style="Card.TFrame")
        row.pack(fill="x", pady=(10, 8))
        self.rec_btn = ttk.Button(row, text="●  Start recording", style="Accent.TButton", command=self.toggle_record)
        self.rec_btn.pack(side="left")
        self.demo_btn = ttk.Button(row, text="Try demo (no ACC)", command=self.run_demo)
        self.demo_btn.pack(side="left", padx=8)
        self.log = tk.Listbox(rec, height=6, bg=BG, fg=TEXT, bd=0, highlightthickness=1,
                              highlightbackground=LINE, font=("Consolas", 10), activestyle="none",
                              selectbackground=PANEL)
        self.log.pack(fill="x")

        # analyse
        an = self._card(self.root, "Analyse")
        grid = ttk.Frame(an, style="Card.TFrame")
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        ttk.Label(grid, text="Session", style="Card.TLabel").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Label(grid, text="Lap to analyse", style="Card.TLabel").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Label(grid, text="Compare against", style="Card.TLabel").grid(row=2, column=0, sticky="w", pady=4)
        self.sess_cb = ttk.Combobox(grid, state="readonly")
        self.cmp_cb = ttk.Combobox(grid, state="readonly")
        self.ref_cb = ttk.Combobox(grid, state="readonly")
        for i, cb in enumerate((self.sess_cb, self.cmp_cb, self.ref_cb)):
            cb.grid(row=i, column=1, sticky="ew", padx=(12, 0), pady=4)
        self.sess_cb.bind("<<ComboboxSelected>>", lambda e: self.load_session())
        row = ttk.Frame(an, style="Card.TFrame")
        row.pack(fill="x", pady=(12, 0))
        self.report_btn = ttk.Button(row, text="Open report", style="Accent.TButton", command=self.open_report)
        self.report_btn.pack(side="left")
        ttk.Button(row, text="Sessions folder", command=lambda: open_path(SESSIONS)).pack(side="left", padx=8)
        ttk.Button(row, text="Reports folder", command=lambda: open_path(REPORTS)).pack(side="left")
        self.hint = ttk.Label(an, text="", style="Mute.TLabel")
        self.hint.pack(anchor="w", pady=(10, 0))

    # ---------- recording ----------
    def toggle_record(self, demo=False):
        if self.thread and self.thread.is_alive():
            self.stop.set()
            self.rec_btn.configure(state="disabled", text="Stopping…")
            return
        self.stop = threading.Event()
        if demo:
            from mock_session import FakeACCReader
            stop = self.stop
            rec = Recorder(SESSIONS, hz=0, reader_factory=lambda: FakeACCReader(on_finish=stop.set))
        else:
            rec = Recorder(SESSIONS)
        self.log.delete(0, "end")

        def work():
            try:
                path = rec.run(self.stop, log=lambda m: self.q.put(("log", m)),
                               on_lap=lambda p, lap: self.q.put(("lap", p)))
                self.q.put(("done", path))
            except Exception as e:  # e.g. not on Windows / ACC memory unavailable
                self.q.put(("error", str(e) or traceback.format_exc()))

        self.thread = threading.Thread(target=work, daemon=True)
        self.thread.start()
        self.rec_btn.configure(text="■  Stop recording")
        self.demo_btn.configure(state="disabled")
        self.status.configure(text="Demo: replaying fake laps…" if demo else "Recording - waiting for ACC…",
                              foreground=ACCENT)

    def run_demo(self):
        self.toggle_record(demo=True)

    def poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self.log.insert("end", val)
                    self.log.see("end")
                    if val.startswith("Recording "):
                        self.status.configure(text=val)
                elif kind == "lap":
                    self.refresh_sessions(select=val)
                elif kind in ("done", "error"):
                    self.rec_btn.configure(state="normal", text="●  Start recording")
                    self.demo_btn.configure(state="normal")
                    if kind == "error":
                        self.status.configure(text="Couldn't start recording", foreground=ACCENT)
                        messagebox.showerror("BrakePoint", val)
                    else:
                        self.status.configure(text="Stopped. Pick laps below and open a report.",
                                              foreground=GOOD)
                        if val:
                            self.refresh_sessions(select=val)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    # ---------- analysis ----------
    def refresh_sessions(self, select=None):
        files = sorted(SESSIONS.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True) \
            if SESSIONS.exists() else []
        self.sessions = {f.stem: f for f in files}
        self.sess_cb["values"] = list(self.sessions)
        if not files:
            self.sess_cb.set("")
            self.hint.configure(text="No sessions yet. Record some laps (or try the demo).")
            return
        want = pathlib.Path(select).stem if select else (self.sess_cb.get() or files[0].stem)
        self.sess_cb.set(want if want in self.sessions else files[0].stem)
        self.load_session()

    def load_session(self):
        path = self.sessions.get(self.sess_cb.get())
        if not path:
            return
        try:
            self.session = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as e:
            self.hint.configure(text=f"Couldn't read session: {e}")
            return
        valid = [l for l in self.session["laps"] if l["valid"]]
        self.lap_opts = {}
        if len(valid) < 2:
            self.cmp_cb["values"] = self.ref_cb["values"] = []
            self.cmp_cb.set("")
            self.ref_cb.set("")
            self.hint.configure(text=f"{len(valid)} complete lap(s) so far. Need at least 2 to compare.")
            return
        best = min(valid, key=lambda l: l["time_ms"])
        for l in valid:
            tag = "  (best)" if l is best else ""
            self.lap_opts[f"Lap {l['lap']}  ·  {fmt_time(l['time_ms'])}{tag}"] = l
        names = list(self.lap_opts)
        best_name = next(n for n, l in self.lap_opts.items() if l is best)
        last_other = [n for n, l in self.lap_opts.items() if l is not best][-1]
        self.cmp_cb["values"] = names
        self.ref_cb["values"] = names
        # default: your latest lap vs your best (reset whenever laps change)
        self.cmp_cb.set(last_other)
        self.ref_cb.set(best_name)
        self.hint.configure(text=f"{self.session['track']} · {self.session['car']} · "
                                 f"{len(valid)} complete laps")

    def open_report(self):
        cmp = self.lap_opts.get(self.cmp_cb.get())
        ref = self.lap_opts.get(self.ref_cb.get())
        if not (cmp and ref):
            messagebox.showinfo("BrakePoint", "Pick a session with at least two complete laps.")
            return
        if cmp is ref:
            messagebox.showinfo("BrakePoint", "Pick two different laps to compare.")
            return
        REPORTS.mkdir(parents=True, exist_ok=True)
        stem = self.sessions[self.sess_cb.get()].stem
        out = REPORTS / f"{stem}_lap{cmp['lap']}_vs_{ref['lap']}.html"
        try:
            analyze.build_report(self.session, ref, cmp, out)
        except Exception as e:
            messagebox.showerror("BrakePoint", f"Couldn't build the report:\n{e}")
            return
        webbrowser.open(out.resolve().as_uri())

    def on_close(self):
        if self.stop:
            self.stop.set()
        self.root.after(250, self.root.destroy)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
