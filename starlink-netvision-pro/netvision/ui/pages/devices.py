from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import QInputDialog, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from netvision.ui import theme
from netvision.ui.widgets import Card, DataTable, fmt_bytes, hbox, hint


class DevicesPage(QWidget):
    title = "Dispositivos"

    def __init__(self, engine):
        super().__init__()
        self.e = engine
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(12)
        self.info = QLabel("Aguardando primeira varredura…")
        self.info.setObjectName("hint")
        b_scan = QPushButton("Escanear agora")
        b_scan.setObjectName("primary")
        b_scan.clicked.connect(engine.request_scan)
        b_name = QPushButton("Renomear…")
        b_name.clicked.connect(self.rename)
        b_forget = QPushButton("Esquecer dispositivo")
        b_forget.clicked.connect(self.forget)
        root.addLayout(hbox(self.info, 1, b_name, b_forget, b_scan))
        root.addWidget(hint(
            "Fontes: <b>API Starlink</b> (nome DHCP, banda e sinal, quando o firmware libera) e <b>scanner local</b> "
            "(ARP/ICMP). “MAC privado” indica endereço aleatório do iPhone/Android/Windows, que esconde o fabricante; "
            "use <i>Renomear</i> para identificar o aparelho. Duplo clique também renomeia."))
        card = Card()
        self.table = DataTable(["Nome", "IP", "MAC", "Fabricante", "Conexão", "Consumo hoje ↓/↑", "Origem",
                                "Primeira vez", "Última vez", "Status"], stretch_col=0)
        self.table.doubleClicked.connect(lambda *_: self.rename())
        card.body.addWidget(self.table)
        root.addWidget(card, 1)
        self._devices: list[dict] = []
        self._usage: dict = {}
        engine.devices_updated.connect(self.on_devices)

    def on_devices(self, d: dict):
        self._devices = d["devices"]
        self._usage = d.get("usage") or {}
        online = sum(1 for x in self._devices if x.get("online"))
        self.info.setText(f"Rede {d['network']} · {online} online / {len(self._devices)} conhecidos · "
                          f"método: {d['method']} · varredura em {d['duration']:.1f} s · "
                          f"{datetime.now().strftime('%H:%M:%S')}")
        self.render()

    def render(self):
        rows, colors, keys = [], {}, []
        for i, x in enumerate(self._devices):
            name = x.get("custom_name") or x.get("hostname") or "(sem nome)"
            tags = []
            if x.get("is_self"):
                tags.append("este PC")
            if x.get("is_gateway"):
                tags.append("roteador Starlink")
            if tags:
                name += f"  [{', '.join(tags)}]"
            conn = x.get("iface") or ""
            if x.get("signal") is not None:
                conn += f" · {x['signal']:.0f} dBm"
            u = self._usage.get(x["mac"])
            usage = f"{fmt_bytes(u['rx'])} / {fmt_bytes(u['tx'])}" if u else "-"
            fs = datetime.fromtimestamp(x["first_seen"]).strftime("%d/%m %H:%M") if x.get("first_seen") else "-"
            ls = datetime.fromtimestamp(x["last_seen"]).strftime("%d/%m %H:%M") if x.get("last_seen") else "-"
            rows.append([name, x.get("ip"), x["mac"], x.get("vendor") or "-", conn or "-", usage, x.get("source") or "-",
                         fs, ls, "Online" if x.get("online") else "Offline"])
            colors[(i, 9)] = theme.OK if x.get("online") else theme.MUTED
            if not x.get("online"):
                colors[(i, 0)] = theme.MUTED
            keys.append(x["mac"])
        self.table.fill(rows, colors, keys)

    def _selected(self) -> dict | None:
        mac = self.table.selected_key()
        return next((d for d in self._devices if d["mac"] == mac), None)

    def rename(self):
        d = self._selected()
        if not d:
            QMessageBox.information(self, "Renomear", "Selecione um dispositivo na lista.")
            return
        cur = d.get("custom_name") or d.get("hostname") or ""
        name, ok = QInputDialog.getText(self, "Renomear dispositivo", f"Nome para {d['mac']} ({d.get('ip')}):", text=cur)
        if ok:
            self.e.db.set_custom_name(d["mac"], name)
            d["custom_name"] = name.strip() or None
            self.render()

    def forget(self):
        d = self._selected()
        if not d:
            return
        if QMessageBox.question(self, "Esquecer", f"Remover {d['mac']} do histórico de dispositivos?") == QMessageBox.Yes:
            self.e.db.forget_device(d["mac"])
            self.e.scanner.known.pop(d["mac"], None)
            self._devices.remove(d)
            self.render()
