from __future__ import annotations

import queue
import threading
import webbrowser
from pathlib import Path
from tkinter import BOTH, END, LEFT, RIGHT, VERTICAL, X, Y, Tk, filedialog, messagebox, ttk

from .cli import default_report_path
from .core import (
    create_project,
    current_baseline_id,
    export_html,
    list_roots,
    list_scans,
    remap_root,
    scan_project,
    trust_scan,
)


class App:
    def __init__(self) -> None:
        self.window = Tk()
        self.window.title("FileIntegrityTimeline")
        self.window.geometry("900x640")
        self.project: Path | None = None
        self.pending_roots: list[tuple[str, str]] = []
        self.events: queue.Queue[tuple] = queue.Queue()
        self.cancel: threading.Event | None = None
        self.busy = False
        self._build()
        self.window.after(100, self._poll)

    def _build(self) -> None:
        main = ttk.Frame(self.window, padding=18)
        main.pack(fill=BOTH, expand=True)
        ttk.Label(main, text="FileIntegrityTimeline", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(
            main,
            text="Keep a trusted SHA-256 baseline, then check for added, missing, or changed files.",
        ).pack(anchor="w", pady=(0, 12))

        top = ttk.Frame(main)
        top.pack(fill=X)
        ttk.Button(top, text="New project", command=self.new_project).pack(side=LEFT)
        ttk.Button(top, text="Open project", command=self.open_project).pack(side=LEFT, padx=8)
        self.project_label = ttk.Label(top, text="No project open")
        self.project_label.pack(side=LEFT, padx=8)

        ttk.Label(main, text="Folders", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(16, 3))
        root_frame = ttk.Frame(main)
        root_frame.pack(fill=X)
        self.roots = ttk.Treeview(root_frame, columns=("id", "label", "path"), show="headings", height=5)
        for key, title, width in (("id", "ID", 50), ("label", "Label", 150), ("path", "Location", 600)):
            self.roots.heading(key, text=title)
            self.roots.column(key, width=width, stretch=key == "path")
        self.roots.pack(side=LEFT, fill=X, expand=True)
        root_scroll = ttk.Scrollbar(root_frame, orient=VERTICAL, command=self.roots.yview)
        root_scroll.pack(side=RIGHT, fill=Y)
        self.roots.configure(yscrollcommand=root_scroll.set)

        root_buttons = ttk.Frame(main)
        root_buttons.pack(fill=X, pady=(7, 0))
        ttk.Button(root_buttons, text="Add folder", command=self.add_folder).pack(side=LEFT)
        ttk.Button(root_buttons, text="Remove selected", command=self.remove_folder).pack(side=LEFT, padx=6)
        ttk.Button(root_buttons, text="Save new project", command=self.save_project).pack(side=LEFT, padx=6)
        ttk.Button(root_buttons, text="Change selected folder location", command=self.remap_folder).pack(side=LEFT, padx=6)

        ttk.Separator(main).pack(fill=X, pady=16)
        action_buttons = ttk.Frame(main)
        action_buttons.pack(fill=X)
        self.scan_button = ttk.Button(action_buttons, text="Create baseline / Check now", command=self.start_scan)
        self.scan_button.pack(side=LEFT)
        self.cancel_button = ttk.Button(action_buttons, text="Cancel scan", command=self.cancel_scan, state="disabled")
        self.cancel_button.pack(side=LEFT, padx=8)
        ttk.Button(action_buttons, text="Open selected report", command=self.open_report).pack(side=LEFT, padx=8)
        ttk.Button(action_buttons, text="Trust selected scan", command=self.trust_selected).pack(side=LEFT, padx=8)

        ttk.Label(main, text="Scan history", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(16, 3))
        history_frame = ttk.Frame(main)
        history_frame.pack(fill=BOTH, expand=True)
        self.history = ttk.Treeview(
            history_frame,
            columns=("id", "time", "status", "files", "added", "missing", "changed"),
            show="headings",
        )
        for key, title, width in (
            ("id", "ID", 45), ("time", "Started (UTC)", 190), ("status", "Status", 90),
            ("files", "Files", 75), ("added", "Added", 70), ("missing", "Missing", 70),
            ("changed", "Changed", 80),
        ):
            self.history.heading(key, text=title)
            self.history.column(key, width=width, stretch=key == "time")
        self.history.pack(side=LEFT, fill=BOTH, expand=True)
        history_scroll = ttk.Scrollbar(history_frame, orient=VERTICAL, command=self.history.yview)
        history_scroll.pack(side=RIGHT, fill=Y)
        self.history.configure(yscrollcommand=history_scroll.set)

        self.progress = ttk.Progressbar(main, mode="indeterminate")
        self.progress.pack(fill=X, pady=(12, 4))
        self.status = ttk.Label(main, text="Create a project to begin.", wraplength=850)
        self.status.pack(anchor="w")
        ttk.Label(
            main,
            text="Source files are only read. The project database and reports store full local paths; keep them private.",
            foreground="#5a6570",
        ).pack(anchor="w", pady=(10, 0))

    def _set_status(self, message: str) -> None:
        self.status.configure(text=message)

    def _refresh(self) -> None:
        self.roots.delete(*self.roots.get_children())
        self.history.delete(*self.history.get_children())
        if self.project:
            self.project_label.configure(text=str(self.project))
            for row in list_roots(self.project):
                self.roots.insert("", END, iid=str(row["id"]), values=(row["id"], row["label"], row["path"]))
            for row in list_scans(self.project):
                self.history.insert(
                    "", END, iid=str(row["id"]),
                    values=(row["id"], row["started_utc"], row["status"], row["file_count"],
                            row["added"], row["missing"], row["changed"]),
                )
            self._set_status(f"Trusted baseline: scan {current_baseline_id(self.project) or 'none'}")
        else:
            self.project_label.configure(text="New project: choose folders, then save")
            for index, (label, path) in enumerate(self.pending_roots):
                self.roots.insert("", END, iid=f"pending-{index}", values=("", label, path))

    def new_project(self) -> None:
        if self.busy:
            return
        self.project = None
        self.pending_roots.clear()
        self._refresh()

    def open_project(self) -> None:
        if self.busy:
            return
        name = filedialog.askopenfilename(filetypes=[("FileIntegrityTimeline project", "*.fit"), ("All files", "*.*")])
        if not name:
            return
        try:
            list_roots(name)
            self.project = Path(name).resolve()
            self.pending_roots.clear()
            self._refresh()
        except (OSError, ValueError) as exc:
            messagebox.showerror("Cannot open project", str(exc))

    def add_folder(self) -> None:
        if self.busy or self.project:
            messagebox.showinfo("Folder selection", "Create a new project to change the set of folders.")
            return
        path = filedialog.askdirectory(title="Select a folder to scan")
        if not path:
            return
        base = Path(path).name or "Drive"
        names = {label for label, _ in self.pending_roots}
        label = base
        suffix = 2
        while label in names:
            label = f"{base} {suffix}"
            suffix += 1
        self.pending_roots.append((label, path))
        self._refresh()

    def remove_folder(self) -> None:
        if self.project or self.busy:
            messagebox.showinfo("Folder selection", "Only unsaved new-project folders can be removed.")
            return
        selected = self.roots.selection()
        if selected:
            self.pending_roots.pop(int(selected[0].split("-")[1]))
            self._refresh()

    def save_project(self) -> None:
        if self.project or self.busy:
            return
        if not self.pending_roots:
            messagebox.showinfo("New project", "Add one or more folders first.")
            return
        name = filedialog.asksaveasfilename(
            defaultextension=".fit", filetypes=[("FileIntegrityTimeline project", "*.fit")],
            title="Save project outside the scanned folders",
        )
        if not name:
            return
        try:
            create_project(name, self.pending_roots)
            self.project = Path(name).resolve()
            self.pending_roots.clear()
            self._refresh()
            self._set_status("Project saved. Create the first trusted baseline when the folders are ready.")
        except (OSError, ValueError) as exc:
            messagebox.showerror("Cannot create project", str(exc))

    def remap_folder(self) -> None:
        if not self.project or self.busy:
            return
        selected = self.roots.selection()
        if not selected:
            messagebox.showinfo("Change location", "Select a folder row first.")
            return
        new_path = filedialog.askdirectory(title="Select the same folder at its new location")
        if not new_path:
            return
        try:
            remap_root(self.project, int(selected[0]), new_path)
            self._refresh()
        except (OSError, ValueError) as exc:
            messagebox.showerror("Cannot change location", str(exc))

    def start_scan(self) -> None:
        if not self.project or self.busy:
            return
        self.busy = True
        self.cancel = threading.Event()
        self.scan_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")
        self.progress.start(15)
        self._set_status("Reading and hashing files. This can take a long time for large drives.")
        project = self.project

        def worker() -> None:
            def progress(files: int, byte_count: int, current: str) -> None:
                if files % 25 == 0:
                    self.events.put(("progress", files, byte_count, current))

            try:
                result = scan_project(project, progress=progress, cancel=self.cancel)
                report = export_html(project, result["id"], default_report_path(project, result["id"]))
                self.events.put(("done", result, report))
            except Exception as exc:
                self.events.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True).start()

    def cancel_scan(self) -> None:
        if self.cancel:
            self.cancel.set()
            self._set_status("Cancelling. The current file read will finish first.")

    def _selected_scan(self) -> int | None:
        selected = self.history.selection()
        return int(selected[0]) if selected else None

    def open_report(self) -> None:
        if not self.project:
            return
        scan_id = self._selected_scan()
        if scan_id is None:
            messagebox.showinfo("Report", "Select a scan in the history first.")
            return
        try:
            path = export_html(self.project, scan_id, default_report_path(self.project, scan_id))
            webbrowser.open(path.as_uri())
        except (OSError, ValueError) as exc:
            messagebox.showerror("Cannot open report", str(exc))

    def trust_selected(self) -> None:
        if not self.project or self.busy:
            return
        scan_id = self._selected_scan()
        if scan_id is None:
            messagebox.showinfo("Trusted baseline", "Select a complete scan first.")
            return
        if not messagebox.askyesno(
            "Trust this scan?",
            f"Use scan {scan_id} as the reference for future checks? Its hashes will be treated as known good. "
            "Earlier scans and reports remain available.",
        ):
            return
        try:
            trust_scan(self.project, scan_id)
            self._refresh()
        except (OSError, ValueError) as exc:
            messagebox.showerror("Cannot trust scan", str(exc))

    def _poll(self) -> None:
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "progress":
                    self._set_status(f"Hashed {event[1]:,} files ({event[2]:,} bytes). Current: {event[3]}")
                else:
                    self.busy = False
                    self.cancel = None
                    self.progress.stop()
                    self.scan_button.configure(state="normal")
                    self.cancel_button.configure(state="disabled")
                    if event[0] == "done":
                        result, report = event[1], event[2]
                        self._refresh()
                        self.history.selection_set(str(result["id"]))
                        if result["status"] == "complete":
                            self._set_status(
                                f"Scan {result['id']} complete: {result['added']} added, {result['missing']} missing, "
                                f"{result['changed']} changed. Report: {report}"
                            )
                        else:
                            self._set_status(
                                f"Scan {result['id']} {result['status']}. No integrity verdict was calculated. "
                                f"Open its report for details."
                            )
                    else:
                        messagebox.showerror("Scan failed", event[1])
                        self._set_status("Scan failed. Review the error and try again.")
        except queue.Empty:
            pass
        self.window.after(100, self._poll)

    def run(self) -> None:
        self.window.mainloop()


def run_gui() -> None:
    App().run()
