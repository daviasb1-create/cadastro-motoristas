; Instalador do TURBO BOOST PRO (Inno Setup 6) - gerado pelo build.bat
#define AppName "TURBO BOOST PRO"
#define AppVersion "1.0.0"
#define AppExe "TurboBoostPro.exe"

[Setup]
AppId={{6E3B1C52-7A1F-4C1E-9C55-9F1B0D2A7B10}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=TURBO BOOST PRO
DefaultDirName={autopf}\TurboBoostPro
DefaultGroupName={#AppName}
OutputDir=Output
OutputBaseFilename=TurboBoostPro_Setup_{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
ArchitecturesAllowed=x64compatible
MinVersion=10.0.17763
PrivilegesRequired=admin

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Área de Trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "..\dist\TurboBoostPro\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Desinstalar {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Abrir o {#AppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
function InitializeUninstall(): Boolean;
begin
  Result := True;
  if not UninstallSilent then
  MsgBox('Antes de desinstalar, recomendamos abrir o TURBO BOOST PRO e usar Segurança > RESTAURAR TUDO ' +
         'para desfazer as otimizações. Os backups ficam em %LOCALAPPDATA%\TurboBoostPro.', mbInformation, MB_OK);
end;
