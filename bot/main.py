import asyncio
import logging
import re
import os
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

# Глобальная переменная для отслеживания лога
last_log_offset = 0

async def log_monitor_task(bot: Bot):
    """Фоновая задача для отслеживания входа/выхода игроков"""
    global last_log_offset
    log_file = f"{utils.DATA_PATH}/logs/latest.log"
    
    # При запуске устанавливаем смещение на конец файла, чтобы не слать старые уведомления
    if os.path.exists(log_file):
        last_log_offset = os.path.getsize(log_file)
    
    while True:
        try:
            if os.path.exists(log_file):
                current_size = os.path.getsize(log_file)
                
                # Если файл был очищен или ротирован, сбрасываем смещение
                if current_size < last_log_offset:
                    last_log_offset = 0
                
                with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                    f.seek(last_log_offset)
                    lines = f.readlines()
                    last_log_offset = f.tell()
                    
                    for line in lines:
                        if "joined the game" in line:
                            # Format: [date time] [thread/level] [class]: Player joined the game
                            try:
                                # Split by the last ': ' to get the actual message
                                message = line.split(": ")[-1].strip()
                                player = message.split(" joined")[0].strip()
                            except IndexError:
                                player = "Игрок"
                            await bot.send_message(
                                ALLOWED_USERS[0], 
                                f"📥 <b>{player}</b> зашел на сервер!", 
                                parse_mode="HTML"
                            )
                        elif "left the game" in line:
                            # Format: [date time] [thread/level] [class]: Player left the game
                            try:
                                message = line.split(": ")[-1].strip()
                                player = message.split(" left")[0].strip()
                            except IndexError:
                                player = "Игрок"
                            await bot.send_message(
                                ALLOWED_USERS[0], 
                                f"📤 <b>{player}</b> вышел с сервера!", 
                                parse_mode="HTML"
                            )
        except Exception as e:
            logging.error(f"Log monitor error: {e}")
        
        await asyncio.sleep(10)

class WorldStates(StatesGroup):
    awaiting_name = State()

class WorldConfigStates(StatesGroup):
    awaiting_seed = State()
    awaiting_gamemode = State()
    awaiting_difficulty = State()
    awaiting_world_type = State()
    awaiting_pvp = State()
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
        types.InlineKeyboardButton(text="👥 Онлайн", callback_data="players_online"),
        types.InlineKeyboardButton(text="📊 Статистика", callback_data="stats_top")
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

@dp.callback_query(F.data == "stats_top")
async def handle_stats(callback: types.CallbackQuery):
    if not is_allowed(callback.from_user.id):
        return await callback.answer("🚫 Доступ запрещен.")
    
    stats = utils.get_world_stats()
    if not stats:
        return await callback.message.answer("📊 Статистика недоступна или пуста.")
    
    top_time = sorted(stats, key=lambda x: x['time'], reverse=True)[:5]
    top_deaths = sorted(stats, key=lambda x: x['deaths'], reverse=True)[:5]
    top_adv = sorted(stats, key=lambda x: x['advancements'], reverse=True)[:5]
    
    text = "🏆 <b>Топ игроков (по времени):</b>\n"
    for i, s in enumerate(top_time, 1):
        text += f"{i}. {s['name']} — {s['time'] // 3600}ч { (s['time'] // 60) % 60}м\n"
    
    text += "\n💀 <b>Топ по смертям:</b>\n"
    for i, s in enumerate(top_deaths, 1):
        text += f"{i}. {s['name']} — {s['deaths']} раз\n"

    text += "\n🌟 <b>Топ по достижениям:</b>\n"
    for i, s in enumerate(top_adv, 1):
        text += f"{i}. {s['name']} — {s['advancements']} шт.\n"
        
    await callback.message.answer(text, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "players_online")
