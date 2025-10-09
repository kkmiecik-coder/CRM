function initIssueJS() {
    console.log("[issue.js] initIssueJS() – startuje");

    const form = document.querySelector('.issue-form');
    const overlay = document.getElementById('loadingOverlay');
    const overlayMsg = document.getElementById('overlayMessage');
    const fileInput = document.getElementById('attachment');
    const fileList = document.getElementById('file-list');
    const fileSizeInfo = document.getElementById('file-size-info');
    const maxFileSizeMB = 2;
    const maxTotalSizeMB = 15;
    
    // Przechowywanie wybranych plików
    let selectedFiles = [];

    if (!form) console.warn("[issue.js] Brak .issue-form");
    if (!overlay) console.warn("[issue.js] Brak #loadingOverlay");
    if (!overlayMsg) console.warn("[issue.js] Brak #overlayMessage");
    if (!fileInput) console.warn("[issue.js] Brak #attachment");
    if (!fileList) console.warn("[issue.js] Brak #file-list");

    if (!form || !overlay || !fileInput || !fileList || !overlayMsg) {
        console.warn("[issue.js] Nie wszystkie wymagane elementy są dostępne – initIssueJS przerwane");
        return;
    }

    console.log("[issue.js] Wszystkie elementy znalezione – przypinam eventy");

    // Funkcja do formatowania rozmiaru pliku
    function formatFileSize(bytes) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
    }

    // Funkcja do obliczania łącznego rozmiaru
    function getTotalSize() {
        return selectedFiles.reduce((total, file) => total + file.size, 0);
    }

    // Funkcja do aktualizacji informacji o rozmiarze
    function updateSizeInfo() {
        if (!fileSizeInfo) return;
        
        const totalSize = getTotalSize();
        const totalSizeMB = totalSize / (1024 * 1024);
        const remainingMB = maxTotalSizeMB - totalSizeMB;
        
        let sizeText = `Łączny rozmiar: ${formatFileSize(totalSize)} / ${maxTotalSizeMB}MB`;
        
        if (totalSizeMB > maxTotalSizeMB) {
            sizeText += ` <span style="color: #E00000;">Przekroczono limit!</span>`;
            fileSizeInfo.style.color = '#E00000';
        } else if (remainingMB < 2) {
            sizeText += ` <span style="color: #FF8C00;">Pozostało: ${remainingMB.toFixed(1)}MB</span>`;
            fileSizeInfo.style.color = '#FF8C00';
        } else {
            fileSizeInfo.style.color = '#333';
        }
        
        fileSizeInfo.innerHTML = sizeText;
    }

    // Funkcja do renderowania listy plików
    function renderFileList() {
        fileList.innerHTML = '';
        
        if (selectedFiles.length === 0) {
            const li = document.createElement('li');
            li.className = 'file-name';
            li.textContent = 'Nie dodano jeszcze żadnych plików.';
            fileList.appendChild(li);
            return;
        }

        selectedFiles.forEach((file, index) => {
            const li = document.createElement('li');
            li.className = 'file-item';
            
            const fileInfo = document.createElement('span');
            fileInfo.className = 'file-info';
            
            const fileName = document.createElement('span');
            fileName.className = 'file-name';
            fileName.textContent = file.name;
            
            const fileSize = document.createElement('span');
            fileSize.className = 'file-size';
            fileSize.textContent = ` (${formatFileSize(file.size)})`;
            
            fileInfo.appendChild(fileName);
            fileInfo.appendChild(fileSize);
            
            const removeBtn = document.createElement('button');
            removeBtn.type = 'button';
            removeBtn.className = 'remove-file-btn';
            removeBtn.innerHTML = '✕';
            removeBtn.title = 'Usuń plik';
            removeBtn.addEventListener('click', () => removeFile(index));
            
            li.appendChild(fileInfo);
            li.appendChild(removeBtn);
            
            // Sprawdź czy plik jest za duży
            if (file.size > maxFileSizeMB * 1024 * 1024) {
                li.style.color = '#E00000';
                const errorSpan = document.createElement('span');
                errorSpan.className = 'file-error';
                errorSpan.textContent = ` - Plik za duży (max ${maxFileSizeMB}MB)`;
                li.appendChild(errorSpan);
            }
            
            fileList.appendChild(li);
        });
        
        updateSizeInfo();
    }

    // Funkcja do usuwania pliku
    function removeFile(index) {
        selectedFiles.splice(index, 1);
        updateFileInput();
        renderFileList();
    }

    // Funkcja do aktualizacji input file
    function updateFileInput() {
        const dt = new DataTransfer();
        selectedFiles.forEach(file => dt.items.add(file));
        fileInput.files = dt.files;
    }

    // Funkcja walidacji plików
    function validateFiles(files) {
        const errors = [];
        let totalSize = 0;
        
        for (let file of files) {
            totalSize += file.size;
            
            if (file.size > maxFileSizeMB * 1024 * 1024) {
                errors.push(`Plik "${file.name}" jest za duży (max ${maxFileSizeMB}MB)`);
            }
        }
        
        if (totalSize > maxTotalSizeMB * 1024 * 1024) {
            errors.push(`Łączny rozmiar plików przekracza ${maxTotalSizeMB}MB`);
        }
        
        return errors;
    }

    // Event listener dla wyboru plików
    fileInput.addEventListener('change', function(event) {
        console.log("[issue.js] Zmiana plików");
        
        const newFiles = Array.from(event.target.files);
        
        if (newFiles.length === 0) {
            selectedFiles = [];
            renderFileList();
            return;
        }
        
        // Sprawdź czy dodanie nowych plików nie przekroczy limitów
        const combinedFiles = [...selectedFiles, ...newFiles];
        const errors = validateFiles(combinedFiles);
        
        if (errors.length > 0) {
            showToast('Błędy walidacji: ' + errors[0], 'warning');
            // Przywróć poprzedni stan
            updateFileInput();
            return;
        }
        
        // Dodaj nowe pliki do listy
        selectedFiles = combinedFiles;
        renderFileList();
    });

    // Event listener dla submitu formularza
    form.addEventListener('submit', function(event) {
        console.log("[issue.js] Form submit – sprawdzam walidację");
        
        // Sprawdź walidację przed wysłaniem
        const errors = validateFiles(selectedFiles);
        if (errors.length > 0) {
            event.preventDefault();
            showToast('Nie można wysłać formularza: ' + errors[0], 'error');
            return;
        }
        
        // Sprawdź czy łączny rozmiar nie przekracza limitu
        const totalSize = getTotalSize();
        if (totalSize > maxTotalSizeMB * 1024 * 1024) {
            event.preventDefault();
            showToast(`Łączny rozmiar plików (${formatFileSize(totalSize)}) przekracza limit ${maxTotalSizeMB}MB`, 'error');
            return;
        }
        
        console.log("[issue.js] Walidacja przeszła – pokazuję overlay");
        overlay.style.display = 'flex';
        overlayMsg.textContent = 'Wysyłanie zgłoszenia...';
        
        // Symulacja postępu
        setTimeout(() => {
            overlayMsg.textContent = 'Przesyłanie załączników...';
        }, 1000);
        
        setTimeout(() => {
            overlayMsg.textContent = 'Zgłoszenie zostało wysłane ✉️';
        }, 2500);
        
        // Ukryj overlay po wysłaniu - toast pokaże się automatycznie przy przeładowaniu
        setTimeout(() => {
            overlay.style.display = 'none';
        }, 4000);
    });

    // Inicjalna renderowanie listy
    renderFileList();
}

