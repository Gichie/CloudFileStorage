document.addEventListener('DOMContentLoaded', function () {
        const dropZone = document.getElementById('dropZone');
        const fileInput = document.getElementById('fileInput'); // Скрытый input[type=file]

        const selectedFilesListContainer = document.getElementById('selectedFilesList');
        const selectedFilesUl = selectedFilesListContainer.querySelector('ul.list-group');
        const uploadActionsDiv = document.getElementById('uploadActions');
        const startUploadButton = document.getElementById('startUploadButton');
        const clearSelectionButton = document.getElementById('clearSelectionButton');

        const uploadProgressContainer = document.getElementById('uploadProgressContainer');
        const uploadProgressBar = document.getElementById('uploadProgressBar');
        const uploadMessages = document.getElementById('uploadMessages');

        let filesToUpload = []; // Массив для хранения выбранных файлов

        function getCookie(name) {
            let cookieValue = null;
            if (document.cookie && document.cookie !== '') {
                const cookies = document.cookie.split(';');
                for (let i = 0; i < cookies.length; i++) {
                    const cookie = cookies[i].trim();
                    if (cookie.substring(0, name.length + 1) === (name + '=')) {
                        cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                        break;
                    }
                }
            }
            return cookieValue;
        }

        const csrftoken = getCookie('csrftoken');

        // --- Обработчики для выбора файлов ---
        if (dropZone) {
            // Клик по зоне или label открывает диалог выбора файлов
            dropZone.addEventListener('click', () => {
                if (fileInput) fileInput.click();
            });

            // Drag & Drop события
            ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
                dropZone.addEventListener(eventName, (e) => {
                    preventDefaults(e);
                }, false);
                document.body.addEventListener(eventName, (e) => {
                    preventDefaults(e);
                }, false);
            });

            ['dragenter', 'dragover'].forEach(eventName => {
                dropZone.addEventListener(eventName, () => {
                    dropZone.classList.add('dragover');
                }, false);
            });

            ['dragleave', 'drop'].forEach(eventName => {
                dropZone.addEventListener(eventName, () => {
                    dropZone.classList.remove('dragover');
                }, false);
            });

            dropZone.addEventListener('drop', (e) => {
                handleDrop(e);
            }, false);

        }

        if (fileInput) {
            fileInput.addEventListener('change', handleFileSelect, false);
        }

        function preventDefaults(e) {
            e.preventDefault();
            e.stopPropagation();
        }

        function handleDrop(e) {
            const dt = e.dataTransfer;
            const files = dt.files;
            addFilesToUploadList(files);
        }

        function handleFileSelect(e) {
            const files = e.target.files;
            addFilesToUploadList(files);
            if (fileInput) fileInput.value = '';
        }

        function addFilesToUploadList(newFiles) {
            for (let i = 0; i < newFiles.length; i++) {
                // Проверка на дубликаты по имени и размеру
                if (!filesToUpload.some(existingFile => existingFile.name === newFiles[i].name && existingFile.size === newFiles[i].size)) {
                    filesToUpload.push(newFiles[i]);
                }
            }
            renderSelectedFiles();
            updateUploadControlsVisibility();
        }

        function renderSelectedFiles() {
            selectedFilesUl.innerHTML = ''; // Очищаем список
            if (filesToUpload.length === 0) {
                selectedFilesListContainer.style.display = 'none';
                return;
            }

            filesToUpload.forEach((file, index) => {
                const li = document.createElement('li');
                li.classList.add('list-group-item', 'd-flex', 'justify-content-between', 'align-items-center');
                li.textContent = `${file.name} (${formatBytes(file.size)})`;

                const removeBtn = document.createElement('button');
                removeBtn.classList.add('btn', 'btn-sm', 'btn-outline-danger');
                removeBtn.innerHTML = '<i class="bi bi-x"></i>';
                removeBtn.title = "Удалить из списка";
                removeBtn.onclick = () => {
                    filesToUpload.splice(index, 1);
                    renderSelectedFiles();
                    updateUploadControlsVisibility();
                };
                li.appendChild(removeBtn);
                selectedFilesUl.appendChild(li);
            });
            selectedFilesListContainer.style.display = 'block';
        }

        function formatBytes(bytes, decimals = 2) {
            if (bytes === 0) return '0 Bytes';
            const k = 1024;
            const dm = decimals < 0 ? 0 : decimals;
            const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB'];
            const i = Math.floor(Math.log(bytes) / Math.log(k));
            return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
        }

        function updateUploadControlsVisibility() {
            if (filesToUpload.length > 0) {
                uploadActionsDiv.style.display = 'block';
            } else {
                uploadActionsDiv.style.display = 'none';
                selectedFilesListContainer.style.display = 'none'; // Скрыть список, если он пуст
            }
        }

        // --- Загрузка файлов ---
        if (startUploadButton) {
            startUploadButton.addEventListener('click', () => {
                if (filesToUpload.length === 0) {
                    uploadMessages.innerHTML = '<p class="text-warning">Нет файлов для загрузки.</p>';
                    return;
                }
                uploadFiles(filesToUpload);
            });
        }

        if (clearSelectionButton) {
            clearSelectionButton.addEventListener('click', () => {
                filesToUpload = [];
                renderSelectedFiles();
                updateUploadControlsVisibility();
                uploadMessages.innerHTML = ''; // Очистить сообщения об ошибках/успехе
                uploadProgressContainer.style.display = 'none'; // Скрыть прогресс-бар
            });
        }

        function uploadFiles(files) {
            const MAX_UPLOAD_SIZE_BYTES = 500 * 1024 * 1024; // 500 МБ (должно совпадать с лимитом Nginx)
            let totalSize = 0;
            let largeFiles = []; // Массив для имен слишком больших файлов

            files.forEach(file => {
                totalSize += file.size;
                if (file.size > MAX_UPLOAD_SIZE_BYTES) {
                    largeFiles.push(file.name);
                }
            });

            // Проверяем как каждый отдельный файл, так и общий размер
            if (largeFiles.length > 0) {
                // Если есть хотя бы один файл, превышающий лимит
                uploadMessages.innerHTML = `<p class="text-danger">Ошибка: Следующие файлы превышают лимит в 500 МБ: <strong>${largeFiles.join(', ')}</strong>. Удалите их из списка и попробуйте снова.</p>`;
                uploadProgressContainer.style.display = 'block';
                uploadProgressBar.classList.add('bg-danger');
                uploadProgressBar.textContent = 'Ошибка размера!';
                return; // Прерываем загрузку
            }

            if (totalSize > MAX_UPLOAD_SIZE_BYTES) {
                // Если общий размер превышает лимит (актуально для мульти-загрузки)
                uploadMessages.innerHTML = `<p class="text-danger">Ошибка: Общий размер выбранных файлов (${formatBytes(totalSize)}) превышает лимит в 500 МБ.</p>`;
                uploadProgressContainer.style.display = 'block';
                uploadProgressBar.classList.add('bg-danger');
                uploadProgressBar.textContent = 'Ошибка размера!';
                return; // Прерываем загрузку
            }

            const uploadUrl = window.UPLOAD_URL;
            if (!uploadUrl) {
                console.error("Upload URL (window.UPLOAD_URL) is not defined.");
                uploadMessages.innerHTML = '<p class="text-danger">Ошибка конфигурации: URL для загрузки не определен.</p>';
                return;
            }

            const currentFolderId = dropZone.dataset.currentFolderId || null;
            const formData = new FormData();

            files.forEach(file => {
                formData.append('files', file, file.name);
            });

            if (currentFolderId) {
                formData.append('parent_id', currentFolderId);
            }

            uploadProgressContainer.style.display = 'block';
            uploadProgressBar.style.width = '0%';
            uploadProgressBar.textContent = '0%';
            uploadProgressBar.setAttribute('aria-valuenow', 0);
            uploadProgressBar.classList.remove('bg-danger', 'bg-success'); // Сброс классов
            uploadMessages.innerHTML = ''; // Очистить предыдущие сообщения
            startUploadButton.disabled = true;
            clearSelectionButton.disabled = true;

            // Использование XMLHttpRequest для отслеживания прогресса
            const xhr = new XMLHttpRequest();
            xhr.open('POST', uploadUrl, true);
            xhr.setRequestHeader('X-CSRFToken', csrftoken);

            xhr.upload.onprogress = function (event) {
                if (event.lengthComputable) {
                    const percentComplete = Math.round((event.loaded / event.total) * 100);
                    uploadProgressBar.style.width = percentComplete + '%';
                    uploadProgressBar.textContent = percentComplete + '%';
                    uploadProgressBar.setAttribute('aria-valuenow', percentComplete);
                }
            };

            xhr.onload = function () {
                startUploadButton.disabled = false;
                clearSelectionButton.disabled = false;

                let hasErrorsInResults = false; // Флаг для отслеживания ошибок в отдельных файлах

                if (xhr.status >= 200 && xhr.status < 300) {
                    try {
                        const data = JSON.parse(xhr.responseText);
                        let messageHtml = '';
                        if (data.message) {
                            messageHtml += `<p class="${data.results && data.results.some(r => r.status === 'error') ? 'text-warning' : 'text-success'}">${data.message}</p>`;
                        }

                        if (data.results && Array.isArray(data.results)) {
                            messageHtml += '<ul>';
                            data.results.forEach(result => {
                                messageHtml += `<li>${result.name}: ${result.status === 'success' ? '<span class="text-success">Успех</span>' : '<span class="text-danger">Ошибка: ' + (result.error || 'Неизвестная ошибка') + '</span>'}</li>`;
                                if (result.status === 'error') {
                                    hasErrorsInResults = true;
                                }
                            });
                            messageHtml += '</ul>';
                        } else if (!data.message) {
                            messageHtml = '<p class="text-success">Загрузка завершена (нет детальной информации).</p>';
                        }
                        uploadMessages.innerHTML = messageHtml;

                        if (!hasErrorsInResults && !(data.error)) { // Если нет ошибок ни в общем ответе, ни в отдельных файлах
                            uploadProgressBar.classList.remove('bg-danger');
                            uploadProgressBar.classList.add('bg-success');
                            uploadProgressBar.textContent = 'Успешно!';

                            // Очищаем список файлов к загрузке ТОЛЬКО после полной успешной операции
                            filesToUpload = [];
                            renderSelectedFiles();
                            updateUploadControlsVisibility();

                            // Перезагружаем страницу для отображения новых файлов
                            setTimeout(() => {
                                window.location.href = window.CURRENT_LIST_URL || window.location.pathname + window.location.search;
                            }, 1300); // Даем немного больше времени на просмотр сообщения
                        } else {
                            // Были ошибки в data.results или общая ошибка data.error
                            uploadProgressBar.classList.remove('bg-success');
                            uploadProgressBar.classList.add('bg-danger');
                            uploadProgressBar.textContent = 'Ошибка!';
                            // НЕ перезагружаем страницу и НЕ очищаем список файлов, чтобы пользователь видел ошибки
                            // и мог попробовать снова (возможно, после исправления чего-либо)
                        }

                    } catch (e) {
                        console.error('Ошибка парсинга JSON ответа:', e, xhr.responseText);
                        uploadMessages.innerHTML = `<p class="text-danger">Ошибка обработки ответа сервера. См. консоль.</p>`;
                        uploadProgressBar.classList.remove('bg-success');
                        uploadProgressBar.classList.add('bg-danger');
                        uploadProgressBar.textContent = 'Ошибка!';
                    }
                } else { // Ошибка HTTP запроса
                    let errorMsg;
                    if (xhr.status === 413) {
                        errorMsg = 'Ошибка: Файл или набор файлов слишком большой. Лимит на сервере превышен.';
                    } else {
                        errorMsg = `Ошибка сервера: ${xhr.status} ${xhr.statusText}`;
                        try {
                            const errData = JSON.parse(xhr.responseText);
                            if (errData.error) { // Если бэкенд шлет JSON с полем error
                                errorMsg = errData.error;
                            } else if (errData.detail) { // DRF часто использует detail
                                errorMsg = errData.detail;
                            } else if (typeof errData === 'string' && errData.length < 200) { // Если просто строка ошибки
                                errorMsg = errData;
                            }
                            // Иначе оставляем исходное сообщение xhr.statusText или добавляем тело ответа, если оно не слишком длинное
                            else if (xhr.responseText && xhr.responseText.length < 500) {
                                errorMsg += `<br><small>${xhr.responseText.replace(/</g, "<").replace(/>/g, ">")}</small>`;
                            }

                        } catch (e) { /* Оставляем errorMsg как есть, если ответ не JSON */
                        }
                    }
                    uploadMessages.innerHTML = `<p class="text-danger">${errorMsg}</p>`;
                    uploadProgressBar.classList.remove('bg-success');
                    uploadProgressBar.classList.add('bg-danger');
                    uploadProgressBar.textContent = 'Ошибка!';
                    // НЕ перезагружаем страницу и НЕ очищаем список файлов
                }
            }
            ;

            xhr.onerror = function () {
                startUploadButton.disabled = false;
                clearSelectionButton.disabled = false;
                uploadMessages.innerHTML = `<p class="text-danger">Ошибка сети или сервер недоступен.</p>`;
                uploadProgressBar.classList.add('bg-danger');
                uploadProgressBar.textContent = 'Ошибка сети';
            };

            xhr.send(formData);
        }

        const renameModal = document.getElementById('renameModal');
        if (renameModal) {
            renameModal.addEventListener('show.bs.modal', function (event) {
                const button = event.relatedTarget;
                const itemId = button.getAttribute('data-item-id');
                const itemName = button.getAttribute('data-item-name');
                const itemType = button.getAttribute('data-item-type');

                const modalTitle = renameModal.querySelector('.modal-title');
                const itemNameInput = renameModal.querySelector('#newItemName');
                const itemIdInput = renameModal.querySelector('#renameItemId');
                const itemTypeInput = renameModal.querySelector('#renameItemType');
                const itemTypeLabel = renameModal.querySelector('#renameItemTypeLabel');

                modalTitle.textContent = 'Переименовать ' + (itemType === 'folder' ? 'папку' : 'файл');
                itemNameInput.value = itemName;
                itemIdInput.value = itemId;
                if (itemTypeInput) itemTypeInput.value = itemType;
                if (itemTypeLabel) itemTypeLabel.textContent = (itemType === 'folder' ? 'Текущее имя папки: ' : 'Текущее имя файла: ') + itemName;
            });
        }

        const deleteModal = document.getElementById('deleteModal');
        if (deleteModal) {
            deleteModal.addEventListener('show.bs.modal', function (event) {
                const button = event.relatedTarget;
                const data = {
                    id: button.getAttribute('data-item-id'),
                    name: button.getAttribute('data-item-name'),
                    type: button.getAttribute('data-item-type')
                };

                // Установка значений в модальное окно
                deleteModal.querySelector('#deleteItemName').textContent = data.name;
                deleteModal.querySelector('#deleteItemType').textContent = data.type;
                deleteModal.querySelector('#deleteItemId').value = data.id;
            });
        }
    }
)
;