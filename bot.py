from requests import get
import telegram
import telegram.bot
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Updater, CommandHandler,
                          MessageHandler, Filters, CallbackQueryHandler)
from telegram.ext.dispatcher import run_async
import logging
from functools import wraps
from datetime import datetime, date
from secrets import bottoken, port, admins, channel
import json

import pickle
import os.path
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

ip = get('https://api.ipify.org').text
try:
    certfile = open("cert.pem")
    keyfile = open("private.key")
    certfile.close()
    keyfile.close()
except IOError:
    from OpenSSL import crypto
    key = crypto.PKey()
    key.generate_key(crypto.TYPE_RSA, 2048)
    cert = crypto.X509()
    cert.get_subject().CN = ip
    cert.set_serial_number(1000)
    cert.gmtime_adj_notBefore(0)
    cert.gmtime_adj_notAfter(10*365*24*60*60)
    cert.set_issuer(cert.get_subject())
    cert.set_pubkey(key)
    cert.sign(key, 'sha256')
    with open("cert.pem", "wt") as certfile:
        certfile.write(crypto.dump_certificate(
            crypto.FILETYPE_PEM, cert).decode('ascii'))
    with open("private.key", "wt") as keyfile:
        keyfile.write(crypto.dump_privatekey(
            crypto.FILETYPE_PEM, key).decode('ascii'))

logging.basicConfig(filename='debug.log', filemode='a+', format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.DEBUG)
logger = logging.getLogger(__name__)

bot = telegram.Bot(token=bottoken)


declaration = '''_You declare that you:_
a. have not visited China or come into contact with anyone in quarantine/Leave of Absence during last 14 days
b. do not have a fever (temperature >37.5)
c. do not have respiratory symptoms (e.g. cough/runny nose/sore throat/difficulty in breathing)

Please *DO NOT* click Check In until instructed to so at the YF temperature screening station.'''


def adminonly(func):
    @wraps(func)
    def wrapped(update, context, *args, **kwargs):
        user_id = str(update.effective_user.id)
        if user_id in admins:
            return func(update, context, *args, **kwargs)
        else:
            update.message.reply_text(
                '`Admin Only`', parse_mode=telegram.ParseMode.MARKDOWN)
    return wrapped


def loader():
    global users
    try:
        with open('users.json') as usersfile:
            users = json.load(usersfile)
    except:
        with open('users.json', 'w+'):
            users = {}
    global checkin
    try:
        with open('checkin.json') as checkinfile:
            checkin = json.load(checkinfile)
    except:
        with open('checkin.json', 'w+'):
            checkin = {}
    global checkout
    try:
        with open('checkout.json') as checkoutfile:
            checkout = json.load(checkoutfile)
    except:
        with open('checkout.json', 'w+'):
            checkout = {}


@adminonly
def new(update, context):
    today = date.today().strftime('%d %b %Y')
    global checkin
    checkin[today] = {}
    checkout[today] = {}
    with open('checkin.json', 'w') as checkinfile:
        json.dump(checkin, checkinfile)
    with open('tracing.txt', 'a+') as tracing:
        tracing.write('\n' + today + '\n')
    msg = '*YF Contact Tracing* ({})\n\n{}\n\n_0 checked in_\n_0 checked out_'.format(
        today, declaration)
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton('CHECK IN', callback_data='checkin')],
         [InlineKeyboardButton('CHECK OUT', callback_data='checkout')]])
    bot.send_message(chat_id=channel, reply_markup=keyboard, text=msg,
                     parse_mode=telegram.ParseMode.MARKDOWN)


@run_async
def start(update, context):
    id = str(update.message.chat_id)
    if id in users or id.startswith('-'):
        update.message.reply_text(
            '_You are already registered_', parse_mode=telegram.ParseMode.MARKDOWN)
        return
    msg = 'First, I need your contact number. Please press the *REGISTER* button below.'
    contact_keyboard = telegram.KeyboardButton(
        text="REGISTER", request_contact=True)
    keyboard = telegram.ReplyKeyboardMarkup([[contact_keyboard]])
    bot.send_message(chat_id=channel, reply_markup=keyboard,
                     text=msg, parse_mode=telegram.ParseMode.MARKDOWN)


@run_async
def contact(update, context):
    global users
    user_id = str(update.effective_user.id)
    contact = update.message.contact
    phone = contact.phone_number
    if user_id != str(contact.user_id):
        update.message.reply_text(
            "Verification failed. Your ID does not match.", reply_markup=telegram.ReplyKeyboardRemove())
    elif phone.startswith('+65') or phone.startswith('65'):
        phone = phone.lstrip('+65')
        users[user_id] = {}
        users[user_id]['phone'] = phone
        with open('users.json', 'w') as userfile:
            json.dump(users, userfile)
        msg = 'Next, please send me your full name.'
        update.message.reply_text(msg, parse_mode=telegram.ParseMode.MARKDOWN,
                                  reply_markup=telegram.ReplyKeyboardRemove())
    else:
        update.message.reply_text(
            "Sorry, you are not permitted to enter at this time.", reply_markup=telegram.ReplyKeyboardRemove())


@run_async
def fullname(update, context):
    global users
    user_id = str(update.effective_user.id)
    message = update.message.text
    count = message.count(' ')
    if user_id not in users:
        return
    if count < 1:
        update.message.reply_text("Is that your full name? Please try again.")
    else:
        users[user_id]['name'] = message
        with open('users.json', 'w') as userfile:
            json.dump(users, userfile)
        update.message.reply_text(
            "Thank you. Your details are saved and will be used for future check-ins.")
        update.message.reply_text(
            "Please return to @YFAnnouncements to complete your check-in.")