async def handle_players(callback: types.CallbackQuery):
    if not is_allowed(callback.from_user.id):
        return await callback.answer("🚫 Доступ запрещен.")
    
    players = utils.get_online_players()
    # get_online_players возвращает строку с именами или "Игроков нет"
    # Если возвращает None, значит произошла ошибка выполнения команды
    if players is None:
        await callback.message.answer("👥 Не удалось получить список игроков (ошибка RCON).")
    else:
        await callback.message.answer(f"👥 Игроки в онлайне:\n{players}")
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
    
    builder.row(types.InlineKeyboardButton(text="➕ Создать", callback_data="world_create"),
                   types.InlineKeyboardButton(text="⚙️ Шаблон", callback_data="world_create_custom"))
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
        types.InlineKeyboardButton(text="👥 Онлайн", callback_data="players_online"),
        types.InlineKeyboardButton(text="📊 Статистика", callback_data="stats_top")
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

@dp.callback_query(F.data == "world_create_custom")
async def handle_custom_world_start(callback: types.CallbackQuery, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        return await callback.answer("🚫 Доступ запрещен.")
    
    await state.set_state(WorldConfigStates.awaiting_seed)
    
    builder = InlineKeyboardBuilder()
    builder.row(types.InlineKeyboardButton(text="🎲 Случайный", callback_data="set_seed_random"))
    
    await callback.message.answer("⚙️ Настройка новой карты\n\nВведите Seed или нажмите кнопку для случайного:", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "set_seed_random")
async def handle_seed_random(callback: types.CallbackQuery, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        return await callback.answer("🚫 Доступ запрещен.")
    
    await state.update_data(seed="random")
    await state.set_state(WorldConfigStates.awaiting_gamemode)
    
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="Survival", callback_data="set_gm_survival"),
        types.InlineKeyboardButton(text="Creative", callback_data="set_gm_creative"),
        types.InlineKeyboardButton(text="Adventure", callback_data="set_gm_adventure")
    )
    
    await callback.message.answer("Seed: random\n\nВыберите режим игры:", reply_markup=builder.as_markup())
    await callback.answer()

@dp.message(WorldConfigStates.awaiting_seed)
async def process_seed(message: types.Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        await state.clear()
        return await message.answer("🚫 Доступ запрещен.")
    
    await state.update_data(seed=message.text)
    await state.set_state(WorldConfigStates.awaiting_gamemode)
    
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="Survival", callback_data="set_gm_survival"),
        types.InlineKeyboardButton(text="Creative", callback_data="set_gm_creative"),
        types.InlineKeyboardButton(text="Adventure", callback_data="set_gm_adventure")
    )
    
    await message.answer("Выберите режим игры:", reply_markup=builder.as_markup())

@dp.message(WorldConfigStates.awaiting_gamemode)
async def process_gamemode(message: types.Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        await state.clear()
        return await message.answer("🚫 Доступ запрещен.")
    
    await state.update_data(gamemode=message.text.lower())
    await state.set_state(WorldConfigStates.awaiting_difficulty)
    await message.answer("Выберите сложность (`peaceful`, `easy`, `normal`, `hard`):")

@dp.message(WorldConfigStates.awaiting_difficulty)
async def process_difficulty(message: types.Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        await state.clear()
        return await message.answer("🚫 Доступ запрещен.")
    
    await state.update_data(difficulty=message.text.lower())
    await state.set_state(WorldConfigStates.awaiting_world_type)
    
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="Default", callback_data="set_wt_default"),
        types.InlineKeyboardButton(text="Flat", callback_data="set_wt_flat")
    )
    builder.row(
        types.InlineKeyboardButton(text="Large Biomes", callback_data="set_wt_large_biomes"),
        types.InlineKeyboardButton(text="Amplified", callback_data="set_wt_amplified")
    )
    
    await message.answer("Выберите тип генерации:", reply_markup=builder.as_markup())

@dp.message(WorldConfigStates.awaiting_world_type)
async def process_world_type(message: types.Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        await state.clear()
        return await message.answer("🚫 Доступ запрещен.")
    
    await state.update_data(world_type=message.text.lower())
    await state.set_state(WorldConfigStates.awaiting_pvp)
    
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="✅ Да", callback_data="set_pvp_true"),
        types.InlineKeyboardButton(text="❌ Нет", callback_data="set_pvp_false")
    )
    
    await message.answer("Разрешить PvP?", reply_markup=builder.as_markup())

