"""Селекторы и подписи UI web.max.ru.

Стратегия: несколько вариантов на действие + поиск по видимому тексту (RU).
При смене вёрстки MAX правьте этот файл.
"""

from __future__ import annotations

# --- Общее ---
APP_READY = [
    "[class*='sidebar']",
    "[class*='chat-list']",
    "[class*='dialogs']",
    "nav",
    "main",
]

COMPOSER = [
    "textarea",
    '[contenteditable="true"]',
    '[data-testid="composer-input"]',
    '[role="textbox"]',
    '[class*="composer"] textarea',
    '[class*="input"] [contenteditable="true"]',
]

SEND_BUTTON = [
    'button[aria-label*="Отправ"]',
    'button[aria-label*="Send"]',
    '[data-testid="send-button"]',
    'button[type="submit"]',
]

INCOMING_MESSAGE = [
    '[data-testid="message-in"]',
    '[class*="message"][class*="in"]',
    '[class*="incoming"]',
    '[class*="Message"][class*="other"]',
    '[class*="bubble"][class*="left"]',
]

# Тексты кнопок / пунктов меню (регистронезависимый поиск в max_ui_actions)
TEXT_START_CHAT = ("Начать общение",)
TEXT_NEW_CHAT = (
    "Новый чат",
    "Написать",
    "Создать чат",
    "новый чат",
    "New chat",
)
TEXT_FIND_BY_PHONE = ("Найти по номеру",)
TEXT_FIND_IN_MAX = ("Найти в MAX",)
TEXT_NEXT = ("Далее",)
TEXT_CREATE_GROUP = (
    "Создать группу",
    "Новая группа",
    "Групповой чат",
    "группу",
    "Group",
)
TEXT_CONTACTS = (
    "Контакты",
    "Контакт",
    "Contacts",
)
TEXT_SEARCH = (
    "Поиск",
    "Найти",
    "Search",
)
TEXT_ADD = (
    "Добавить",
    "Add",
    "Пригласить",
)
TEXT_SAVE_CONTACT = (
    "Сохранить",
    "Готово",
    "Применить",
)
TEXT_ADD_CONTACT = (
    "Добавить контакт",
)
TEXT_SAVE_CONTACT_BTN = (
    "Сохранить контакт",
)
TEXT_EDIT_CONTACT = (
    "Изменить",
    "Редактировать",
    "Имя в контактах",
)
CONTACT_NAME_INPUT = [
    'input[placeholder*="имя" i]',
    'input[placeholder*="Имя"]',
    'input[placeholder*="запис"]',
    'input[placeholder*="как"]',
    'input[placeholder*="Контакт"]',
]
TEXT_CREATE = (
    "Создать",
    "Готово",
    "Create",
    "Done",
)
TEXT_LEAVE_GROUP = (
    "Покинуть группу",
    "Покинуть чат",
    "Выйти из группы",
    "Удалить группу",
    "Удалить чат",
    "Leave group",
    "Leave",
)
TEXT_CONFIRM_DELETE = (
    "Покинуть",
    "Удалить",
    "Да",
    "Подтвердить",
    "Confirm",
)
TEXT_GROUP_NAME = (
    "Название",
    "Имя группы",
    "название группы",
    "Group name",
)

SEARCH_INPUT = [
    'input[type="search"]',
    'input[placeholder*="Поиск"]',
    'input[placeholder*="Найти"]',
    'input[placeholder*="Search"]',
    '[role="searchbox"]',
    'input[type="text"]',
]

GROUP_NAME_INPUT = [
    'input[placeholder*="назван"]',
    'input[placeholder*="Назван"]',
    'input[placeholder*="групп"]',
    'input[placeholder*="имя"]',
    'input[type="text"]',
]

CONTACT_RESULT = [
    '[class*="contact"]',
    '[class*="search"] [class*="result"]',
    '[class*="user"]',
    '[role="option"]',
    '[role="listitem"]',
]
