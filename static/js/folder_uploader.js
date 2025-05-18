document.addEventListener('DOMContentLoaded', function () {

    // --- Элементы DOM ---
    const uploadFolderButton = document.getElementById('uploadFolderBtn');
    const folderInputElement = document.getElementById('folder_input_element');

    // Элементы для отображения прогресса загрузки папки
    const folderUploadProgressContainer = document.getElementById('folderUploadProgressContainer');
    const folderProgressBar = document.getElementById('folderProgressBar');
    const folderProgressCounter = document.getElementById('folderProgressCounter');
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
        if (folderProgressCounter) folderProgressCounter.textContent = `0/${totalFilesCount} файлов`;
        if (currentFileUploading) currentFileUploading.textContent = 'Подготовка...';
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
        if (folderProgressCounter) {
            folderProgressCounter.textContent = `${processed}/${total} файлов (Успешно: ${successful})`;
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
        const files = event.target.files;
        const parentId = getCurrentFolderId();
        const csrfToken = getCsrfToken();

        const totalFiles = files.length;
        resetFolderUploadUI(totalFiles);

        if (!totalFiles) {
            showFinalStatusMessage('Папка не выбрана или пуста.', true);
            if (folderUploadProgressContainer) folderUploadProgressContainer.style.display = 'none';
            return;
        }
        if (!csrfToken) {
            showFinalStatusMessage('Ошибка: Не удалось получить CSRF токен. Загрузка невозможна.', true);
            if (folderUploadProgressContainer) folderUploadProgressContainer.style.display = 'none';
            return;
        }

        updateFolderUploadProgress(0, totalFiles, 0, files.length > 0 ? (files[0].webkitRelativePath || files[0].name) : "Подготовка...");


        let successfulUploads = 0;
        let failedUploads = 0;
        let processedFiles = 0;

        for (const file of files) {
            const displayName = file.webkitRelativePath || file.name;
            // Обновляем прогресс перед каждой загрузкой
            updateFolderUploadProgress(processedFiles, totalFiles, successfulUploads, displayName);

            const formData = new FormData();
            formData.append('file', file);
            formData.append('relative_path', file.webkitRelativePath);
            if (parentId) formData.append('parent_id', parentId);
            formData.append('csrfmiddlewaretoken', csrfToken);

            const uploadUrl = window.UPLOAD_URL;
            if (!uploadUrl) {
                addFolderUploadError(displayName, 'URL для загрузки не определен.');
                failedUploads++;
                // processedFiles инкрементируется ниже, после блока try/catch
            } else {
                try {
                    const response = await fetch(uploadUrl, {method: 'POST', body: formData});
                    const responseData = await response.json();

                    if (response.ok) {
                        if (responseData.results && responseData.results.length > 0) {
                            const fileResult = responseData.results[0];
                            if (fileResult.status === 'success') {
                                successfulUploads++;
                            } else {
                                failedUploads++;
                                addFolderUploadError(displayName, fileResult.error || 'Неизвестная ошибка обработки файла.');
                            }
                        } else {
                            failedUploads++;
                            addFolderUploadError(displayName, responseData.message || 'Ответ сервера не содержит результатов по файлу.');
                        }
                    } else {
                        failedUploads++;
                        const serverErrorMsg = responseData.error || responseData.detail || responseData.message || `HTTP ошибка ${response.status}`;
                        addFolderUploadError(displayName, `Ошибка сервера (${response.status}): ${serverErrorMsg}`);
                    }
                } catch (error) {
                    console.error('Сетевая/неожиданная ошибка при загрузке:', displayName, error);
                    failedUploads++;
                    addFolderUploadError(displayName, 'Сетевая ошибка или ошибка ответа. См. консоль.');
                }
            }
            processedFiles++;
        }
        // Обновляем прогресс после завершения цикла (когда все файлы обработаны)
        updateFolderUploadProgress(processedFiles, totalFiles, successfulUploads, "Завершено.");

        event.target.value = null; // Сброс инпута

        let finalMessageText;
        let finalIsError = false;
        let finalIsWarning = false;

        if (failedUploads === 0 && successfulUploads === totalFiles && totalFiles > 0) {
            finalMessageText = 'Все файлы из папки успешно загружены!';
            setTimeout(() => {
                if (window.CURRENT_LIST_URL) window.location.href = window.CURRENT_LIST_URL;
                else window.location.reload();
            }, 1500);
        } else if (failedUploads > 0) {
            finalMessageText = `Загрузка папки завершена. Успешно: ${successfulUploads} из ${totalFiles}. Ошибок: ${failedUploads}.`;
            finalIsError = true;
        } else if (successfulUploads > 0 && successfulUploads < totalFiles) {
            finalMessageText = `Загрузка папки завершена. Успешно: ${successfulUploads} из ${totalFiles}. Не все файлы были обработаны.`;
            finalIsWarning = true;
        } else if (totalFiles > 0) {
            finalMessageText = `Загрузка папки завершена. Успешно: ${successfulUploads} из ${totalFiles}. Проверьте ошибки выше.`;
            finalIsWarning = true;
        }

        if (finalMessageText) {
            showFinalStatusMessage(finalMessageText, finalIsError, finalIsWarning);
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

            // Опционально: можно сбросить значения в прогресс-баре и счетчиках,
            // хотя они и так будут скрыты. Это для чистоты, если контейнер
            // folderUploadProgressContainer будет снова показан без вызова resetFolderUploadUI.
            if (folderProgressBar) {
                folderProgressBar.style.width = '0%';
                folderProgressBar.textContent = '0%';
                folderProgressBar.classList.remove('bg-success', 'bg-danger', 'bg-warning');
                // Важно: если анимация была убрана, ее нужно вернуть, если планируется повторное использование
                // Но resetFolderUploadUI это делает при новой загрузке.
                // folderProgressBar.classList.add('progress-bar-animated'); // Это сделает resetFolderUploadUI
            }
            if (folderProgressCounter) folderProgressCounter.textContent = `0/0 файлов`;
            if (currentFileUploading) currentFileUploading.textContent = '';
        });
    } else {
        console.warn('Кнопка очистки ошибок (clearFolderUploadErrorsBtn) не найдена.');
    }
});