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
DisableDirPage=no
UsePreviousAppDir=yes
AlwaysShowDirOnReadyPage=yes
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
english.DataInfo=Your catalogue, settings, runs and MCP studies use %LOCALAPPDATA%\TwinPALS\Data by default. Updates preserve your data. During uninstall you can choose which data to keep.
german.DataInfo=Katalog, Einstellungen, Messläufe und MCP-Studien liegen standardmäßig unter %LOCALAPPDATA%\TwinPALS\Data. Updates erhalten deine Daten. Bei der Deinstallation kannst du sie behalten oder entfernen.
english.Maintenance=Maintain TwinPALS
german.Maintenance=TwinPALS verwalten
english.MaintenancePrompt=Choose what to do with the existing installation.
german.MaintenancePrompt=Wähle eine Aktion für die vorhandene Installation.
english.Repair=Repair program files
german.Repair=Programmdateien reparieren
english.RemoveProgram=Uninstall TwinPALS
german.RemoveProgram=TwinPALS deinstallieren
english.UninstallFailed=The uninstaller could not be started. You can also open it from Windows Settings.
german.UninstallFailed=Das Deinstallationsprogramm konnte nicht gestartet werden. Du kannst es auch über die Windows-Einstellungen öffnen.
english.ChooseRetention=What should happen to your TwinPALS data?
german.ChooseRetention=Was soll mit deinen TwinPALS-Daten geschehen?
english.KeepData=Keep my data
german.KeepData=Meine Daten behalten
english.SelectData=Choose data to delete…
german.SelectData=Zu löschende Daten auswählen…
english.RetentionInfo=You can reuse your catalogue, settings, runs and MCP studies after reinstalling.
german.RetentionInfo=Katalog, Einstellungen, Messläufe und MCP-Studien lassen sich nach einer Neuinstallation wiederverwenden.
english.DeleteList=Review the folders to delete
german.DeleteList=Zu löschende Ordner prüfen
english.DeleteWarning=All contents of the listed folders will be permanently deleted. Files elsewhere will be kept.
german.DeleteWarning=Der gesamte Inhalt der aufgeführten Ordner wird endgültig gelöscht. Dateien an anderen Speicherorten bleiben erhalten.
english.AddWorkspace=Add a dedicated TwinPALS data folder…
german.AddWorkspace=Separaten TwinPALS-Datenordner hinzufügen…
english.DeleteFolders=Delete listed folders on uninstall
german.DeleteFolders=Aufgeführte Ordner bei der Deinstallation löschen
english.NoFolders=No data folder selected.
german.NoFolders=Kein Datenordner ausgewählt.
english.UnsafeData=Choose a dedicated, local TwinPALS workspace with its own catalogue. Shared folders, linked paths and folders with unrelated top-level files are excluded.
german.UnsafeData=Wähle einen lokalen, ausschließlich für TwinPALS verwendeten Arbeitsordner mit eigenem Katalog. Gemischte Ordner und verknüpfte Pfade sind ausgeschlossen.
english.DeleteIncomplete=TwinPALS could not completely remove the following folder. Check whether another process is using it.
german.DeleteIncomplete=TwinPALS konnte den folgenden Ordner nicht vollständig entfernen. Prüfe, ob er noch von einem anderen Prozess verwendet wird.
english.UnsafeDir=Choose an empty program folder, or the original folder of this installation. Portable copies and user data need a separate folder.
german.UnsafeDir=Wähle einen leeren Programmordner oder den bisherigen Ordner dieser Installation. Portable Kopien und Nutzerdaten benötigen einen eigenen Ordner.
english.Busy=Files in this installation are still in use. Close its desktop and study services and disconnect its MCP clients before continuing.
german.Busy=Dateien dieser Installation werden noch verwendet. Beende ihre Desktop- und Studiendienste und trenne ihre MCP-Verbindungen.
english.StopToUninstall=Close TwinPALS processes to continue?
german.StopToUninstall=TwinPALS-Prozesse zum Fortfahren beenden?
english.StopInfo=Open MCP connections will disconnect and active work in this installation will stop. Unfinished MCP study steps can resume the next time the study service starts.
german.StopInfo=Offene MCP-Verbindungen werden getrennt und laufende Arbeiten dieser Installation gestoppt. Unfertige MCP-Studienschritte können beim nächsten Start des Studiendiensts fortgesetzt werden.
english.StopAndContinue=Close processes and continue
german.StopAndContinue=Prozesse beenden und fortfahren
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
var
  MaintenancePage: TInputOptionWizardPage;
  PriorDir, PriorVersionText: String;
  LeavingSetup: Boolean;
  DeleteFolders: TStringList;

