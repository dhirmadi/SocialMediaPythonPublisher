import sys
import logging
import configparser
import dropbox
from dropbox.oauth import DropboxOAuth2FlowNoRedirect
from pprint import pprint

"""
Script to manage Dropbox OAuth2 authentication and update configuration.

This script facilitates OAuth2 authentication with Dropbox using the Dropbox SDK.
It reads configuration details from a specified INI file, including app key and secret,
and manages the OAuth2 flow to obtain a refresh token. The refresh token is then used
to create a Dropbox client instance, which can be used to interact with the Dropbox API.

Functions:
- start_initial_auth: Initiates the OAuth2 flow for Dropbox authentication.
- get_dropbox_client: Creates and returns a Dropbox client instance using the refresh token.
- update_config: Updates the configuration file with the latest refresh token.

Usage:
Ensure the script is run with the path to the configuration file as an argument:
    python script.py <path_to_config_file>
    
NOTE: Requires initial temporary DropBox API Key to create full key and refresh key
"""

# Setup basic logging
logging.basicConfig(level=logging.INFO)

def start_initial_auth(app_key, app_secret):
    try:
        #auth_flow = DropboxOAuth2FlowNoRedirect(app_key, app_secret)
        auth_flow = DropboxOAuth2FlowNoRedirect(app_key, use_pkce=True, token_access_type='offline')
        authorize_url = auth_flow.start()
        print("1. Go to: " + authorize_url)
        print("2. Click 'Allow' (you might have to log in first).")
        print("3. Copy the authorization code.")
        auth_code = input("Enter the authorization code here: ")
        oauth_result = auth_flow.finish(auth_code)
        return oauth_result
    except Exception as e:
        logging.error(f"Error during authentication: {e}")
        sys.exit(1)

def get_dropbox_client(app_key, app_secret, refresh_token):
    try:
        dbx = dropbox.Dropbox(oauth2_refresh_token=refresh_token, app_key=app_key, app_secret=app_secret)
        return dbx
    except Exception as e:
        logging.error(f"Error creating Dropbox client: {e}")
        sys.exit(1)

def update_config(config_file, section, refresh_token):
    config = configparser.ConfigParser()
    config.read(config_file)
    config.set(section, 'db_refresh', refresh_token)
    with open(config_file, 'w') as configfile:
        config.write(configfile)

def main(config_file):
    config = configparser.ConfigParser()
    config.read(config_file)
    app_key = config.get('Dropbox', 'db_app')
    app_secret = config.get('Dropbox', 'db_key')
    refresh_token = config.get('Dropbox', 'db_refresh', fallback='')

    if not refresh_token:
        oauth_result = start_initial_auth(app_key, app_secret)
        refresh_token=oauth_result.refresh_token
        pprint(vars(oauth_result))

    dbx = get_dropbox_client(app_key, app_secret, refresh_token)
    # You can now use `dbx` to interact with the Dropbox API.

    update_config(config_file, 'Dropbox', refresh_token)
    logging.info("Configuration updated with the new refresh token.")
    pprint(vars(dbx))

if __name__ == "__main__":
    if len(sys.argv) < 2:
        logging.error("Usage: python script.py <path_to_config_file>")
        sys.exit(1)
    config_file_path = sys.argv[1]
    main(config_file_path)
