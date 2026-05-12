
import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox
import paho.mqtt.client as mqtt
import json
import threading
import datetime
import random
import math

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ─── MQTT ─────────────────────────────────────────────────────────────────────
MQTT_BROKER = "broker.emqx.io"
MQTT_PORT = 1883
MQTT_TOPIC_IN = "tollbooth/scan"
MQTT_TOPIC_CMD = "tollbooth/command"
MQTT_TOPIC_LOG = "tollbooth/log"

# ─── Palette: Deep Slate + Electric Lime ──────────────────────────────────────
C = {
    "bg": "#070B12",
    "bg2": "#0D1421",
    "bg3": "#111827",
    "border": "#1C2A3A",
    "border2": "#243040",
    "lime": "#AAFF00",
    "lime_dim": "#6EAA00",
    "amber": "#F59E0B",
    "red": "#FF3B5C",
    "cyan": "#00E5FF",
    "text": "#ECF0F7",
    "text2": "#B8C5D6",
    "muted": "#5A7A9A",
    "muted2": "#3A5570",
}

# Vehicle Database (No premium user - all regular)
VEHICLES = {
    "8BCFF105": {"name": "malak", "balance": 0.00, "plate": "ABC-123"},
 }
TOLL_FEE = 5.00
TRANSACTIONS = []


class RadarWidget(tk.Canvas):
    def __init__(self, parent, size=120, **kw):
        super().__init__(parent, width=size, height=size, highlightthickness=0, **kw)
        self.size = size
        self.cx = size // 2
        self.cy = size // 2
        self.r = size // 2 - 8
        self.angle = 0
        self._draw()

    def _draw(self):
        self.delete("all")
        cx, cy, r = self.cx, self.cy, self.r
        for i in range(1, 4):
            rr = r * i / 3
            self.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, outline=C["lime_dim"], width=1)
        self.create_line(cx - r, cy, cx + r, cy, fill=C["lime_dim"], width=1)
        self.create_line(cx, cy - r, cx, cy + r, fill=C["lime_dim"], width=1)
        for i in range(60):
            a = math.radians(self.angle - i * 2)
            alpha = int(180 * (1 - i / 60))
            col = self._fade(C["lime"], alpha)
            x2 = cx + r * math.cos(a)
            y2 = cy + r * math.sin(a)
            self.create_line(cx, cy, x2, y2, fill=col, width=1)
        a = math.radians(self.angle)
        x2 = cx + r * math.cos(a)
        y2 = cy + r * math.sin(a)
        self.create_line(cx, cy, x2, y2, fill=C["lime"], width=2)
        self.create_oval(cx - 3, cy - 3, cx + 3, cy + 3, fill=C["lime"], outline="")
        self.angle = (self.angle + 3) % 360
        self.after(40, self._draw)

    @staticmethod
    def _fade(hex_color, alpha):
        r = int(hex_color[1:3], 16)
        g = int(hex_color[3:5], 16)
        b = int(hex_color[5:7], 16)
        a = alpha / 255
        br, bg_, bb = 0x11, 0x18, 0x27
        return f"#{int(r * a + br * (1 - a)):02x}{int(g * a + bg_ * (1 - a)):02x}{int(b * a + bb * (1 - a)):02x}"