@dp.message(WorldConfigStates.awaiting_pvp)
async def process_pvp(message: types.Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        await state.clear()
        return await message.answer("🚫 Доступ запрещен.")
    
    await state.update_data(pvp=message.text.lower())
    await state.set_state(WorldConfigStates.awaiting_name)
    await message.answer("Введите название (суффикс) для новой карты:")

@dp.message(WorldConfigStates.awaiting_name)
async def process_custom_name(message: types.Message, state: FSMContext):
    if not is_allowed(message.from_user.id):
        await state.clear()
        return await message.answer("🚫 Доступ запрещен.")
    
    data = await state.get_data()
    suffix = message.text
    if not re.match(r'^[a-zA-Z0-9_-]+$', suffix):
        return await message.answer("❌ Недопустимые символы. Используйте только A-Z, a-z, 0-9, _, -")
    
    diff_map = {"peaceful": "0", "easy": "1", "normal": "2", "hard": "3"}
    utils.update_server_property("level-seed", data['seed'])
    utils.update_server_property("gamemode", data['gamemode'])
    utils.update_server_property("difficulty", diff_map.get(data['difficulty'], "2"))
    utils.update_server_property("level-type", data['world_type'])
    utils.update_server_property("pvp", data['pvp'])
    
    success, name = utils.create_world(suffix)
    if success:
        await message.answer(f"✅ Карта {name} создана с заданными параметрами. Сервер перезагружается...")
    else:
        await message.answer("❌ Ошибка при создании карты.")
    
    await state.clear()

@dp.callback_query(F.data.startswith("set_gm_"))
async def handle_set_gamemode(callback: types.CallbackQuery, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        return await callback.answer("🚫 Доступ запрещен.")
    
    gm = callback.data.replace("set_gm_", "")
    await state.update_data(gamemode=gm)
    await state.set_state(WorldConfigStates.awaiting_difficulty)
    
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="Peaceful", callback_data="set_diff_peaceful"),
        types.InlineKeyboardButton(text="Easy", callback_data="set_diff_easy"),
        types.InlineKeyboardButton(text="Normal", callback_data="set_diff_normal"),
        types.InlineKeyboardButton(text="Hard", callback_data="set_diff_hard")
    )
    
    await callback.message.answer("Выберите сложность:", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("set_diff_"))
async def handle_set_difficulty(callback: types.CallbackQuery, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        return await callback.answer("🚫 Доступ запрещен.")
    
    diff = callback.data.replace("set_diff_", "")
    await state.update_data(difficulty=diff)
    await state.set_state(WorldConfigStates.awaiting_world_type)
    
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="Default", callback_data="set_wt_default"),
        types.InlineKeyboardButton(text="Flat", callback_data="set_wt_flat")
    )
    builder.row(
        types.InlineKeyboardButton(text="Large Biomes", callback_data="set_wt_large_biomes"),
        types.InlineKeyboardButton(text="Amplified", callback_data="set_wt_amplified")
    )
    
    await callback.message.answer("Выберите тип генерации:", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("set_wt_"))
async def handle_set_world_type(callback: types.CallbackQuery, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        return await callback.answer("🚫 Доступ запрещен.")
    
    wt = callback.data.replace("set_wt_", "")
    await state.update_data(world_type=wt)
    await state.set_state(WorldConfigStates.awaiting_pvp)
    
    builder = InlineKeyboardBuilder()
    builder.row(
        types.InlineKeyboardButton(text="✅ Да", callback_data="set_pvp_true"),
        types.InlineKeyboardButton(text="❌ Нет", callback_data="set_pvp_false")
    )
    
    await callback.message.answer("Разрешить PvP?", reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data.startswith("set_pvp_"))
async def handle_set_pvp(callback: types.CallbackQuery, state: FSMContext):
    if not is_allowed(callback.from_user.id):
        return await callback.answer("🚫 Доступ запрещен.")
    
    pvp = callback.data.replace("set_pvp_", "")
    await state.update_data(pvp=pvp)
    await state.set_state(WorldConfigStates.awaiting_name)
    await callback.message.answer("Введите название (суффикс) для новой карты:")
    await callback.answer()

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
    # Запускаем мониторинг логов в фоне
    asyncio.create_task(log_monitor_task(bot))
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