function FileAttributes(Name: String): LongWord;
  external 'GetFileAttributesW@kernel32.dll stdcall';

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
  RegQueryStringValue(HKCU, UninstallKey, 'InstallLocation', PriorDir);
  RegQueryStringValue(HKCU, UninstallKey, 'DisplayVersion', PriorVersionText);
  WizardForm.WelcomeLabel2.Caption := CustomMessage('Intro') + #13#10#13#10 + CustomMessage('DataInfo');
  if (PriorDir <> '') and (PriorVersionText = '{#ProductVersion}') then begin
    MaintenancePage := CreateInputOptionPage(wpWelcome, CustomMessage('Maintenance'),
      CustomMessage('MaintenancePrompt'), PriorDir, True, False);
    MaintenancePage.Add(CustomMessage('Repair'));
    MaintenancePage.Add(CustomMessage('RemoveProgram'));
    MaintenancePage.SelectedValueIndex := 0;
  end;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := (PageID = wpSelectDir) and (PriorDir <> '');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var Uninstaller: String; Code: Integer;
begin
  Result := True;
  if MaintenancePage = nil then exit;
  if (CurPageID <> MaintenancePage.ID) or (MaintenancePage.SelectedValueIndex <> 1) then exit;
  Result := False;
  if not RegQueryStringValue(HKCU, UninstallKey, 'UninstallString', Uninstaller) then Uninstaller := '';
  Uninstaller := RemoveQuotes(Uninstaller);
  if (CompareText(ExtractFileDir(Uninstaller), RemoveBackslashUnlessRoot(PriorDir)) <> 0) or
     not FileExists(Uninstaller) then begin MsgBox(CustomMessage('UninstallFailed'), mbError, MB_OK); exit; end;
  if not Exec(Uninstaller, '', '', SW_SHOWNORMAL, ewWaitUntilTerminated, Code) then begin
    MsgBox(CustomMessage('UninstallFailed'), mbError, MB_OK); exit;
  end;
  LeavingSetup := True;
  WizardForm.Close;
end;

procedure CancelButtonClick(CurPageID: Integer; var Cancel, Confirm: Boolean);
begin
  if LeavingSetup then begin Cancel := True; Confirm := False; end;
end;

function DefaultDataDir(): String;
begin
  Result := ExpandConstant('{localappdata}\TwinPALS\Data');
end;

