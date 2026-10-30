; Instalador do JARVIS (Inno Setup 6). Gerado por scripts\build_exe.ps1.
; Instala para o usuário atual, sem precisar de administrador.
#define AppName "JARVIS"
#define AppVersion "1.0.0"

[Setup]
AppId={{6C1E9B0A-4D2F-4B8E-9A7C-1F2E3D4C5B6A}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Uso pessoal
DefaultDirName={localappdata}\Programs\Jarvis
DefaultGroupName=JARVIS
PrivilegesRequired=lowest
OutputBaseFilename=JarvisSetup-{#AppVersion}
SetupIconFile=..\assets\jarvis.ico
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\Jarvis.exe

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"; Flags: unchecked
Name: "autostart"; Description: "Iniciar o JARVIS com o Windows"; Flags: unchecked

[Files]
Source: "..\dist\Jarvis\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\JARVIS"; Filename: "{app}\Jarvis.exe"; Parameters: "--show"
Name: "{group}\Desinstalar JARVIS"; Filename: "{uninstallexe}"
Name: "{userdesktop}\JARVIS"; Filename: "{app}\Jarvis.exe"; Parameters: "--show"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "JarvisAssistente"; ValueData: """{app}\Jarvis.exe"" --minimized"; Tasks: autostart; Flags: uninsdeletevalue

[Run]
Filename: "{app}\Jarvis.exe"; Parameters: "--show"; Description: "Abrir o JARVIS agora"; Flags: nowait postinstall skipifsilent
