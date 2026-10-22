; Instalator agenta druku WoodPower (Inno Setup 6). Budowanie: zbuduj.ps1, które podaje
;   /DWersja=<agent_druku.WERSJA> /DZrodlo=<dist\AgentDruku> /DWinsw=<vendor\WinSW-x64.exe>
;
; Parametr instalacji /CRM=https://... — adres serwera CRM, z którym agent może się łączyć
; (zapisany w crm_url.txt w katalogu danych; parowanie z okienka przyjmuje tylko token). Bez
; parametru: przy aktualizacji zostaje dotychczasowy adres, przy pierwszej instalacji domyślny.
;
; Program:  C:\Program Files\WoodPower\AgentDruku\  (AgentDruku.exe + AgentDrukuUsluga.exe/.xml)
; Dane:     %ProgramData%\WoodPower\AgentDruku\    (konfiguracja z tokenem, klucz lokalny,
;           dziennik, logi) — dostęp tylko SYSTEM i Administratorzy; NIE usuwane przy odinstalowaniu.
; Usługa:   WoodPowerAgentDruku (WinSW, LocalSystem). Ikona: HKLM\...\Run "AgentDruku".
;
; Aktualizacja (też cicha: /VERYSILENT /SUPPRESSMSGBOXES /NORESTART, uruchamiana przez usługę):
; ikony w zasobniku zamykają się same → zatrzymanie usługi → reszta procesów AgentDruku.exe
; zamknięta siłą → podmiana plików → start usługi. Błąd albo przerwanie PRZED kopiowaniem plików:
; stara wersja zostaje i usługa wraca na niej (DeinitializeSetup). Błąd W TRAKCIE kopiowania może
; zostawić mieszankę starych i nowych plików — wtedy zainstaluj ponownie z pliku setup. Usługa,
; która nie wstanie po instalacji, to błąd w logu instalatora (i okno, gdy instalacja nie jest cicha).

#ifndef Wersja
  #error Podaj wersje: ISCC /DWersja=x.y.z (zbuduj.ps1 robi to samo)
#endif
#ifndef Zrodlo
  #define Zrodlo "dist\AgentDruku"
#endif
#ifndef Winsw
  #define Winsw "vendor\WinSW-x64.exe"
#endif

#define Usluga "WoodPowerAgentDruku"
#define Dane "{commonappdata}\WoodPower\AgentDruku"
#define CrmDomyslny "https://crm.woodpower.pl"