function LocalUnlinkedDir(Dir: String): Boolean;
var Parent: String; Attr: LongWord;
begin
  Result := False;
  if (Length(Dir) < 4) or (Copy(Dir, 2, 2) <> ':\') then exit;
  repeat
    Attr := FileAttributes(Dir);
    if (Attr = $FFFFFFFF) or ((Attr and $400) <> 0) then exit;
    Parent := ExtractFileDir(Dir);
    if Parent = Dir then break;
    Dir := Parent;
  until False;
  Result := True;
end;

function ContainsLinkedEntry(Dir: String): Boolean;
var Entry: TFindRec;
begin
  Result := True;
  if not FindFirst(AddBackslash(Dir) + '*', Entry) then exit;
  try
    repeat
      if (Entry.Name <> '.') and (Entry.Name <> '..') then begin
        if (Entry.Attributes and $400) <> 0 then exit;
        if (Entry.Attributes and $10) <> 0 then
          if ContainsLinkedEntry(AddBackslash(Dir) + Entry.Name) then exit;
      end;
    until not FindNext(Entry);
  finally FindClose(Entry); end;
  Result := False;
end;

function DedicatedWorkspace(Dir: String): Boolean;
var Stream: TFileStream; Header: AnsiString; Found: TFindRec; Name: String;
begin
  Result := False;
  if not LocalUnlinkedDir(Dir) then exit;
  if (Pos(Lowercase(AddBackslash(Dir)), Lowercase(AddBackslash(ExpandConstant('{app}')))) = 1) or
     (CompareText(Dir, ExpandConstant('{userdocs}')) = 0) or
     (CompareText(Dir, ExpandConstant('{userdesktop}')) = 0) or
     (CompareText(Dir, ExpandConstant('{userappdata}')) = 0) or
     (CompareText(Dir, ExpandConstant('{localappdata}')) = 0) or
     (CompareText(Dir, ExpandConstant('{%USERPROFILE}')) = 0) then exit;
  if not LocalUnlinkedDir(Dir + '\catalogue.tpdb') then exit;
  try
    Stream := TFileStream.Create(Dir + '\catalogue.tpdb', fmOpenRead or fmShareDenyNone);
    try
      SetLength(Header, 72);
      if Stream.Read(Header, 72) <> 72 then exit;
      if (Copy(Header, 1, 15) <> 'SQLite format 3') or (Copy(Header, 69, 4) <> 'TPDB') then exit;
    finally Stream.Free; end;
  except exit; end;
  if not FindFirst(Dir + '\*', Found) then exit;
  try
    repeat
      Name := Lowercase(Found.Name);
      if (Name <> '.') and (Name <> '..') and (Name <> 'catalogue.tpdb') and
         (Name <> 'catalogue.tpdb-wal') and (Name <> 'catalogue.tpdb-shm') and
         (Name <> 'catalogue.tpdb-journal') and (Name <> 'app-state.json') and (Name <> 'app-state.previous.json') and
         (Name <> '.server.lock') and (Name <> 'release-check.sqlite') and
         (Name <> 'release-check.sqlite-journal') and (Name <> 'studies') and (Name <> 'runs') and
         (Copy(Name, 1, 17) <> 'app-state.backup-') then exit;
    until not FindNext(Found);
  finally FindClose(Found); end;
  Result := not ContainsLinkedEntry(Dir);
end;

function CanRemoveWorkspace(Dir: String): Boolean;
begin
  Result := DedicatedWorkspace(Dir) and not FileBusy(Dir + '\.server.lock') and
    not FileBusy(Dir + '\studies\service\.server.lock') and
    not FileBusy(Dir + '\catalogue.tpdb');
end;

function InitializeUninstall(): Boolean;
var Choice, I: Integer; Dir, Listed: String;
begin
  Result := False;
  if ServicesBusy() then begin
    if UninstallSilent then begin Log(CustomMessage('Busy')); exit; end;
    Choice := TaskDialogMsgBox(CustomMessage('StopToUninstall'), CustomMessage('StopInfo'),
      mbConfirmation, MB_OKCANCEL, [CustomMessage('StopAndContinue')], 0);
    if Choice <> IDOK then exit;
  end;
  { Held through removal. Each process observes only its own installation. }
  CreateMutex('Local\TwinPALS.Uninstall.' + Lowercase(GetSHA256OfString(Utf8Encode(Uppercase(ExpandConstant('{app}'))))));
  while ServicesBusy() do begin
    for I := 1 to 100 do begin
      Sleep(100);
      if not ServicesBusy() then break;
    end;
    if ServicesBusy() then begin
      if UninstallSilent then exit;
      if MsgBox(CustomMessage('Busy'), mbError, MB_RETRYCANCEL) <> IDRETRY then exit;
    end;
  end;
  Result := True;
  if UninstallSilent then exit;
  Choice := TaskDialogMsgBox(CustomMessage('ChooseRetention'), CustomMessage('RetentionInfo'),
    mbConfirmation, MB_YESNOCANCEL, [CustomMessage('KeepData'), CustomMessage('SelectData')], 0);
  Result := Choice = IDYES;
  if Choice <> IDNO then exit;
  DeleteFolders := TStringList.Create;
  Dir := DefaultDataDir();
  if DirExists(Dir) and CanRemoveWorkspace(Dir) then DeleteFolders.Add(Dir);
  repeat
    Listed := Trim(DeleteFolders.Text);
    if Listed = '' then Listed := CustomMessage('NoFolders');
    Choice := TaskDialogMsgBox(CustomMessage('DeleteList'), Listed + #13#10#13#10 + CustomMessage('DeleteWarning'),
      mbConfirmation, MB_YESNOCANCEL, [CustomMessage('AddWorkspace'), CustomMessage('DeleteFolders')], 0);
    if Choice = IDNO then begin Result := DeleteFolders.Count > 0; exit; end;
    if Choice <> IDYES then exit;
    Dir := '';
    if BrowseForFolder(CustomMessage('AddWorkspace'), Dir, False) then begin
      Dir := RemoveBackslashUnlessRoot(ExpandFileName(Dir));
      if not CanRemoveWorkspace(Dir) then MsgBox(CustomMessage('UnsafeData'), mbError, MB_OK)
      else if DeleteFolders.IndexOf(Dir) < 0 then DeleteFolders.Add(Dir);
    end;
  until False;
end;

procedure CurUninstallStepChanged(Step: TUninstallStep);
var Names: TArrayOfString; I: Integer; Value, Executable, Quoted, Plain: String; Removed: Boolean;
begin
  if Step <> usPostUninstall then exit;
  if DeleteFolders <> nil then
    for I := 0 to DeleteFolders.Count - 1 do begin
      Value := DeleteFolders[I];
      if DirExists(Value) then begin
        Removed := False;
        if CanRemoveWorkspace(Value) then Removed := DelTree(Value, True, True, True);
        if not Removed then MsgBox(CustomMessage('DeleteIncomplete') + #13#10 + Value, mbError, MB_OK);
      end;
    end;
  Executable := ExpandConstant('{app}\TwinPALS-MCP.exe');
  Quoted := '"' + Executable + '" --resume --data-dir ';
  Plain := Executable + ' --resume --data-dir ';
  if RegGetValueNames(HKCU, RunKey, Names) then
    for I := 0 to GetArrayLength(Names) - 1 do
      if (Pos('TwinPALS study ', Names[I]) = 1) and RegQueryStringValue(HKCU, RunKey, Names[I], Value)
        and ((CompareText(Copy(Value, 1, Length(Quoted)), Quoted) = 0) or
             (CompareText(Copy(Value, 1, Length(Plain)), Plain) = 0)) then RegDeleteValue(HKCU, RunKey, Names[I]);
end;

