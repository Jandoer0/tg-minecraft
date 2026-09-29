import asyncio
import logging
import re
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from config import TOKEN, ALLOWED_USERS
import utils

logging.basicConfig(level=logging.INFO)

bot = Bot(token=TOKEN)
dp = Dispatcher()

class WorldStates(StatesGroup):
    awaiting_name = State()

def is_allowed(user_id):
    return user_id in ALLOWED_USERS

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    if not is_allowed(message.from_user.id):
        return await message.answer("🚫 Доступ запрещен.")
    
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="🚀 Старт", callback_data="server_start"),
        types.InlineKeyboardButton(text="🛑 Стоп", callback_data="server_stop"),
        types.InlineKeyboardButton(text="🔄 Рестарт", callback_data="server_restart")
    )
    builder.row(
        types.InlineKeyboardButton(text="🌍 Карты", callback_data="worlds_list"),
        types.InlineKeyboardButton(text="👥 Онлайн", callback_data="players_online")
    )
    
    status = utils.get_server_status()
    status_text = "🟢 Запущен" if status == "active" else "🔴 Остановлен"
    
    await message.answer(
        f"🎮 <b>Управление Minecraft сервером</b>\n\n"
        f"Статус: {status_text}\n"
        f"Текущая карта: {utils.get_current_world()}",
        reply_markup=builder.as_markup(),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("server_"))
async def handle_server_action(callback: types.CallbackQuery):
    if not is_allowed(callback.from_user.id):
        return await callback.answer("🚫 Доступ запрещен.")
    
    action = callback.data.split("_")[1]
    
    try:
        await callback.answer(f"⏳ Выполняю {action}...")
    except Exception:
        pass
        
    success = utils.manage_server(action)
    
    if success:
        await callback.message.answer(f"✅ Команда {action} успешно выполнена.")
    else:
        await callback.message.answer(f"❌ Ошибка при выполнении команды {action}.")
    
    # Update main menu with current status
    await handle_main_menu(callback)

@dp.callback_query(F.data == "players_online")
async def handle_players(callback: types.CallbackQuery):
    if not is_allowed(callback.from_user.id):
        return await callback.answer("🚫 Доступ запрещен.")
    
    players = utils.get_online_players()
    if players:
        await callback.message.answer(f"👥 Игроки в онлайне:\n{players}")
    else:
        await callback.message.answer("👥 Сервер пуст или недоступен.")
    await callback.answer()

@dp.callback_query(F.data == "worlds_list")
async def handle_worlds(callback: types.CallbackQuery):
    if not is_allowed(callback.from_user.id):
        return await callback.answer("🚫 Доступ запрещен.")
    
    worlds = utils.get_worlds()
    if not worlds:
        return await callback.message.answer("🌍 Карт не найдено.")
    
    builder = InlineKeyboardBuilder()
    for world in worlds:
        prefix = "✅ " if world == utils.get_current_world() else ""
        builder.row(types.InlineKeyboardButton(text=f"{prefix}{world}", callback_data=f"world_select_{world}"))
    
    builder.row(types.InlineKeyboardButton(text="➕ Создать", callback_data="world_create"))
    builder.row(types.InlineKeyboardButton(text="🗑 Удалить", callback_data="world_delete"))
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="main_menu"))
    
    await callback.message.answer("🌍 Выберите карту:", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "main_menu")
