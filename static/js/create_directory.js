// js/create_directory.js

// Функция, которая будет инициализировать все обработчики и получать элементы DOM
function initializeCreateDirectoryModal() {
    // Получаем ссылки на элементы DOM
    const createFolderModalEl = document.getElementById('createFolderModal');
    const createFolderForm = document.getElementById('createFolderForm');
    const submitCreateFolderBtn = document.getElementById('submitCreateFolderBtn');
    const folderNameInput = document.getElementById('folderNameInput');
    const createFolderFormAlerts = document.getElementById('createFolderFormAlerts');
    const folderNameError = document.getElementById('folderNameError');

    // **Важно:** Проверяем, что все необходимые элементы найдены.
    // Если какой-то из них null, это означает, что JS пытается получить к нему доступ
    // до того, как он загрузился, или его ID неверен.
    if (!createFolderModalEl || !createFolderForm || !submitCreateFolderBtn ||
        !folderNameInput || !createFolderFormAlerts || !folderNameError) {
        console.error("Ошибка: Один или несколько элементов DOM для модального окна создания папки не найдены.");
        console.log({
            createFolderModalEl,
            createFolderForm,
            submitCreateFolderBtn,
            folderNameInput,
            createFolderFormAlerts,
            folderNameError
        });
        return; // Прекращаем выполнение функции, чтобы избежать ошибок null
    }

    // Получаем экземпляр модального окна Bootstrap
    // Используем getInstance для предотвращения повторной инициализации
    const createFolderModal = bootstrap.Modal.getInstance(createFolderModalEl) || new bootstrap.Modal(createFolderModalEl);

    // Очистка ошибок и полей при открытии модального окна
    createFolderModalEl.addEventListener('show.bs.modal', function () {
        createFolderForm.reset(); // Сбросить значения полей формы
        // Значение скрытого поля 'parent' уже установлено Django при рендеринге страницы
        // и будет корректно взято FormData.
        // Если бы оно могло меняться динамически на клиенте, его нужно было бы обновлять здесь.

        // Сброс сообщений об ошибках
        createFolderFormAlerts.style.display = 'none';
        createFolderFormAlerts.innerHTML = '';
        folderNameInput.classList.remove('is-invalid');
        folderNameError.style.display = 'none';
        folderNameError.innerHTML = '';
    });

    // Обработчик события клика по кнопке "Создать"
    submitCreateFolderBtn.addEventListener('click', function () {
        const formData = new FormData(createFolderForm);
        
        // Используем глобальную переменную, переданную из Django шаблона
        const postUrl = window.CURRENT_LIST_URL; 

        fetch(postUrl, {
            method: 'POST',
            body: formData,
            headers: {
                // CSRF-токен уже включен в formData благодаря {% csrf_token %} в форме.
                // Добавлять его в заголовок X-CSRFToken необязательно, но не повредит.
                'X-CSRFToken': formData.get('csrfmiddlewaretoken')
            }
        })
        .then(response => {
            // Проверяем, является ли ответ JSON
            const contentType = response.headers.get("content-type");
            if (contentType && contentType.includes("application/json")) {
                return response.json().then(data => ({ status: response.status, body: data }));
            } else {
                // Если не JSON, возможно, это HTML ошибки (например, отладочная страница Django)
                return response.text().then(text => {
                    throw new Error(`Неожиданный ответ сервера (не JSON): ${response.status}. Содержимое: ${text.substring(0, 200)}...`);
                });
            }
        })
        .then(({ status, body }) => {
            // Сброс предыдущих ошибок перед отображением новых
            createFolderFormAlerts.style.display = 'none';
            createFolderFormAlerts.innerHTML = '';
            folderNameInput.classList.remove('is-invalid');
            folderNameError.style.display = 'none';
            folderNameError.innerHTML = '';

            if (status >= 200 && status < 300 && body.status === 'success') {
                createFolderModal.hide();
                // Для лучшего UX можно было бы динамически добавить элемент в список,
                // но для простоты пока перезагрузим страницу.
                window.location.reload();
            } else {
                // Обработка ошибок от сервера (валидация или другие)
                if (body.errors) {
                    // Ошибки конкретного поля 'name'
                    if (body.errors.name) {
                        folderNameInput.classList.add('is-invalid');
                        folderNameError.textContent = body.errors.name.map(e => e.message).join(' ');
                        folderNameError.style.display = 'block';
                    }
                    // Общие ошибки формы (non_field_errors или ошибки, добавленные через form.add_error(None, ...))
                    const nonFieldErrors = body.errors.__all__ || [];
                    if (body.message && !nonFieldErrors.some(e => e.message === body.message)) {
                        // Если есть общее сообщение и оно не дублирует __all__, добавим его
                        nonFieldErrors.push({ message: body.message });
                    }
                    if (nonFieldErrors.length > 0) {
                        createFolderFormAlerts.innerHTML = nonFieldErrors.map(e => e.message).join('<br>');
                        createFolderFormAlerts.style.display = 'block';
                    }
                } else if (body.message) {
                    // Если есть только общее сообщение об ошибке
                    createFolderFormAlerts.innerHTML = body.message;
                    createFolderFormAlerts.style.display = 'block';
                } else {
                    // Неизвестная ошибка
                    createFolderFormAlerts.innerHTML = 'Произошла неизвестная ошибка при создании папки.';
                    createFolderFormAlerts.style.display = 'block';
                }
            }
        })
        .catch(error => {
            console.error('Ошибка при создании папки (в блоке catch):', error);
            createFolderFormAlerts.innerHTML = `Ошибка сети или сервера: ${error.message}. Попробуйте еще раз.`;
            createFolderFormAlerts.style.display = 'block';
        });
    });
}

// **Ключевая часть:** Вызываем initializeCreateDirectoryModal
// либо сразу, если DOM уже готов, либо по событию DOMContentLoaded.
if (document.readyState === 'loading') { // DOM еще загружается
    document.addEventListener('DOMContentLoaded', initializeCreateDirectoryModal);
} else {
    initializeCreateDirectoryModal();
}