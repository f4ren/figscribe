; Inno Setup script for the Windows installer (decision 0066).
; Run by packaging/make_installer.py with /DAppVersion, /DSourceDir, /DIconFile,
; /DOutputDir and /DOutputName.

#define AppName "figscribe"

[Setup]
AppId={{6F1D5B1E-8B3A-4C57-9C1E-2D6B0F4A7E31}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=f4ren
AppPublisherURL=https://github.com/f4ren/figscribe
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={#OutputDir}
OutputBaseFilename={#OutputName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile={#IconFile}
UninstallDisplayIcon={app}\figscribe.exe
ChangesAssociations=yes

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\figscribe.exe"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\figscribe.exe"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Create a desktop icon"; Flags: unchecked

[Registry]
; Double-clicking a project opens it in figscribe.
Root: HKA; Subkey: "Software\Classes\.figscribe"; ValueType: string; ValueData: "figscribe.project"; Flags: uninsdeletevalue
Root: HKA; Subkey: "Software\Classes\figscribe.project"; ValueType: string; ValueData: "figscribe project"; Flags: uninsdeletekey
Root: HKA; Subkey: "Software\Classes\figscribe.project\DefaultIcon"; ValueType: string; ValueData: "{app}\figscribe.exe,0"
Root: HKA; Subkey: "Software\Classes\figscribe.project\shell\open\command"; ValueType: string; ValueData: """{app}\figscribe.exe"" ""%1"""

[Run]
Filename: "{app}\figscribe.exe"; Description: "Start figscribe"; Flags: nowait postinstall skipifsilent
