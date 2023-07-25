# Imports
import os
import time
from datetime import datetime
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
import requests

from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.ssl_ import create_urllib3_context
from urllib3 import PoolManager
from dateutil.parser import parse
from concurrent.futures import ThreadPoolExecutor
import ssl

class SSLAdapter(HTTPAdapter):
    def init_poolmanager(self, connections, maxsize, block=False):
        self.poolmanager = PoolManager(num_pools=connections,
                                       maxsize=maxsize,
                                       block=block,
                                       ssl_version=ssl.PROTOCOL_TLS,
                                       ssl_context=create_urllib3_context())

# Create a session
s = requests.Session()

# Mount it for both http and https usage
adapter = SSLAdapter()
s.mount("http://", adapter)
s.mount("https://", adapter)

# OAuth setup
SCOPES = ['https://www.googleapis.com/auth/photoslibrary.readonly']
flow = InstalledAppFlow.from_client_secrets_file('client_secrets.json', SCOPES)
creds = flow.run_local_server(port=0)

photos_api = build('photoslibrary', 'v1', static_discovery=False, credentials=creds)

# Helper functions
def download_image(item, backup_path):
  try:
    request = photos_api.mediaItems().get(mediaItemId=item['id'])
    image = request.execute()
    image_url = image['baseUrl'] + '=d'  # '=d' to get the full resolution image
    response = s.get(image_url)

    # Get metadata
    filename = item['filename']
    creation_time_str = item['mediaMetadata']['creationTime']

    # Parse the creation time string into a datetime object
    creation_time = parse(creation_time_str)

    # Construct folder path
    folder = f"{backup_path}/{creation_time.year}/{creation_time.month}"
    os.makedirs(folder, exist_ok=True)

    # Construct file path
    file_path = f"{folder}/{filename}"

    # Check if file exists
    if os.path.exists(file_path):
      print(f"File {file_path} already exists, skipping")
      return

    print(f"Downloading {item['filename']}")

    # Save image
    with open(file_path, "wb") as f:
        f.write(response.content)

    print(f"Finished processing {file_path}")

  except Exception as e:
    print(f"Error downloading {item['filename']}: {e}")

# User input
print("Enter start date (YYYY-MM-DD):")
start_date = input()
print("Enter end date (YYYY-MM-DD):")
end_date = input()
print("Enter the path to the folder where you want to save the backup:")
backup_path = input()

# Parse date
start_datetime = datetime.strptime(start_date, "%Y-%m-%d")
end_datetime = datetime.strptime(end_date, "%Y-%m-%d")

# Construct date filter
date_filter = {
  "dateFilter": {
    "ranges": [
      {
        "startDate": {
          "year": start_datetime.year,
          "month": start_datetime.month,
          "day": start_datetime.day
        },
        "endDate": {
          "year": end_datetime.year,
          "month": end_datetime.month,
          "day": end_datetime.day
        }
      }
    ]
  }
}

print("Downloading media...")

# Pagination 
page_token = None

while True:
    # API search
    results = photos_api.mediaItems().search(
        body={
            'pageToken': page_token,
            'filters': date_filter  
        } 
    ).execute()

    # Print page token
    print(f"Page token: {results.get('nextPageToken')}")

    # Update page token
    page_token = results.get('nextPageToken')

    items = results.get('mediaItems')
    if not items:
        print("No more results")
        break
    
    # Process each item
    with ThreadPoolExecutor(max_workers=5) as executor:
        executor.map(download_image, items, [backup_path]*len(items))

    # Next page
    page_token = results.get('nextPageToken')
    time.sleep(1)

print("Backup completed!")
