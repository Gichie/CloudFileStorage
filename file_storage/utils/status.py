def get_message_and_status(
        results: list[dict[str, str | None]]
) -> tuple[dict[str, str | list[dict[str, str | None]]], int]:
    """
    Формирует общее сообщение и HTTP-статус на основе результатов обработки файлов.

    :param results: Список словарей, где каждый словарь представляет результат
                    обработки одного файла и содержит ключи 'status' и 'name'.
    :return: Кортеж из словаря с сообщением и списком результатов, и HTTP-статуса.
             HTTP-статус 200 если все успешно, 207 (Multi-Status) если были ошибки.
    """
    total_files = len(results)
    error_count = sum(1 for res in results if res.get("status") == "error")

    if error_count == 0:
        message = 'Все файлы успешно загружены.'
        http_status = 200
    elif error_count == total_files:
        message = 'Файл(ы) не удалось загрузить.'
        http_status = 400 if total_files == 1 else 207
    else:
        message = 'Некоторые файлы были загружены с ошибкой.'
        http_status = 207

    return {'message': message, 'results': results}, http_status
