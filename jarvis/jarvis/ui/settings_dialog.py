"""Tela de configurações: tudo que o JARVIS guarda pode ser visto, editado e apagado aqui."""
from __future__ import annotations

import json
import logging
import sys
from typing import Any, Callable

from PySide6.QtCore import Qt, QTime
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSlider,
    QSpinBox, QTableWidget, QTableWidgetItem, QTabWidget, QTimeEdit, QVBoxLayout, QWidget,
)

from ..core import paths
from ..core.secrets import KNOWN_KEYS
from ..platform import windows as win
from .bridge import run_async

log = logging.getLogger(__name__)


def csv(text: str) -> list[str]:
    return [p.strip() for p in text.split(",") if p.strip()]


class SettingsDialog(QDialog):
    def __init__(self, app, parent=None) -> None:
        super().__init__(parent)
        self.app = app
        self.services = app.services
        self.settings = app.services.settings
        self.secrets = app.services.secrets
        self.setWindowTitle("Configurações do JARVIS")
        self.resize(860, 680)
        self._binds: list[tuple[str, Callable[[], Any]]] = []
        self._secret_fields: dict[str, QLineEdit] = {}
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        for title, builder in (
            ("Geral", self._tab_general), ("Voz", self._tab_voice), ("Ativação", self._tab_wake),
            ("Jogos", self._tab_gaming), ("IA", self._tab_ai), ("Microsoft 365", self._tab_microsoft),
            ("Planilhas", self._tab_excel), ("WhatsApp", self._tab_whatsapp),
            ("Notificações", self._tab_notifications), ("Música", self._tab_music), ("Comandos", self._tab_commands),
            ("Privacidade e memória", self._tab_privacy),
        ):
            self.tabs.addTab(self._scroll(builder()), title)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = QPushButton("Cancelar")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Salvar")
        save.setObjectName("accent")
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        layout.addLayout(buttons)

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _scroll(widget: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(widget)
        area.setFrameShape(QScrollArea.NoFrame)
        return area

    def _form(self) -> tuple[QWidget, QFormLayout]:
        widget = QWidget()
        form = QFormLayout(widget)
        form.setLabelAlignment(Qt.AlignRight)
        form.setSpacing(10)
        return widget, form

    def _check(self, key: str, label: str) -> QCheckBox:
        box = QCheckBox(label)
        box.setChecked(bool(self.settings.get(key)))
        self._binds.append((key, box.isChecked))
        return box

    def _line(self, key: str, placeholder: str = "", as_list: bool = False) -> QLineEdit:
        edit = QLineEdit()
        value = self.settings.get(key)
        edit.setText(", ".join(value) if as_list and isinstance(value, list) else str(value or ""))
        edit.setPlaceholderText(placeholder)
        self._binds.append((key, (lambda e=edit: csv(e.text())) if as_list else edit.text))
        return edit

    def _combo(self, key: str, options: list[tuple[str, Any]]) -> QComboBox:
        combo = QComboBox()
        current = self.settings.get(key)
        for label, value in options:
            combo.addItem(label, value)
            if value == current:
                combo.setCurrentIndex(combo.count() - 1)
        self._binds.append((key, combo.currentData))
        return combo

    def _slider(self, key: str, low: int, high: int, scale: float = 1.0) -> QWidget:
        box = QWidget()
        row = QHBoxLayout(box)
        row.setContentsMargins(0, 0, 0, 0)
        slider = QSlider(Qt.Horizontal)
        slider.setRange(low, high)
        slider.setValue(int(float(self.settings.get(key) or 0) * scale))
        label = QLabel(str(slider.value()))
        label.setFixedWidth(40)
        slider.valueChanged.connect(lambda v: label.setText(str(v)))
        row.addWidget(slider)
        row.addWidget(label)
        self._binds.append((key, (lambda: slider.value() / scale) if scale != 1 else slider.value))
        return box

    def _spin(self, key: str, low: int, high: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(low, high)
        spin.setValue(int(self.settings.get(key) or 0))
        self._binds.append((key, spin.value))
        return spin

    def _secret(self, name: str) -> QLineEdit:
        edit = QLineEdit()
        edit.setEchoMode(QLineEdit.Password)
        edit.setPlaceholderText("guardada com segurança" if self.secrets.has(name) else "não configurada")
        self._secret_fields[name] = edit
        return edit

    @staticmethod
    def _note(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setObjectName("heard")
        label.setOpenExternalLinks(True)
        return label

    def _busy(self, button: QPushButton, fn: Callable[[], Any], done: Callable[[Any], None], label: str = "Aguarde…") -> None:
        original = button.text()
        button.setEnabled(False)
        button.setText(label)

        def finish(result, error):
            button.setEnabled(True)
            button.setText(original)
            if error:
                QMessageBox.warning(self, "JARVIS", str(error))
            else:
                done(result)

        run_async(fn, finish)

    # ---------------------------------------------------------------- abas
    def _tab_general(self) -> QWidget:
        w, f = self._form()
        f.addRow("Seu nome:", self._line("general.user_name", "usado em assinaturas e saudações"))
        f.addRow("Tratamento:", self._line("general.user_title", "ex.: senhor, senhora (vazio = nenhum)"))
        self.autostart = QCheckBox("Iniciar com o Windows (sem precisar de administrador)")
        self.autostart.setChecked(win.is_autostart_enabled())
        f.addRow("", self.autostart)
        f.addRow("", self._check("general.start_minimized", "Iniciar minimizado na bandeja"))
        f.addRow("", self._check("general.close_to_tray", "Fechar a janela mantém o JARVIS na bandeja"))
        f.addRow("", self._check("general.ui_animations", "Animações da interface"))
        f.addRow("", self._note(f"Dados locais: {paths.data_dir()}"))
        return w

    def _tab_voice(self) -> QWidget:
        w, f = self._form()
        f.addRow("Perfil de voz:", self._combo("voice.profile", [("JARVIS (masculina)", "jarvis"), ("FRIDAY (feminina)", "friday")]))
        f.addRow("Motor de voz:", self._combo("voice.engine", [
            ("Automático (neural online, com reserva offline)", "auto"), ("Neural Microsoft Edge (online, gratuito)", "edge"),
            ("Azure AI Speech (oficial, chave própria)", "azure"), ("Vozes do Windows (offline)", "sapi")]))
        f.addRow("Velocidade (%):", self._slider("voice.rate", -50, 50))
        f.addRow("Volume da voz:", self._slider("voice.volume", 10, 100))
        f.addRow("Respostas:", self._combo("voice.verbosity", [("Curtas", "short"), ("Detalhadas", "detailed")]))
        f.addRow("", self._check("voice.spoken_replies", "Responder falando (desligado = só texto na tela)"))
        f.addRow("Voz neural JARVIS:", self._line("profiles.jarvis.edge_voice"))
        f.addRow("Tom JARVIS:", self._line("profiles.jarvis.edge_pitch", "-4Hz"))
        f.addRow("Voz neural FRIDAY:", self._line("profiles.friday.edge_voice", "pt-BR-FranciscaNeural ou pt-BR-ThalitaMultilingualNeural"))
        f.addRow("Tom FRIDAY:", self._line("profiles.friday.edge_pitch", "+0Hz"))
        f.addRow("Região Azure:", self._line("voice.azure_region", "brazilsouth"))
        f.addRow("Chave Azure Speech:", self._secret("azure_speech_key"))
        test = QPushButton("Testar voz")
        test.clicked.connect(self._test_voice)
        f.addRow("", test)
        f.addRow("", self._note("As vozes originais dos filmes não podem ser usadas legalmente; os perfis usam vozes "
                                "neurais em português com estilo próximo. A voz neural online envia apenas o texto "
                                "da resposta para síntese; a reserva offline usa as vozes instaladas no Windows."))
        return w

    def _test_voice(self) -> None:
        self._save(close=False)
        name = "Friday" if self.settings.get("voice.profile") == "friday" else "Jarvis"
        self.app.speak(f"Olá. Eu sou {name}, seu assistente pessoal. Todos os sistemas operacionais.", force=True)

    def _tab_wake(self) -> QWidget:
        from ..audio.capture import list_input_devices, list_output_devices

        w, f = self._form()
        f.addRow("Detecção:", self._combo("wake.engine", [
            ("Local Vosk (gratuito, offline)", "vosk"), ("Porcupine (mais preciso, AccessKey grátis)", "porcupine"),
            ("Desligada (só atalho/botão)", "off")]))
        f.addRow("Palavra de ativação:", self._line("wake.words", "jarvis", as_list=True))
        f.addRow("Variantes aceitas:", self._line("wake.variants", "jarvis, jarbas…", as_list=True))
        calibrate = QPushButton("Calibrar com a minha voz")
        calibrate.clicked.connect(lambda: self._calibrate(calibrate))
        f.addRow("", calibrate)
        f.addRow("Sensibilidade:", self._slider("wake.sensitivity", 0, 100, scale=100))
        f.addRow("Resposta ao chamado:", self._combo("wake.ack_mode", [
            ("Voz (\"Às suas ordens\")", "voice"), ("Bipe", "beep"), ("Voz e bipe", "both"), ("Nenhuma", "none")]))
        f.addRow("", self._check("audio.beep_on_listen", "Bipe ao abrir o microfone (atalho/continuação)"))
        f.addRow("AccessKey Porcupine:", self._secret("porcupine_access_key"))
        f.addRow("Reconhecimento:", self._combo("stt.engine", [("Vosk local (leve)", "vosk"), ("Whisper local (preciso, mais CPU)", "whisper")]))
        f.addRow("Modelo Whisper:", self._combo("stt.whisper_model", [("base", "base"), ("small", "small"), ("medium", "medium")]))
        conf = QDoubleSpinBox()
        conf.setRange(0.0, 1.0)
        conf.setSingleStep(0.05)
        conf.setValue(float(self.settings.get("stt.min_confidence", 0.55)))
        self._binds.append(("stt.min_confidence", conf.value))
        f.addRow("Confiança mínima:", conf)
        mic = QComboBox()
        mic.addItem("Padrão do Windows", None)
        for index, name in list_input_devices():
            mic.addItem(name, index)
            if index == self.settings.get("audio.input_device"):
                mic.setCurrentIndex(mic.count() - 1)
        self._binds.append(("audio.input_device", mic.currentData))
        f.addRow("Microfone:", mic)
        out = QComboBox()
        out.addItem("Padrão do Windows", None)
        for index, name in list_output_devices():
            out.addItem(name, index)
            if index == self.settings.get("audio.output_device"):
                out.setCurrentIndex(out.count() - 1)
        self._binds.append(("audio.output_device", out.currentData))
        f.addRow("Saída da voz:", out)
        f.addRow("", self._note("O reconhecimento roda no seu computador: o áudio do microfone não é enviado para a "
                                "internet. Mudanças de detecção, microfone e modelo valem após reiniciar o JARVIS."))
        return w

    def _calibrate(self, button: QPushButton) -> None:
        pipeline = self.services.pipeline
        if pipeline is None:
            QMessageBox.information(self, "JARVIS", "O reconhecimento de voz não está ativo.")
            return
        QMessageBox.information(self, "Calibração", "Após clicar em OK, diga \"Jarvis\" três vezes, uma a cada bipe.")
        self._busy(button, lambda: pipeline.calibrate(3), lambda words: QMessageBox.information(
            self, "Calibração", "Variantes aprendidas: " + (", ".join(words) or "nenhuma (tente num ambiente mais silencioso)")),
            "Ouvindo…")

    def _tab_gaming(self) -> QWidget:
        w, f = self._form()
        f.addRow("", self._check("gaming.auto_game_mode", "Ativar modo jogo automaticamente"))
        f.addRow("Processos de jogos:", self._line("gaming.game_processes", "NSUNS4.exe", as_list=True))
        f.addRow("", self._check("gaming.detect_fullscreen", "Considerar qualquer app em tela cheia exclusiva como jogo"))
        f.addRow("", self._check("gaming.short_replies_in_game", "Respostas curtas durante jogos"))
        f.addRow("", self._check("gaming.silence_notifications_in_game", "Durante jogos, só avisar notificações importantes"))
        f.addRow("", self._check("gaming.pause_ui_in_game", "Pausar animações durante jogos"))
        f.addRow("", self._check("audio.duck_others", "Abaixar o som de outros apps enquanto falo"))
        f.addRow("", self._check("audio.duck_only_in_game", "…somente no modo jogo"))
        f.addRow("Volume dos outros apps (%):", self._slider("audio.duck_level", 0, 100))
        f.addRow("Atalho: parar fala:", self._line("gaming.hotkeys.stop_speech", "ctrl+alt+s"))
        f.addRow("Atalho: falar:", self._line("gaming.hotkeys.push_to_talk", "ctrl+alt+j"))
        f.addRow("Atalho: microfone:", self._line("gaming.hotkeys.toggle_mic", "ctrl+alt+m"))
        f.addRow("", self._check("gaming.gamepad.enabled", "Usar controle Xbox (XInput)"))
        f.addRow("Combinação falar:", self._line("gaming.gamepad.talk_combo", "BACK, LEFT_THUMB", as_list=True))
        f.addRow("Combinação parar:", self._line("gaming.gamepad.stop_combo", "BACK, RIGHT_THUMB", as_list=True))
        f.addRow("Segurar por (ms):", self._spin("gaming.gamepad.hold_ms", 100, 3000))
        f.addRow("", self._note("Botões: A, B, X, Y, BACK (View), START (Menu), LEFT_SHOULDER, RIGHT_SHOULDER, "
                                "LEFT_THUMB, RIGHT_THUMB, DPAD_UP/DOWN/LEFT/RIGHT. O botão Xbox (Guide) e o touchpad "
                                "do controle PlayStation não são acessíveis pelo XInput; com DS4Windows, mapeie o "
                                "touchpad para o atalho de teclado acima. O JARVIS não injeta nada no jogo."))
        return w

    def _tab_ai(self) -> QWidget:
        w, f = self._form()
        f.addRow("Provedor:", self._combo("ai.provider", [
            ("Nenhum (só comandos locais, sem custo)", "none"), ("Claude (Anthropic API, pago por uso)", "anthropic"),
            ("Ollama (modelo local gratuito)", "ollama")]))
        f.addRow("Modelo Claude:", self._line("ai.anthropic_model", "claude-opus-5-5"))
        f.addRow("Chave Anthropic:", self._secret("anthropic_api_key"))
        f.addRow("Esforço:", self._combo("ai.effort", [("Baixo (mais rápido)", "low"), ("Médio", "medium"), ("Alto", "high")]))
        f.addRow("URL do Ollama:", self._line("ai.ollama_url"))
        f.addRow("Modelo Ollama:", self._line("ai.ollama_model", "llama3.1"))
        f.addRow("", self._check("ai.send_content", "Permitir enviar conteúdo de e-mails/mensagens à IA para resumos"))
        f.addRow("", self._check("ai.web_search", "Claude pode pesquisar na internet (notícias, cotações, clima...)"))
        f.addRow("Pesquisas por pergunta:", self._spin("ai.web_search_max", 1, 10))
        test = QPushButton("Testar conexão")
        test.clicked.connect(lambda: (self._save(close=False), self._busy(
            test, self.services.llm.test, lambda text: QMessageBox.information(self, "IA", f"Resposta: {text}"))))
        f.addRow("", test)
        f.addRow("", self._note("A IA só é usada quando o comando não é reconhecido localmente ou para resumir e "
                                "redigir textos. A API da Anthropic é cobrada por uso: crie a chave em "
                                "<a href='https://console.anthropic.com/'>console.anthropic.com</a>. "
                                "O Ollama roda no seu PC sem custo, mas exige memória e um modelo com suporte a ferramentas."))
        return w

    def _tab_microsoft(self) -> QWidget:
        w, f = self._form()
        f.addRow("ID do aplicativo (client id):", self._line("microsoft.client_id", "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"))
        f.addRow("Locatário (tenant):", self._line("microsoft.tenant", "common, organizations ou o ID da empresa"))
        f.addRow("", self._check("microsoft.features.mail", "Ler e-mails e criar rascunhos"))
        f.addRow("", self._check("microsoft.features.send_mail", "Permitir envio (sempre com confirmação)"))
        f.addRow("", self._check("microsoft.features.calendar", "Ler calendário"))
        f.addRow("", self._check("microsoft.features.excel", "Planilhas do OneDrive/SharePoint"))
        f.addRow("Verificar e-mails a cada (min):", self._spin("microsoft.poll_minutes", 1, 60))
        f.addRow("Gestor (nome ou e-mail):", self._line("outlook.manager"))
        f.addRow("Remetentes importantes:", self._line("outlook.important_senders", "emails separados por vírgula", as_list=True))
        f.addRow("Palavras urgentes:", self._line("outlook.urgent_keywords", as_list=True))
        f.addRow("", self._check("outlook.notify_new", "Avisar novos e-mails"))
        self.ms_status = QLabel("verificando…")
        run_async(self._ms_status_text, lambda text, error: self.ms_status.setText(text if not error else "indisponível"))
        f.addRow("Situação:", self.ms_status)
        row = QHBoxLayout()
        connect = QPushButton("Conectar (navegador)")
        connect.setObjectName("accent")
        connect.clicked.connect(lambda: self._ms_connect(connect, device=False))
        code = QPushButton("Conectar com código")
        code.clicked.connect(lambda: self._ms_connect(code, device=True))
        disconnect = QPushButton("Desconectar")
        disconnect.setObjectName("danger")
        disconnect.clicked.connect(self._ms_disconnect)
        for b in (connect, code, disconnect):
            row.addWidget(b)
        holder = QWidget()
        holder.setLayout(row)
        f.addRow("", holder)
        f.addRow("", self._note("Passo a passo para obter o ID do aplicativo em docs/INTEGRACOES.md (registro gratuito "
                                "no portal Microsoft Entra). O login acontece na página oficial da Microsoft; o JARVIS "
                                "nunca vê sua senha e guarda os tokens criptografados (DPAPI)."))
        return w

    def _ms_status_text(self) -> str:
        graph = self.services.graph
        if graph is None or not graph.configured:
            return "não configurado"
        name = graph.account_name()
        return f"conectado como {name}" if name else "não conectado"

    def _ms_connect(self, button: QPushButton, device: bool) -> None:
        self._save(close=False)
        graph = self.services.graph
        if device:
            def show(info):
                self.services.bus.publish("login_code", **info)
            fn = lambda: graph.sign_in_device_code(show)  # noqa: E731
        else:
            fn = graph.sign_in_interactive
        self._busy(button, fn, lambda user: (self.ms_status.setText(f"conectado como {user}"), self.app.on_microsoft_connected()),
                   "Aguardando login…")

    def _ms_disconnect(self) -> None:
        if self.services.graph is not None:
            run_async(self.services.graph.sign_out, lambda *_: self.ms_status.setText("não conectado"))

    # ------------------------------------------------------------ planilhas
    def _tab_excel(self) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)
        left = QVBoxLayout()
        left.addWidget(QLabel("Planilhas que o JARVIS pode usar:"))
        self.wb_list = QListWidget()
        self.wb_list.currentRowChanged.connect(self._wb_select)
        left.addWidget(self.wb_list, 1)
        row = QHBoxLayout()
        discover = QPushButton("Descobrir")
        discover.clicked.connect(lambda: self._wb_discover(discover))
        by_link = QPushButton("Adicionar link")
        by_link.clicked.connect(lambda: self._wb_add_link(by_link))
        remove = QPushButton("Remover")
        remove.setObjectName("danger")
        remove.clicked.connect(self._wb_remove)
        for b in (discover, by_link, remove):
            row.addWidget(b)
        left.addLayout(row)
        left.addWidget(self._note("Remover só tira da lista do JARVIS; o arquivo continua intacto no OneDrive."))
        layout.addLayout(left, 1)

        editor = QWidget()
        form = QFormLayout(editor)
        self.wb_alias = QLineEdit()
        self.wb_sheet = QComboBox()
        self.wb_sheet.setEditable(True)
        self.wb_header = QSpinBox()
        self.wb_header.setRange(0, 1000)
        self.wb_header.setSpecialValueText("automático")
        self.wb_status = QComboBox()
        self.wb_status.setEditable(True)
        self.wb_pending = QLineEdit()
        self.wb_pending.setPlaceholderText("ex.: pendente, em aberto")
        self.wb_done = QLineEdit()
        self.wb_done.setPlaceholderText("ex.: concluído, entregue (alternativa)")
        self.wb_date = QComboBox()
        self.wb_date.setEditable(True)
        self.wb_keys = QLineEdit()
        self.wb_keys.setPlaceholderText("ex.: Nota Fiscal, Cliente")
        self.wb_watch = QCheckBox("Avisar quando surgirem novas pendências")
        load = QPushButton("Carregar abas e colunas")
        load.clicked.connect(lambda: self._wb_load_columns(load))
        apply_btn = QPushButton("Aplicar a esta planilha")
        apply_btn.setObjectName("accent")
        apply_btn.clicked.connect(self._wb_apply)
        form.addRow("Apelido falado:", self.wb_alias)
        form.addRow("", load)
        form.addRow("Aba:", self.wb_sheet)
        form.addRow("Linha do cabeçalho:", self.wb_header)
        form.addRow("Coluna de status:", self.wb_status)
        form.addRow("Valores pendentes:", self.wb_pending)
        form.addRow("Valores concluídos:", self.wb_done)
        form.addRow("Coluna de data/prazo:", self.wb_date)
        form.addRow("Colunas-chave:", self.wb_keys)
        form.addRow("", self.wb_watch)
        form.addRow("", apply_btn)
        self.wb_hint = self._note("Selecione uma planilha. O JARVIS sugere colunas, mas você decide quais usar.")
        form.addRow("", self.wb_hint)
        layout.addWidget(editor, 1)
        self._wb_refresh()
        return w

    def _wb_refresh(self) -> None:
        self.wb_list.clear()
        for wb in self.settings.get("excel.workbooks", []) or []:
            item = QListWidgetItem(f"{wb.get('alias')}  -  {wb.get('name')}")
            item.setData(Qt.UserRole, wb.get("item_id"))
            self.wb_list.addItem(item)

    def _wb_current(self) -> dict | None:
        item = self.wb_list.currentItem()
        if not item:
            return None
        for wb in self.settings.get("excel.workbooks", []) or []:
            if wb.get("item_id") == item.data(Qt.UserRole):
                return wb
        return None

    def _wb_select(self, _row: int) -> None:
        wb = self._wb_current()
        if not wb:
            return
        self.wb_alias.setText(wb.get("alias", ""))
        for combo, value in ((self.wb_sheet, wb.get("sheet", "")), (self.wb_status, wb.get("status_column", "")),
                             (self.wb_date, wb.get("date_column", ""))):
            combo.clear()
            if value:
                combo.addItem(value)
            combo.setCurrentText(value or "")
        self.wb_header.setValue(int(wb.get("header_row") or 0))
        self.wb_pending.setText(", ".join(wb.get("pending_values", [])))
        self.wb_done.setText(", ".join(wb.get("done_values", [])))
        self.wb_keys.setText(", ".join(wb.get("key_columns", [])))
        self.wb_watch.setChecked(bool(wb.get("watch")))

    def _wb_apply(self) -> None:
        wb = self._wb_current()
        if not wb or self.services.excel is None:
            return
        self.services.excel.update_workbook(wb["item_id"], {
            "alias": self.wb_alias.text().strip() or wb.get("alias"), "sheet": self.wb_sheet.currentText().strip(),
            "header_row": self.wb_header.value() or None, "status_column": self.wb_status.currentText().strip(),
            "pending_values": csv(self.wb_pending.text()), "done_values": csv(self.wb_done.text()),
            "date_column": self.wb_date.currentText().strip(), "key_columns": csv(self.wb_keys.text()),
            "watch": self.wb_watch.isChecked()})
        row = self.wb_list.currentRow()
        self._wb_refresh()
        self.wb_list.setCurrentRow(row)
        self.wb_hint.setText("Configuração salva.")

    def _wb_load_columns(self, button: QPushButton) -> None:
        wb = self._wb_current()
        excel = self.services.excel
        if not wb or excel is None:
            return
        sheet = self.wb_sheet.currentText().strip()

        def work():
            sheets = excel.worksheets(wb)
            table = excel.table({**wb, "sheet": sheet or (sheets[0] if sheets else "")}, fresh=True)
            return sheets, table

        def done(result):
            from ..integrations.excel_analysis import guess_columns

            sheets, table = result
            current_sheet = self.wb_sheet.currentText()
            self.wb_sheet.clear()
            self.wb_sheet.addItems(sheets)
            self.wb_sheet.setCurrentText(current_sheet or table.sheet)
            headers = [h for h in table.headers if h]
            guesses = guess_columns(headers)
            for combo, kind in ((self.wb_status, "status"), (self.wb_date, "date")):
                current = combo.currentText()
                combo.clear()
                combo.addItem("")
                combo.addItems(headers)
                combo.setCurrentText(current or (guesses[kind][0] if guesses[kind] else ""))
            if not self.wb_keys.text() and guesses["key"]:
                self.wb_keys.setText(", ".join(guesses["key"][:2]))
            self.wb_hint.setText(f"Aba {table.sheet}: {len(table.rows)} linhas, colunas: {', '.join(headers)}. "
                                 "Sugestões preenchidas; confira antes de aplicar.")

        self._busy(button, work, done)

    def _wb_discover(self, button: QPushButton) -> None:
        excel = self.services.excel
        if excel is None:
            return

        def done(items):
            if not items:
                QMessageBox.information(self, "Planilhas", "Nenhuma planilha encontrada. Use 'Adicionar link'.")
                return
            labels = [f"{i['name']}  ({i.get('location', '')})" for i in items]
            choice, ok = QInputDialog.getItem(self, "Planilhas encontradas", "Escolha uma planilha para adicionar:",
                                              labels, 0, False)
            if ok:
                excel.add_workbook(items[labels.index(choice)])
                self._wb_refresh()

        self._busy(button, excel.discover, done, "Procurando…")

    def _wb_add_link(self, button: QPushButton) -> None:
        excel = self.services.excel
        if excel is None:
            return
        url, ok = QInputDialog.getText(self, "Adicionar planilha",
                                       "Cole o link da planilha (Excel Online > Compartilhar > Copiar link):")
        if ok and url.strip():
            self._busy(button, lambda: excel.resolve_url(url.strip()),
                       lambda info: (excel.add_workbook(info), self._wb_refresh()))

    def _wb_remove(self) -> None:
        wb = self._wb_current()
        if wb and self.services.excel is not None:
            self.services.excel.remove_workbook(wb["item_id"])
            self._wb_refresh()

    # --------------------------------------------------------------- whatsapp
    def _tab_whatsapp(self) -> QWidget:
        w, f = self._form()
        f.addRow("", self._check("whatsapp.enabled", "Acompanhar notificações do WhatsApp"))
        f.addRow("", self._check("whatsapp.prefer_app", "Abrir conversas no aplicativo (senão, WhatsApp Web)"))
        f.addRow("Identificação do app:", self._line("whatsapp.handler_match", "whatsapp", as_list=True))
        self.contacts = QTableWidget(0, 2)
        self.contacts.setHorizontalHeaderLabels(["Nome", "Número com DDI e DDD (ex.: +5521999998888)"])
        self.contacts.horizontalHeader().setStretchLastSection(True)
        self.contacts.setMinimumHeight(200)
        for name, number in (self.settings.get("whatsapp.contacts", {}) or {}).items():
            self._contact_row(name, number)
        f.addRow("Contatos:", self.contacts)
        row = QHBoxLayout()
        add = QPushButton("Adicionar contato")
        add.clicked.connect(lambda: self._contact_row("", ""))
        rem = QPushButton("Remover selecionado")
        rem.clicked.connect(lambda: self.contacts.removeRow(self.contacts.currentRow()))
        row.addWidget(add)
        row.addWidget(rem)
        holder = QWidget()
        holder.setLayout(row)
        f.addRow("", holder)
        wa = self.services.whatsapp
        status = "ativo" if wa and wa.status == "ok" else "inativo (ver docs/SOLUCAO_DE_PROBLEMAS.md)"
        f.addRow("Leitura de notificações:", QLabel(status))
        f.addRow("", self._note(
            "Como funciona: o JARVIS lê as notificações que o WhatsApp Desktop (ou o WhatsApp Web no navegador) "
            "mostra no Windows, com as permissões do seu usuário. Para ver o texto das mensagens, deixe ativada a "
            "prévia de mensagens nas notificações do WhatsApp. Mensagens nunca são enviadas sozinhas: o JARVIS "
            "abre a conversa com o texto pronto e você confirma o envio."))
        return w

    def _contact_row(self, name: str, number: str) -> None:
        row = self.contacts.rowCount()
        self.contacts.insertRow(row)
        self.contacts.setItem(row, 0, QTableWidgetItem(name))
        self.contacts.setItem(row, 1, QTableWidgetItem(number))

    # ------------------------------------------------------------ notificações
    def _tab_notifications(self) -> QWidget:
        w, f = self._form()
        f.addRow("", self._check("notifications.speak_new", "Avisar por voz quando algo chegar"))
        for source, label in (("whatsapp", "WhatsApp"), ("outlook", "Outlook"), ("excel", "Planilhas"),
                              ("reminder", "Lembretes"), ("windows", "Outros apps do Windows")):
            f.addRow("", self._check(f"notifications.sources.{source}", f"Fonte: {label}"))
        f.addRow("Apps do Windows (se ativado):", self._line("notifications.windows_apps", "ex.: Teams, Slack", as_list=True))
        f.addRow("Remetentes importantes:", self._line("notifications.important_senders", as_list=True))
        f.addRow("Palavras importantes:", self._line("notifications.important_keywords", as_list=True))
        f.addRow("Agrupar avisos em (s):", self._spin("notifications.batch_seconds", 0, 120))
        f.addRow("Ignorar repetidas por (min):", self._spin("notifications.dedupe_minutes", 1, 1440))
        f.addRow("", self._check("notifications.quiet_hours.enabled", "Horário silencioso (só importantes)"))
        start, end = QTimeEdit(), QTimeEdit()
        for edit, key in ((start, "notifications.quiet_hours.start"), (end, "notifications.quiet_hours.end")):
            edit.setDisplayFormat("HH:mm")
            edit.setTime(QTime.fromString(self.settings.get(key, "22:00"), "HH:mm"))
            self._binds.append((key, lambda e=edit: e.time().toString("HH:mm")))
        f.addRow("Início:", start)
        f.addRow("Fim:", end)
        return w

    # ---------------------------------------------------------------- comandos
    def _tab_music(self) -> QWidget:
        w, f = self._form()
        row = QHBoxLayout()
        self.music_file = self._line("music.file", "Escolha um arquivo MP3, WAV, FLAC ou OGG")
        pick = QPushButton("Escolher…")
        pick.clicked.connect(self._pick_music)
        row.addWidget(self.music_file, 1)
        row.addWidget(pick)
        holder = QWidget()
        holder.setLayout(row)
        f.addRow("Música:", holder)
        self.music_url = self._line("music.url", "Ou cole um link do Spotify/YouTube (usado se não houver arquivo)")
        f.addRow("Link:", self.music_url)
        presets = QHBoxLayout()
        for label, url in (("Back in Black (Spotify)", "spotify:search:back%20in%20black%20ac%2Fdc"),
                           ("Back in Black (YouTube)", "https://www.youtube.com/results?search_query=back+in+black+ac+dc"),
                           ("Shoot to Thrill (Spotify)", "spotify:search:shoot%20to%20thrill%20ac%2Fdc")):
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, u=url: self.music_url.setText(u))
            presets.addWidget(button)
        preset_box = QWidget()
        preset_box.setLayout(presets)
        f.addRow("Sugestões:", preset_box)
        f.addRow("Volume da música:", self._slider("music.volume", 5, 100))
        f.addRow("", self._check("music.play_on_startup", "Tocar quando o JARVIS iniciar (exceto durante jogos)"))
        f.addRow("", self._check("music.loop", "Repetir sem parar"))
        f.addRow("Tocar só os primeiros (s):", self._spin("music.max_seconds", 0, 3600))
        buttons = QHBoxLayout()
        play = QPushButton("▶ Tocar")
        play.setObjectName("accent")
        play.clicked.connect(lambda: (self._save(close=False), self.app.run_action("music_play", {})))
        stop = QPushButton("■ Parar")
        stop.clicked.connect(lambda: self.app.run_action("music_stop", {}))
        buttons.addWidget(play)
        buttons.addWidget(stop)
        box = QWidget()
        box.setLayout(buttons)
        f.addRow("", box)
        f.addRow("", self._note(
            "Comandos de voz: \"Jarvis, modo Homem de Ferro\", \"Jarvis, cheguei em casa\", \"toca a música\", "
            "\"para a música\", \"aumenta/abaixa a música\". \"Jarvis, pare\" também para a música. "
            "Com ARQUIVO, a música abaixa sozinha enquanto o JARVIS escuta e fala (melhor experiência). "
            "Com LINK, o Spotify/YouTube abre a música e o volume fica por conta do app. "
            "Use uma música que você possua (ex.: MP3 comprado). 0 segundos = música inteira."))
        return w

    def _pick_music(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Escolher música", "", "Áudio (*.mp3 *.wav *.flac *.ogg)")
        if path:
            self.music_file.setText(path)

    def _tab_commands(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(self._note(
            "Comandos personalizados (JSON). Cada comando tem frases e uma sequência de ações permitidas. "
            "Exemplo: [{\"phrases\": [\"modo trabalho\"], \"actions\": [{\"action\": \"open_target\", \"target\": "
            "\"outlook\"}, {\"action\": \"excel_open\", \"workbook\": \"pendências\"}], \"response\": \"Modo trabalho "
            "ativado.\", \"confirm\": false}]. Ações disponíveis: " + ", ".join(self._action_names())))
        self.custom_edit = QPlainTextEdit(json.dumps(self.settings.get("custom_commands", []), ensure_ascii=False, indent=2))
        layout.addWidget(self.custom_edit, 1)
        layout.addWidget(self._note("Atalhos de programas/sites (JSON). Tipos: url, path, steam (appid), store (appid), "
                                    "uri, command (argv). Ex.: {\"storm 4\": {\"type\": \"steam\", \"appid\": \"349040\"}}"))
        self.alias_edit = QPlainTextEdit(json.dumps(self.settings.get("apps.aliases", {}), ensure_ascii=False, indent=2))
        layout.addWidget(self.alias_edit, 1)
        layout.addWidget(self._note("Pastas com apelido (JSON). Ex.: {\"relatórios\": \"C:\\\\Users\\\\Voce\\\\Documents\\\\Relatorios\"}"))
        self.folder_edit = QPlainTextEdit(json.dumps(self.settings.get("folders.aliases", {}), ensure_ascii=False, indent=2))
        self.folder_edit.setMaximumHeight(90)
        layout.addWidget(self.folder_edit)
        layout.addWidget(self._check("apps.close_requires_confirmation", "Pedir confirmação antes de fechar programas"))
        return w

    @staticmethod
    def _action_names() -> list[str]:
        from ..actions.base import REGISTRY

        return [n for n in REGISTRY.names() if n != "custom_command"]

    # -------------------------------------------------------------- privacidade
    def _tab_privacy(self) -> QWidget:
        w, f = self._form()
        f.addRow("", self._check("memory.history_enabled", "Guardar histórico de conversas e atividades"))
        f.addRow("Manter histórico por (dias):", self._spin("memory.keep_days", 1, 3650))
        self.facts = QPlainTextEdit("\n".join(self.settings.get("memory.facts", []) or []))
        self.facts.setMaximumHeight(120)
        f.addRow("O que sei sobre você\n(uma por linha):", self.facts)
        counts = self.services.storage.counts()
        labels = {"activity": "atividades", "notifications": "notificações", "reminders": "lembretes",
                  "excel_audit": "auditoria de planilhas", "conversation": "conversas", "kv": "estado interno"}
        for table, label in labels.items():
            row = QHBoxLayout()
            row.addWidget(QLabel(f"{counts.get(table, 0)} registros"))
            view = QPushButton("Ver")
            view.clicked.connect(lambda _=False, t=table: self._view_table(t))
            clear = QPushButton("Apagar")
            clear.setObjectName("danger")
            clear.clicked.connect(lambda _=False, t=table, lb=label: self._clear_table(t, lb))
            row.addWidget(view)
            row.addWidget(clear)
            holder = QWidget()
            holder.setLayout(row)
            f.addRow(label.capitalize() + ":", holder)
        f.addRow("Segredos guardados:", QLabel(", ".join(v for k, v in KNOWN_KEYS.items() if self.secrets.has(k)) or "nenhum"))
        f.addRow("Local dos segredos:", QLabel(self.secrets.backend_name))
        row = QHBoxLayout()
        open_dir = QPushButton("Abrir pasta de dados")
        open_dir.clicked.connect(lambda: self.app.open_url(str(paths.data_dir())))
        clear_tts = QPushButton("Limpar cache de voz")
        clear_tts.clicked.connect(lambda: self.app.speaker and self.app.speaker.tts.clear_cache())
        export = QPushButton("Exportar configurações")
        export.clicked.connect(self._export)
        wipe = QPushButton("Apagar TUDO")
        wipe.setObjectName("danger")
        wipe.clicked.connect(self._wipe)
        for b in (open_dir, clear_tts, export, wipe):
            row.addWidget(b)
        holder = QWidget()
        holder.setLayout(row)
        f.addRow("", holder)
        return w

    def _view_table(self, table: str) -> None:
        rows = self.services.storage.query(f"SELECT * FROM {table} ORDER BY rowid DESC LIMIT 300")
        text = "\n".join(json.dumps(r, ensure_ascii=False, default=str) for r in rows) or "(vazio)"
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Dados: {table}")
        dialog.resize(800, 500)
        layout = QVBoxLayout(dialog)
        view = QPlainTextEdit(text)
        view.setReadOnly(True)
        layout.addWidget(view)
        dialog.exec()

    def _clear_table(self, table: str, label: str) -> None:
        if QMessageBox.question(self, "Apagar", f"Apagar todos os registros de {label}?") == QMessageBox.Yes:
            self.services.storage.clear_table(table)
            QMessageBox.information(self, "Apagar", "Registros apagados.")

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Exportar configurações", "jarvis-config.json", "JSON (*.json)")
        if path:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(self.settings.as_dict(), fh, ensure_ascii=False, indent=2)

    def _wipe(self) -> None:
        if QMessageBox.question(self, "Apagar tudo", "Apagar histórico, notificações, lembretes, memória, segredos e "
                                "desconectar contas? As configurações básicas serão mantidas.") != QMessageBox.Yes:
            return
        for table in ("activity", "notifications", "reminders", "excel_audit", "conversation", "kv"):
            self.services.storage.clear_table(table)
        for key in KNOWN_KEYS:
            self.secrets.delete(key)
        if self.services.graph is not None:
            self.services.graph.sign_out()
        self.settings.set("memory.facts", [])
        self.facts.setPlainText("")
        QMessageBox.information(self, "Apagar tudo", "Dados apagados.")

    # ------------------------------------------------------------------ salvar
    def _save(self, close: bool = True) -> None:
        try:
            custom = json.loads(self.custom_edit.toPlainText() or "[]")
            aliases = json.loads(self.alias_edit.toPlainText() or "{}")
            folders = json.loads(self.folder_edit.toPlainText() or "{}")
            if not isinstance(custom, list) or not isinstance(aliases, dict) or not isinstance(folders, dict):
                raise ValueError("formato inválido")
            for command in custom:
                if not command.get("phrases") or not isinstance(command.get("actions", []), list):
                    raise ValueError("cada comando precisa de 'phrases' e 'actions'")
        except (ValueError, AttributeError) as exc:
            self.tabs.setCurrentIndex(10)
            QMessageBox.warning(self, "Comandos", f"JSON inválido: {exc}")
            return
        data = self.settings.as_dict()
        for key, getter in self._binds:
            node = data
            parts = key.split(".")
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = getter()
        data["custom_commands"] = custom
        data["apps"]["aliases"] = aliases
        data["folders"]["aliases"] = folders
        data["memory"]["facts"] = [line.strip() for line in self.facts.toPlainText().splitlines() if line.strip()]
        contacts = {}
        for row in range(self.contacts.rowCount()):
            name = (self.contacts.item(row, 0).text() if self.contacts.item(row, 0) else "").strip()
            number = (self.contacts.item(row, 1).text() if self.contacts.item(row, 1) else "").strip()
            if name and number:
                contacts[name] = number
        data["whatsapp"]["contacts"] = contacts
        data["excel"]["workbooks"] = self.settings.get("excel.workbooks", [])  # editadas na própria aba
        self.settings.replace_all(data)
        for name, edit in self._secret_fields.items():
            if edit.text().strip():
                self.secrets.set(name, edit.text().strip())
                edit.clear()
                edit.setPlaceholderText("guardada com segurança")
        if sys.platform == "win32":
            try:
                win.set_autostart(self.autostart.isChecked())
                self.settings.set("general.start_with_windows", self.autostart.isChecked())
            except OSError as exc:
                QMessageBox.warning(self, "Inicialização", f"Não foi possível ajustar a inicialização: {exc}")
        self.app.on_settings_saved()
        if close:
            self.accept()

