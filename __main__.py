from distutils.command.config import LANG_EXT
from os import cpu_count, terminal_size
from akinator import Akinator
from telegram import Update ,InputMediaPhoto
from keyboard import AKI_LANG_BUTTON, AKI_LEADERBOARD_KEYBOARD, AKI_PLAY_KEYBOARD, AKI_WIN_BUTTON, CHILDMODE_BUTTON, START_KEYBOARD
from random import randint
from telegram.constants import ParseMode
from telegram.ext import CommandHandler,Application 
from telegram.ext import  CommandHandler, CallbackContext, CallbackQueryHandler
from config import BOT_TOKEN
import logging 
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


async def aki_start(update: Update, context: CallbackContext) -> None:
    #/start command.
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name
    last_name = update.effective_user.last_name
    user_name = update.effective_user.username
    #Adding user to the database.
    addUser(user_id, first_name, last_name, user_name)

    await update.message.reply_text(START_MSG.format(first_name), 
                              parse_mode=ParseMode.HTML, 
                              reply_markup=START_KEYBOARD)

async def aki_find(update: Update, context: CallbackContext) -> None:
        total_users = totalUsers()
        await update.message.reply_text(f"Users : {total_users}")
    





async def aki_me(update: Update, context: CallbackContext) -> None:
    #/me command
    user_id = update.effective_user.id
    profile_pic =( await  update.effective_user.get_profile_photos(limit=1)).photos
    if len(profile_pic) == 0:
        profile_pic = "https://telegra.ph/file/a65ee7219e14f0d0225a9.png"
    else:
        profile_pic = profile_pic[0][1]
    user = getUser(user_id)

    await update.message.reply_photo(photo= profile_pic, 
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

async def aki_lang(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    await update.message.reply_text(AKI_LANG_MSG.format(AKI_LANG_CODE[getLanguage(user_id)]),
                                parse_mode=ParseMode.HTML,
                                reply_markup=AKI_LANG_BUTTON)

async def aki_childmode(update: Update, context: CallbackContext) -> None:
    user_id =  update.effective_user.id
    status = "enabled" if getChildMode(user_id) else "disabled"
    await update.message.reply_text(
        text=CHILDMODE_MSG.format(status),
        parse_mode=ParseMode.HTML,
        reply_markup=CHILDMODE_BUTTON
    )

async def aki_set_child_mode(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    query = update.callback_query
    to_set = int(query.data.split('_')[-1])
    updateChildMode(user_id, to_set)
    await query.edit_message_text(f"Child mode is {'enabled' if to_set else 'disabled'} Successfully!")
    

async def aki_set_lang(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    lang_code = query.data.split('_')[-1]
    user_id = update.effective_user.id
    updateLanguage(user_id, lang_code)
    query.edit_message_text(f"Language Successfully changed to {AKI_LANG_CODE[lang_code]} !")
async def aki_play_cmd_handler(update: Update, context: CallbackContext) -> None:

    #/play command.

    user_id = update.effective_user.id
    aki = Akinator()

    msg = await update.message.reply_photo(
        photo=open('aki_pics/aki_01.png', 'rb'),
        caption="Loading..."
    )
    
    
    updateTotalGuess(user_id, total_guess=1)
    q = aki.start_game(language=getLanguage(user_id), child_mode=getChildMode(user_id))

    context.user_data[f"aki_{user_id}"] = aki 
    context.user_data[f"q_{user_id}"] = q
    context.user_data[f"ques_{user_id}"] = 1

    await msg.edit_caption(
        caption=q,
        reply_markup=AKI_PLAY_KEYBOARD
        )

async def aki_lead(update: Update, _:CallbackContext) -> None:
        await update.message.reply_text(
            text="Check Leaderboard on specific categories in Akinator.",
            reply_markup=AKI_LEADERBOARD_KEYBOARD
        )

async def get_lead_total(lead_list: list, lead_category: str) -> str:
    lead = f'Top 10 {lead_category} are :\n'
    for i in lead_list:
        lead = lead+f"{i[0]} : {i[1]}\n"
    return lead


async def del_data(context:CallbackContext, user_id: int):
    del context.user_data[f"q_{user_id}"]
    del context.user_data[f"aki_{user_id}"]


async def aki_play_callback_handler(update: Update, context:CallbackContext) -> None:
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
            await query.answer(text=AKI_FIRST_QUESTION, show_alert=True)
            return
        except akinator.exceptions.AkiTimedOut:
            await query.answer(text="Akinator timed out, please /play again", show_alert=True)
    else:
        try:
            q = aki.answer(a)
        except akinator.exceptions.AkiTimedOut:
            await query.answer(text="Akinator timed out, please /play again", show_alert=True)
        
    query.answer()
    if aki.progression < 80:
        await query.message.edit_media(
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
        await query.message.edit_media(
            InputMediaPhoto(media=aki['absolute_picture_path'],
            caption=f"It's {aki['name']} ({aki['description']})! Was I correct?"
            ),
            reply_markup=AKI_WIN_BUTTON
        )
        del_data(context, user_id)



async def aki_lead_cb_handler(update: Update, context:CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    data = query.data.split('_')[-1]

    if data == 'cguess':
        text =await  get_lead_total(getLead("correct_guess"), 'correct guesses')
        await query.edit_message_text(
            text= text,
            reply_markup=AKI_LEADERBOARD_KEYBOARD
        )
    elif data == 'tguess':
        text =await  get_lead_total(getLead("total_guess"), 'total guesses')
        await query.edit_message_text(
            text= text,
            reply_markup=AKI_LEADERBOARD_KEYBOARD
        )
    elif data == 'wguess':
        text =await  get_lead_total(getLead("wrong_guess"), 'wrong guesses')
        await query.edit_message_text(
            text= text,
            reply_markup=AKI_LEADERBOARD_KEYBOARD
        )
    elif data == 'tquestions':
        text = await get_lead_total(getLead("total_questions"), 'total questions')
        await query.edit_message_text(
            text= text,
            reply_markup=AKI_LEADERBOARD_KEYBOARD
        )

async def aki_win(update: Update, context: CallbackContext):
    user_id = update.effective_user.id
    query = update.callback_query
    ans = query.data.split('_')[-1]
    if ans =='y':
        await query.message.edit_media(
            InputMediaPhoto(
                media=open('aki_pics/aki_win.png', 'rb'),
                caption="gg!"
            )
        )
        updateCorrectGuess(user_id=user_id, correct_guess=1)
    else:
        await query.message.edit_media(
            InputMediaPhoto(
                media=open('aki_pics/aki_defeat.png', 'rb'),
                caption="bruh :("
            ),
            reply_markup=None
        )
        updateWrongGuess(user_id=user_id, wrong_guess=1)



def main():
    
    logging.basicConfig(
        filename='bot.log',
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',  
        level=logging.WARNING
        
    )
    try :
        
        dp = Application.builder().token(BOT_TOKEN).build()
        dp.add_handler(CommandHandler("start", aki_start))
        dp.add_handler(CommandHandler("find", aki_find))
        dp.add_handler(CommandHandler("me", aki_me))
        dp.add_handler(CommandHandler('language', aki_lang))
        dp.add_handler(CommandHandler('childmode', aki_childmode))
        dp.add_handler(CommandHandler('play', aki_play_cmd_handler))
        dp.add_handler(CommandHandler('leaderboard', aki_lead))
        dp.add_handler(CommandHandler('me', aki_me))
        
        
        dp.add_handler(CallbackQueryHandler(aki_win, pattern=r"aki_win_"))
        dp.add_handler(CallbackQueryHandler(aki_play_callback_handler, pattern=r"aki_play_"))
        dp.add_handler(CallbackQueryHandler(aki_set_child_mode, pattern=r"c_mode_"))
        dp.add_handler(CallbackQueryHandler(aki_set_lang, pattern=r"aki_set_lang_"))
        dp.add_handler(CallbackQueryHandler(aki_lead_cb_handler, pattern=r"aki_lead_"))
        dp.run_polling(allowed_updates=Update.ALL_TYPES)
        
    except Exception as e:
        logging.info(f"Error : {e}")

if __name__ == '__main__':
    main()