class GateArc(tk.Canvas):
    def __init__(self, parent, size=160, **kw):
        super().__init__(parent, width=size, height=size, highlightthickness=0, **kw)
        self.size = size
        self.open = False
        self._phase = 0
        self._draw()

    def set_open(self, is_open):
        self.open = is_open

    def _draw(self):
        self.delete("all")
        s = self.size
        pad = 16
        cx = cy = s // 2
        self.create_oval(pad // 2, pad // 2, s - pad // 2, s - pad // 2, outline=C["border2"], width=1)
        if self.open:
            pulse = 0.6 + 0.4 * abs(math.sin(math.radians(self._phase)))
            glow_color = self._alpha_blend(C["lime"], C["bg3"], pulse)
            self.create_oval(pad, pad, s - pad, s - pad, outline=glow_color, width=4)
            start = self._phase % 360
            self.create_arc(pad + 4, pad + 4, s - pad - 4, s - pad - 4, start=start, extent=240, style="arc", outline=C["lime"], width=3)
            self.create_arc(pad + 4, pad + 4, s - pad - 4, s - pad - 4, start=start + 240, extent=60, style="arc", outline=C["lime_dim"], width=1)
        else:
            for i in range(12):
                angle = math.radians(i * 30 + self._phase * 0.1)
                r_out = s // 2 - pad
                r_in = r_out - 6
                x1 = cx + r_in * math.cos(angle)
                y1 = cy + r_in * math.sin(angle)
                x2 = cx + r_out * math.cos(angle)
                y2 = cy + r_out * math.sin(angle)
                self.create_line(x1, y1, x2, y2, fill=C["muted2"], width=2)
        icon = "▲" if self.open else "▬"
        icon_color = C["lime"] if self.open else C["red"]
        self.create_text(cx, cy - 10, text=icon, fill=icon_color, font=("Courier New", 22, "bold"))
        status = "OPEN" if self.open else "CLOSED"
        self.create_text(cx, cy + 18, text=status, fill=icon_color, font=("Courier New", 11, "bold"))
        self._phase = (self._phase + 4) % 3600
        self.after(40, self._draw)

    @staticmethod
    def _alpha_blend(hex_a, hex_b, t):
        def parse(h): return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)
        r1, g1, b1 = parse(hex_a)
        r2, g2, b2 = parse(hex_b)
        return f"#{int(r1 * t + r2 * (1 - t)):02x}{int(g1 * t + g2 * (1 - t)):02x}{int(b1 * t + b2 * (1 - t)):02x}"


class TollBoothApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("TollGate Pro · Control System v2")
        self.geometry("1400x840")
        self.minsize(1200, 740)
        self.configure(fg_color=C["bg"])
        self.mqtt_connected = False
        self.mqtt_client = None
        self.gate_open = False
        self._build_ui()
        self._start_mqtt()

    def _build_ui(self):
        # Sidebar
        self.sidebar = tk.Frame(self, bg=C["bg2"], width=220)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        logo_block = tk.Frame(self.sidebar, bg=C["bg2"])
        logo_block.pack(fill="x")
        tk.Frame(logo_block, bg=C["lime"], height=3).pack(fill="x")
        tk.Label(logo_block, text="TOLLGATE", font=("Courier New", 17, "bold"), fg=C["lime"], bg=C["bg2"]).pack(pady=(18, 0))
        tk.Label(logo_block, text="P R O", font=("Courier New", 9), fg=C["muted"], bg=C["bg2"]).pack()
        tk.Label(logo_block, text="CONTROL SYSTEM", font=("Courier New", 7), fg=C["muted2"], bg=C["bg2"]).pack(pady=(0, 14))
        radar = RadarWidget(self.sidebar, size=110, bg=C["bg2"])
        radar.pack(pady=(4, 16))
        tk.Frame(self.sidebar, bg=C["border2"], height=1).pack(fill="x", padx=20)
        self.nav_btns = {}
        nav_items = [("DASHBOARD", "◈"), ("VEHICLES", "◉"), ("TRANSACTIONS", "▤"), ("SETTINGS", "◎")]
        for label, icon in nav_items:
            btn = tk.Button(self.sidebar, text=f" {icon}  {label}", anchor="w", font=("Courier New", 10, "bold"), fg=C["muted"], bg=C["bg2"], activeforeground=C["lime"], activebackground=C["bg3"], relief="flat", bd=0, padx=18, pady=12, cursor="hand2", command=lambda l=label: self._switch_tab(l))
            btn.pack(fill="x")
            self.nav_btns[label] = btn
        tk.Frame(self.sidebar, bg=C["bg2"]).pack(fill="both", expand=True)
        tk.Frame(self.sidebar, bg=C["border2"], height=1).pack(fill="x", padx=20)
        mqtt_frame = tk.Frame(self.sidebar, bg=C["bg2"])
        mqtt_frame.pack(fill="x", padx=16, pady=14)
        self.mqtt_dot = tk.Label(mqtt_frame, text="●", font=("Courier New", 12), fg=C["amber"], bg=C["bg2"])
        self.mqtt_dot.pack(side="left")
        self.mqtt_lbl = tk.Label(mqtt_frame, text=" CONNECTING", font=("Courier New", 8), fg=C["muted"], bg=C["bg2"])
        self.mqtt_lbl.pack(side="left")
        tk.Frame(self.sidebar, bg=C["lime"], height=2).pack(side="bottom", fill="x")
        # Main area
        self.main = tk.Frame(self, bg=C["bg"])
        self.main.pack(side="left", fill="both", expand=True)
        topbar = tk.Frame(self.main, bg=C["bg2"], height=52)
        topbar.pack(fill="x")
        topbar.pack_propagate(False)
        tk.Frame(topbar, bg=C["lime"], width=3).pack(side="left", fill="y")
        self.page_title_lbl = tk.Label(topbar, text="DASHBOARD", font=("Courier New", 14, "bold"), fg=C["lime"], bg=C["bg2"])
        self.page_title_lbl.pack(side="left", padx=20)
        self.breadcrumb = tk.Label(topbar, text="/ OVERVIEW", font=("Courier New", 9), fg=C["muted"], bg=C["bg2"])
        self.breadcrumb.pack(side="left")
        self.clock_lbl = tk.Label(topbar, text="", font=("Courier New", 10), fg=C["muted"], bg=C["bg2"])
        self.clock_lbl.pack(side="right", padx=20)
        self._tick_clock()
        self.frames = {}
        for name, builder in [("DASHBOARD", self._build_dashboard), ("VEHICLES", self._build_vehicles), ("TRANSACTIONS", self._build_transactions), ("SETTINGS", self._build_settings)]:
            f = tk.Frame(self.main, bg=C["bg"])
            builder(f)
            self.frames[name] = f
        self._switch_tab("DASHBOARD")

    def _switch_tab(self, name):
        for n, f in self.frames.items():
            f.pack_forget()
        self.frames[name].pack(fill="both", expand=True)
        self.page_title_lbl.configure(text=name)
        sub = {"DASHBOARD": "OVERVIEW", "VEHICLES": "REGISTRY", "TRANSACTIONS": "HISTORY", "SETTINGS": "CONFIG"}
        self.breadcrumb.configure(text=f"/ {sub.get(name, '')}")
        for n, btn in self.nav_btns.items():
            btn.configure(fg=C["lime"] if n == name else C["muted"], bg=C["bg3"] if n == name else C["bg2"])

    def _build_dashboard(self, parent):
        kpi_row = tk.Frame(parent, bg=C["bg"])
        kpi_row.pack(fill="x", padx=18, pady=(16, 0))
        self.kpi_total = self._kpi(kpi_row, "SCANS", "0", C["cyan"], "◈")
        self.kpi_rev = self._kpi(kpi_row, "REVENUE", "EGP 0.00", C["lime"], "◆")
        self.kpi_denied = self._kpi(kpi_row, "DENIED", "0", C["red"], "✕")
        self.kpi_gate = self._kpi(kpi_row, "GATE", "CLOSED", C["amber"], "▬")
        mid = tk.Frame(parent, bg=C["bg"])
        mid.pack(fill="both", expand=True, padx=18, pady=12)
        left = tk.Frame(mid, bg=C["bg"])
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))
        self._section_label(left, "◈  LAST RFID SCAN")
        scan_card = self._card(left)
        scan_card.pack(fill="x", pady=(4, 10))
        self.scan_uid = tk.Label(scan_card, text="– – – – – – – –", font=("Courier New", 26, "bold"), fg=C["text"], bg=C["bg3"])
        self.scan_uid.pack(anchor="w", padx=20, pady=(16, 2))
        self.scan_name = tk.Label(scan_card, text="Awaiting scan…", font=("Courier New", 11), fg=C["muted"], bg=C["bg3"])
        self.scan_name.pack(anchor="w", padx=20)
        self.scan_status = tk.Label(scan_card, text="", font=("Courier New", 13, "bold"), fg=C["muted"], bg=C["bg3"])
        self.scan_status.pack(anchor="w", padx=20, pady=(4, 16))
        self._section_label(left, "▬  GATE CONTROL")
        gate_card = self._card(left)
        gate_card.pack(fill="both", expand=True, pady=(4, 0))
        self.gate_arc = GateArc(gate_card, size=154, bg=C["bg3"])
        self.gate_arc.pack(pady=(18, 12))
        btn_row = tk.Frame(gate_card, bg=C["bg3"])
        btn_row.pack(pady=(0, 18))
        self._pill_btn(btn_row, "▲  OPEN", C["lime"], "#000", lambda: self._send_cmd("OPEN")).pack(side="left", padx=(0, 8))
        self._pill_btn(btn_row, "▬  CLOSE", C["red"], "#fff", lambda: self._send_cmd("CLOSE")).pack(side="left")
        right = tk.Frame(mid, bg=C["bg"])
        right.pack(side="right", fill="both", expand=True, padx=(10, 0))
        self._section_label(right, "▤  LIVE EVENT FEED")
        feed_card = self._card(right)
        feed_card.pack(fill="both", expand=True, pady=(4, 0))
        self.feed_box = tk.Text(feed_card, bg=C["bg3"], fg=C["text2"], font=("Courier New", 10), insertbackground=C["lime"], relief="flat", bd=0, padx=14, pady=10, state="disabled", wrap="word")
        self.feed_box.pack(fill="both", expand=True, padx=2, pady=2)
        self.feed_box.tag_config("ok", foreground=C["lime"])
        self.feed_box.tag_config("err", foreground=C["red"])
        self.feed_box.tag_config("info", foreground=C["cyan"])
        self.feed_box.tag_config("ts", foreground=C["muted"])
        sb = ttk.Scrollbar(feed_card, command=self.feed_box.yview)
        sb.pack(side="right", fill="y")
        self.feed_box.configure(yscrollcommand=sb.set)

    def _kpi(self, parent, label, value, color, icon):
        card = tk.Frame(parent, bg=C["bg3"], highlightbackground=C["border2"], highlightthickness=1)
        card.pack(side="left", expand=True, fill="both", padx=5)
        tk.Frame(card, bg=color, height=2).pack(fill="x")
        tk.Label(card, text=icon, font=("Courier New", 14), fg=color, bg=C["bg3"]).pack(anchor="w", padx=16, pady=(12, 0))
        tk.Label(card, text=label, font=("Courier New", 8, "bold"), fg=C["muted"], bg=C["bg3"]).pack(anchor="w", padx=16)
        lbl = tk.Label(card, text=value, font=("Courier New", 22, "bold"), fg=color, bg=C["bg3"])
        lbl.pack(anchor="w", padx=16, pady=(4, 14))
        return lbl

    def _section_label(self, parent, text):
        tk.Label(parent, text=text, font=("Courier New", 9, "bold"), fg=C["muted"], bg=C["bg"]).pack(anchor="w", pady=(0, 2))

    def _card(self, parent):
        return tk.Frame(parent, bg=C["bg3"], highlightbackground=C["border2"], highlightthickness=1)

    def _pill_btn(self, parent, text, bg, fg, cmd):
        btn = tk.Button(parent, text=text, font=("Courier New", 11, "bold"), fg=fg, bg=bg, activeforeground=fg, activebackground=bg, relief="flat", bd=0, padx=22, pady=10, cursor="hand2", command=cmd)
        btn.bind("<Enter>", lambda e: btn.configure(bg=self._darken(bg)))
        btn.bind("<Leave>", lambda e: btn.configure(bg=bg))
        return btn

    @staticmethod
    def _darken(hex_color, factor=0.8):
        r = int(int(hex_color[1:3], 16) * factor)
        g = int(int(hex_color[3:5], 16) * factor)
        b = int(int(hex_color[5:7], 16) * factor)
        return f"#{r:02x}{g:02x}{b:02x}"

    def _build_vehicles(self, parent):
        toolbar = tk.Frame(parent, bg=C["bg"])
        toolbar.pack(fill="x", padx=18, pady=(16, 8))
        tk.Label(toolbar, text="◉  VEHICLE REGISTRY", font=("Courier New", 12, "bold"), fg=C["lime"], bg=C["bg"]).pack(side="left")
        self._pill_btn(toolbar, "+ ADD", C["cyan"], "#000", self._add_vehicle_dialog).pack(side="right", padx=(4, 0))
        self._pill_btn(toolbar, "✕ REMOVE", C["red"], "#fff", self._remove_vehicle).pack(side="right", padx=4)
        self._pill_btn(toolbar, "◆ TOP UP", C["lime"], "#000", self._topup_dialog).pack(side="right", padx=4)
        table_frame = self._card(parent)
        table_frame.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Pro.Treeview", background=C["bg3"], fieldbackground=C["bg3"], foreground=C["text2"], rowheight=44, borderwidth=0, font=("Courier New", 11))
        style.configure("Pro.Treeview.Heading", background=C["bg2"], foreground=C["muted"], font=("Courier New", 9, "bold"), relief="flat", borderwidth=0)
        style.map("Pro.Treeview", background=[("selected", C["lime"])], foreground=[("selected", "#000")])
        cols = ("UID", "Name", "Plate", "Balance", "Status")
        self.tree = ttk.Treeview(table_frame, columns=cols, show="headings", style="Pro.Treeview")
        for col, w in zip(cols, [145, 170, 120, 120, 90]):
            self.tree.heading(col, text=col)
            self.tree.column(col, width=w, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=2, pady=2)
        self._refresh_tree()

    def _refresh_tree(self):
        for row in self.tree.get_children():
            self.tree.delete(row)
        for uid, info in VEHICLES.items():
            bal = f"EGP {info['balance']:.2f}"
            status = "ACTIVE" if info["balance"] >= TOLL_FEE else "LOW BAL"
            self.tree.insert("", "end", values=(uid, info["name"], info["plate"], bal, status))

    def _add_vehicle_dialog(self):
        dlg = ctk.CTkToplevel(self)
        dlg.title("Register Vehicle")
        dlg.geometry("430x340")
        dlg.configure(fg_color=C["bg2"])
        dlg.grab_set()
        tk.Frame(dlg, bg=C["lime"], height=3).pack(fill="x")
        tk.Label(dlg, text="◉  REGISTER VEHICLE", font=("Courier New", 13, "bold"), fg=C["lime"], bg=C["bg2"]).pack(pady=(16, 12))
        fields = {}
        for lbl, key in [("RFID UID", "uid"), ("OWNER NAME", "name"), ("PLATE NUMBER", "plate"), ("INITIAL BALANCE (EGP)", "balance")]:
            tk.Label(dlg, text=lbl, font=("Courier New", 8), fg=C["muted"], bg=C["bg2"]).pack(anchor="w", padx=30, pady=(8, 2))
            e = ctk.CTkEntry(dlg, width=350, height=32, fg_color=C["bg3"], border_color=C["border2"], text_color=C["text"], corner_radius=4, font=ctk.CTkFont(family="Courier New", size=11))
            e.pack(padx=30)
            fields[key] = e

        def save():
            uid = fields["uid"].get().strip().upper().replace(" ", "")
            name = fields["name"].get().strip()
            plate = fields["plate"].get().strip()
            try:
                bal = float(fields["balance"].get())
            except ValueError:
                messagebox.showerror("Error", "Balance must be a number")
                return
            if not uid or not name:
                messagebox.showerror("Error", "UID and Name required")
                return
            VEHICLES[uid] = {"name": name, "plate": plate, "balance": bal}
            self._refresh_tree()
            self._log(f"Vehicle added: {name} ({uid})", "ok")
            dlg.destroy()

        self._pill_btn(dlg, "REGISTER →", C["lime"], "#000", save).pack(pady=16)

    def _topup_dialog(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Info", "Select a vehicle first")
            return
        uid = self.tree.item(sel[0])["values"][0]
        info = VEHICLES.get(uid)
        if not info:
            return
        dlg = ctk.CTkToplevel(self)
        dlg.title("Top Up")
        dlg.geometry("380x230")
        dlg.configure(fg_color=C["bg2"])
        dlg.grab_set()
        tk.Frame(dlg, bg=C["lime"], height=3).pack(fill="x")
        tk.Label(dlg, text=f"◆  TOP UP: {info['name'].upper()}", font=("Courier New", 12, "bold"), fg=C["lime"], bg=C["bg2"]).pack(pady=(16, 4))
        tk.Label(dlg, text=f"Current Balance: EGP {info['balance']:.2f}", font=("Courier New", 10), fg=C["muted"], bg=C["bg2"]).pack()
        tk.Label(dlg, text="AMOUNT (EGP)", font=("Courier New", 8), fg=C["muted"], bg=C["bg2"]).pack(anchor="w", padx=30, pady=(16, 4))
        amt_e = ctk.CTkEntry(dlg, width=300, height=32, fg_color=C["bg3"], border_color=C["border2"], text_color=C["text"], corner_radius=4, font=ctk.CTkFont(family="Courier New", size=13))
        amt_e.pack(padx=30)

        def do():
            try:
                amt = float(amt_e.get())
                if amt <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Error", "Enter valid amount")
                return
            VEHICLES[uid]["balance"] += amt
            self._refresh_tree()
            self._log(f"Top-up EGP {amt:.2f} → {info['name']}", "ok")
            dlg.destroy()

        self._pill_btn(dlg, "CONFIRM →", C["lime"], "#000", do).pack(pady=16)

    def _remove_vehicle(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Info", "Select a vehicle first")
            return
        uid = self.tree.item(sel[0])["values"][0]
        name = VEHICLES[uid]["name"]
        if messagebox.askyesno("Confirm", f"Remove {name} ({uid})?"):
            VEHICLES.pop(uid, None)
            self._refresh_tree()
            self._log(f"Vehicle removed: {name}", "err")

    def _build_transactions(self, parent):
        toolbar = tk.Frame(parent, bg=C["bg"])
        toolbar.pack(fill="x", padx=18, pady=(16, 8))
        tk.Label(toolbar, text="▤  TRANSACTION HISTORY", font=("Courier New", 12, "bold"), fg=C["lime"], bg=C["bg"]).pack(side="left")
        self._pill_btn(toolbar, "✕ CLEAR", C["red"], "#fff", self._clear_transactions).pack(side="right")
        table_frame = self._card(parent)
        table_frame.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        style = ttk.Style()
        style.configure("TX.Treeview", background=C["bg3"], fieldbackground=C["bg3"], foreground=C["text2"], rowheight=40, borderwidth=0, font=("Courier New", 11))
        style.configure("TX.Treeview.Heading", background=C["bg2"], foreground=C["muted"], font=("Courier New", 9, "bold"), relief="flat", borderwidth=0)
        style.map("TX.Treeview", background=[("selected", C["lime"])], foreground=[("selected", "#000")])
        cols = ("#", "TIME", "UID", "NAME", "FEE", "RESULT", "BALANCE")
        self.tx_tree = ttk.Treeview(table_frame, columns=cols, show="headings", style="TX.Treeview")
        for col, w in zip(cols, [40, 100, 150, 165, 80, 110, 100]):
            self.tx_tree.heading(col, text=col)
            self.tx_tree.column(col, width=w, anchor="center")
        self.tx_tree.pack(fill="both", expand=True, padx=2, pady=2)

    def _add_transaction(self, uid, name, result, balance_after):
        t = datetime.datetime.now().strftime("%H:%M:%S")
        fee = f"EGP {TOLL_FEE:.2f}" if result == "GRANTED" else "—"
        bal = f"EGP {balance_after:.2f}"
        icon = "✓" if result == "GRANTED" else "✕"
        idx = len(TRANSACTIONS) + 1
        TRANSACTIONS.append({"time": t, "uid": uid, "name": name, "result": result, "balance_after": balance_after})
        self.tx_tree.insert("", 0, values=(idx, t, uid, name, fee, f"{icon} {result}", bal))

    def _clear_transactions(self):
        if messagebox.askyesno("Confirm", "Clear all transactions?"):
            TRANSACTIONS.clear()
            for row in self.tx_tree.get_children():
                self.tx_tree.delete(row)
            self._log("Transactions cleared", "info")

    def _build_settings(self, parent):
        card1 = self._card(parent)
        card1.pack(fill="x", padx=18, pady=(16, 8))
        tk.Frame(card1, bg=C["cyan"], height=2).pack(fill="x")
        tk.Label(card1, text="◈  MQTT CONFIGURATION", font=("Courier New", 11, "bold"), fg=C["cyan"], bg=C["bg3"]).pack(anchor="w", padx=20, pady=(14, 8))
        for label, val in [("BROKER HOST", MQTT_BROKER), ("PORT", str(MQTT_PORT)), ("ESP32 → SERVER TOPIC", MQTT_TOPIC_IN), ("SERVER → ESP32 TOPIC", MQTT_TOPIC_CMD)]:
            row = tk.Frame(card1, bg=C["bg3"])
            row.pack(fill="x", padx=20, pady=3)
            tk.Label(row, text=label, font=("Courier New", 8), fg=C["muted"], bg=C["bg3"], width=26, anchor="w").pack(side="left")
            tk.Label(row, text=val, font=("Courier New", 10, "bold"), fg=C["text"], bg=C["bg3"]).pack(side="left")
        card2 = self._card(parent)
        card2.pack(fill="x", padx=18, pady=8)
        tk.Frame(card2, bg=C["amber"], height=2).pack(fill="x")
        tk.Label(card2, text="◆  TOLL FEE", font=("Courier New", 11, "bold"), fg=C["amber"], bg=C["bg3"]).pack(anchor="w", padx=20, pady=(14, 6))
        fee_row = tk.Frame(card2, bg=C["bg3"])
        fee_row.pack(anchor="w", padx=20, pady=(0, 14))
        tk.Label(fee_row, text="FEE (EGP):", font=("Courier New", 9), fg=C["muted"], bg=C["bg3"]).pack(side="left", padx=(0, 8))
        self.fee_entry = ctk.CTkEntry(fee_row, width=100, height=30, fg_color=C["bg2"], border_color=C["border2"], text_color=C["text"], corner_radius=4, font=ctk.CTkFont(family="Courier New", size=12))
        self.fee_entry.insert(0, str(TOLL_FEE))
        self.fee_entry.pack(side="left", padx=(0, 8))
        self._pill_btn(fee_row, "APPLY", C["amber"], "#000", self._update_fee).pack(side="left")
        card3 = self._card(parent)
        card3.pack(fill="x", padx=18, pady=8)
        tk.Frame(card3, bg=C["lime"], height=2).pack(fill="x")
        tk.Label(card3, text="▶  DEMO MODE", font=("Courier New", 11, "bold"), fg=C["lime"], bg=C["bg3"]).pack(anchor="w", padx=20, pady=(14, 4))
        tk.Label(card3, text="Test without hardware", font=("Courier New", 9), fg=C["muted"], bg=C["bg3"]).pack(anchor="w", padx=20, pady=(0, 10))
        btn_row = tk.Frame(card3, bg=C["bg3"])
        btn_row.pack(anchor="w", padx=20, pady=(0, 16))
        self._pill_btn(btn_row, "✓ VALID CARD", C["lime"], "#000", lambda: self._simulate_scan(True)).pack(side="left", padx=(0, 10))
        self._pill_btn(btn_row, "✕ INVALID CARD", C["red"], "#fff", lambda: self._simulate_scan(False)).pack(side="left")

    def _update_fee(self):
        global TOLL_FEE
        try:
            TOLL_FEE = float(self.fee_entry.get())
            self._log(f"Toll fee → EGP {TOLL_FEE:.2f}", "info")
        except ValueError:
            messagebox.showerror("Error", "Invalid amount")

    def _start_mqtt(self):
        def connect():
            try:
                self.mqtt_client = mqtt.Client(client_id="tollbooth_pro_v3")
                self.mqtt_client.on_connect = self._on_mqtt_connect
                self.mqtt_client.on_disconnect = self._on_mqtt_disconnect
                self.mqtt_client.on_message = self._on_mqtt_message
                self.mqtt_client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
                self.mqtt_client.loop_forever()
            except Exception as e:
                self.after(0, lambda: self._set_mqtt("offline", str(e)))
        threading.Thread(target=connect, daemon=True).start()

    def _set_mqtt(self, status, msg=""):
        colors = {"connected": C["lime"], "connecting": C["amber"], "offline": C["red"]}
        labels = {"connected": "CONNECTED", "connecting": "CONNECTING…", "offline": "OFFLINE"}
        col = colors.get(status, C["muted"])
        self.mqtt_dot.configure(fg=col)
        self.mqtt_lbl.configure(text=f" {labels.get(status, '')}", fg=col)

    def _on_mqtt_connect(self, client, userdata, flags, rc):
        self.mqtt_connected = True
        self.mqtt_client.subscribe(MQTT_TOPIC_IN)
        self.mqtt_client.subscribe(MQTT_TOPIC_LOG)
        self.after(0, lambda: self._set_mqtt("connected"))
        self._log("MQTT connected to broker.emqx.io", "info")

    def _on_mqtt_disconnect(self, client, userdata, rc):
        self.mqtt_connected = False
        self.after(0, lambda: self._set_mqtt("offline"))

    def _on_mqtt_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode())
        except Exception:
            return
        self.after(0, lambda p=payload: self._handle_scan(p))

    def _send_cmd(self, command):
        payload = json.dumps({"command": command, "timestamp": datetime.datetime.now().isoformat()})
        if self.mqtt_client and self.mqtt_connected:
            self.mqtt_client.publish(MQTT_TOPIC_CMD, payload)
        self._log(f"Command: {command}", "info")
        if command == "OPEN":
            self.gate_open = True
            self.gate_arc.set_open(True)
            self.kpi_gate.configure(text="OPEN", fg=C["lime"])
            self.after(4000, lambda: self._send_cmd("CLOSE"))
        else:
            self.gate_open = False
            self.gate_arc.set_open(False)
            self.kpi_gate.configure(text="CLOSED", fg=C["amber"])

    def _handle_scan(self, payload):
        uid = payload.get("uid", "").strip().upper().replace(" ", "")
        info = VEHICLES.get(uid)
        if info and info["balance"] >= TOLL_FEE:
            VEHICLES[uid]["balance"] -= TOLL_FEE
            result = "GRANTED"
            color = C["lime"]
            self._send_cmd("OPEN")
        else:
            result = "DENIED"
            color = C["red"]
        name = info["name"] if info else "Unknown"
        bal_after = info["balance"] if info else 0.0
        self.kpi_total.configure(text=str(len(TRANSACTIONS) + 1))
        self.kpi_rev.configure(text=f"EGP {sum(TOLL_FEE for tx in TRANSACTIONS if tx['result'] == 'GRANTED') + (TOLL_FEE if result == 'GRANTED' else 0):.2f}")
        self.kpi_denied.configure(text=str(sum(1 for tx in TRANSACTIONS if tx['result'] == 'DENIED') + (1 if result == 'DENIED' else 0)))
        self.scan_uid.configure(text=uid or "UNKNOWN")
        self.scan_name.configure(text=f"{name.upper()}  ·  BAL EGP {bal_after:.2f}")
        icon = "✓" if result == "GRANTED" else "✕"
        self.scan_status.configure(text=f"{icon}  {result}", fg=color)
        tag = "ok" if result == "GRANTED" else "err"
        self._log(f"SCAN  {uid}  →  {name}  →  {result}", tag)
        self._add_transaction(uid, name, result, bal_after)
        self._refresh_tree()

    def _simulate_scan(self, valid=True):
        if valid:
            candidates = [u for u, v in VEHICLES.items() if v["balance"] >= TOLL_FEE]
            uid = random.choice(candidates) if candidates else list(VEHICLES.keys())[0]
        else:
            uid = "FFFFFFFF"
        self._handle_scan({"uid": uid})

    def _log(self, text, tag="info"):
        stamp = datetime.datetime.now().strftime("%H:%M:%S")
        prefix = {"ok": "✓", "err": "✕", "info": "◈"}.get(tag, "·")
        self.feed_box.configure(state="normal")
        self.feed_box.insert("1.0", "\n")
        self.feed_box.insert("1.0", f"  {text}\n", tag)
        self.feed_box.insert("1.0", f"[{stamp}] {prefix}", "ts")
        self.feed_box.configure(state="disabled")

    def _tick_clock(self):
        now = datetime.datetime.now().strftime("%a %d %b %Y   %H:%M:%S")
        self.clock_lbl.configure(text=now)
        self.after(1000, self._tick_clock)


if __name__ == "__main__":
    app = TollBoothApp()
    app.mainloop()