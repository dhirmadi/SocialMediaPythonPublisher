# SocialMediaPythonPublisher
 A Python script running as a cron job takes an image from a folder and publishes it to various channels. Using AI(replicate and chatGPT) to create image descriptions and taglines to automate the process of publishing to social media.

 Command line/Cron entry: python /path/to/script/py_rotator_daily.py /path/to/config/configfilename.ini

Current channels supported
- Instagram
- Telegram
- email

  To install
  - create new Python virtual environment
  - run 'pip install -r requirements.txt' to get the required libraries for your python environment
  - configure your .env file with the required keys for Dropbox, chatGPT etc using dotenv.example as a blueprint (make sure you got your temporary dropbox token
  - configure the socialmedia.ini.example to create your config file
  - run py_db_auth with config file to setup dropbox authentication

    To test
     run python /path/to/script/py_rotator_daily.py /path/to/config/configfilename.ini manually to see if it ges desired result (i recomend setting an email you can receive emails to as and set all other channels to false, until you are know you get the emails sent)

  - Configure your cron job
 
 how it works
 The script takes an image from a folder in your Dropbox and sends it to the Replicate service, evaluating what is on the picture. The resulting text is sent to chatGPT to create a caption.
 Now, the image, caption, and hashtags from the config file are used to publish the selected image to the channels according to your configuration file.

 When all is done, the image is moved into the folder/archive folder so it's not used again any time soon
  
