document.addEventListener('DOMContentLoaded', function () {

    // --- Элементы DOM ---
    const uploadFolderButton = document.getElementById('uploadFolderBtn');
    const folderInputElement = document.getElementById('folder_input_element');

    // Элементы для отображения прогресса загрузки папки
    const folderUploadProgressContainer = document.getElementById('folderUploadProgressContainer');
    const folderProgressBar = document.getElementById('folderProgressBar');
    //const folderProgressCounter = document.getElementById('folderProgressCounter');
    const currentFileUploading = document.getElementById('currentFileUploading');
    const folderUploadErrorsContainer = document.getElementById('folderUploadErrorsContainer');
    const clearFolderUploadErrorsBtn = document.getElementById('clearFolderUploadErrorsBtn');
    const folderUploadErrorList = document.getElementById('folderUploadErrorList');
    const uploadFinalStatusMessageContainer = document.getElementById('uploadFinalStatusMessage');

    // --- Функции-хелперы ---
    function getCurrentFolderId() {
        const currentFolderElement = document.getElementById('current_folder_id_holder');
        if (currentFolderElement && currentFolderElement.value) {
            return currentFolderElement.value;
        }
        return null;
    }

    function getCsrfToken() {
        const csrfInput = document.querySelector('input[name="csrfmiddlewaretoken"]');
        if (csrfInput) {
            return csrfInput.value;
        }
        console.error('CSRF token not found. Make sure {% csrf_token %} is in your template.');
        return null;
    }

    function resetFolderUploadUI(totalFilesCount) {
        if (folderUploadProgressContainer) folderUploadProgressContainer.style.display = 'block';
        if (folderProgressBar) {
            folderProgressBar.style.width = '0%';
            folderProgressBar.textContent = '0%';
            folderProgressBar.classList.remove('bg-success', 'bg-danger', 'bg-warning');
            folderProgressBar.classList.add('progress-bar-animated'); // Восстанавливаем анимацию
        }

        if (currentFileUploading) currentFileUploading.textContent = 'Загрузка...';
        if (folderUploadErrorList) folderUploadErrorList.innerHTML = '';
        if (folderUploadErrorsContainer) folderUploadErrorsContainer.style.display = 'none';
        if (uploadFinalStatusMessageContainer) uploadFinalStatusMessageContainer.innerHTML = '';
    }

    function updateFolderUploadProgress(processed, total, successful, currentFileName) {
        const percentage = total > 0 ? Math.round((processed / total) * 100) : 0;
        if (folderProgressBar) {
            folderProgressBar.style.width = percentage + '%';
            folderProgressBar.textContent = percentage + '%';
        }
        if (currentFileUploading) {
            currentFileUploading.textContent = currentFileName ? `Загрузка: ${currentFileName}` : (processed === total ? "Завершение..." : "Ожидание...");
        }
    }

    function addFolderUploadError(fileName, errorMessage) {
        if (folderUploadErrorList) {
            const listItem = document.createElement('li');
            listItem.className = 'list-group-item p-1 small text-danger'; // Сделал текст ошибки красным
            listItem.textContent = `${fileName}: ${errorMessage}`;
            folderUploadErrorList.appendChild(listItem);
        }
        if (folderUploadErrorsContainer && folderUploadErrorsContainer.style.display === 'none') {
            folderUploadErrorsContainer.style.display = 'block';
        }
    }

    function showFinalStatusMessage(message, isError = false, isWarning = false) {
        if (!uploadFinalStatusMessageContainer) return;
        uploadFinalStatusMessageContainer.innerHTML = ''; // Очищаем предыдущие сообщения
        const messageElement = document.createElement('div');
        messageElement.textContent = message;
        let alertClass = 'alert-info';
        if (isError) alertClass = 'alert-danger';
        else if (isWarning) alertClass = 'alert-warning';
        else alertClass = 'alert-success';
        messageElement.className = `alert ${alertClass} mt-1 mb-1 p-2`;
        uploadFinalStatusMessageContainer.appendChild(messageElement);
        uploadFinalStatusMessageContainer.style.display = 'block';

        if (folderProgressBar) {
            folderProgressBar.classList.remove('progress-bar-animated');
            if (isError) folderProgressBar.classList.add('bg-danger');
            else if (isWarning && !isError) folderProgressBar.classList.add('bg-warning'); // Если только предупреждения, но не ошибки
            else folderProgressBar.classList.add('bg-success');
        }
    }

    async function handleFolderUpload(event) {
        const files = Array.from(event.target.files);
        const parentId = getCurrentFolderId();
        const MAX_ALLOWED_FILES = window.MAX_ALLOWED_FILES;
        const MAX_UPLOAD_SIZE_BYTES = window.MAX_UPLOAD_SIZE_BYTES; // 500 МБ (должно совпадать с лимитом Nginx and in settings)

        // Проверка лимита файлов до любой другой логики
        if (files.length > MAX_ALLOWED_FILES) {
            showFinalStatusMessage(
                `Ошибка: Количество файлов в папке (${files.length}) превышает максимально допустимое (${MAX_ALLOWED_FILES}). Загрузите меньше файлов за один раз.`,
                true
            );
            event.target.value = null; // сброс выбранных файлов, чтобы пользователь мог повторить выбор
            return;
        }

        let totalSize = 0;
        for (const file of files) {
            totalSize += file.size;
        }

        if (totalSize > MAX_UPLOAD_SIZE_BYTES) {
            // Показываем ошибку МГНОВЕННО, до отправки запроса
            showFinalStatusMessage(
                `Ошибка: Общий размер папки (${(totalSize / 1024 / 1024).toFixed(2)} МБ) превышает лимит в ${MAX_UPLOAD_SIZE_BYTES} МБ.`,
                true
            );
            event.target.value = null; // Сбрасываем инпут
            return;
        }

        const csrfToken = getCsrfToken();
        const uploadUrl = window.UPLOAD_URL;

        const totalFiles = files.length;
        resetFolderUploadUI(totalFiles);

        // --- Блок начальных проверок ---
        if (!totalFiles) {
            showFinalStatusMessage('Папка не выбрана или пуста.', true);
            if (folderUploadProgressContainer) folderUploadProgressContainer.style.display = 'none';
            return;
        }
        if (!csrfToken || !uploadUrl) {
            const errorMessage = !csrfToken ? 'Ошибка: Не удалось получить CSRF токен.' : 'Ошибка: URL для загрузки не определен.';
            showFinalStatusMessage(errorMessage, true);
            if (folderUploadProgressContainer) folderUploadProgressContainer.style.display = 'none';
            return;
        }

        // --- Создание общего FormData ---
        const formData = new FormData();
        files.forEach(file => {
            formData.append('files', file);
            formData.append('relative_paths', file.webkitRelativePath);
        });
        if (parentId) {
            formData.append('parent_id', parentId);
        }

        function uploadWithXHR(url, data) {
            return new Promise((resolve, reject) => {
                const xhr = new XMLHttpRequest();
                xhr.open('POST', url, true);
                xhr.setRequestHeader('X-CSRFToken', csrfToken);

                xhr.onload = function () {
                    // Этот блок сработает для любого HTTP-статуса, включая 413.
                    if (xhr.status === 413) {

                        reject({
                            isNginxLimitError: true,
                            message: 'Ошибка: Папка слишком большая. Превышен лимит на сервере.'
                        });
                        return;
                    }

                    resolve({
                        ok: xhr.status >= 200 && xhr.status < 300,
                        status: xhr.status,
                        json: () => {
                            try {
                                return JSON.parse(xhr.responseText);
                            } catch (e) {
                                return {error: "Не удалось разобрать ответ сервера."};
                            }
                        }
                    });
                };

                xhr.onerror = function () {
                    reject({
                        isNetworkError: true,
                        message: 'Ошибка сети или сервер разорвал соединение. Возможно, папка слишком большая.'
                    });
                };

                // Опционально: можно показывать реальный прогресс загрузки.
                xhr.upload.onprogress = function (e) {
                    if (e.lengthComputable) {
                        const percentage = Math.round((e.loaded / e.total) * 100);
                        // Здесь можно обновлять UI, показывая реальный процент загрузки
                        if (folderProgressBar) {
                            folderProgressBar.style.width = percentage + '%';
                            folderProgressBar.textContent = `Загрузка: ${percentage}%`;
                        }
                    }
                };

                xhr.send(data);
            });
        }

        // --- Основной блок Try/Catch для обработки загрузки ---
        try {
            const response = await uploadWithXHR(uploadUrl, formData);
            console.log("Response status:", response.status, "Response ok:", response.ok);

            if (!response.ok) {
                let errorData;
                try {
                    errorData = await response.json(); // <--- Используй await здесь
                } catch (e) {
                    errorData = {detail: await response.text()}; // Если не JSON, взять как текст
                }
                const serverErrorMsg = errorData?.error || errorData?.detail || `HTTP ошибка ${response.status}`;
                showFinalStatusMessage(`Ошибка сервера: ${serverErrorMsg}`, true);
                return;
            }

            let responseData;
            try {
                responseData = await response.json(); // <--- Используй await здесь
            } catch (e) {
                showFinalStatusMessage('Ошибка парсинга ответа от сервера.', true);
                return;
            }

            let successfulUploads = 0;
            let failedUploads = 0;

            if (Array.isArray(responseData.results)) {
                responseData.results.forEach(fileResult => {

                    if (fileResult.status === 'success') {
                        successfulUploads++;
                    } else {
                        failedUploads++;
                        addFolderUploadError(fileResult.name, fileResult.error || 'Неизвестная ошибка.');
                    }
                });
            } else {
                showFinalStatusMessage('Ответ сервера не содержит корректных результатов по файлам.', true);

                console.error("responseData.results is not an array:", responseData.results);

                return;
            }

            updateFolderUploadProgress(totalFiles, totalFiles, successfulUploads, "Завершено.");

            console.log("Uploads - Success:", successfulUploads, "Failed:", failedUploads);

            if (failedUploads === 0) {
                showFinalStatusMessage('Все файлы из папки успешно загружены!');

                console.log("All files uploaded successfully. Preparing for redirect/reload.");
                console.log("window.CURRENT_LIST_URL:", window.CURRENT_LIST_URL);

                setTimeout(() => {
                    console.log("Inside setTimeout. Attempting redirect/reload.");

                    if (window.CURRENT_LIST_URL) {
                        console.log("Redirecting to:", window.CURRENT_LIST_URL); // <--- ДОБАВЬ ЭТО
                        window.location.href = window.CURRENT_LIST_URL;
                    } else {
                        console.log("Reloading current page."); // <--- ДОБАВЬ ЭТО
                        window.location.reload();
                    }
                }, 1400);
            } else {
                showFinalStatusMessage(
                    `Загрузка папки завершена. Успешно: ${successfulUploads} из ${totalFiles}. Ошибок: ${failedUploads}.`,
                    true
                );
                console.log("Some files failed to upload.");
            }

        } catch (error) {
            console.error('Upload failed:', error);
            // Ловим наши кастомные ошибки из промиса
            if (error.isNginxLimitError || error.isNetworkError) {
                showFinalStatusMessage(error.message, true);
            } else {
                // Ловим все остальные непредвиденные ошибки
                console.error('Непредвиденная ошибка при загрузке:', error);
                showFinalStatusMessage('Произошла непредвиденная ошибка. См. консоль.', true);
            }
        } finally {
            event.target.value = null; // Сброс инпута в любом случае
        }
    }

// --- Привязка обработчиков событий ---
    if (uploadFolderButton && folderInputElement) {
        uploadFolderButton.addEventListener('click', () => folderInputElement.click());
        folderInputElement.addEventListener('change', handleFolderUpload);
    } else {
        if (!uploadFolderButton) console.warn('Кнопка "Загрузить папку" (uploadFolderBtn) не найдена.');
        if (!folderInputElement) console.warn('Элемент input для выбора папки (folder_input_element) не найден.');
    }

// Обработчик для кнопки очистки ошибок и всего блока прогресса
    if (clearFolderUploadErrorsBtn) {
        clearFolderUploadErrorsBtn.addEventListener('click', function () {
            // 1. Очищаем и скрываем список ошибок
            if (folderUploadErrorList) folderUploadErrorList.innerHTML = '';
            if (folderUploadErrorsContainer) folderUploadErrorsContainer.style.display = 'none';

            // 2. Очищаем и скрываем финальное статусное сообщение
            if (uploadFinalStatusMessageContainer) {
                uploadFinalStatusMessageContainer.innerHTML = '';
                uploadFinalStatusMessageContainer.style.display = 'none';
            }

            // 3. Скрываем весь контейнер прогресса загрузки папки
            // Это также скроет прогресс-бар, счетчики и надпись "Загрузка папки:"
            if (folderUploadProgressContainer) {
                folderUploadProgressContainer.style.display = 'none';
            }

            if (folderProgressBar) {
                folderProgressBar.style.width = '0%';
                folderProgressBar.textContent = '0%';
                folderProgressBar.classList.remove('bg-success', 'bg-danger', 'bg-warning');

            }
            if (folderProgressCounter) folderProgressCounter.textContent = `0/0 файлов`;
            if (currentFileUploading) currentFileUploading.textContent = '';
        });
    } else {
        console.warn('Кнопка очистки ошибок (clearFolderUploadErrorsBtn) не найдена.');
    }
})
;