; Inno Setup script for Queryon. Built by the GitHub Actions workflow:
;   iscc /DAppVersion=1.0.0 packaging\installer.iss

#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{6B2F3C1E-8A41-4D7B-9E5A-2C7D1F0B9A11}
AppName=Queryon
AppVersion={#AppVersion}
AppVerName=Queryon {#AppVersion}
AppPublisher=Malak Zubair
AppPublisherURL=https://github.com/Zubair-DLCS/Queryon
AppSupportURL=https://github.com/Zubair-DLCS/Queryon/issues
AppCopyright=Copyright (c) 2026 Malak Zubair
DefaultDirName={autopf}\Queryon
DefaultGroupName=Queryon
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=Queryon-Setup-{#AppVersion}
SetupIconFile=..\assets\queryon.ico
UninstallDisplayIcon={app}\Queryon.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\Queryon\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Dirs]
; Lab PCs: copy model .gguf files here to skip the download.
Name: "{app}\models"; Permissions: users-modify

[Icons]
Name: "{group}\Queryon"; Filename: "{app}\Queryon.exe"
Name: "{group}\Uninstall Queryon"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Queryon"; Filename: "{app}\Queryon.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Queryon.exe"; Description: "Start Queryon now"; Flags: nowait postinstall skipifsilent
