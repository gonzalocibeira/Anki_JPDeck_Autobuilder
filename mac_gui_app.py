"""Simple Tkinter GUI for the Anki JP Deck Builder."""
from __future__ import annotations

import threading
import time
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from anki_deck_builder import (
    BuildError,
    BuildParams,
    BuildResult,
    DEFAULT_DECK_NAME,
    InputMode,
    NullBuildReporter,
    run_builder,
)


class TkBuildReporter(NullBuildReporter):
    """Report build progress to the Tkinter UI."""

    def __init__(
        self,
        root: tk.Tk,
        status_var: tk.StringVar,
        progress: ttk.Progressbar,
        time_var: tk.StringVar,
    ) -> None:
        super().__init__()
        self.root = root
        self.status_var = status_var
        self.progress = progress
        self.time_var = time_var
        self._start_time: float | None = None
        self._completed = 0
        self._total = 0

    def _dispatch(self, func, *args) -> None:
        self.root.after(0, lambda: func(*args))

    def _format_duration(self, seconds: float | None) -> str:
        if seconds is None:
            return "--"
        seconds = max(0, int(seconds))
        hours, remainder = divmod(seconds, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:02}:{minutes:02}:{secs:02}"

    def _schedule_time_update(self) -> None:
        if self._start_time is None:
            return

        elapsed = max(time.time() - self._start_time, 0)
        remaining: float | None = None
        if self._total and self._completed >= self._total:
            remaining = 0
        elif self._total and self._completed > 0 and elapsed > 0:
            rate = self._completed / elapsed
            if rate > 0:
                remaining = max((self._total - self._completed) / rate, 0)

        display = (
            f"Elapsed: {self._format_duration(elapsed)} — "
            f"Remaining: {self._format_duration(remaining)}"
        )
        self._dispatch(self.time_var.set, display)

    def info(self, message: str) -> None:
        self._dispatch(self.status_var.set, message)

    def warning(self, message: str) -> None:
        self._dispatch(self.status_var.set, f"Warning: {message}")

    def error(self, message: str) -> None:
        self._dispatch(self.status_var.set, f"Error: {message}")

    def debug(self, message: str) -> None:
        self._dispatch(self.status_var.set, message)

    def progress_start(self, total: int, description: str = "") -> None:
        self._total = total
        self._completed = 0
        self._start_time = time.time()

        def setup() -> None:
            self.progress.config(maximum=max(total, 1))
            self.progress["value"] = 0
            if description:
                self.status_var.set(description)
            self.time_var.set(
                f"Elapsed: {self._format_duration(0)} — Remaining: {self._format_duration(None)}"
            )

        self._dispatch(setup)

    def progress_advance(self, advance: int = 1) -> None:
        self._completed += advance
        if self._total:
            self._completed = min(self._completed, self._total)
        self._schedule_time_update()
        self._dispatch(self.progress.step, advance)

    def progress_finish(self) -> None:
        self._completed = self._total
        self._schedule_time_update()

        def finish() -> None:
            if self._total:
                self.progress['value'] = self._total
        self._dispatch(finish)


class BuilderGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Anki JP Deck Builder")

        self.csv_path_var = tk.StringVar()
        self.output_dir_var = tk.StringVar(value=str(Path.cwd() / "out"))
        self.deck_name_var = tk.StringVar(value=DEFAULT_DECK_NAME)
        self.new_deck_var = tk.BooleanVar(value=True)
        self.config_path_var = tk.StringVar()
        self._mode_display = {
            InputMode.VOCABULARY: "Vocabulary",
            InputMode.GRAMMAR: "Grammar",
        }
        self._display_to_mode = {display: mode for mode, display in self._mode_display.items()}
        self.mode_var = tk.StringVar(value=self._mode_display[InputMode.VOCABULARY])
        self.status_var = tk.StringVar(value="Idle")
        self.time_var = tk.StringVar(value="Elapsed: 00:00 — Remaining: --")

        self._mode_hints = {
            InputMode.VOCABULARY: "Vocabulary mode: CSV should include vocabulary entries (term, reading, meaning).",
            InputMode.GRAMMAR: "Grammar mode: CSV should include grammar entries (expression, meaning, notes).",
        }

        self._build_thread: threading.Thread | None = None

        self._build_layout()

    def _build_layout(self) -> None:
        padding = {"padx": 8, "pady": 4}

        frame = ttk.Frame(self.root)
        frame.grid(column=0, row=0, sticky="nsew")

        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        # Header
        ttk.Label(
            frame,
            text="Made by Turco Cibeira",
            font=("TkDefaultFont", 12, "italic"),
        ).grid(column=0, row=0, columnspan=3, sticky="w", **padding)

        # CSV path
        ttk.Label(frame, text="CSV Path:").grid(column=0, row=1, sticky="w", **padding)
        csv_entry = ttk.Entry(frame, textvariable=self.csv_path_var, width=40)
        csv_entry.grid(column=1, row=1, sticky="ew", **padding)
        ttk.Button(frame, text="Browse", command=self._choose_csv).grid(column=2, row=1, **padding)

        # Mode selector
        ttk.Label(frame, text="Mode:").grid(column=0, row=2, sticky="w", **padding)
        self.mode_combo = ttk.Combobox(
            frame,
            state="readonly",
            textvariable=self.mode_var,
            values=[self._mode_display[InputMode.VOCABULARY], self._mode_display[InputMode.GRAMMAR]],
        )
        self.mode_combo.grid(column=1, row=2, sticky="ew", **padding)
        self.mode_combo.bind("<<ComboboxSelected>>", self._on_mode_change)

        # Output directory
        ttk.Label(frame, text="Output Directory:").grid(column=0, row=3, sticky="w", **padding)
        output_entry = ttk.Entry(frame, textvariable=self.output_dir_var, width=40)
        output_entry.grid(column=1, row=3, sticky="ew", **padding)
        ttk.Button(frame, text="Browse", command=self._choose_output_dir).grid(column=2, row=3, **padding)

        # Deck name
        ttk.Label(frame, text="Deck Name:").grid(column=0, row=4, sticky="w", **padding)
        ttk.Entry(frame, textvariable=self.deck_name_var, width=40).grid(column=1, row=4, sticky="ew", **padding)

        # New deck toggle
        ttk.Checkbutton(frame, text="Create new deck", variable=self.new_deck_var).grid(
            column=1, row=5, sticky="w", **padding
        )

        # Config path (optional)
        ttk.Label(frame, text="Config Path (optional):").grid(column=0, row=6, sticky="w", **padding)
        ttk.Entry(frame, textvariable=self.config_path_var, width=40).grid(column=1, row=6, sticky="ew", **padding)
        ttk.Button(frame, text="Browse", command=self._choose_config).grid(column=2, row=6, **padding)

        # Status label
        ttk.Label(frame, textvariable=self.status_var).grid(column=0, row=7, columnspan=3, sticky="w", **padding)

        # Time label
        ttk.Label(frame, textvariable=self.time_var).grid(
            column=0, row=8, columnspan=3, sticky="w", **padding
        )

        # Progress bar
        self.progress = ttk.Progressbar(frame, orient="horizontal", mode="determinate")
        self.progress.grid(column=0, row=9, columnspan=3, sticky="ew", **padding)

        # Build button
        self.build_button = ttk.Button(frame, text="Build", command=self._start_build)
        self.build_button.grid(column=0, row=10, columnspan=3, sticky="ew", **padding)

        frame.columnconfigure(1, weight=1)

    def _choose_csv(self) -> None:
        path = filedialog.askopenfilename(
            title="Select CSV file",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
        )
        if path:
            self.csv_path_var.set(path)

    def _choose_output_dir(self) -> None:
        path = filedialog.askdirectory(title="Select output directory")
        if path:
            self.output_dir_var.set(path)

    def _choose_config(self) -> None:
        path = filedialog.askopenfilename(
            title="Select config JSON",
            filetypes=[("JSON Files", "*.json"), ("All Files", "*.*")],
        )
        if path:
            self.config_path_var.set(path)

    def _start_build(self) -> None:
        if self._build_thread and self._build_thread.is_alive():
            return

        csv_path = Path(self.csv_path_var.get()).expanduser()
        if not csv_path.exists():
            messagebox.showerror("Error", "Please select a valid CSV file.")
            return

        output_value = self.output_dir_var.get().strip()
        if not output_value:
            messagebox.showerror("Error", "Please choose an output directory.")
            return
        output_dir = Path(output_value).expanduser()

        deck_name = self.deck_name_var.get().strip() or DEFAULT_DECK_NAME
        config_value = self.config_path_var.get().strip()
        config_path = Path(config_value).expanduser() if config_value else None

        mode_display = self.mode_var.get()
        mode = self._display_to_mode.get(mode_display, InputMode.VOCABULARY)

        params = BuildParams(
            csv_path=csv_path,
            output_dir=output_dir,
            new_deck=self.new_deck_var.get(),
            deck_name=deck_name,
            config_path=config_path,
            debug=False,
            mode=mode,
        )

        reporter = TkBuildReporter(self.root, self.status_var, self.progress, self.time_var)
        self.status_var.set("Starting build...")
        self.progress.config(value=0)
        self.build_button.config(state=tk.DISABLED)
        self.mode_combo.config(state="disabled")

        def worker() -> None:
            try:
                result = run_builder(params, reporter)
            except BuildError as exc:
                self._on_build_error(str(exc), fatal=exc.exit_code != 0)
            except Exception as exc:  # pragma: no cover - unexpected runtime failure
                self._on_build_error(str(exc))
            else:
                self._on_build_success(result)
            finally:
                self._finalize_build()

        self._build_thread = threading.Thread(target=worker, daemon=True)
        self._build_thread.start()

    def _finalize_build(self) -> None:
        def finalize() -> None:
            self.build_button.config(state=tk.NORMAL)
            self.mode_combo.config(state="readonly")
            self._build_thread = None
        self.root.after(0, finalize)

    def _on_build_success(self, result: BuildResult) -> None:
        def notify() -> None:
            self.status_var.set("Build complete!")
            messagebox.showinfo(
                "Build complete",
                f"Deck created at:\n{result.apkg_path}",
            )
        self.root.after(0, notify)

    def _on_build_error(self, message: str, *, fatal: bool = True) -> None:
        def notify() -> None:
            if fatal:
                self.status_var.set(f"Error: {message}")
                messagebox.showerror("Build failed", message)
            else:
                self.status_var.set(message)
                messagebox.showinfo("Build finished", message)
        self.root.after(0, notify)

    def _on_mode_change(self, *_: object) -> None:
        mode = self._display_to_mode.get(self.mode_var.get(), InputMode.VOCABULARY)
        hint = self._mode_hints.get(mode)
        if hint and not (self._build_thread and self._build_thread.is_alive()):
            self.status_var.set(hint)


def main() -> None:
    root = tk.Tk()
    BuilderGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
