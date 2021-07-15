from os import cpu_count, terminal_size
import akinator
from telegram.files.inputmedia import InputMediaPhoto
from random import randint
from pprint import pprint
from keyboard import AKI_LANG_BUTTON, AKI_LEADERBOARD_KEYBOARD, AKI_PLAY_KEYBOARD, AKI_WIN_BUTTON, CHILDMODE_BUTTON, START_KEYBOARD
from telegram import Update, ParseMode
from telegram.ext import Updater, CommandHandler, CallbackContext, CallbackQueryHandler
from config import BOT_TOKEN
from database import (
    addUser, 
    getChildMode, 
    getCorrectGuess, 
    getLanguage, 
    getLead, 
    getTotalGuess, 
    getTotalQuestions, 
    getUnfinishedGuess, 
    getUser, getWrongGuess, 
    totalUsers, 
    updateChildMode, 
    updateCorrectGuess, 
    updateLanguage, 
    updateTotalGuess, 
    updateTotalQuestions, 
    updateWrongGuess)

from strings import AKI_FIRST_QUESTION, AKI_LANG_CODE, AKI_LANG_MSG, CHILDMODE_MSG, ME_MSG, START_MSG
import akinator


def aki_start(update: Update, context: CallbackContext) -> None:
    #/start command.
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name
    last_name = update.effective_user.last_name
    user_name = update.effective_user.username
    #Adding user to the database.
    addUser(user_id, first_name, last_name, user_name)
    update.message.reply_text(START_MSG.format(first_name), 
                              parse_mode=ParseMode.HTML, 
                              reply_markup=START_KEYBOARD)


def aki_find(update: Update, context: CallbackContext) -> None:
    total_users = totalUsers()
    update.message.reply_text(f"Users : {total_users}")


def aki_play_cmd_handler(update: Update, context: CallbackContext) -> None:
    #/play command.
    aki = akinator.Akinator()
    user_id = update.effective_user.id
    msg = update.message.reply_photo(
        photo=open('aki_pics/aki_01.png', 'rb'),
        caption="Loading..."
    )
    updateTotalGuess(user_id, total_guess=1)
    q = aki.start_game(language=getLanguage(user_id), child_mode=getChildMode(user_id))
    context.user_data[f"aki_{user_id}"] = aki
    context.user_data[f"q_{user_id}"] = q
    context.user_data[f"ques_{user_id}"] = 1
    msg.edit_caption(
        caption=q,
        reply_markup=AKI_PLAY_KEYBOARD
        )


def aki_play_callback_handler(update: Update, context:CallbackContext) -> None:
    user_id = update.effective_user.id
    aki = context.user_data[f"aki_{user_id}"]
    q = context.user_data[f"q_{user_id}"]
    updateTotalQuestions(user_id, 1)
    query = update.callback_query
    a = query.data.split('_')[-1]
    if a == '5':
        updateTotalQuestions(user_id, -1)
        try:
            q = aki.back()
        except akinator.exceptions.CantGoBackAnyFurther:
            query.answer(text=AKI_FIRST_QUESTION, show_alert=True)
            return
    else:
        q = aki.answer(a)
    query.answer()
    if aki.progression < 80:
        query.message.edit_media(
            InputMediaPhoto(
                open(f'aki_pics/aki_0{randint(1,5)}.png', 'rb'),
                caption=q,
            ),
            reply_markup=AKI_PLAY_KEYBOARD
        )
        context.user_data[f"aki_{user_id}"] = aki
        context.user_data[f"q_{user_id}"] = q
    else:
        aki.win()
        aki = aki.first_guess
        if aki['picture_path'] == 'none.jpg':
            aki['absolute_picture_path'] = open('aki_pics/none.jpg', 'rb')
        query.message.edit_media(
            InputMediaPhoto(media=aki['absolute_picture_path'],
            caption=f"It's {aki['name']} ({aki['description']})! Was I correct?"
            ),
            reply_markup=AKI_WIN_BUTTON
        )
        del_data(context, user_id)


