; SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
; SPDX-License-Identifier: MIT
; Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

[Setup]
AppId={{EFB6315D-091C-4B7C-B04C-BF6C1DF58097}
AppName=TwinPALS 2.0
AppVersion={#ProductVersion}
AppVerName=TwinPALS {#ProductVersion}
AppPublisher=Danny Petschke
AppPublisherURL=https://github.com/dpscience/TwinPALS2.0-public
AppSupportURL=mailto:twinpals@proton.me
AppUpdatesURL=https://github.com/dpscience/TwinPALS2.0-public/releases
VersionInfoVersion={#ProductVersion}.0
VersionInfoDescription=TwinPALS 2.0 Setup
VersionInfoCopyright=Copyright (c) 2026 Danny Petschke
DefaultDirName={localappdata}\Programs\TwinPALS 2.0
DefaultGroupName=TwinPALS 2.0
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableProgramGroupPage=yes
DisableWelcomePage=no
AllowNoIcons=yes
WizardStyle=modern
SetupIconFile=..\..\..\frontend\public\favicon.ico
WizardImageFile=wizard.png
WizardSmallImageFile=mark.png
LicenseFile=..\..\..\LICENSE
UninstallDisplayIcon={app}\TwinPALS.exe
OutputBaseFilename=TwinPALS-setup
Compression=lzma2/fast
SolidCompression=yes
CloseApplications=no
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Messages]
english.WelcomeLabel1=Install TwinPALS 2.0
german.WelcomeLabel1=TwinPALS 2.0 installieren

[CustomMessages]
english.Intro=Set up the desktop workbench and MCP study server for your Windows account. The detector catalogue, simulation engines and physics data are included for offline use.
german.Intro=Installiere die Desktop-Anwendung und den MCP-Studienserver für dein Windows-Konto. Detektorkatalog, Simulationsprogramme und Physikdaten sind für den Offline-Betrieb enthalten.
english.DataInfo=Your catalogue, settings, runs and MCP studies are stored under %LOCALAPPDATA%\TwinPALS\Data. Updates and uninstall preserve this folder.
german.DataInfo=Katalog, Einstellungen, Messläufe und MCP-Studien liegen unter %LOCALAPPDATA%\TwinPALS\Data. Updates und Deinstallation erhalten diesen Ordner.
english.UnsafeDir=Choose an empty program folder, or the original folder of this installation. Portable copies and user data need a separate folder.
german.UnsafeDir=Wähle einen leeren Programmordner oder den bisherigen Ordner dieser Installation. Portable Kopien und Nutzerdaten benötigen einen eigenen Ordner.
english.Busy=Stop the desktop service, study service and workers through the tray or your MCP client before continuing.
german.Busy=Beende vor dem Fortfahren den Desktopdienst, den Studiendienst und laufende Worker über das Tray oder den MCP-Client.
english.NetRequired=The tray needs Microsoft .NET Framework 4.x. Install the Microsoft runtime and run Setup again.
german.NetRequired=Das Tray benötigt Microsoft .NET Framework 4.x. Installiere die Microsoft-Laufzeit und starte das Setup erneut.
english.NetConsent=The tray needs Microsoft .NET Framework. Download the Microsoft .NET Framework 4.8 installer and open it now? Windows may request administrator approval.
german.NetConsent=Das Tray benötigt Microsoft .NET Framework. Soll das Setup den Microsoft-Installer für .NET Framework 4.8 herunterladen und öffnen? Windows kann Administratorrechte anfordern.
english.OlderVersion=A newer version is installed. Choose the same version or a newer installer.
german.OlderVersion=Eine neuere Version ist installiert. Verwende dieselbe Version oder ein neueres Setup.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; Flags: unchecked

[Files]
#include PayloadList
Source: "twinpals-installed.ini"; DestDir: "{app}"; Flags: ignoreversion
Source: "Inno-Setup-license.txt"; DestDir: "{app}\legal"; Flags: ignoreversion

[Icons]
Name: "{group}\TwinPALS 2.0"; Filename: "{app}\TwinPALS.exe"
Name: "{autodesktop}\TwinPALS 2.0"; Filename: "{app}\TwinPALS.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\TwinPALS.exe"; Description: "{cm:LaunchProgram,TwinPALS 2.0}"; Flags: nowait postinstall skipifsilent unchecked

[Code]
const
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{EFB6315D-091C-4B7C-B04C-BF6C1DF58097}_is1';
  RunKey = 'Software\Microsoft\Windows\CurrentVersion\Run';

function FileBusy(Name: String): Boolean;
var Stream: TFileStream;
begin
  Result := False;
  if not FileExists(Name) then exit;
  try
    Stream := TFileStream.Create(Name, fmOpenReadWrite or fmShareExclusive);
    Stream.Free;
  except
    Result := True;
  end;
end;

function ServicesBusy(): Boolean;
var Base: String;
begin
  Base := AddBackslash(ExpandConstant('{app}'));
  Result := FileBusy(Base + 'TwinPALS.exe') or FileBusy(Base + 'TwinPALS-MCP.exe') or
    FileBusy(Base + '_internal\TwinPALS.Tray.exe') or FileBusy(Base + '.runtime\bin\twinpals-worker.exe');
end;

function HasEntries(Dir: String): Boolean;
var Found: TFindRec;
begin
  Result := False;
  if FindFirst(AddBackslash(Dir) + '*', Found) then
    try
      repeat
        if (Found.Name <> '.') and (Found.Name <> '..') then begin Result := True; exit; end;
      until not FindNext(Found);
    finally
      FindClose(Found);
    end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var Dir, Prior, PriorVersion: String; OldV, NewV: Int64; Code: Integer;
begin
  Result := '';
  Dir := RemoveBackslashUnlessRoot(ExpandConstant('{app}'));
  if RegQueryStringValue(HKCU, UninstallKey, 'InstallLocation', Prior) then begin
    if CompareText(Dir, RemoveBackslashUnlessRoot(Prior)) <> 0 then begin Result := CustomMessage('UnsafeDir'); exit; end;
    if RegQueryStringValue(HKCU, UninstallKey, 'DisplayVersion', PriorVersion) and
       StrToVersion(PriorVersion, OldV) and StrToVersion('{#ProductVersion}', NewV) and (ComparePackedVersion(OldV, NewV) > 0) then begin
      Result := CustomMessage('OlderVersion'); exit;
    end;
  end;
  if HasEntries(Dir) and ((Prior = '') or (GetIniString('TwinPALS','Layout','',Dir + '\twinpals-installed.ini') <> 'installed-v1')) then begin
    Result := CustomMessage('UnsafeDir'); exit;
  end;
  if ServicesBusy() then begin Result := CustomMessage('Busy'); exit; end;
  if IsDotNetInstalled(net4Full, 0) then exit;
  Result := CustomMessage('NetRequired');
  if WizardSilent then exit;
  if MsgBox(CustomMessage('NetConsent'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) <> IDYES then exit;
  try
    DownloadTemporaryFile('https://go.microsoft.com/fwlink/?LinkId=2085155', 'ndp48-web.exe',
      '0bba3094588c4bfec301939985222a20b340bf03431563dec8b2b4478b06fffa', nil);
    if ShellExec('runas', ExpandConstant('{tmp}\ndp48-web.exe'), '/norestart', '', SW_SHOWNORMAL, ewWaitUntilTerminated, Code) then begin
      if (Code = 3010) or (Code = 1641) then NeedsRestart := True
      else if (Code = 0) and IsDotNetInstalled(net4Full, 0) then Result := '';
    end;
  except
    Result := Result + #13#10 + GetExceptionMessage;
  end;
end;

procedure InitializeWizard();
begin
  WizardForm.WelcomeLabel2.Caption := CustomMessage('Intro') + #13#10#13#10 + CustomMessage('DataInfo');
end;

function InitializeUninstall(): Boolean;
begin
  Result := not ServicesBusy();
  if not Result then SuppressibleMsgBox(CustomMessage('Busy'), mbError, MB_OK, IDOK);
end;

procedure CurUninstallStepChanged(Step: TUninstallStep);
var Names: TArrayOfString; I: Integer; Value, Executable, Quoted, Plain: String;
begin
  if Step <> usPostUninstall then exit;
  Executable := ExpandConstant('{app}\TwinPALS-MCP.exe');
  Quoted := '"' + Executable + '" --resume --data-dir ';
  Plain := Executable + ' --resume --data-dir ';
  if RegGetValueNames(HKCU, RunKey, Names) then
    for I := 0 to GetArrayLength(Names) - 1 do
      if (Pos('TwinPALS study ', Names[I]) = 1) and RegQueryStringValue(HKCU, RunKey, Names[I], Value)
        and ((CompareText(Copy(Value, 1, Length(Quoted)), Quoted) = 0) or
             (CompareText(Copy(Value, 1, Length(Plain)), Plain) = 0)) then RegDeleteValue(HKCU, RunKey, Names[I]);
end;

