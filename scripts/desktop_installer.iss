[Setup]
AppId=EmpathyCopilotDesktop
AppName=共情副驾
AppVersion=0.3.2
DefaultDirName={localappdata}\Programs\EmpathyCopilot
DefaultGroupName=共情副驾
PrivilegesRequired=lowest
OutputDir=..\release\desktop
OutputBaseFilename=EmpathyCopilot-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\.scratch\desktop-assets\icon.ico
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\EmpathyCopilot.exe

[Files]
Source: "..\release\desktop\EmpathyCopilot\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\共情副驾"; Filename: "{app}\EmpathyCopilot.exe"
Name: "{autodesktop}\共情副驾"; Filename: "{app}\EmpathyCopilot.exe"

[Run]
Filename: "{app}\EmpathyCopilot.exe"; Description: "打开共情副驾"; Flags: nowait postinstall skipifsilent
