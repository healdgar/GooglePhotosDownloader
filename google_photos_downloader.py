import os
import time
import argparse
import logging
import pickle
from datetime import datetime
from dateutil.parser import parse
from concurrent.futures import ThreadPoolExecutor
import requests
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

class GooglePhotosDownloader:

    SCOPES = ['https://www.googleapis.com/auth/photoslibrary.readonly']

    def __init__(self, start_date, end_date, backup_path, num_workers=5):
        self.start_date = start_date
        self.end_date = end_date
        self.backup_path = backup_path
        self.num_workers = num_workers
        self.downloaded_count = 0
        self.skipped_count = 0  # Initialize the counter for skipped images
        self.failed_count = 0  # Initialize the counter for failed downloads

        # Create a session
        self.session = requests.Session()

        # OAuth setup
        creds = None
        token_path = 'token.pickle'
        
        # Load the token if it exists
        if os.path.exists(token_path):
            with open(token_path, 'rb') as token_file:
                creds = pickle.load(token_file)
        
        # If no valid token, then authenticate
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file('client_secrets.json', self.SCOPES)
                creds = flow.run_local_server(port=0)
            
            # Save the token for next run
            with open(token_path, 'wb') as token_file:
                pickle.dump(creds, token_file)

        self.photos_api = build('photoslibrary', 'v1', static_discovery=False, credentials=creds)
    
    def download_image(self, item):
        # Create a session for this thread
        session = requests.Session()

        # Delay based on the index of the item
        time.sleep(item['index'] * 0.6)  # sleep for index * 500 ms

        for _ in range(3):  # Retry up to 3 times
            try:
                request = self.photos_api.mediaItems().get(mediaItemId=item['id'])
                image = request.execute()
                image_url = image['baseUrl'] + '=d'  # '=d' to get the full resolution image
                response = session.get(image_url)

                # Get metadata
                filename = item['filename']
                creation_time_str = item['mediaMetadata']['creationTime']

                # Parse the creation time string into a datetime object
                creation_time = parse(creation_time_str)

                # Construct folder path
                folder = os.path.join(self.backup_path, str(creation_time.year), str(creation_time.month))
                os.makedirs(folder, exist_ok=True)

                # Construct file path
                file_path = os.path.join(folder, filename)

                # Check if file exists
                if os.path.exists(file_path):
                    logging.info(f"File {file_path} already exists, skipping")
                    self.skipped_count += 1  # Increment the skipped counter
                    return

                logging.info(f"Downloading {item['filename']}")

                # Save image
                with open(file_path, "wb") as f:
                    f.write(response.content)
    
                # Get file size
                file_size_bytes = os.path.getsize(file_path)
                file_size_kb = file_size_bytes / 1024
                file_size_mb = file_size_kb / 1024

                logging.info(f"Finished processing {file_path}, size: {file_size_mb:.2f} MB")
                self.downloaded_count += 1  # Increment the downloaded counter

                break  # If the download was successful, break the loop

            except requests.exceptions.RequestException as e:
                logging.error(f"Network error downloading {item['filename']}: {e}")
                self.failed_count += 1  # Increment the failed counter
                time.sleep(1)  # Wait for 1 second before retrying
            except Exception as e:
                logging.error(f"Error downloading {item['filename']}: {e}")
                self.failed_count += 1  # Increment the failed counter
                break  # If it's not a network error, don't retry

    def download_photos(self):
        # Parse date
        start_datetime = datetime.strptime(self.start_date, "%Y-%m-%d")
        end_datetime = datetime.strptime(self.end_date, "%Y-%m-%d")

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

        logging.info("Downloading media...")

        # Pagination 
        page_token = None

        while True:
            # API search
            results = self.photos_api.mediaItems().search(
                body={
                    'pageToken': page_token,
                    'filters': date_filter  
                } 
            ).execute()

            items = results.get('mediaItems')
            if not items:
                logging.info("No more results")
                break

            # Process each item
            with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
                # Add the index to each item
                items_with_index = [{'index': i, **item} for i, item in enumerate(items)]
                
                # Process each item
                for item in items_with_index:
                    executor.submit(self.download_image, item)

            # Next page
            page_token = results.get('nextPageToken')
            if not page_token:
                break  # If there's no next page, break the loop

            time.sleep(1)

        logging.info(f"Downloaded {self.downloaded_count} images between the dates of {self.start_date} and {self.end_date} to the {self.backup_path}.")  # Print tally report
        logging.info(f"Downloaded {self.downloaded_count} images, skipped {self.skipped_count} images, failed to download {self.failed_count} images.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Google Photos Downloader')
    parser.add_argument('--start_date', type=str, required=True, help='Start date in the format YYYY-MM-DD')
    parser.add_argument('--end_date', type=str, required=True, help='End date in the format YYYY-MM-DD')
    parser.add_argument('--backup_path', type=str, required=True, help='Path to the folder where you want to save the backup')
    parser.add_argument('--num_workers', type=int, default=5, help='Number of worker threads for downloading images')

    args = parser.parse_args()

    log_filename = os.path.join(args.backup_path, 'google_photos_downloader.log')
    logging.basicConfig(filename=log_filename, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    downloader = GooglePhotosDownloader(args.start_date, args.end_date, args.backup_path, args.num_workers)
    downloader.download_photos()
