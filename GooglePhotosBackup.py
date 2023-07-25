# Imports
import os
import time
from datetime import datetime
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
import requests
import base64
from dateutil.parser import parse


# OAuth setup
SCOPES = ['https://www.googleapis.com/auth/photoslibrary.readonly']
flow = InstalledAppFlow.from_client_secrets_file('client_secrets.json', SCOPES)
creds = flow.run_local_server(port=0)

photos_api = build('photoslibrary', 'v1', static_discovery=False, credentials=creds)

# Helper functions
def download_image(id):
  request = photos_api.mediaItems().get(mediaItemId=id)
  image = request.execute()
  image_url = image['baseUrl'] + '=d'  # '=d' to get the full resolution image
  response = requests.get(image_url)
  return response.content

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
# Initialize counters
downloaded_files = 0
skipped_files = 0

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
    for item in items:
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
          continue # Skip download

        # Check if file already exists
        if os.path.exists(file_path):
            print(f"File {file_path} already exists, skipping")
            continue

        print(f"Downloading {item['filename']}")

        try:
            # Download image
            binary = download_image(item['id'])

            # Save image
            with open(file_path, "wb") as f:
                f.write(binary)

            # Increment downloaded files counter
            downloaded_files += 1

        except Exception as e:
            print(f"Error downloading {item['filename']}: {e}")

            # Increment skipped files counter
            skipped_files += 1

        print(f"Finished processing {file_path} (Downloaded: {downloaded_files}, Skipped: {skipped_files})")


        # Next page
        page_token = results.get('nextPageToken')
        time.sleep(1)

print("Backup completed!")
