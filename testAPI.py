import requests
import os
import time

# OAuth credentials 
CLIENT_ID = '106401500207-rl8m19lcerum3h4ljt238fqqhhk3bac3.apps.googleusercontent.com'
CLIENT_SECRET = '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'  

# Redirect URI for desktop app
REDIRECT_URI = 'urn:ietf:wg:oauth:2.0:oob'  

# Authorization and token URLs
AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URL = 'https://oauth2.googleapis.com/token'

# Set up auth URLs
client_id = CLIENT_ID
redirect_uri = REDIRECT_URI
auth_url = f'{AUTH_URL}?client_id={client_id}&redirect_uri={redirect_uri}&response_type=code&access_type=offline&scope=https://www.googleapis.com/auth/photoslibrary.readonly'

print('Please go to this URL and authorize:', auth_url)

# Get authorization code
code = input('Enter authorization code: ')

# Exchange code for access token
token_response = requests.post(TOKEN_URL, {
  'client_id': CLIENT_ID,
  'client_secret': CLIENT_SECRET,
  'redirect_uri': REDIRECT_URI,
  'grant_type': 'authorization_code',
  'code': code  
})

access_token = token_response.json()['access_token']
refresh_token = token_response.json()['refresh_token']

# Call API with access token
headers = {'Authorization': f'Bearer {access_token}'}

albums_url = 'https://photoslibrary.googleapis.com/v1/albums'
albums_response = requests.get(albums_url, headers=headers)

if albums_response.ok:
  # Process albums here
  print(albums_response.json())
else:
  print('Error fetching albums:', albums_response.status_code)

# Refresh access token after 1 hour
time.sleep(3600) 

refresh_response = requests.post(TOKEN_URL, {
  'client_id': CLIENT_ID,
  'client_secret': CLIENT_SECRET,
  'refresh_token': refresh_token,
  'grant_type': 'refresh_token'
})

access_token = refresh_response.json()['access_token']

# Make API call with refreshed token
headers = {'Authorization': f'Bearer {access_token}'} 
media_items_url = 'https://photoslibrary.googleapis.com/v1/mediaItems'
media_response = requests.get(media_items_url, headers=headers)

print(media_response.json())