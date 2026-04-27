/* Migracja: Releasy aplikacji mobilnej (auto-update APK).
   Data: 2026-04-27.
   Cel: Tabela MobileAppRelease — backend auto-update APK dla tabletów stanowiskowych.
        Plik APK trzymany lokalnie w instance/mobile_apk/, w bazie tylko metadata. */

CREATE TABLE IF NOT EXISTS mobile_app_releases (
    id INT AUTO_INCREMENT PRIMARY KEY,
    version_code INT NOT NULL UNIQUE COMMENT 'Android versionCode z manifestu APK (rosnąca liczba całkowita)',
    version_name VARCHAR(50) NOT NULL COMMENT 'Wersja widoczna dla użytkownika np. 1.0.4',
    file_path VARCHAR(500) NOT NULL COMMENT 'Ścieżka relatywna od instance/, np. mobile_apk/5-d5e2a671.apk',
    file_size_bytes BIGINT NOT NULL COMMENT 'Rozmiar pliku APK w bajtach',
    sha256 CHAR(64) NOT NULL COMMENT 'SHA-256 całego pliku APK (do weryfikacji integralności pobierania)',
    release_notes TEXT DEFAULT NULL COMMENT 'Notatki release dla operatora — pokazywane w UI tabletu po update',
    uploaded_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT 'Kiedy admin wgrał APK',
    uploaded_by_user_id INT DEFAULT NULL COMMENT 'Kto wgrał (FK users.id, NULL = system/script)',
    is_active BOOLEAN NOT NULL DEFAULT TRUE COMMENT 'FALSE = release wycofany (np. krytyczny bug) - pomijany przy /app/version i /app/apk',
    INDEX idx_version_code (version_code),
    INDEX idx_is_active (is_active),
    CONSTRAINT fk_mobile_release_user
        FOREIGN KEY (uploaded_by_user_id) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
