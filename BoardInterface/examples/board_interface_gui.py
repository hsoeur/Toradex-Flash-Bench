from __future__ import annotations

import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

from board_interface import BoardInterface


class BoardInterfaceTester(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("BoardInterface Tester")
        self.geometry("980x700")
        self.minsize(860, 620)

        self.board: BoardInterface | None = None
        self.worker_queue: queue.Queue[tuple[str, str]] = queue.Queue()

        self.port_var = tk.StringVar(value="/dev/ttyACM0")
        self.baudrate_var = tk.StringVar(value="115200")
        self.timeout_var = tk.StringVar(value="10000")
        self.power_output_var = tk.IntVar(value=0)
        self.cycle_delay_var = tk.StringVar(value="1.0")
        self.target_var = tk.IntVar(value=0)
        self.raw_command_var = tk.StringVar(value="*IDN?")
        self.status_var = tk.StringVar(value="Deconnecte")

        self._build_ui()
        self.after(100, self._drain_worker_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=12)
        root.pack(fill=tk.BOTH, expand=True)

        connection = ttk.LabelFrame(root, text="Connexion", padding=10)
        connection.pack(fill=tk.X)

        ttk.Label(connection, text="Port").grid(row=0, column=0, sticky=tk.W)
        ttk.Entry(connection, textvariable=self.port_var, width=12).grid(row=0, column=1, padx=(6, 14))

        ttk.Label(connection, text="Baudrate").grid(row=0, column=2, sticky=tk.W)
        ttk.Entry(connection, textvariable=self.baudrate_var, width=12).grid(row=0, column=3, padx=(6, 14))

        ttk.Label(connection, text="Timeout ms").grid(row=0, column=4, sticky=tk.W)
        ttk.Entry(connection, textvariable=self.timeout_var, width=12).grid(row=0, column=5, padx=(6, 14))

        ttk.Button(connection, text="Connecter", command=self.connect_board).grid(row=0, column=6, padx=4)
        ttk.Button(connection, text="Deconnecter", command=self.disconnect_board).grid(row=0, column=7, padx=4)
        ttk.Label(connection, textvariable=self.status_var).grid(row=0, column=8, padx=(18, 0), sticky=tk.W)
        connection.columnconfigure(8, weight=1)

        top = ttk.Frame(root)
        top.pack(fill=tk.X, pady=(12, 0))

        general = ttk.LabelFrame(top, text="Commandes generales", padding=10)
        general.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 6))

        ttk.Button(general, text="Lire ID (*IDN?)", command=lambda: self.run_board_task("Lire ID", self.read_id)).grid(row=0, column=0, sticky=tk.EW, padx=4, pady=4)
        ttk.Button(general, text="Lire sorties (FIXT?)", command=lambda: self.run_board_task("Lire sorties", self.read_outputs_mask)).grid(row=0, column=1, sticky=tk.EW, padx=4, pady=4)
        ttk.Button(general, text="Reset (*RST)", command=lambda: self.run_board_task("Reset", self.reset_board)).grid(row=1, column=0, sticky=tk.EW, padx=4, pady=4)
        ttk.Button(general, text="Clear errors (*CLS)", command=lambda: self.run_board_task("Clear errors", self.clear_errors)).grid(row=1, column=1, sticky=tk.EW, padx=4, pady=4)
        ttk.Button(general, text="Lire erreur (SYST:ERR?)", command=lambda: self.run_board_task("Lire erreur", self.read_error)).grid(row=2, column=0, columnspan=2, sticky=tk.EW, padx=4, pady=4)
        general.columnconfigure(0, weight=1)
        general.columnconfigure(1, weight=1)

        target = ttk.LabelFrame(top, text="Cible", padding=10)
        target.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(6, 0))

        ttk.Label(target, text="Index cible").grid(row=0, column=0, sticky=tk.W, padx=4, pady=4)
        ttk.Spinbox(target, from_=0, to=6, textvariable=self.target_var, width=8).grid(row=0, column=1, sticky=tk.W, padx=4, pady=4)
        ttk.Button(target, text="Lire TARG?", command=lambda: self.run_board_task("Lire cible", self.read_target)).grid(row=1, column=0, sticky=tk.EW, padx=4, pady=4)
        ttk.Button(target, text="Ecrire TARG", command=lambda: self.run_board_task("Ecrire cible", self.write_target)).grid(row=1, column=1, sticky=tk.EW, padx=4, pady=4)
        target.columnconfigure(0, weight=1)
        target.columnconfigure(1, weight=1)

        outputs = ttk.LabelFrame(root, text="Sorties fixture / alimentation", padding=10)
        outputs.pack(fill=tk.X, pady=(12, 0))

        for index in range(8):
            frame = ttk.Frame(outputs, padding=4)
            frame.grid(row=index // 4, column=index % 4, sticky=tk.EW, padx=4, pady=4)
            ttk.Label(frame, text=f"Sortie {index}").pack(anchor=tk.W)
            buttons = ttk.Frame(frame)
            buttons.pack(fill=tk.X, pady=(4, 0))
            ttk.Button(buttons, text="ON", command=lambda i=index: self.run_board_task(f"Sortie {i} ON", lambda i=i: self.power_on(i))).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 2))
            ttk.Button(buttons, text="OFF", command=lambda i=index: self.run_board_task(f"Sortie {i} OFF", lambda i=i: self.power_off(i))).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(2, 0))
            outputs.columnconfigure(index % 4, weight=1)

        cycle = ttk.LabelFrame(root, text="Power cycle", padding=10)
        cycle.pack(fill=tk.X, pady=(12, 0))

        ttk.Label(cycle, text="Sortie").grid(row=0, column=0, sticky=tk.W)
        ttk.Spinbox(cycle, from_=0, to=7, textvariable=self.power_output_var, width=8).grid(row=0, column=1, padx=(6, 14), sticky=tk.W)
        ttk.Label(cycle, text="Temps OFF (s)").grid(row=0, column=2, sticky=tk.W)
        ttk.Entry(cycle, textvariable=self.cycle_delay_var, width=10).grid(row=0, column=3, padx=(6, 14), sticky=tk.W)
        ttk.Button(cycle, text="Power OFF", command=lambda: self.run_board_task("Power OFF", self.power_off_selected)).grid(row=0, column=4, padx=4)
        ttk.Button(cycle, text="Power ON", command=lambda: self.run_board_task("Power ON", self.power_on_selected)).grid(row=0, column=5, padx=4)
        ttk.Button(cycle, text="Power CYCLE", command=lambda: self.run_board_task("Power cycle", self.power_cycle_selected)).grid(row=0, column=6, padx=4)
        cycle.columnconfigure(7, weight=1)

        raw = ttk.LabelFrame(root, text="Commande SCPI brute", padding=10)
        raw.pack(fill=tk.X, pady=(12, 0))

        ttk.Entry(raw, textvariable=self.raw_command_var).grid(row=0, column=0, sticky=tk.EW, padx=(0, 8))
        ttk.Button(raw, text="Envoyer sans reponse", command=lambda: self.run_board_task("Commande brute", self.raw_write)).grid(row=0, column=1, padx=4)
        ttk.Button(raw, text="Envoyer avec reponse", command=lambda: self.run_board_task("Question brute", self.raw_query)).grid(row=0, column=2, padx=4)
        raw.columnconfigure(0, weight=1)

        log_frame = ttk.LabelFrame(root, text="Journal", padding=10)
        log_frame.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

        self.log_text = tk.Text(log_frame, height=14, wrap=tk.WORD)
        scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def connect_board(self) -> None:
        if self.board is not None:
            self.log("INFO", "Carte deja connectee")
            return

        try:
            baudrate = int(self.baudrate_var.get())
            timeout_ms = int(self.timeout_var.get())
            board = BoardInterface(self.port_var.get().strip(), baudrate, timeout_ms)
            board.init()
        except Exception as exc:
            self.board = None
            self.status_var.set("Erreur connexion")
            self.log("ERROR", str(exc))
            messagebox.showerror("Connexion impossible", str(exc))
            return

        self.board = board
        self.status_var.set(f"Connecte sur {self.port_var.get().strip()}")
        self.log("OK", "Connexion etablie")

    def disconnect_board(self) -> None:
        if self.board is None:
            self.status_var.set("Deconnecte")
            return

        try:
            self.board.close()
            self.log("OK", "Connexion fermee")
        except Exception as exc:
            self.log("ERROR", str(exc))
        finally:
            self.board = None
            self.status_var.set("Deconnecte")

    def run_board_task(self, label: str, action) -> None:
        if self.board is None:
            messagebox.showwarning("Carte non connectee", "Connecte d'abord la carte.")
            return

        self.log("RUN", label)
        threading.Thread(target=self._run_worker, args=(label, action), daemon=True).start()

    def _run_worker(self, label: str, action) -> None:
        try:
            result = action()
        except Exception as exc:
            self.worker_queue.put(("ERROR", f"{label}: {exc}"))
            return

        if result is not None:
            self.worker_queue.put(("OK", f"{label}: {result}"))
        else:
            self.worker_queue.put(("OK", label))

    def _drain_worker_queue(self) -> None:
        while True:
            try:
                level, message = self.worker_queue.get_nowait()
            except queue.Empty:
                break
            self.log(level, message)
        self.after(100, self._drain_worker_queue)

    def read_id(self) -> str:
        return self._board.id

    def read_outputs_mask(self) -> str:
        mask = self._board.fixture_outputs_mask
        return f"{mask} (binaire {mask:08b})"

    def reset_board(self) -> None:
        self._board.reset()

    def clear_errors(self) -> None:
        self._board.clear_errors()

    def read_error(self) -> str:
        return str(self._board.get_error())

    def read_target(self) -> str:
        return str(self._board.active_target)

    def write_target(self) -> None:
        self._board.active_target = int(self.target_var.get())

    def power_on(self, index: int) -> None:
        self._board.power_on(index)

    def power_off(self, index: int) -> None:
        self._board.power_off(index)

    def power_on_selected(self) -> None:
        self._board.power_on(int(self.power_output_var.get()))

    def power_off_selected(self) -> None:
        self._board.power_off(int(self.power_output_var.get()))

    def power_cycle_selected(self) -> None:
        self._board.power_cycle(int(self.power_output_var.get()), float(self.cycle_delay_var.get()))

    def raw_write(self) -> None:
        self._board.write_scpi_command(self.raw_command_var.get())

    def raw_query(self) -> str:
        return self._board.query_scpi_command(self.raw_command_var.get())

    @property
    def _board(self) -> BoardInterface:
        if self.board is None:
            raise RuntimeError("Board is not connected")
        return self.board

    def log(self, level: str, message: str) -> None:
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {level} - {message}\n")
        self.log_text.see(tk.END)

    def _on_close(self) -> None:
        self.disconnect_board()
        self.destroy()


def main() -> None:
    app = BoardInterfaceTester()
    app.mainloop()


if __name__ == "__main__":
    main()
