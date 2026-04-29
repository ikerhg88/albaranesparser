from __future__ import annotations

import logging
import os
import queue
import shutil
import threading
from contextlib import redirect_stderr, redirect_stdout
from io import TextIOBase
from pathlib import Path
from typing import Any, Callable

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk


class _QueueLogHandler(logging.Handler):
    def __init__(self, target_queue: queue.Queue) -> None:
        super().__init__()
        self.target_queue = target_queue

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.target_queue.put(
                {
                    "type": "log",
                    "message": self.format(record),
                    "level": record.levelname,
                }
            )
        except Exception:
            pass


class _LogRedirector(TextIOBase):
    def __init__(self, logger: logging.Logger, level: int) -> None:
        self.logger = logger
        self.level = level
        self.buf = ""

    def write(self, s: str) -> int:
        if not s:
            return 0
        self.buf += s
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            line = line.strip()
            if line:
                # Evita bucles de logging cuando algun handler externo escribe
                # prefijos del propio logger en stderr/stdout.
                if line.startswith("albaranes.gui.worker:"):
                    continue
                self.logger.log(self.level, line)
        return len(s)

    def flush(self) -> None:
        line = self.buf.strip()
        if line:
            self.logger.log(self.level, line)
        self.buf = ""


class _MainWindow:
    def __init__(
        self,
        base_dir: Path,
        run_pipeline_fn: Callable[..., dict],
        selftest_fn: Callable[..., dict] | None,
        apply_settings_fn: Callable[[dict], None],
        load_settings_fn: Callable[[Path], dict],
        save_settings_fn: Callable[[Path, dict], None],
        defaults: dict,
    ) -> None:
        self.base_dir = base_dir
        self.run_pipeline_fn = run_pipeline_fn
        self.selftest_fn = selftest_fn
        self.apply_settings_fn = apply_settings_fn
        self.load_settings_fn = load_settings_fn
        self.save_settings_fn = save_settings_fn
        self.defaults = defaults

        self.root = tk.Tk()
        self.root.title("Albaranes Parser")
        self.root.geometry("980x730")
        self.root.minsize(900, 650)

        self.queue: queue.Queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.current_output: Path | None = None
        self.current_out_dir: Path | None = None
        self.current_report: Path | None = None
        self.total_pages = 0
        self.ok_pages = 0
        self.fail_pages = 0
        self.done_pages = 0

        saved = self.load_settings_fn(base_dir) or {}
        cfg = dict(defaults)
        cfg.update(saved)
        cfg.setdefault("input_path", "")
        cfg.setdefault("output_path", str((base_dir / "albaranes_master.xlsx").resolve()))
        cfg.setdefault("ocr_mode", "auto")
        cfg.setdefault("OCR_CONFIG", defaults.get("OCR_CONFIG", {}))
        cfg.setdefault("OCR_WORKFLOW", defaults.get("OCR_WORKFLOW", {}))

        self.input_var = tk.StringVar(value=cfg.get("input_path", ""))
        self.output_var = tk.StringVar(value=cfg.get("output_path", ""))
        self.precheck_var = tk.BooleanVar(value=bool(cfg.get("PRECHECK_ENABLED", True)))
        self.stop_var = tk.BooleanVar(value=bool(cfg.get("STOP_ON_ERROR", False)))
        self.debug_var = tk.BooleanVar(value=bool(cfg.get("DEBUG_ENABLED", True)))
        self.supedido_trunc_var = tk.BooleanVar(value=bool(cfg.get("SUPEDIDO_TRUNCATED_ENABLED", True)))
        self.ocr_mode_var = tk.StringVar(value=cfg.get("ocr_mode", "auto"))

        ocr_cfg = cfg.get("OCR_CONFIG", {})
        self.ocrmypdf_var = tk.BooleanVar(value=False)
        self.doctr_var = tk.BooleanVar(value=False)
        self.tesseract_var = tk.BooleanVar(value=bool(ocr_cfg.get("tesseract", {}).get("enabled", True)))
        self.force_adv_var = tk.BooleanVar(value=False)

        self.status_var = tk.StringVar(value="Listo")
        self.count_var = tk.StringVar(value="OK: 0 | Fallidos: 0")
        self.summary_var = tk.StringVar(value="")

        self._build_ui()
        self._apply_ocr_availability()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(120, self._poll_queue)

    def _build_ui(self) -> None:
        frame = ttk.Frame(self.root, padding=10)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(5, weight=1)

        ttk.Label(frame, text="Entrada (carpeta PDFs):").grid(row=0, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.input_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(frame, text="Examinar", command=self._pick_input).grid(row=0, column=2)

        ttk.Label(frame, text="Salida (Excel master):").grid(row=1, column=0, sticky="w", pady=4)
        ttk.Entry(frame, textvariable=self.output_var).grid(row=1, column=1, sticky="ew", padx=8)
        ttk.Button(frame, text="Guardar como", command=self._pick_output).grid(row=1, column=2)

        opts = ttk.LabelFrame(frame, text="Opciones", padding=8)
        opts.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(10, 8))
        ttk.Checkbutton(opts, text="Precheck", variable=self.precheck_var).grid(row=0, column=0, sticky="w", padx=(0, 12))
        ttk.Checkbutton(opts, text="Parar en primer error grave", variable=self.stop_var).grid(row=0, column=1, sticky="w", padx=(0, 12))
        ttk.Checkbutton(opts, text="Debug", variable=self.debug_var).grid(row=0, column=2, sticky="w")
        ttk.Checkbutton(opts, text="SuPedido truncated", variable=self.supedido_trunc_var).grid(row=0, column=3, sticky="w", padx=(0, 12))
        ttk.Radiobutton(opts, text="OCR automatico", value="auto", variable=self.ocr_mode_var).grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Radiobutton(opts, text="Forzar OCR siempre", value="force", variable=self.ocr_mode_var).grid(row=1, column=1, sticky="w", pady=(6, 0))

        self.show_adv = tk.BooleanVar(value=False)
        ttk.Button(opts, text="Opciones OCR avanzadas", command=self._toggle_advanced).grid(row=1, column=2, sticky="e")
        self.adv = ttk.Frame(opts)
        self.chk_tesseract = ttk.Checkbutton(self.adv, text="Tesseract OCR", variable=self.tesseract_var)
        self.chk_tesseract.grid(row=0, column=0, sticky="w", padx=(0, 12))
        self.chk_force_adv = ttk.Checkbutton(self.adv, text="Forzar OCR (usar selector principal)", variable=self.force_adv_var)
        self.chk_force_adv.grid(row=0, column=1, sticky="w")

        runf = ttk.Frame(frame)
        runf.grid(row=3, column=0, columnspan=3, sticky="ew", pady=6)
        runf.columnconfigure(4, weight=1)
        self.btn_start = ttk.Button(runf, text="Procesar", command=self._start)
        self.btn_start.grid(row=0, column=0)
        self.btn_cancel = ttk.Button(runf, text="Cancelar", command=self._cancel, state="disabled")
        self.btn_cancel.grid(row=0, column=1, padx=(8, 8))
        ttk.Button(runf, text="Restaurar defaults", command=self._restore_defaults).grid(row=0, column=2)
        self.btn_selftest = ttk.Button(runf, text="Diagnostico instalacion", command=self._start_selftest)
        self.btn_selftest.grid(row=0, column=3, padx=(8, 0))
        self.progress = ttk.Progressbar(runf, mode="determinate")
        self.progress.grid(row=0, column=4, sticky="ew", padx=(10, 0))
        ttk.Label(runf, textvariable=self.status_var).grid(row=1, column=0, columnspan=4, sticky="w", pady=(6, 0))
        ttk.Label(runf, textvariable=self.count_var).grid(row=1, column=4, sticky="e", pady=(6, 0))

        ttk.Label(frame, text="Log").grid(row=4, column=0, sticky="w")
        self.log_text = scrolledtext.ScrolledText(frame, height=18, state="disabled")
        self.log_text.grid(row=5, column=0, columnspan=3, sticky="nsew", pady=(4, 8))

        endf = ttk.Frame(frame)
        endf.grid(row=6, column=0, columnspan=3, sticky="ew")
        self.btn_open_master = ttk.Button(endf, text="Abrir Excel master", command=self._open_master, state="disabled")
        self.btn_open_master.grid(row=0, column=0)
        self.btn_open_folder = ttk.Button(endf, text="Abrir carpeta de salida", command=self._open_folder, state="disabled")
        self.btn_open_folder.grid(row=0, column=1, padx=8)
        self.btn_open_report = ttk.Button(endf, text="Abrir informe diagnostico", command=self._open_report, state="disabled")
        self.btn_open_report.grid(row=0, column=2, padx=(0, 8))
        ttk.Label(endf, textvariable=self.summary_var).grid(row=0, column=3, sticky="w")

    def _tesseract_available(self) -> bool:
        if shutil.which("tesseract.exe" if os.name == "nt" else "tesseract"):
            return True
        candidates = [
            self.base_dir / "external_bin" / "tesseract" / ("tesseract.exe" if os.name == "nt" else "tesseract"),
            Path.cwd() / "external_bin" / "tesseract" / ("tesseract.exe" if os.name == "nt" else "tesseract"),
        ]
        return any(path.exists() for path in candidates)

    def _apply_ocr_availability(self) -> None:
        notes = []
        self.ocrmypdf_var.set(False)
        self.doctr_var.set(False)
        if not self._tesseract_available():
            self.tesseract_var.set(False)
            self.chk_tesseract.configure(state="disabled", text="Tesseract (no encontrado)")
            notes.append("Tesseract no encontrado")
        self.force_adv_var.set(False)
        self.chk_force_adv.configure(state="disabled", text="Forzar OCR (usar selector principal)")
        if self.ocr_mode_var.get() == "force":
            notes.append("Forzar OCR puede empeorar documentos con texto embebido")
        if notes:
            self._append_log("[OCR] " + " | ".join(notes))

    def _toggle_advanced(self) -> None:
        show = not self.show_adv.get()
        self.show_adv.set(show)
        if show:
            self.adv.grid(row=2, column=0, columnspan=3, sticky="w", pady=(6, 0))
        else:
            self.adv.grid_forget()

    def _append_log(self, text: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", text + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _pick_input(self) -> None:
        path = filedialog.askdirectory(title="Selecciona carpeta con PDFs", initialdir=str(self.base_dir))
        if path:
            self.input_var.set(path)
            if not self.output_var.get().strip():
                self.output_var.set(str((Path(path) / "albaranes_master.xlsx").resolve()))

    def _pick_output(self) -> None:
        init_dir = self.base_dir
        inp = self.input_var.get().strip()
        if inp:
            init_dir = Path(inp)
        path = filedialog.asksaveasfilename(
            title="Guardar Excel master",
            initialdir=str(init_dir),
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialfile="albaranes_master.xlsx",
        )
        if path:
            self.output_var.set(path)

    def _collect_cfg(self) -> dict:
        force_ocr = self.ocr_mode_var.get() == "force"
        return {
            "input_path": self.input_var.get().strip(),
            "output_path": self.output_var.get().strip(),
            "PRECHECK_ENABLED": self.precheck_var.get(),
            "STOP_ON_ERROR": self.stop_var.get(),
            "DEBUG_ENABLED": self.debug_var.get(),
            "SUPEDIDO_TRUNCATED_ENABLED": self.supedido_trunc_var.get(),
            "ocr_mode": self.ocr_mode_var.get(),
            "OCR_CONFIG": {
                "ocrmypdf": {"enabled": self.ocrmypdf_var.get()},
                "doctr": {"enabled": self.doctr_var.get()},
                "tesseract": {"enabled": self.tesseract_var.get()},
            },
            "OCR_WORKFLOW": {"ocr_force_all": bool(force_ocr)},
        }

    def _restore_defaults(self) -> None:
        cfg = dict(self.defaults)
        self.precheck_var.set(bool(cfg.get("PRECHECK_ENABLED", True)))
        self.stop_var.set(bool(cfg.get("STOP_ON_ERROR", False)))
        self.debug_var.set(bool(cfg.get("DEBUG_ENABLED", True)))
        self.supedido_trunc_var.set(bool(cfg.get("SUPEDIDO_TRUNCATED_ENABLED", True)))
        self.ocr_mode_var.set("force" if bool(cfg.get("OCR_WORKFLOW", {}).get("ocr_force_all", False)) else "auto")
        self.ocrmypdf_var.set(False)
        self.doctr_var.set(False)
        self.tesseract_var.set(bool(cfg.get("OCR_CONFIG", {}).get("tesseract", {}).get("enabled", True)))
        self.force_adv_var.set(False)
        self._apply_ocr_availability()

    def _build_logger(self, out_dir: Path, debug_enabled: bool) -> logging.Logger:
        logger = logging.getLogger("albaranes.gui.worker")
        logger.setLevel(logging.INFO)
        logger.propagate = False
        for handler in list(logger.handlers):
            try:
                handler.close()
            except Exception:
                pass
        logger.handlers.clear()
        qh = _QueueLogHandler(self.queue)
        qh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", "%H:%M:%S"))
        logger.addHandler(qh)
        if debug_enabled:
            try:
                out_dir.mkdir(parents=True, exist_ok=True)
                fh = logging.FileHandler(out_dir / "albaranes_gui.log", encoding="utf-8")
                fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
                logger.addHandler(fh)
            except Exception:
                pass
        return logger

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        cfg = self._collect_cfg()
        in_raw = cfg["input_path"]
        if not in_raw:
            messagebox.showwarning("Entrada", "Selecciona una carpeta de entrada con PDFs.")
            return
        in_path = Path(in_raw)
        if not in_path.exists():
            messagebox.showerror("Entrada", f"No existe la ruta de entrada:\\n{in_path}")
            return
        out_raw = cfg["output_path"] or str((in_path / "albaranes_master.xlsx").resolve())
        out_path = Path(out_raw)
        self.output_var.set(str(out_path))

        self.save_settings_fn(self.base_dir, cfg)
        self.apply_settings_fn(
            {
                "PRECHECK_ENABLED": cfg["PRECHECK_ENABLED"],
                "STOP_ON_ERROR": cfg["STOP_ON_ERROR"],
                "DEBUG_ENABLED": cfg["DEBUG_ENABLED"],
                "SUPEDIDO_TRUNCATED_ENABLED": cfg["SUPEDIDO_TRUNCATED_ENABLED"],
                "OCR_CONFIG": cfg["OCR_CONFIG"],
                "OCR_WORKFLOW": cfg["OCR_WORKFLOW"],
            }
        )

        self.total_pages = 0
        self.ok_pages = 0
        self.fail_pages = 0
        self.done_pages = 0
        self.progress["value"] = 0
        self.progress["maximum"] = 1
        self.status_var.set("Procesando...")
        self.count_var.set("OK: 0 | Fallidos: 0")
        self.summary_var.set("")
        self.current_output = out_path
        self.current_out_dir = out_path.parent
        self.btn_start.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.btn_open_master.configure(state="disabled")
        self.btn_open_folder.configure(state="disabled")
        self.btn_open_report.configure(state="disabled")
        self.cancel_event.clear()
        self._append_log("=== Inicio de ejecucion ===")

        self.worker = threading.Thread(target=self._worker_run, args=(in_path, out_path, cfg), daemon=True)
        self.worker.start()

    def _worker_run(self, in_path: Path, out_path: Path, cfg: dict) -> None:
        logger = self._build_logger(out_path.parent, bool(cfg.get("DEBUG_ENABLED", False)))

        def _progress(data: dict) -> None:
            self.queue.put({"type": "progress", "data": data})

        try:
            with redirect_stdout(_LogRedirector(logger, logging.INFO)), redirect_stderr(_LogRedirector(logger, logging.ERROR)):
                summary = self.run_pipeline_fn(
                    in_path,
                    out_path,
                    recursive=False,
                    cancel_event=self.cancel_event,
                    progress_cb=_progress,
                    logger=logger,
                )
            self.queue.put({"type": "done", "summary": summary})
        except Exception as exc:
            self.queue.put({"type": "error", "error": repr(exc)})

    def _start_selftest(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        if self.selftest_fn is None:
            messagebox.showerror("Diagnostico", "La funcion de diagnostico no esta disponible.")
            return
        cfg = self._collect_cfg()
        self.save_settings_fn(self.base_dir, cfg)
        self.apply_settings_fn(
            {
                "PRECHECK_ENABLED": cfg["PRECHECK_ENABLED"],
                "STOP_ON_ERROR": cfg["STOP_ON_ERROR"],
                "DEBUG_ENABLED": True,
                "SUPEDIDO_TRUNCATED_ENABLED": cfg["SUPEDIDO_TRUNCATED_ENABLED"],
                "OCR_CONFIG": cfg["OCR_CONFIG"],
                "OCR_WORKFLOW": cfg["OCR_WORKFLOW"],
            }
        )
        self.total_pages = 0
        self.ok_pages = 0
        self.fail_pages = 0
        self.done_pages = 0
        self.progress["value"] = 0
        self.progress["maximum"] = 1
        self.status_var.set("Ejecutando diagnostico...")
        self.count_var.set("OK: 0 | Fallidos: 0")
        self.summary_var.set("")
        self.current_output = None
        self.current_out_dir = self.base_dir / "debug" / "installation_selftest"
        self.current_report = None
        self.btn_start.configure(state="disabled")
        self.btn_selftest.configure(state="disabled")
        self.btn_cancel.configure(state="disabled")
        self.btn_open_master.configure(state="disabled")
        self.btn_open_folder.configure(state="disabled")
        self.btn_open_report.configure(state="disabled")
        self._append_log("=== Inicio diagnostico de instalacion ===")
        self.worker = threading.Thread(target=self._worker_selftest, args=(cfg,), daemon=True)
        self.worker.start()

    def _worker_selftest(self, cfg: dict) -> None:
        try:
            report = self.selftest_fn(
                base_dir=self.base_dir,
                run_pipeline_fn=self.run_pipeline_fn,
                config={
                    "OCR_CONFIG": cfg.get("OCR_CONFIG", {}),
                    "OCR_WORKFLOW": cfg.get("OCR_WORKFLOW", {}),
                },
                output_dir=None,
                keep_artifacts=True,
            )
            self.queue.put({"type": "selftest_done", "report": report})
        except Exception as exc:
            self.queue.put({"type": "error", "error": repr(exc)})

    def _cancel(self) -> None:
        if self.worker and self.worker.is_alive():
            self.cancel_event.set()
            self.status_var.set("Cancelando...")
            self._append_log("[INFO] Solicitud de cancelacion enviada.")

    def _poll_queue(self) -> None:
        try:
            while True:
                msg = self.queue.get_nowait()
                mtype = msg.get("type")
                if mtype == "log":
                    self._append_log(msg.get("message", ""))
                elif mtype == "progress":
                    data = msg.get("data", {})
                    if data.get("event") == "precheck":
                        self.total_pages = int(data.get("total_pages") or 0)
                        self.progress["maximum"] = max(self.total_pages, 1)
                        self.progress["value"] = 0
                    elif data.get("processed"):
                        self.done_pages += 1
                        if data.get("ok"):
                            self.ok_pages += 1
                        else:
                            self.fail_pages += 1
                        if self.total_pages > 0:
                            self.progress["value"] = min(self.done_pages, self.total_pages)
                        self.count_var.set(f"OK: {self.ok_pages} | Fallidos: {self.fail_pages}")
                elif mtype == "done":
                    summary = msg.get("summary", {})
                    if summary.get("cancelled"):
                        self.status_var.set("Cancelado")
                        self.summary_var.set("Proceso cancelado")
                    else:
                        self.status_var.set("Finalizado")
                        self.summary_var.set(
                            f"Totales: {summary.get('albaranes_totales', 0)} | OK: {summary.get('albaranes_procesados', 0)} | Fallidos: {summary.get('albaranes_fallidos', 0)}"
                        )
                        if self.current_output and self.current_output.exists():
                            self.btn_open_master.configure(state="normal")
                            self.btn_open_folder.configure(state="normal")
                    self.btn_start.configure(state="normal")
                    self.btn_selftest.configure(state="normal")
                    self.btn_cancel.configure(state="disabled")
                elif mtype == "selftest_done":
                    report = msg.get("report", {})
                    ok = bool(report.get("ok"))
                    report_dir = Path(report.get("report_dir", self.base_dir))
                    report_file = report_dir / "installation_selftest_report.txt"
                    self.current_out_dir = report_dir
                    self.current_report = report_file if report_file.exists() else None
                    self.status_var.set("Diagnostico OK" if ok else "Diagnostico con errores")
                    self.summary_var.set(f"Informe: {report_dir}")
                    self._append_log(f"[SELFTEST] {'OK' if ok else 'FAIL'}")
                    self._append_log(f"[SELFTEST] Informe: {report_dir}")
                    tesseract = report.get("tesseract", {})
                    pipeline = report.get("pipeline", {})
                    self._append_log(f"[SELFTEST] Tesseract: {'OK' if tesseract.get('ok') else 'FAIL'}")
                    self._append_log(f"[SELFTEST] Pipeline: {'OK' if pipeline.get('ok') else 'FAIL'}")
                    if report_dir.exists():
                        self.btn_open_folder.configure(state="normal")
                    if self.current_report and self.current_report.exists():
                        self.btn_open_report.configure(state="normal")
                    self.btn_start.configure(state="normal")
                    self.btn_selftest.configure(state="normal")
                    self.btn_cancel.configure(state="disabled")
                elif mtype == "error":
                    self.status_var.set("Error")
                    self._append_log(f"[ERROR] {msg.get('error', '')}")
                    self.btn_start.configure(state="normal")
                    self.btn_selftest.configure(state="normal")
                    self.btn_cancel.configure(state="disabled")
        except queue.Empty:
            pass
        self.root.after(120, self._poll_queue)

    def _open_master(self) -> None:
        if self.current_output and self.current_output.exists():
            os.startfile(str(self.current_output))

    def _open_folder(self) -> None:
        if self.current_out_dir and self.current_out_dir.exists():
            os.startfile(str(self.current_out_dir))

    def _open_report(self) -> None:
        if self.current_report and self.current_report.exists():
            os.startfile(str(self.current_report))

    def _on_close(self) -> None:
        try:
            self.save_settings_fn(self.base_dir, self._collect_cfg())
        except Exception:
            pass
        self.root.destroy()

    def run(self) -> None:
        self.root.mainloop()


def launch_gui(
    base_dir: Path,
    run_pipeline_fn: Callable[..., dict],
    selftest_fn: Callable[..., dict] | None,
    apply_settings_fn: Callable[[dict], None],
    load_settings_fn: Callable[[Path], dict],
    save_settings_fn: Callable[[Path, dict], None],
    defaults: dict[str, Any],
) -> None:
    app = _MainWindow(
        base_dir=base_dir,
        run_pipeline_fn=run_pipeline_fn,
        selftest_fn=selftest_fn,
        apply_settings_fn=apply_settings_fn,
        load_settings_fn=load_settings_fn,
        save_settings_fn=save_settings_fn,
        defaults=defaults,
    )
    app.run()