[Setup]
AppId={{6E3C2B71-4D0A-4F57-9A39-1C7B3E5D2A90}
AppName=WoodPower Agent druku
AppVersion={#Wersja}
AppVerName=WoodPower Agent druku {#Wersja}
AppPublisher=WoodPower
VersionInfoVersion={#Wersja}
DefaultDirName={autopf}\WoodPower\AgentDruku
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=no
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputBaseFilename=AgentDruku-{#Wersja}-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupLogging=yes
; Dwa instalatory naraz (np. dwa kliknięcia „Aktualizuj”) — drugi kończy się od razu.
SetupMutex=WoodPowerAgentDrukuInstalator,Global\WoodPowerAgentDrukuInstalator
; Procesy AgentDruku.exe zamyka [Code] (usługa przez WinSW), nie Restart Manager.
CloseApplications=no
RestartApplications=no
UninstallDisplayName=WoodPower Agent druku
UninstallDisplayIcon={app}\AgentDruku.exe

[Languages]
Name: "pl"; MessagesFile: "compiler:Languages\Polish.isl"

[Dirs]
Name: "{#Dane}"; Flags: uninsneveruninstall
Name: "{#Dane}\logi"; Flags: uninsneveruninstall

[Files]
Source: "{#Zrodlo}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Winsw}"; DestDir: "{app}"; DestName: "AgentDrukuUsluga.exe"; Flags: ignoreversion
Source: "AgentDrukuUsluga.xml"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{commonprograms}\WoodPower\Agent druku"; Filename: "{app}\AgentDruku.exe"; Parameters: "tray"

[Registry]
; Ikona w zasobniku przy logowaniu każdego użytkownika.
Root: HKLM; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "AgentDruku"; ValueData: """{app}\AgentDruku.exe"" tray"; Flags: uninsdeletevalue

[Run]
; Adres CRM, uprawnienia, klucz i usługa — w [Code] (PoInstalacji), żeby sprawdzić wyniki.
; Ikona dla administratora, który instaluje ręcznie; przy cichej aktualizacji wraca sama.
Filename: "{app}\AgentDruku.exe"; Parameters: "tray"; Flags: nowait runasoriginaluser skipifsilent

[UninstallRun]
Filename: "{app}\AgentDrukuUsluga.exe"; Parameters: "stop"; Flags: runhidden waituntilterminated; RunOnceId: "ZatrzymajUsluge"
Filename: "{app}\AgentDrukuUsluga.exe"; Parameters: "uninstall"; Flags: runhidden waituntilterminated; RunOnceId: "UsunUsluge"
Filename: "{sys}\taskkill.exe"; Parameters: "/F /T /IM AgentDruku.exe"; Flags: runhidden waituntilterminated; RunOnceId: "ZamknijIkony"

[Code]
var
  UslugaZatrzymana: Boolean;
  InstalacjaUdana: Boolean;
  PlikWinsw: String;
  AdresCrm: String;
  PierwszaInstalacja: Boolean;

function Uruchom(const Plik, Parametry: String): Integer;
var
  Kod: Integer;
begin
  if not Exec(Plik, Parametry, '', SW_HIDE, ewWaitUntilTerminated, Kod) then
    Kod := -1;
  Result := Kod;
end;

function UslugaZainstalowana: Boolean;
begin
  Result := Uruchom(ExpandConstant('{sys}\sc.exe'), 'query {#Usluga}') = 0;
end;

function UslugaWStanie(const Stan: String): Boolean;
begin
  Result := Uruchom(ExpandConstant('{cmd}'),
    '/c ""' + ExpandConstant('{sys}\sc.exe') + '" query {#Usluga} | "' +
    ExpandConstant('{sys}\find.exe') + '" "' + Stan + '" >nul"') = 0;
end;

procedure Blad(const Opis: String);
begin
  { Log trafia do logu instalatora (/LOG); okno pojawia się tylko poza /SUPPRESSMSGBOXES. }
  Log('BŁĄD: ' + Opis);
  SuppressibleMsgBox(Opis, mbError, MB_OK, IDOK);
end;

function TylkoZnaki(const Tekst, Dozwolone: String): Boolean;
var
  I: Integer;
begin
  Result := False;
  for I := 1 to Length(Tekst) do
    if Pos(Tekst[I], Dozwolone) = 0 then
      Exit;
  Result := True;
end;

function AdresCrmPoprawny(const Adres: String): Boolean;
{ Sam adres serwera: https://host[:port][/] albo http://127.0.0.1|localhost[:port][/].
  Bez ścieżki, zapytania i danych logowania (ściślej niż konfiguracja.normalizuj_adres_crm). }
var
  A, Reszta, Host, Port: String;
  I: Integer;
  Lokalny: Boolean;
begin
  Result := False;
  A := Lowercase(Adres);
  if Pos('https://', A) = 1 then
  begin
    Reszta := Copy(A, 9, Length(A));
    Lokalny := False;
  end
  else if Pos('http://', A) = 1 then
  begin
    Reszta := Copy(A, 8, Length(A));
    Lokalny := True;
  end
  else
    Exit;
  I := Pos('/', Reszta);
  if I > 0 then
  begin
    if I <> Length(Reszta) then
      Exit;
    Reszta := Copy(Reszta, 1, I - 1);
  end;
  I := Pos(':', Reszta);
  if I > 0 then
  begin
    Host := Copy(Reszta, 1, I - 1);
    Port := Copy(Reszta, I + 1, Length(Reszta));
    if (Port = '') or (Length(Port) > 5) or not TylkoZnaki(Port, '0123456789') then
      Exit;
  end
  else
    Host := Reszta;
  if Host = '' then
    Exit;
  if Lokalny then
    Result := (Host = '127.0.0.1') or (Host = 'localhost')
  else
    Result := TylkoZnaki(Host, 'abcdefghijklmnopqrstuvwxyz0123456789.-') and (Host[1] <> '.')
      and (Host[1] <> '-');
end;

function InitializeSetup: Boolean;
begin
  AdresCrm := Trim(ExpandConstant('{param:CRM|}'));
  Result := (AdresCrm = '') or AdresCrmPoprawny(AdresCrm);
  if not Result then
    Blad('Parametr /CRM musi być adresem https:// serwera CRM (podano: ' + AdresCrm + ').');
end;

function Icacls(const Parametry: String): Boolean;
begin
  Result := Uruchom(ExpandConstant('{sys}\icacls.exe'), Parametry) = 0;
  if not Result then
    Log('icacls ' + Parametry + ' — błąd');
end;

function ZabezpieczKatalogi: String;
{ Przed instalacją (przy aktualizacji jeszcze przed zatrzymaniem usługi). Właściciel: Administratorzy
  dla całego drzewa; na WoodPower i AgentDruku tylko SYSTEM (S-1-5-18) i Administratorzy
  (S-1-5-32-544), bez dziedziczenia z ProgramData i bez żadnych jawnych wpisów innych kont (/reset
  usuwa je wszystkie, także nieznanych SID-ów); pliki w środku dziedziczą tylko z AgentDruku.
  Kolejność bez chwili, w której dane byłyby czytelne dla innych: najpierw dziecko odcięte od
  dziedziczenia (/reset rodzica go nie rusza), potem rodzic /reset → /inheritance:r /grant:r, potem
  dziecko /reset (dziedziczy już z bezpiecznego rodzica) → /inheritance:r /grant:r, na końcu pliki.
  Bez /C: błąd icacls przerywa instalację, zamiast przejść po cichu.
  /reset odbiera ikonie w zasobniku prawo odczytu klucza — nadajemy je od razu z powrotem. }
var
  Korzen, Dane, Klucz, Chron: String;
begin
  Result := '';
  Korzen := ExpandConstant('{commonappdata}\WoodPower');
  Dane := ExpandConstant('{#Dane}');
  Klucz := Dane + '\klucz_lokalny';
  ForceDirectories(Dane);
  Chron := ' /inheritance:r /grant:r *S-1-5-18:(OI)(CI)F *S-1-5-32-544:(OI)(CI)F';
  if not Icacls('"' + Korzen + '" /setowner *S-1-5-32-544 /T /Q') then
    Result := 'Nie ustawiono właściciela katalogu ' + Korzen + '.'
  else if not Icacls('"' + Dane + '"' + Chron) then
    Result := 'Nie ustawiono uprawnień katalogu ' + Dane + '.'
  else if not (Icacls('"' + Korzen + '" /reset /Q') and Icacls('"' + Korzen + '"' + Chron)) then
    Result := 'Nie ustawiono uprawnień katalogu ' + Korzen + '.'
  else if not (Icacls('"' + Dane + '" /reset /Q') and Icacls('"' + Dane + '"' + Chron)) then
    Result := 'Nie ustawiono uprawnień katalogu ' + Dane + '.'
  else if not Icacls('"' + Dane + '\*" /reset /T /Q') then
    Result := 'Nie ustawiono uprawnień plików w ' + Dane + '.'
  else if FileExists(Klucz) and not Icacls('"' + Klucz + '" /grant *S-1-5-4:(R)') then
    Log('Nie przywrócono ikonie prawa odczytu ' + Klucz + ' — usługa nada je przy starcie.');
  if Result <> '' then
    Blad(Result + ' Instalacja przerwana — uruchom ją ponownie jako administrator.');
end;

function PrzeniesDaneNaBok: String;
{ Pierwsza instalacja (usługi jeszcze nie ma): zastany %ProgramData%\WoodPower mógł założyć każdy
  użytkownik (jawne wpisy ACL, podłożony crm_url.txt albo klucz_lokalny, dowiązanie do własnego
  katalogu). Zamiast go łatać przenosimy go na bok i instalator zakłada katalog od nowa. Dowiązania
  (junction, symlink) nie śledzimy: usuwamy samo dowiązanie, a jego cel zostaje nietknięty. }
var
  Korzen, Cel: String;
  Wpis: TFindRec;
  Dowiazanie: Boolean;
begin
  Result := '';
  Korzen := ExpandConstant('{commonappdata}\WoodPower');
  if not FindFirst(Korzen, Wpis) then
    Exit;
  Dowiazanie := (Wpis.Attributes and $400) <> 0;  { FILE_ATTRIBUTE_REPARSE_POINT }
  FindClose(Wpis);
  if Dowiazanie then
  begin
    { RemoveDir na dowiązaniu katalogu usuwa samo dowiązanie; dowiązanie do pliku — DeleteFile. }
    if not (RemoveDir(Korzen) or DeleteFile(Korzen)) then
      Result := 'Nie usunięto dowiązania ' + Korzen + ' zastanego przed instalacją.'
    else
      Log('Usunięto dowiązanie ' + Korzen + ' zastane przed pierwszą instalacją.');
  end
  else
  begin
    Cel := Korzen + '.przed-instalacja-' + GetDateTimeString('yyyymmdd', #0, #0) + '-' +
      GetDateTimeString('hhnnss', #0, #0);
    if not RenameFile(Korzen, Cel) then
      Result := 'Nie przeniesiono katalogu ' + Korzen + ' zastanego przed instalacją.'
    else
      Log('Katalog ' + Korzen + ' zastany przed pierwszą instalacją przeniesiony na ' + Cel + '.');
  end;
  if Result <> '' then
    Blad(Result + ' Instalacja przerwana — usuń go ręcznie jako administrator i uruchom instalację ponownie.');
end;

procedure ZapiszAdresCrm;
{ Pierwsza instalacja (usługa jeszcze nie istnieje): adres zawsze z /CRM albo domyślny — plik
  zastany na dysku mógł podłożyć ktoś przed instalacją. Aktualizacja: przypięty adres zostaje,
  chyba że podano /CRM. }
var
  Plik: String;
begin
  Plik := ExpandConstant('{#Dane}\crm_url.txt');
  if (not PierwszaInstalacja) and (AdresCrm = '') and FileExists(Plik) then
    Exit;
  if AdresCrm = '' then
    AdresCrm := '{#CrmDomyslny}';
  if FileExists(Plik) and not DeleteFile(Plik) then
  begin
    Blad('Nie usunięto starego pliku ' + Plik + ' — adres CRM nie został ustawiony.');
    Exit;
  end;
  if SaveStringToFile(Plik, AdresCrm, False) then
    Log('Adres CRM: ' + AdresCrm)
  else
    Blad('Nie zapisano adresu CRM do ' + Plik + '.');
end;

procedure PoInstalacji;
var
  Dane, Winsw: String;
  I: Integer;
begin
  Dane := ExpandConstant('{#Dane}');
  Winsw := ExpandConstant('{app}\AgentDrukuUsluga.exe');
  { Uprawnienia katalogów ustawił już PrepareToInstall (ZabezpieczKatalogi). }
  ZapiszAdresCrm;
  { Klucz lokalnego API (jeśli brak). Ikona w zasobniku działa bez podniesionych uprawnień (przy
    UAC grupa Administratorzy jest wtedy „deny-only”) — sam klucz musi być czytelny dla
    zalogowanego interaktywnie (S-1-5-4). Usługa nadaje to samo przy każdym starcie. Przy pierwszej
    instalacji klucz zawsze od nowa (zastany mógł ktoś podłożyć). }
  if PierwszaInstalacja and FileExists(Dane + '\klucz_lokalny') and not DeleteFile(Dane + '\klucz_lokalny') then
    Blad('Nie usunięto zastanego klucza ' + Dane + '\klucz_lokalny.');
  if Uruchom(ExpandConstant('{app}\AgentDruku.exe'), 'klucz') <> 0 then
    Blad('Nie założono klucza lokalnego API agenta.');
  if not Icacls('"' + Dane + '\klucz_lokalny" /grant *S-1-5-4:(R)') then
    Blad('Nie nadano ikonie w zasobniku prawa odczytu klucza ' + Dane + '\klucz_lokalny.');
  if not UslugaZainstalowana then
    if Uruchom(Winsw, 'install') <> 0 then
      Blad('Nie zainstalowano usługi {#Usluga}.');
  Uruchom(Winsw, 'start');
  for I := 1 to 20 do
  begin
    if UslugaWStanie('RUNNING') then
    begin
      Log('Usługa {#Usluga} działa.');
      Exit;
    end;
    Sleep(1000);
  end;
  Blad('Usługa agenta druku ({#Usluga}) nie wystartowała. Sprawdź logi w ' + Dane +
    '\logi i uruchom ją ponownie (sc start {#Usluga}).');
end;

function UslugaZatrzymanaWSc: Boolean;
begin
  Result := Uruchom(ExpandConstant('{cmd}'),
    '/c ""' + ExpandConstant('{sys}\sc.exe') + '" query {#Usluga} | "' +
    ExpandConstant('{sys}\find.exe') + '" "STOPPED" >nul"') = 0;
end;

function DzialaAgentDruku: Boolean;
begin
  Result := Uruchom(ExpandConstant('{cmd}'),
    '/c ""' + ExpandConstant('{sys}\tasklist.exe') + '" /FI "IMAGENAME eq AgentDruku.exe" /NH | "' +
    ExpandConstant('{sys}\find.exe') + '" /I "AgentDruku.exe" >nul"') = 0;
end;

procedure CzekajNaIkony;
var
  I: Integer;
begin
  { Ikony widzą „instalacja” w stanie usługi i zamykają się same (zostawiając zadanie powrotu)
    — dajemy im na to chwilę, zanim usługa przestanie odpowiadać. Usługa działa w sesji 0,
    ikony w sesjach użytkowników; czekamy najwyżej 10 s. }
  for I := 1 to 10 do
  begin
    if Uruchom(ExpandConstant('{cmd}'),
      '/c ""' + ExpandConstant('{sys}\tasklist.exe') + '" /FI "IMAGENAME eq AgentDruku.exe" /FI "SESSION ne 0" /NH | "' +
      ExpandConstant('{sys}\find.exe') + '" /I "AgentDruku.exe" >nul"') <> 0 then
      Exit;
    Sleep(1000);
  end;
end;

procedure ZatrzymajUsluge;
var
  I: Integer;
begin
  PlikWinsw := ExpandConstant('{app}\AgentDrukuUsluga.exe');
  if FileExists(PlikWinsw) then
    Uruchom(PlikWinsw, 'stop')
  else
    Uruchom(ExpandConstant('{sys}\sc.exe'), 'stop {#Usluga}');
  UslugaZatrzymana := True;
  for I := 1 to 30 do
  begin
    if UslugaZatrzymanaWSc then
      Exit;
    Sleep(1000);
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  I: Integer;
begin
  { Pierwsza instalacja = usługi jeszcze nie ma (nie: brak crm_url.txt — ten plik może podłożyć
    każdy przed instalacją). }
  PierwszaInstalacja := not UslugaZainstalowana;
  { Najpierw ikony: zamykają się same, gdy zobaczą „instalacja” w stanie usługi — po /reset uprawnień
    nie mogłyby już odczytać klucza i nie zobaczyłyby tego. }
  CzekajNaIkony;
  if PierwszaInstalacja then
  begin
    Result := PrzeniesDaneNaBok;
    if Result <> '' then
      Exit;
  end;
  Result := ZabezpieczKatalogi;
  if Result <> '' then
    Exit;
  if not PierwszaInstalacja then
    ZatrzymajUsluge;
  { Pozostałe procesy (ikony innych sesji, zawieszona usługa) blokowałyby podmianę AgentDruku.exe. }
  if DzialaAgentDruku then
    Uruchom(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM AgentDruku.exe');
  for I := 1 to 10 do
  begin
    if not DzialaAgentDruku then
      Exit;
    Sleep(500);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    InstalacjaUdana := True;
    PoInstalacji;
  end;
end;

procedure DeinitializeSetup;
begin
  { Instalacja nieudana albo przerwana przed końcem kopiowania: usługa wraca na plikach, które są
    na dysku (stara wersja, gdy błąd był przed kopiowaniem). }
  if UslugaZatrzymana and (not InstalacjaUdana) and FileExists(PlikWinsw) then
    Uruchom(PlikWinsw, 'start');
end;
