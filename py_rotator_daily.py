import os
import sys
import random
import asyncio
import logging
import smtplib
import traceback
from typing import Any
from dotenv import load_dotenv
import dropbox
import replicate
import openai
import telegram
import configparser
from instagrapi import Client
from PIL import Image
from PIL.Image import Resampling
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage


"""
Script for managing social media content automation.

This script integrates with various APIs (Dropbox, OpenAI, Telegram, Email, Instagram, etc.) 
to automate the processing and distribution of social media content. It reads configuration 
from a specified INI file, interacts with Dropbox for image storage, utilizes AI for content 
generation, and posts content to Telegram, Email, and Instagram based on configuration settings.

Functions:
- read_config: Reads configuration variables from environment variables and INI file.
- query_openai: Queries OpenAI API to generate captions based on given prompts.
- list_images_in_dropbox: Asynchronously lists images from Dropbox folder.
- download_image_from_dropbox: Asynchronously downloads images from Dropbox.
- get_temp_link: Retrieves temporary links for images stored in Dropbox.
- resize_image: Resizes images using PIL library.
- archive_image: Archives images on Dropbox after successful distribution.
- send_email: Sends emails with attached images.
- post_image_to_instagram: Posts images and captions to Instagram.
- send_telegram_message: Sends images and captions to Telegram.

Usage:
Ensure the script is run with the path to the configuration file as an argument:
    python script_name.py <config_file>
"""

def read_config(configfile):
    """Reads configuration variables from environment variables and INI file."""
    configuration = configparser.ConfigParser()
    configuration.read(configfile)
    return {
        'db_token': os.getenv('DROPBOX_TOKEN'),
        'db_refresh': os.getenv('DROPBOX_REFRESH_TOKEN'),
        'db_app': os.getenv('DROPBOX_APP_KEY'),
        'db_app_pw': os.getenv('DROPBOX_APP_PASSWORD'),
        'bot_token': os.getenv('TELEGRAM_BOT_TOKEN'),
        'chat_id': os.getenv('TELEGRAM_CHANNEL_ID'),
        'image_folder': configuration['Dropbox']['image_folder'],
        'archive_folder': 'archive',
        'instaname': configuration['Instagram']['name'],
        'instaword': os.getenv('INSTA_PASSWORD'),
        'email_recipient': configuration['Email']['recipient'],
        'email_sender': configuration['Email']['sender'],
        'email_password': os.getenv('EMAIL_PASSWORD'),
        'hashtag_string': configuration['Content']['hashtag_string'],
        'run_archive': configuration['Content'].getboolean('archive'),
        'run_telegram': configuration['Content'].getboolean('telegram'),
        'run_instagram': configuration['Content'].getboolean('instagram'),
        'run_fetlife': configuration['Content'].getboolean('fetlife'),
        'run_debug': configuration['Content'].getboolean('debug'),
        'openai_api_key': os.getenv('OPENAI_API_KEY'),
        'openai_engine': configuration['openAI']['engine'],
        'openai_systemcontent': configuration['openAI']['systemcontent'],
        'openai_rolecontent': configuration['openAI']['rolecontent'],
        'replicate_model': configuration['Replicate']['model']
    }


def query_openai(prompt, engine, api_key,systemcontent,rolecontent):
    client = openai.OpenAI(api_key=api_key)
    try:
        response = client.chat.completions.create(
            messages=[
                {"role": "system", "content": systemcontent},
                {"role": "user", "content": rolecontent + " " + prompt}
            ],
            model=engine
        )
        return response.choices[0].message.content
    except openai.APIError as e:
        logging.error(f"An error occurred: {e}")
        return []


async def list_images_in_dropbox(dbx, path):
    try:
        # Adjust path for Dropbox API requirements
        if path == "/":
            dbx_path = ""
        else:
            dbx_path = path
        return [entry.name for entry in dbx.files_list_folder(dbx_path).entries if
                isinstance(entry, dropbox.files.FileMetadata)]
    except dropbox.exceptions.ApiError as e:
        logging.error(f"Dropbox API error: {e}")
        return []