def callbackquery(update, context):
    query = update.callback_query
    data = query.data
    user_id = str(query.from_user.id)
    global users
    if user_id not in users:
        context.bot.answer_callback_query(
            query.id, url='t.me/lifeyf_bot?start=1')
        return
    global checkin
    global checkout
    if data == 'checkin':
        now = datetime.now().strftime('%H:%M:%S')
        today = date.today().strftime('%d %b %Y')
        name = users[user_id]['name']
        v1 = name
        v2 = users[user_id]['phone']
        v3 = now
        v4 = ''
        if name in checkin[today]:
            context.bot.answer_callback_query(
                query.id, text='Error: you are already checked in.', show_alert=True)
            with open('tracing.txt', 'a+') as tracing:
                tracing.write(v1 + ',' + v2 + ',' + v3 + ',' +
                              v4 + ',Temporary / Duplicate' + '\n')
            sheetappend([date, v1, v2, v3, v4, 'Temporary / Duplicate'])
            return
        checkin[today][name] = now
        with open('checkin.json', 'w') as checkinfile:
            json.dump(checkin, checkinfile)
        with open('tracing.txt', 'a+') as tracing:
            tracing.write(v1 + ',' + v2 + ',' + v3 +
                          ',' + v4 + ',Temporary' + '\n')
        sheetappend([date, v1, v2, v3, v4, 'Temporary'])
        context.bot.answer_callback_query(
            query.id, text='Welcome, {}!'.format(name), show_alert=True)
        countin = str(len(checkin[today]))
        countout = str(len(checkout[today]))
        msg = '*YF Contact Tracing* ({})\n\n{}\n\n_{} checked in_\n_{} checked out'.format(
            today, declaration, countin, countout)
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton('CHECK IN', callback_data='checkin')],
             [InlineKeyboardButton('CHECK OUT', callback_data='checkout')]])
        bot.edit_message_text(
            chat_id=channel,
            message_id=query.message.message_id,
            text=msg,
            reply_markup=keyboard,
            parse_mode=telegram.ParseMode.MARKDOWN
        )
    elif data == 'checkout':
        now = datetime.now().strftime('%H:%M:%S')
        today = date.today().strftime('%d %b %Y')
        name = users[user_id]['name']
        if name not in checkin[today]:
            context.bot.answer_callback_query(
                query.id, text='Error: you are not checked in.', show_alert=True)
        v1 = name
        v2 = users[user_id]['phone']
        v3 = checkin[today][name]
        v4 = now
        if name in checkout[today]:
            context.bot.answer_callback_query(
                query.id, text='Error: you are already checked out.', show_alert=True)
            with open('tracing.txt', 'a+') as tracing:
                tracing.write(v1 + ',' + v2 + ',' + v3 + ',' +
                              v4 + ',Duplicate' + '\n')
            sheetappend([date, v1, v2, v3, v4, 'Duplicate'])
            return
        checkout[today][name] = now
        with open('checkout.json', 'w') as checkoutfile:
            json.dump(checkout, checkoutfile)
        with open('tracing.txt', 'a+') as tracing:
            tracing.write(v1 + ',' + v2 + ',' + v3 +
                          ',' + v4 + ',Temporary' + '\n')
        sheetappend([date, v1, v2, v3, v4, 'Temporary'])
        context.bot.answer_callback_query(
            query.id, text='Goodbye, {}!'.format(name), show_alert=True)
        countin = str(len(checkin[today]))
        countout = str(len(checkout[today]))
        msg = '*YF Contact Tracing* ({})\n\n{}\n\n_{} checked in_\n_{} checked out'.format(
            today, declaration, countin, countout)
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton('CHECK IN', callback_data='checkin')],
             [InlineKeyboardButton('CHECK OUT', callback_data='checkout')]])
        bot.edit_message_text(
            chat_id=channel,
            message_id=query.message.message_id,
            text=msg,
            reply_markup=keyboard,
            parse_mode=telegram.ParseMode.MARKDOWN
        )
    else:
        context.bot.answer_callback_query(
            query.id, url='t.me/lifeyf_bot?start=1')
    return


@run_async
def sheetappend(values):
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    service = build('sheets', 'v4', credentials=creds)

    spreadsheet_id = '1JBVKfcF_CDZiYVJv5nN10XdLh32VRUiUW4TAvOwni4o'
    range_ = 'A1'
    value_input_option = 'RAW'
    insert_data_option = 'INSERT_ROWS'

    value_range_body = {
        'values': [values]
    }

    request = service.spreadsheets().values().append(spreadsheetId=spreadsheet_id, range=range_,
                                                     valueInputOption=value_input_option, insertDataOption=insert_data_option, body=value_range_body)
    response = request.execute()
    return response


def main():
    updater = Updater(token=bottoken, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("new", new))
    dp.add_handler(MessageHandler(Filters.contact, contact))
    dp.add_handler(MessageHandler(Filters.text, fullname))
    dp.add_handler(CallbackQueryHandler(callbackquery))

    loader()

    # updater.start_polling()
    updater.start_webhook(listen='0.0.0.0',
                          port=port,
                          url_path=bottoken,
                          key='private.key',
                          cert='cert.pem',
                          webhook_url='https://{}:{}/{}'.format(ip, port, bottoken))

    print("Bot is running. Press Ctrl+C to stop.")
    updater.idle()
    print("Bot stopped successfully.")


if __name__ == '__main__':
    main()
