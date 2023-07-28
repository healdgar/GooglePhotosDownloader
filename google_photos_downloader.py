import os
import json
import ssl
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
from datetime import timezone
from datetime import timedelta
from dateutil.tz import tzlocal
from dateutil.tz import tzutc

class GooglePhotosDownloader:
    SCOPES = ['https://www.googleapis.com/auth/photoslibrary.readonly']

    def __init__(self, start_date, end_date, backup_path, num_workers=5, checkpoint_interval=25):
        self.start_date = start_date
        self.end_date = end_date
        self.backup_path = backup_path
        self.num_workers = num_workers
        self.downloaded_count = 0
        self.skipped_count = 0
        self.failed_count = 0
        self.total_file_size = 0
        self.failed_items = []
        self.skipped_items = []
        
        self.downloaded_items_path = os.path.join(self.backup_path, 'DownloadItems.json')
        if os.path.exists(self.downloaded_items_path):
            with open(self.downloaded_items_path, 'r') as f:
                self.downloaded_items = json.load(f)
        else:
            self.downloaded_items = []

        self.session = requests.Session()

        creds = None
        token_path = 'token.pickle'

       
        if os.path.exists(token_path):
            with open(token_path, 'rb') as token_file:
                creds = pickle.load(token_file)
        
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file('client_secrets.json', self.SCOPES)
                creds = flow.run_local_server(port=0)
            
            with open(token_path, 'wb') as token_file:
                pickle.dump(creds, token_file)

        self.photos_api = build('photoslibrary', 'v1', static_discovery=False, credentials=creds)
        logging.info("Connected to Google server.")

        self.checkpoint_interval = checkpoint_interval
        self.all_media_items = []  # Initialize all_media_items as an empty list

    def get_all_media_items(self):
        # Load existing media items
        self.all_media_items_path = os.path.join(self.backup_path, 'DownloadItems.json')
        if os.path.exists(self.all_media_items_path):
            with open(self.all_media_items_path, 'r') as f:
                self.all_media_items = json.load(f)
        else:
            self.all_media_items = []

        # Convert existing items to a dictionary for easy lookup
        existing_items_dict = {item['id']: item for item in self.all_media_items}

        # Convert the start and end dates to UTC
        start_datetime = datetime.strptime(self.start_date, "%Y-%m-%d").replace(tzinfo=tzutc())
        end_datetime = datetime.strptime(self.end_date, "%Y-%m-%d").replace(tzinfo=tzutc())

        # Filter out any items that are outside the date range
        self.all_media_items = [item for item in self.all_media_items if start_datetime <= datetime.strptime(item['mediaMetadata']['creationTime'], "%Y-%m-%dT%H:%M:%S%z") <= end_datetime]
  
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

        page_token = None

        while True:
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

            for item in items:
                if item['id'] not in existing_items_dict:
                    item['status'] = 'not downloaded'
                    self.all_media_items.append(item)
                    print(f"Added item with ID {item['id']} to all_media_items")

            page_token = results.get('nextPageToken')
            if not page_token:
                logging.info("No more pages")
                break

        self.save_lists_to_file(self.all_media_items)

    def get_all_downloaded_filepaths(self):
        # Generate a list of all filepaths in the backup folder
        all_downloaded_filepaths = []
        for root_subdir in os.listdir(self.backup_path):
            root_subdir_path = os.path.join(self.backup_path, root_subdir)
            if os.path.isdir(root_subdir_path):  # ensure that root_subdir is a directory
                for dirpath, dirnames, filenames in os.walk(root_subdir_path):
                    for filename in filenames:
                        filepath = os.path.join(dirpath, filename)
                        all_downloaded_filepaths.append(filepath)

        # For each downloaded file, add file_path and file_size to the JSON record if they are missing
        for filepath in all_downloaded_filepaths:
            filename = os.path.basename(filepath)
            for item in self.all_media_items:
                try:
                    item_filename = item['filename']
                except TypeError:
                    print(f"TypeError for item: {item}")
                if item_filename == filename:
                    # Construct the presumed file path
                    creation_time = parse(item['mediaMetadata']['creationTime'])
                    print(f"filepath filter Creation time: {creation_time}")
                    presumed_filepath = os.path.join(self.backup_path, str(creation_time.year), str(creation_time.month), filename)
                    print(f"Presumed filepath: {presumed_filepath}")

                    # Normalize and compare the presumed and actual file paths
                    if os.path.normpath(presumed_filepath) == os.path.normpath(filepath):
                        item['file_path'] = filepath  # Update file_path in item
                        item['file_size'] = os.path.getsize(filepath)  # Update file_size in item
                        item['status'] = 'verified'  # Set status to 'verified'

        return all_downloaded_filepaths


    def save_lists_to_file(self, all_items):
        logging.info("Starting to save lists to file...")

        if os.access(self.downloaded_items_path, os.W_OK):
            # Load existing items
            if os.path.exists(self.downloaded_items_path):
                with open(self.downloaded_items_path, 'r') as f:
                    existing_items = json.load(f)
            else:
                existing_items = []

            # Convert existing items to a dictionary for easy lookup
            existing_items_dict = {item['id']: item for item in existing_items}

            # Update existing items and append new ones
            for item in all_items:
                if item['id'] in existing_items_dict:
                    existing_items_dict[item['id']].update(item)  # Update existing item
                else:
                    existing_items.append(item)  # Append new item

            # Write the updated items back to the file
            with open(self.downloaded_items_path, 'w') as f:
                json.dump(existing_items, f, indent=4)

            logging.info("Successfully saved lists to file.")
        else:
            logging.error(f"No write access to the file: {self.downloaded_items_path}")

    def download_image(self, item):
        logging.info(f"considering {item['filename']}...")

        # Parse the creation time
        creation_time = parse(item['mediaMetadata']['creationTime']).astimezone(tzlocal())
        print(f"Creation time: {creation_time}")

        # Convert the start and end dates to UTC
        start_datetime = datetime.strptime(self.start_date, "%Y-%m-%d").replace(tzinfo=tzutc())
        end_datetime = datetime.strptime(self.end_date, "%Y-%m-%d").replace(tzinfo=tzutc()) + timedelta(days=1, seconds=-1)

        # Convert the creation time to UTC
        creation_time_utc = creation_time.astimezone(tzutc())

        # Skip the download if the item was already downloaded or if it's verified or if its outside the date range
        if item['status'] == 'downloaded' or item['status'] == 'verified' or creation_time_utc < start_datetime or creation_time_utc > end_datetime:
            
            return

        session = requests.Session()
        for _ in range(3):
            try:
                logging.info("About to make request to Google Photos API...")
                filename = item['filename']
                request = self.photos_api.mediaItems().get(mediaItemId=item['id'])
                image = request.execute()
                logging.info("Request to Google Photos API completed.")

                if 'video' in item['mimeType']:  # Check if 'video' is in mimeType
                    image_url = image['baseUrl'] + '=dv'
                else:
                    image_url = image['baseUrl'] + '=d'

                logging.info(f"Attempting to download {filename}...")  # Log a message before the download attempt
                response = session.get(image_url, stream=True)
                logging.info(f"Download attempt finished. Status code: {response.status_code}")  # Log a message after the download attempt

                creation_time_str = item['mediaMetadata']['creationTime']
                creation_time = parse(creation_time_str)
                folder = os.path.join(self.backup_path, str(creation_time.year), str(creation_time.month))
                os.makedirs(folder, exist_ok=True)
                file_path = os.path.join(folder, filename)

                # Check if the file exists in the current folder
                if os.path.exists(file_path):
                    item['status'] = 'verified'
                    logging.info(f"File {filename} already exists in path, verified")
                    # Add the item to the all_media_items list if it's not already there
                    if item not in self.all_media_items:
                        self.all_media_items.append(item)
                        print(f"Added {filename} to all_media_items")
                    break  # break the loop when file already exists
                else:    
                    with open(file_path, "wb") as f:
                        f.write(response.content)

                    item['file_path'] = file_path  # record the file path
                    item['file_size'] = os.path.getsize(file_path)  # record the file size
                    item['status'] = 'downloaded'  # record the status
                    print(f"Downloaded {file_path}")

                    break
            except requests.exceptions.RequestException as e:
                item['status'] = 'failed'
                logging.error(f"RequestException occurred while trying to get {image_url}: {e}")
                time.sleep(1)
            except ssl.SSLError as e:
                item['status'] = 'failed'
                logging.error(f"SSLError occurred while trying to get {image_url}: {e}")
                time.sleep(1)
            except Exception as e:
                item['status'] = 'failed'
                logging.error(f"An unexpected error occurred: {e}")
                break

    def download_photos(self, all_media_items):
        print(f"Number of items in all_media_items: {len(all_media_items)}")
        print(f"Statuses of items in all_media_items: {[item['status'] for item in all_media_items]}")

        try:
            logging.info("Downloading media...")

            with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
                executor.map(self.download_image, all_media_items)

        except Exception as e:
            logging.error(f"An unexpected error occurred in download_photos: {e}")
        finally:
            logging.info(f"threads complete...")

    def report_stats(self):
        now = datetime.now(timezone.utc)
        total_size = 0
        total_files = 0
        recent_files = 0
        recent_size = 0
        status_counts = {}
        with open(self.downloaded_items_path, 'r') as f:
            all_items = json.load(f)
            for item in all_items:
                total_files += 1
                total_size += item.get('file_size', 0)
                creation_time = datetime.strptime(item['mediaMetadata']['creationTime'], "%Y-%m-%dT%H:%M:%S%z")
                if (now - creation_time).days <= 7:
                    recent_files += 1
                    recent_size += item.get('file_size', 0)
                status = item.get('status', 'unknown')
                status_counts[status] = status_counts.get(status, 0) + 1
        print(f"Total files: {total_files}")
        print(f"Total size: {total_size / (1024 * 1024):.2f} MB")
        print(f"Files added in the last 7 days: {recent_files}")
        print(f"Size of files added in the last 7 days: {recent_size / (1024 * 1024):.2f} MB")
        print("File status counts:")
        for status, count in status_counts.items():
            print(f"  {status}: {count}")


if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(description='Google Photos Downloader')
        parser.add_argument('--start_date', type=str, required=True, help='Start date in the format YYYY-MM-DD')
        parser.add_argument('--end_date', type=str, required=True, help='End date in the format YYYY-MM-DD')
        parser.add_argument('--backup_path', type=str, required=True, help='Path to the folder where you want to save the backup')
        parser.add_argument('--num_workers', type=int, default=5, help='Number of worker threads for downloading images')
        parser.add_argument('--refresh_index', action='store_true', help='Refresh the index by fetching a new one from the server')

        args = parser.parse_args()

        log_filename = os.path.join(args.backup_path, 'google_photos_downloader.log')
        logging.basicConfig(filename=log_filename, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(formatter)
        logging.getLogger().addHandler(console_handler)

        downloader = GooglePhotosDownloader(args.start_date, args.end_date, args.backup_path, args.num_workers)
        downloader.get_all_downloaded_filepaths()  

        if args.refresh_index:
            downloader.get_all_media_items()
        else:
            downloader.all_media_items = json.load(open(downloader.downloaded_items_path, 'r'))

        downloader.download_photos(downloader.all_media_items)
        downloader.save_lists_to_file(downloader.all_media_items)
        downloader.report_stats()

    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
