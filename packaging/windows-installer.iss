#ifndef AppVersion
  #error AppVersion is required
#endif
#ifndef AppExecutable
  #error AppExecutable is required
#endif
#ifndef SourceDirectory
  #error SourceDirectory is required
#endif

[Setup]
AppId={{CA853470-581D-46F2-BBEC-E4327EF4919A}
AppName=天堂支点
AppVersion={#AppVersion}
AppPublisher=YLFF
DefaultDirName={localappdata}\Programs\CFARA
DefaultGroupName=天堂支点
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes
Compression=lzma2
SolidCompression=yes
UninstallDisplayIcon={app}\{#AppExecutable}.exe
CloseApplications=yes
RestartApplications=no
Uninstallable=not IsTestInstall
SetupIconFile=..\assets\ui\sitting-dog-v1.ico
LicenseFile=..\LICENSE

[Files]
Source: "{#SourceDirectory}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\天堂支点"; Filename: "{app}\{#AppExecutable}.exe"; WorkingDir: "{app}"

[Run]
Filename: "{app}\{#AppExecutable}.exe"; Description: "启动天堂支点"; Flags: nowait postinstall skipifsilent

[Code]
function IsTestInstall: Boolean;
begin
  Result := ExpandConstant('{param:CFARATest|0}') = '1';
end;
