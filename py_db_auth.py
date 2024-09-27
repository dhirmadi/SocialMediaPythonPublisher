import sys
import logging
import dropbox
from dropbox.oauth import DropboxOAuth2FlowNoRedirect
from dotenv import load_dotenv, set_key, dotenv_values
import os
from pprint import pprint

# Setup basic logging
logging.basicConfig(level=logging.INFO)

# Load environment variables from the .env file
def load_env(env_file):
    load_dotenv(env_file)
    return dotenv_values(env_file)

def update_env(env_file, key, value):
    set_key(env_file, key, value)

def start_initial_auth(app_key, app_secret):
    try:
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

def main(env_file):
    # Load environment variables from the .env file
    env_vars = load_env(env_file)

    app_key = env_vars.get('DROPBOX_APP_KEY')
    app_secret = env_vars.get('DROPBOX_APP_PASSWORD')
    refresh_token = env_vars.get('DROPBOX_REFRESH_TOKEN', '')

    if not app_key or not app_secret:
        logging.error("Dropbox app key and secret are required in the .env file.")
        sys.exit(1)

    if not refresh_token:
        oauth_result = start_initial_auth(app_key, app_secret)
        refresh_token = oauth_result.refresh_token
        pprint(vars(oauth_result))

        # Update the .env file with the new refresh token
        update_env(env_file, 'DROPBOX_REFRESH_TOKEN', refresh_token)

    dbx = get_dropbox_client(app_key, app_secret, refresh_token)
    
    # Use the dbx client for Dropbox operations here

    logging.info("Configuration updated with the new refresh token.")
    pprint(vars(dbx))

if __name__ == "__main__":
    if len(sys.argv) < 2:
        logging.error("Usage: python script.py <path_to_env_file>")
        sys.exit(1)
    env_file_path = sys.argv[1]
    main(env_file_path)