async def download_image_from_dropbox(dbx, path, image_name):
    try:
        _, res = dbx.files_download(os.path.join(path, image_name))
        image_file = os.path.join('/tmp', image_name)
        with open(image_file, "wb") as f:
            f.write(res.content)
        return image_file
    except dropbox.exceptions.ApiError as e:
        logging.error(f"Dropbox download error: {e}")
        return None


def get_temp_link(dbx, path, image_name):
    """Create a shared link for the file and return the URL."""
    try:
        shared_link_metadata = dbx.files_get_temporary_link(os.path.join(path, image_name))
        return shared_link_metadata.link
    except dropbox.exceptions.ApiError as err:
        logging.error(f"Dropbox API Error getting temporary link: {err}")
        return None


def resize_image(image_file):
    with Image.open(image_file) as img:
        width, height = img.size
        new_width = min(width, 1280)
        new_height = int((new_width / width) * height)
        resized_img = img.resize((new_width, new_height), resample=Resampling.LANCZOS)
        resized_file = os.path.join(os.path.dirname(image_file), f"resized_{os.path.basename(image_file)}")
        resized_img.save(resized_file)

        return resized_file


def archive_image(dbx, image_folder_path, selected_image_name, archive_folder_path):
    try:
        image_file_path = os.path.join(image_folder_path, selected_image_name)
        archive_file_path = os.path.join(image_folder_path, archive_folder_path, selected_image_name)
        logging.info(f"Moving {image_file_path} to  {archive_file_path}")
        dbx.files_move_v2(image_file_path, archive_file_path)
    except dropbox.exceptions.ApiError as e:
        logging.error(f"Dropbox file move error: {e}")


async def send_email(image_file, message, email_config):
    msg = MIMEMultipart()
    msg['Subject'] = message
    msg['From'] = email_config['email_sender']
    msg['To'] = email_config['email_recipient']

    with open(image_file, 'rb') as f:
        img_data = f.read()
        image = MIMEImage(img_data, name=os.path.basename(image_file))
        msg.attach(image)

    text = MIMEText(message)
    msg.attach(text)

    try:
        smtp_server = smtplib.SMTP('smtp.gmail.com', 587)
        smtp_server.starttls()
        smtp_server.login(email_config['email_sender'], email_config['email_password'])
        smtp_server.sendmail(email_config['email_sender'], email_config['email_recipient'], msg.as_string())
        smtp_server.quit()
        logging.info(f"Email sent successfully to {email_config['email_recipient']}")
    except Exception as e:
        logging.error(f"Failed to send email: {e}")


async def post_image_to_instagram(username, password, image_path, caption):
    client = Client()
    client.login(username, password)

    # Post the image
    try:
        media = client.photo_upload(image_path, caption)
        print(f"Successfully posted: {media.model_dump()}")
    except Exception as e:
        print(f"An error occurred: {e}")


async def send_telegram_message(bot_token, chat_id, image_file, message):
    try:
        with open(image_file, 'rb') as f:
            bot = telegram.Bot(token=bot_token)
            await bot.send_photo(chat_id=chat_id, photo=f, caption=message)
    except Exception as e:
        logging.error(f"Failed to send Telegram message: {e}")


def get_dropbox_client(configfile):
    # return dropbox.Dropbox(config['db_token'])
    return dropbox.Dropbox(oauth2_refresh_token=configfile['db_refresh'], app_key=configfile['db_app'])