def aki_win(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    query = update.callback_query
    ans = query.data.split('_')[-1]
    if ans =='y':
        query.message.edit_media(
            InputMediaPhoto(
                media=open('aki_pics/aki_win.png', 'rb'),
                caption="gg!"
            ),
            reply_markup=None
        )
        updateCorrectGuess(user_id=user_id, correct_guess=1)
    else:
        query.message.edit_media(
            InputMediaPhoto(
                media=open('aki_pics/aki_defeat.png', 'rb'),
                caption="bruh :("
            ),
            reply_markup=None
        )
        updateWrongGuess(user_id=user_id, wrong_guess=1)


def aki_me(update: Update, context: CallbackContext) -> None:
    #/me command
    user_id = update.effective_user.id
    profile_pic = update.effective_user.get_profile_photos(limit=1).photos
    if len(profile_pic) == 0:
        profile_pic = "https://telegra.ph/file/a65ee7219e14f0d0225a9.png"
    else:
        profile_pic = profile_pic[0][1]
    user = getUser(user_id)
    update.message.reply_photo(photo= profile_pic, 
                               caption=ME_MSG.format(user["first_name"], 
                                                     user["user_name"], 
                                                     user["user_id"],
                                                     AKI_LANG_CODE[user["aki_lang"]],
                                                     "Enabled" if getChildMode(user_id) else "Disabled",
                                                     getTotalGuess(user_id),
                                                     getCorrectGuess(user_id),
                                                     getWrongGuess(user_id),
                                                     getUnfinishedGuess(user_id),
                                                     getTotalQuestions(user_id),
                                                     ),
                               parse_mode=ParseMode.HTML)


def aki_set_lang(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    lang_code = query.data.split('_')[-1]
    user_id = update.effective_user.id
    updateLanguage(user_id, lang_code)
    query.edit_message_text(f"Language Successfully changed to {AKI_LANG_CODE[lang_code]} !")


def aki_lang(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    update.message.reply_text(AKI_LANG_MSG.format(AKI_LANG_CODE[getLanguage(user_id)]),
                                parse_mode=ParseMode.HTML,
                                reply_markup=AKI_LANG_BUTTON)


def aki_childmode(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    status = "enabled" if getChildMode(user_id) else "disabled"
    update.message.reply_text(
        text=CHILDMODE_MSG.format(status),
        parse_mode=ParseMode.HTML,
        reply_markup=CHILDMODE_BUTTON
    )


def aki_set_child_mode(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    query = update.callback_query
    to_set = int(query.data.split('_')[-1])
    updateChildMode(user_id, to_set)
    query.edit_message_text(f"Child mode is {'enabled' if to_set else 'disabled'} Successfully!")


def del_data(context:CallbackContext, user_id: int):
    del context.user_data[f"aki_{user_id}"]
    del context.user_data[f"q_{user_id}"]


def aki_lead(update: Update, _:CallbackContext) -> None:
    update.message.reply_text(
        text="Check Leaderboard on specific categories in Akinator.",
        reply_markup=AKI_LEADERBOARD_KEYBOARD
    )


def get_lead_total(lead_list: list, lead_category: str) -> str:
    lead = f'Top 10 {lead_category} are :\n'
    for i in lead_list:
        lead = lead+f"{i[0]} : {i[1]}\n"
    return lead


def aki_lead_cb_handler(update: Update, context:CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    data = query.data.split('_')[-1]
    #print(data)
    if data == 'cguess':
        text = get_lead_total(getLead("correct_guess"), 'correct guesses')
        query.edit_message_text(
            text= text,
            reply_markup=AKI_LEADERBOARD_KEYBOARD
        )
    elif data == 'tguess':
        text = get_lead_total(getLead("total_guess"), 'total guesses')
        query.edit_message_text(
            text= text,
            reply_markup=AKI_LEADERBOARD_KEYBOARD
        )
    elif data == 'wguess':
        text = get_lead_total(getLead("wrong_guess"), 'wrong guesses')
        query.edit_message_text(
            text= text,
            reply_markup=AKI_LEADERBOARD_KEYBOARD
        )
    elif data == 'tquestions':
        text = get_lead_total(getLead("total_questions"), 'total questions')
        query.edit_message_text(
            text= text,
            reply_markup=AKI_LEADERBOARD_KEYBOARD
        )



def main():
    updater = Updater(token=BOT_TOKEN)
    dp = updater.dispatcher
    dp.add_handler(CommandHandler('start', aki_start, run_async=True))
    dp.add_handler(CommandHandler('find', aki_find, run_async=True))
    dp.add_handler(CommandHandler('me', aki_me, run_async=True))
    dp.add_handler(CommandHandler('play', aki_play_cmd_handler, run_async=True))
    dp.add_handler(CommandHandler('language', aki_lang, run_async=True))
    dp.add_handler(CommandHandler('childmode', aki_childmode, run_async=True))
    dp.add_handler(CommandHandler('leaderboard', aki_lead, run_async=True))

    dp.add_handler(CallbackQueryHandler(aki_set_lang, pattern=r"aki_set_lang_", run_async=True))
    dp.add_handler(CallbackQueryHandler(aki_set_child_mode, pattern=r"c_mode_", run_async=True))
    dp.add_handler(CallbackQueryHandler(aki_play_callback_handler, pattern=r"aki_play_", run_async=True))
    dp.add_handler(CallbackQueryHandler(aki_win, pattern=r"aki_win_", run_async=True))
    dp.add_handler(CallbackQueryHandler(aki_lead_cb_handler, pattern=r"aki_lead_", run_async=True))

    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