// Funkcja toast notifications
function showToast(message, type = 'success') {
    // Usuń istniejące toasty
    const existingToasts = document.querySelectorAll('.toast-notification');
    existingToasts.forEach(toast => toast.remove());

    // Utwórz nowy toast
    const toast = document.createElement('div');
    toast.className = `toast-notification ${type}`;
    toast.textContent = message;

    document.body.appendChild(toast);

    // Pokaż toast
    setTimeout(() => toast.classList.add('show'), 100);

    // Ukryj toast po 3 sekundach
    setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.remove(), 300);
    }, 6000);
}

// Automatyczne wywołanie po załadowaniu DOM
document.addEventListener('DOMContentLoaded', function() {
    initIssueJS();
    
    // 🔍 DEBUG: Sprawdź flash messages
    console.log("=== DEBUG FLASH MESSAGES ===");
    const flashMessages = document.querySelectorAll('.alert');
    console.log("Znalezione alerty:", flashMessages.length);
    
    flashMessages.forEach((alert, index) => {
        const message = alert.textContent.trim();
        console.log(`Alert ${index}:`);
        console.log('- innerHTML:', alert.innerHTML);
        console.log('- className:', alert.className);
        console.log('- textContent:', message);
        
        // Sprawdź wszystkie możliwe klasy
        let type = 'success'; // domyślnie success
        
        if (alert.classList.contains('alert-error')) {
            type = 'error';
            console.log('- Wykryto: alert-error');
        } else if (alert.classList.contains('alert-warning')) {
            type = 'warning';
            console.log('- Wykryto: alert-warning');
        } else if (alert.classList.contains('alert-success')) {
            type = 'success';
            console.log('- Wykryto: alert-success');
        } else {
            console.log('- Brak rozpoznanej klasy, używam domyślnej: success');
        }
        
        console.log('- Typ toast:', type);
        console.log("========================");
        
        showToast(message, type);
        alert.style.display = 'none';
    });
});