async def handle_main_menu(callback: types.CallbackQuery):
    if not is_allowed(callback.from_user.id):
        return await callback.answer("🚫 Доступ запрещен.")
    
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="🚀 Старт", callback_data="server_start"),
        types.InlineKeyboardButton(text="🛑 Стоп", callback_data="server_stop"),
        types.InlineKeyboardButton(text="🔄 Рестарт", callback_data="server_restart")
    )
    builder.row(
        types.InlineKeyboardButton(text="🌍 Карты", callback_data="worlds_list"),
        types.InlineKeyboardButton(text="👥 Онлайн", callback_data="players_online")
    )
    status = utils.get_server_status()
    status_text = "🟢 Запущен" if status == "active" else "🔴 Остановлен"
    
    # If this is called from a callback, we try to edit. 
    # But to make it act like a 'new window', we can check if we should edit or send.
    try:
        await callback.message.edit_text(
            f"🎮 <b>Управление Minecraft сервером</b>\n\n"
            f"Статус: {status_text}\n"
            f"Текущая карта: {utils.get_current_world()}",
            reply_markup=builder.as_markup(),
            parse_mode="HTML"
        )
    except Exception as e:
        if "message is not modified" in str(e):
            pass
        else:
            # Fallback to sending a new message if editing fails
            await callback.message.answer(
                f"🎮 <b>Управление Minecraft сервером</b>\n\n"
                f"Статус: {status_text}\n"
                f"Текущая карта: {utils.get_current_world()}",
                reply_markup=builder.as_markup(),
                parse_mode="HTML"
            )
    await callback.answer()

@dp.callback_query(F.data.startswith("world_select_"))
async def handle_world_select(callback: types.CallbackQuery):
    if not is_allowed(callback.from_user.id):
        return await callback.answer("🚫 Доступ запрещен.")
    
    world_name = callback.data.replace("world_select_", "")
    if world_name == utils.get_current_world():
        return await callback.answer("Эта карта уже активна.")
    
    if utils.set_current_world(world_name):
        utils.manage_server("restart")
        await callback.message.answer(f"🌍 Карта изменена на {world_name}. Сервер перезагружается...")
    else:
        await callback.answer("❌ Ошибка при смене карты.", show_alert=True)
    await callback.answer()

@dp.callback_query(F.data == "world_create")
async def handle_world_create_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        return await callback.answer("🚫 Доступ запрещен.")
    
    await state.set_state(WorldStates.awaiting_name)
    await callback.message.answer("Введите название (суффикс) для новой карты (буквы, цифры, _ -):")
    await callback.answer()

@dp.message(WorldStates.awaiting_name)
async def handle_world_name_input(message: types.Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        await state.clear()
        return await message.answer("🚫 Доступ запрещен.")
    
    suffix = message.text
    if not re.match(r'^[a-zA-Z0-9_-]+$', suffix):
        return await message.answer("❌ Недопустимые символы. Используйте только A-Z, a-z, 0-9, _, -")
    
    success, name = utils.create_world(suffix)
    if success:
        await message.answer(f"✅ Карта {name} создана и активирована. Сервер перезагружается...")
    else:
        await message.answer("❌ Ошибка при создании карты.")
    
    await state.clear()

@dp.callback_query(F.data == "world_delete")
async def handle_world_delete_start(callback: types.CallbackQuery):
    if not is_allowed(callback.from_user.id):
        return await callback.answer("🚫 Доступ запрещен.")
    
    worlds = utils.get_worlds()
    if not worlds:
        return await callback.answer("Нет карт для удаления.")
    
    builder = InlineKeyboardBuilder()
    for world in worlds:
        if world == utils.get_current_world():
            continue
        builder.row(types.InlineKeyboardButton(text=f"🗑 {world}", callback_data=f"world_del_{world}"))
    
    builder.row(types.InlineKeyboardButton(text="⬅️ Назад", callback_data="worlds_list"))
    await callback.message.answer("Выберите карту для удаления:", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("world_del_"))
async def handle_world_del(callback: types.CallbackQuery):
    if not is_allowed(callback.from_user.id):
        return await callback.answer("🚫 Доступ запрещен.")
    
    world_name = callback.data.replace("world_del_", "")
    if utils.delete_world(world_name):
        await callback.message.answer(f"✅ Карта {world_name} удалена.")
    else:
        await callback.message.answer(f"❌ Ошибка при удалении карты {world_name}.", show_alert=True)
    await callback.answer()

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