async def main(configfile):
    logging.basicConfig(level=logging.INFO)

    # Read configuration
    load_dotenv()
    configuration: dict[str | Any, str | int | Any] = read_config(configfile)

    # Setting up run variables
    run_archive = configuration.get('run_archive')
    run_telegram = configuration.get('run_telegram')
    run_instagram: bool = configuration.get('run_instagram')
    run_fetlife: bool = configuration.get('run_fetlife')
    run_debug: bool = configuration.get('run_debug')

    # ====================================content preparations==========================================================

    # Initialize Dropbox client
    dbx = get_dropbox_client(configuration)
    image_folder = configuration['image_folder']

    # List images from Dropbox
    image_names = await list_images_in_dropbox(dbx, image_folder)
    if not image_names:
        logging.error("No image files found in Dropbox. Exiting.")
        return

    # Select a random image and download it
    selected_image_name = random.choice(image_names)
    image_file = await download_image_from_dropbox(dbx, image_folder, selected_image_name)
    if not image_file:
        logging.error(f"Failed to download image {selected_image_name} from Dropbox. Exiting.")
        return

    # get temporary downloadable link for Replicate
    # path_image_name = image_folder + '/'+random.choice(image_names)
    temp_image_link = get_temp_link(dbx, image_folder, selected_image_name)
    if run_debug:  # debugging
        print("Temporary Dropbox Link :" + temp_image_link)

    # get mood description of image
    mood = replicate.run(
        configuration['replicate_model'],
        input={
            "image": temp_image_link,
            "caption": False,
            "question": "What is the mood for this image?",
            "temperature": 1,
            "use_nucleus_sampling": False
        }
    )

    # get caption for image
    caption = replicate.run(
        configuration['replicate_model'],
        input={
            "image": temp_image_link,
            "caption": True,
            "question": "What is the mood for this image?",
            "temperature": 1,
            "use_nucleus_sampling": False
        }
    )

    image_summary = caption + ' ' + mood
    if run_debug:
        print("Image Summary:" + image_summary)

    # get caption from openAI API and append the basic hashtags
    caption = query_openai(image_summary, configuration['openai_engine'], configuration['openai_api_key'],configuration['openai_systemcontent'],configuration['openai_rolecontent'],)
    message = caption.strip('"') + ' ' + configuration['hashtag_string']

    if run_debug:
        print("Message :" + message)

    # ====================================Social media channels=========================================================
    telegram_sent: bool = False
    email_sent: bool = False
    instagram_sent: bool = False
    # Send the image to the Telegram channel
    if run_telegram:
        try:
            if run_debug:
                print("Sending Telegram:"+message)
            resized_image_file = resize_image(image_file)  # resize the image for telegram
            await send_telegram_message(configuration['bot_token'], configuration['chat_id'], resized_image_file, message)
            telegram_sent = True
        except Exception as e:
            logging.error(f"Failed to send Telegram message: {e}")
            traceback.print_exc()

    # Send the image as an email attachment
    if run_fetlife:
        try:
            if run_debug:
                print("Sending Mail:"+message)
            await send_email(image_file, message, configuration)
            email_sent = True
        except Exception as e:
            logging.error(f"Failed to send email: {e}")

            # Send the image as an email attachment
    if run_instagram:
        try:
            if run_debug:
                print("Sending Instagram:"+message)
            await post_image_to_instagram(configuration['instaname'], configuration['instaword'], image_file, message)
            instagram_sent = True
        except Exception as e:
            logging.error(f"Failed to post to instagram: {e}")

    # ====================================Closing/Archiving============================================================================

    # Only archive the image if both Telegram and Email were sent successfully
    if (telegram_sent or email_sent or instagram_sent) and not run_debug:
        if run_archive:
            try:
                archive_image(dbx, configuration['image_folder'], selected_image_name, configuration['archive_folder'])
                logging.info("Image archived successfully.")
            except Exception as e:
                logging.error(f"Failed to archive image: {e}")
    else:
        logging.info("No active output channel selected. No need to archive image")


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python py_rotato_daily.py /path/to/<config_file>")
        sys.exit(1)

    config_file = sys.argv[1]
    config = read_config(config_file)
    asyncio.run(main(config_file))
