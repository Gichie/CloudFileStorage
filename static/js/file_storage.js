document.addEventListener('DOMContentLoaded', function () {
            // Твой JS для подтверждения удаления (без изменений)
            document.querySelectorAll('.delete-confirm-btn').forEach(button => {
                button.addEventListener('click', function (event) {
                    const formId = this.dataset.formId;
                    const form = document.getElementById(formId);
                    if (form && confirm('{% trans "Вы уверены, что хотите удалить этот элемент?" %}')) {
                        form.submit();
                    }
                });
            });

            // --- JS для формы загрузки в модальном окне ---
            const uploadModalElement = document.getElementById('uploadFileModal');
            if (uploadModalElement) {
                const uploadForm = document.getElementById('fileUploadModalForm');
                const fileInput = uploadForm.querySelector('#{{ upload_form.file.id_for_label }}');
                const clickZone = uploadForm.querySelector('#uploadClickZone');
                const clickZoneText = clickZone.querySelector('#uploadClickZoneText');

                const emptyFileNameInput = uploadForm.querySelector('#emptyFileNameInputModal');
                const createEmptyFileBtn = uploadForm.querySelector('#createEmptyFileBtnModal');

                const fullscreenOverlay = document.getElementById('fullscreen-drop-overlay');
                let bodyDragCounter = 0; // Счетчик для корректной работы dragleave на body

                function updateUploadUI(files) {
                    if (files && files.length > 0) {
                        clickZoneText.textContent = `{% trans "Выбран файл:" %} ${files[0].name}`;
                        clickZone.classList.add('file-selected');
                    } else {
                        clickZoneText.textContent = '{% trans "Щёлкните здесь или перетащите файл" %}';
                        clickZone.classList.remove('file-selected');
                    }
                }

                fileInput.addEventListener('change', () => {
                    updateUploadUI(fileInput.files);
                });

                createEmptyFileBtn.addEventListener('click', (e) => {
                    e.preventDefault();
                    const emptyContent = new Uint8Array([0]); // Минимальный непустой файл
                    let fileName = emptyFileNameInput.value.trim();
                    if (!fileName) {
                        fileName = `empty_file_${Date.now()}.bin`;
                    } else if (!fileName.includes('.')) {
                        fileName += '.bin'; // Добавляем расширение по умолчанию, если его нет
                    }

                    try {
                        const emptyFile = new File([emptyContent], fileName, {
                            type: "application/octet-stream",
                            lastModified: Date.now()
                        });
                        const dataTransfer = new DataTransfer();
                        dataTransfer.items.add(emptyFile);
                        fileInput.files = dataTransfer.files;
                        updateUploadUI(fileInput.files);
                        emptyFileNameInput.value = ''; // Очищаем поле
                    } catch (error) {
                        console.error("Ошибка при создании пустого файла:", error);
                        // Можно показать сообщение пользователю
                    }
                });

                // --- Drag and Drop ---
                function preventDefaults(e) {
                    e.preventDefault();
                    e.stopPropagation();
                }

                // Глобальные обработчики для fullscreen-overlay
                ['dragenter', 'dragover'].forEach(eventName => {
                    document.body.addEventListener(eventName, (e) => {
                        preventDefaults(e);
                        if (e.dataTransfer.types.includes('Files')) {
                            fullscreenOverlay.classList.add('visible');
                        }
                    }, false);
                });

                // Используем document.body для dragleave, чтобы правильно скрывать оверлей
                document.body.addEventListener('dragleave', (e) => {
                    // Проверяем, что ушли именно с body или на элемент вне body
                    if (e.target === document.body || e.relatedTarget === null || !document.body.contains(e.relatedTarget)) {
                        bodyDragCounter--;
                        if (bodyDragCounter <= 0) { // <=0 на случай нескольких быстрых enter/leave
                            fullscreenOverlay.classList.remove('visible');
                            bodyDragCounter = 0; // Сброс
                        }
                    }
                }, false);

                document.body.addEventListener('dragenter', (e) => {
                    if (e.dataTransfer.types.includes('Files')) {
                        bodyDragCounter++;
                        fullscreenOverlay.classList.add('visible');
                    }
                }, false);


                fullscreenOverlay.addEventListener('drop', (e) => {
                    preventDefaults(e);
                    fullscreenOverlay.classList.remove('visible');
                    bodyDragCounter = 0;
                    const files = e.dataTransfer.files;
                    if (files.length > 0) {
                        fileInput.files = files;
                        updateUploadUI(files);
                        // Открываем модальное окно, если оно было закрыто
                        const modal = bootstrap.Modal.getInstance(uploadModalElement) || new bootstrap.Modal(uploadModalElement);
                        modal.show();
                    }
                }, false);

                // Обработчики для clickZone внутри модального окна
                ['dragenter', 'dragover'].forEach(eventName => {
                    clickZone.addEventListener(eventName, (e) => {
                        preventDefaults(e); // Останавливаем всплытие, чтобы body не показал fullscreenOverlay
                        clickZone.classList.add('dragover');
                        // Важно: если мы над clickZone, fullscreenOverlay не должен быть виден
                        fullscreenOverlay.classList.remove('visible');
                        bodyDragCounter = 0; // сбрасываем счетчик body, т.к. мы уже над целевой зоной
                    }, false);
                });

                clickZone.addEventListener('dragleave', (e) => {
                    preventDefaults(e);
                    clickZone.classList.remove('dragover');
                }, false);

                clickZone.addEventListener('drop', (e) => {
                    preventDefaults(e);
                    clickZone.classList.remove('dragover');
                    fullscreenOverlay.classList.remove('visible'); // Убедимся, что он скрыт
                    bodyDragCounter = 0;
                    const files = e.dataTransfer.files;
                    if (files.length > 0) {
                        fileInput.files = files;
                        updateUploadUI(files);
                    }
                }, false);

                // Очистка формы и UI при закрытии модального окна
                uploadModalElement.addEventListener('hidden.bs.modal', function () {
                    uploadForm.reset(); // Сбрасывает значения полей формы
                    updateUploadUI(null); // Обновляет UI click-zone
                    // Очистка сообщений об ошибках Django, если они были добавлены динамически (сложнее)
                    // Проще всего, если страница перезагружается после сабмита (что Django и делает при редиректе)
                });
            }
        });