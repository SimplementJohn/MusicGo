; =============================================================================
; MusicGo — Script d'installation Inno Setup
; =============================================================================
; Compile avec : iscc.exe musicgo-setup.iss
; Prerequis    : executer build-installer.ps1 avant (remplit installer/bundle/)
; Cible        : Windows 10/11 x64
; =============================================================================

#define AppName         "MusicGo"
#define AppVersion      "1.1.1"
#define AppPublisher    "MusicGo"
#define AppExeName      "MusicGo.exe"
#define AppGUID         "B8F1C5A0-4E8A-4C9E-8E7D-3D2F9A1B7C5E"
#define AppRegKey       "Software\Microsoft\Windows\CurrentVersion\Uninstall\" + AppName

[Setup]
AppId={{{#AppGUID}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=
AppSupportURL=
AppUpdatesURL=
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
OutputBaseFilename=MusicGo-Setup-{#AppVersion}
OutputDir=output
SetupIconFile=musicgo.ico
UninstallDisplayIcon={app}\musicgo.ico
UninstallDisplayName={#AppName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
WizardImageFile=assets\wizard-large.bmp
WizardSmallImageFile=assets\wizard-small.bmp
WizardImageStretch=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
DisableProgramGroupPage=yes
LicenseFile=license.txt
CloseApplications=yes
RestartApplications=no
; Pas de page de selection dossier si repair (gere en Pascal)
DisableDirPage=auto
DisableReadyPage=no
ShowLanguageDialog=auto

[Languages]
Name: "french"; MessagesFile: "compiler:Languages\French.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Creer un raccourci sur le Bureau"; GroupDescription: "Raccourcis :"

[Files]
; Tout le contenu du bundle
Source: "bundle\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion
; Icones
Source: "musicgo.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "musicgo_logo.ico"; DestDir: "{app}"; Flags: ignoreversion skipifsourcedoesntexist

[Icons]
; Menu Demarrer — exe natif (icone integree, pas de tooltip wscript)
Name: "{group}\{#AppName}"; \
    Filename: "{app}\musicgo_launcher.exe"; \
    WorkingDir: "{app}"; \
    IconFilename: "{app}\musicgo_launcher.exe"; \
    IconIndex: 0
Name: "{group}\Desinstaller {#AppName}"; Filename: "{uninstallexe}"

; Bureau — optionnel
Name: "{autodesktop}\{#AppName}"; \
    Filename: "{app}\musicgo_launcher.exe"; \
    WorkingDir: "{app}"; \
    IconFilename: "{app}\musicgo.ico"; \
    IconIndex: 0; \
    Tasks: desktopicon

[Registry]
; Inno Setup ecrit UninstallString/DisplayName/etc. automatiquement via AppId.
; On ajoute seulement InstallLocation (non ecrit automatiquement).
Root: HKLM; Subkey: "Software\Microsoft\Windows\CurrentVersion\Uninstall\{{{#AppGUID}}}"; \
    ValueType: string; ValueName: "InstallLocation"; ValueData: "{app}"

[Run]
Filename: "{app}\musicgo_launcher.exe"; \
    WorkingDir: "{app}"; \
    Description: "Lancer {#AppName} maintenant"; \
    Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
// ============================================================================
// Variables globales du wizard repair
// ============================================================================
var
  RepairPage: TWizardPage;
  RadioRepair, RadioUninstall, RadioCancel: TRadioButton;

// ============================================================================
// Detection installation existante
// ============================================================================
function IsAlreadyInstalled(var InstallPath: String): Boolean;
begin
  Result := RegQueryStringValue(HKLM,
    'Software\Microsoft\Windows\CurrentVersion\Uninstall\{{{#AppGUID}}}',
    'InstallLocation', InstallPath);
  if Result then
    Result := (InstallPath <> '') and DirExists(InstallPath);
end;

function IsPortInUse(Port: Integer): Boolean;
var
  ResultCode: Integer;
  TempFile, Output: String;
  Lines: TStringList;
begin
  Result := False;
  TempFile := ExpandConstant('{tmp}\portcheck.txt');
  Exec(ExpandConstant('{cmd}'),
       '/C netstat -ano | findstr LISTENING | findstr :' + IntToStr(Port) + ' > "' + TempFile + '"',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  if FileExists(TempFile) then
  begin
    Lines := TStringList.Create;
    try
      Lines.LoadFromFile(TempFile);
      Result := Lines.Count > 0;
    finally
      Lines.Free;
    end;
    DeleteFile(TempFile);
  end;
end;

// ============================================================================
// Page repair custom (radio buttons + Next du wizard)
// ============================================================================
procedure CreateRepairPage;
var
  lbl: TNewStaticText;
  InstallPath: String;
begin
  IsAlreadyInstalled(InstallPath);

  RepairPage := CreateCustomPage(
    wpWelcome,
    'MusicGo est deja installe',
    'Choisissez une action puis cliquez sur Suivant.');

  lbl := TNewStaticText.Create(RepairPage);
  lbl.Parent := RepairPage.Surface;
  lbl.Left := 0;
  lbl.Top := 0;
  lbl.Width := RepairPage.SurfaceWidth;
  lbl.AutoSize := True;
  lbl.WordWrap := True;
  lbl.Caption := 'Une version de MusicGo est deja installee dans :' + #13#10 +
                 '  ' + InstallPath + #13#10#13#10 +
                 'Que souhaitez-vous faire ?';

  RadioRepair := TRadioButton.Create(RepairPage);
  RadioRepair.Parent := RepairPage.Surface;
  RadioRepair.Left := 0;
  RadioRepair.Top := 80;
  RadioRepair.Width := RepairPage.SurfaceWidth;
  RadioRepair.Caption := 'Reparer  -  Reinstaller MusicGo par-dessus';
  RadioRepair.Font.Style := [fsBold];
  RadioRepair.Checked := True;

  RadioUninstall := TRadioButton.Create(RepairPage);
  RadioUninstall.Parent := RepairPage.Surface;
  RadioUninstall.Left := 0;
  RadioUninstall.Top := 112;
  RadioUninstall.Width := RepairPage.SurfaceWidth;
  RadioUninstall.Caption := 'Desinstaller  -  Supprimer MusicGo et quitter';

  RadioCancel := TRadioButton.Create(RepairPage);
  RadioCancel.Parent := RepairPage.Surface;
  RadioCancel.Left := 0;
  RadioCancel.Top := 144;
  RadioCancel.Width := RepairPage.SurfaceWidth;
  RadioCancel.Caption := 'Annuler  -  Quitter sans rien faire';
end;

// ============================================================================
// Hooks Inno Setup
// ============================================================================
function InitializeSetup(): Boolean;
var
  InstallPath: String;
begin
  Result := True;

  // Avertissement port 8080 occupe (non bloquant)
  if not IsAlreadyInstalled(InstallPath) then
  begin
    if IsPortInUse(8080) then
    begin
      if MsgBox('Le port 8080 est deja utilise.' + #13#10 +
                'MusicGo risque de ne pas demarrer apres installation.' + #13#10#13#10 +
                'Continuer quand meme ?', mbConfirmation, MB_YESNO) = IDNO then
        Result := False;
    end;
  end;
end;

procedure InitializeWizard;
var
  InstallPath: String;
begin
  if IsAlreadyInstalled(InstallPath) then
    CreateRepairPage;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  InstallPath, UninstExe: String;
  ResultCode: Integer;
begin
  Result := True;
  if (RepairPage <> nil) and (CurPageID = RepairPage.ID) then
  begin
    if RadioCancel.Checked then
    begin
      Result := False;
      WizardForm.Close;
    end
    else if RadioUninstall.Checked then
    begin
      Result := False;
      IsAlreadyInstalled(InstallPath);
      UninstExe := InstallPath + '\unins000.exe';
      if FileExists(UninstExe) then
        Exec(UninstExe, '/SILENT', '', SW_SHOW, ewWaitUntilTerminated, ResultCode);
      WizardForm.Close;
    end;
    // RadioRepair.Checked => Result=True, wizard continue normalement
  end;
end;

function InitializeUninstall(): Boolean;
var
  ResultCode: Integer;
begin
  Result := True;
  // Kill les process Python avant desinstallation pour liberer les DLLs
  Exec(ExpandConstant('{cmd}'),
       '/C taskkill /F /IM pythonw.exe >nul 2>&1 & taskkill /F /IM python.exe >nul 2>&1',
       '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(1000);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  AppDir: String;
  ResultCode: Integer;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    AppDir := ExpandConstant('{app}');
    if DirExists(AppDir) then
    begin
      // Force suppression via cmd (contourne les DLLs residuelles)
      Exec(ExpandConstant('{cmd}'),
           '/C rmdir /S /Q "' + AppDir + '"',
           '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
    end;
  end;
end;
