import os
import concurrent.futures
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

        self.files_dict = {}

        if os.path.exists(self.downloaded_items_path):
            with open(self.downloaded_items_path, 'r') as f:
                self.downloaded_items = json.load(f)
                for item in self.downloaded_items:
                    if 'filename' in item and 'id' in item and 'mediaMetadata' in item:
                        if item['filename'] not in self.files_dict:
                            self.files_dict[item['filename']] = []
                        self.files_dict[item['filename']].append((item['id'], item['mediaMetadata']))
        
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

    def save_lists_to_file(self):
        logging.info("Starting to save lists to file...")

        downloaded_items_list = [{'status': 'downloaded', **item} for item in self.downloaded_items]
        skipped_items_list = [{'status': 'skipped', **item} for item in self.skipped_items]
        failed_items_list = [{'status': 'failed', **item} for item in self.failed_items]

        all_items_list = downloaded_items_list + skipped_items_list + failed_items_list

        existing_items_dict = {}
        if os.path.isfile(self.downloaded_items_path):
            with open(self.downloaded_items_path, 'r') as f:
                existing_items_list = json.load(f)
                existing_items_dict = {item['id']: item for item in existing_items_list}
        else:
            with open(self.downloaded_items_path, 'w') as f:
                f.write("[]")

        for item in all_items_list:
            if item['id'] in existing_items_dict:
                if existing_items_dict[item['id']]['status'] == 'failed' and item['status'] == 'downloaded':
                    existing_items_dict[item['id']] = item
            else:
                existing_items_dict[item['id']] = item

        updated_items_list = list(existing_items_dict.values())

        if os.access(self.downloaded_items_path, os.W_OK):
            with open(self.downloaded_items_path, 'w') as f:
                json.dump(updated_items_list, f, indent=4)
                    
            logging.info("Successfully saved lists to file.")
        else:
            logging.error(f"No write access to the file: {self.downloaded_items_path}")

      
    def identify_missing_files(self):
        try:
            with open(self.downloaded_items_path, 'r') as f:
                downloaded_items = json.load(f)
        except Exception as e:
            logging.error(f"Error reading downloaded items JSON: {e}")
            return []

        if not downloaded_items:
            logging.info("No downloaded items found.")  
            return []

        downloaded_item_ids = set(item['id'] for item in downloaded_items)

        current_items = []

        # Pagination logic to retrieve all items
        request = self.photos_api.mediaItems().list()
        while request is not None:
            response = request.execute()
            current_items.extend(response.get('mediaItems', []))
            request = self.photos_api.mediaItems().list_next(request, response)

        missing_items = [item for item in current_items 
                        if item['id'] not in downloaded_item_ids]

        if not missing_items:
            logging.info("No missing items found.")

        return missing_items
        
    def download_image(self, item):
        downloaded_item_ids = [item['id'] for item in self.downloaded_items]
        skipped_item_ids = [item['id'] for item in self.skipped_items]
        if item['id'] in downloaded_item_ids or item['id'] in skipped_item_ids:
            logging.info(f"Item {item['filename']} already downloaded or skipped and logged to JSON, skipping")
            return

        if item['filename'] in self.files_dict:
            for existing_id, existing_metadata in self.files_dict[item['filename']]:
                if existing_id != item['id']:
                    if existing_metadata == item['mediaMetadata']:
                        logging.info(f"Duplicate file found with different ID but same metadata: {item['filename']}")
                    else:
                        logging.info(f"Duplicate file found with different ID and different metadata: {item['filename']}")
                    # Add more code here to handle the situation as you see fit.
            if item['id'] not in skipped_item_ids:
                self.skipped_count += 1
                self.skipped_items.append(item)
            return


        session = requests.Session()

        time.sleep(item['index'] * 1)

        for _ in range(3):
            try:
                request = self.photos_api.mediaItems().get(mediaItemId=item['id'])
                image = request.execute()
                image_url = image['baseUrl'] + '=d'
                response = session.get(image_url)

                filename = item['filename']
                creation_time_str = item['mediaMetadata']['creationTime']

                creation_time = parse(creation_time_str)

                folder = os.path.join(self.backup_path, str(creation_time.year), str(creation_time.month))
                os.makedirs(folder, exist_ok=True)

                file_path = os.path.join(folder, filename)

                if os.path.exists(file_path):
                    logging.info(f"File {file_path} already exists in path, skipping")
                    self.skipped_count += 1
                    if item['id'] not in skipped_item_ids:
                        self.skipped_items.append(item)
                    break  # break the loop when file already exists
                else:    
                    with open(file_path, "wb") as f:
                        f.write(response.content)

                    file_size_bytes = os.path.getsize(file_path)
                    file_size_kb = file_size_bytes / 1024
                    file_size_mb = file_size_kb / 1024
                    self.total_file_size += file_size_mb

                    logging.info(f"Finished downloading {file_path}, size: {file_size_mb:.2f} MB")
                    self.downloaded_count += 1
                    self.downloaded_items.append(item)

                    break
            except requests.exceptions.RequestException as e:
                logging.error(f"Network error downloading {item['filename']}: {e}")
                self.failed_count += 1
                self.failed_items.append(item)
                time.sleep(1)
            except ssl.SSLError as e:
                logging.error(f"SSL error downloading {item['filename']}: {e}")
                self.failed_count += 1
                self.failed_items.append(item)
                time.sleep(1)
            except Exception as e:
                logging.error(f"Unhandled exception in download_image: {e}")
                self.failed_count += 1
                self.failed_items.append(item)
                break

        total_processed = self.downloaded_count + self.skipped_count + self.failed_count
        if total_processed > 0 and total_processed % self.checkpoint_interval == 0:
            logging.info(f"{total_processed} items processed, performing checkpoint...")
            self.save_lists_to_file()
            self.cleanup()

    def cleanup(self):
        try:
            logging.info("Starting cleanup...")
            
            if os.access(self.downloaded_items_path, os.R_OK):
                with open(self.downloaded_items_path, 'r') as f:
                    items = json.load(f)

                items_dict = {item['id']: item for item in items}
                deduplicated_items_list = list(items_dict.values())

                with open(self.downloaded_items_path, 'w') as f:
                    json.dump(deduplicated_items_list, f, indent=4)

                logging.info("Finished cleanup.")
            else:
                logging.error(f"No read access to the file: {self.downloaded_items_path}")

        except Exception as e:
            logging.error(f"Error in cleanup: {e}")
            logging.debug(f"Downloaded items: {self.downloaded_items}")
            logging.debug(f"Skipped items: {self.skipped_items}")
            logging.debug(f"Failed items: {self.failed_items}")
            raise

    def download_photos(self):
        try:
            start_datetime = datetime.strptime(self.start_date, "%Y-%m-%d")
            end_datetime = datetime.strptime(self.end_date, "%Y-%m-%d")

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

                with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
                    items_with_index = [{'index': i, **item} for i, item in enumerate(items)]
                                    
                    futures = []
                    for item in items_with_index:
                        futures.append(executor.submit(self.download_image, item))

                    concurrent.futures.wait(futures)

                    for future in concurrent.futures.as_completed(futures):
                        total_processed = self.downloaded_count + self.skipped_count + self.failed_count
                        if total_processed > 0 and total_processed % self.checkpoint_interval == 0:
                            logging.info(f"Total processed: {total_processed}, checkpoint interval: {self.checkpoint_interval}")
                            logging.info(f"{total_processed} items processed, performing checkpoint...")
                            self.save_lists_to_file()
                            self.cleanup() 
                              
                   
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
            for item in self.all_media_items.values():
                try:
                    item_filename = item['filename']
                except TypeError:
                    print(f"TypeError for item: {item}")
                if item_filename == filename:
                    # Construct the presumed file path
                    creation_time = parse(item['mediaMetadata']['creationTime'])
                    print(f"filepath filter Creation time: {creation_time}")
                    #the below line will be updated to reflect the new filename+last 10 digits of id format
                    presumed_filepath = os.path.join(self.backup_path, str(creation_time.year), str(creation_time.month), filename)
                    print(f"Presumed filepath: {presumed_filepath}")

                    # Normalize and compare the presumed and actual file paths
                    if os.path.normpath(presumed_filepath) == os.path.normpath(filepath):
                        item['file_path'] = filepath  # Update file_path in item
                        item['file_size'] = os.path.getsize(filepath)  # Update file_size in item
                        item['status'] = 'verified'  # Set status to 'verified'
                    else:
                        item['status'] = 'missing'  # Set status to 'missing'              

        return all_downloaded_filepaths


    def save_lists_to_file(self, all_items):
        logging.info("Starting to save lists to file...")

        if os.access(self.downloaded_items_path, os.W_OK):
            # Load existing items
            if os.path.exists(self.downloaded_items_path):
                with open(self.downloaded_items_path, 'r') as f:
                    existing_items_dict = {item['id']: item for item in json.load(f)}
            else:
                existing_items_dict = {}

            # Update existing items and append new ones
            for item in all_items.values():
                if item['id'] in existing_items_dict:
                    existing_items_dict[item['id']].update(item)  # Update existing item
                else:
                    existing_items_dict[item['id']] = item  # Append new item

            # Write the updated items back to the file
            with open(self.downloaded_items_path, 'w') as f:
                json.dump(list(existing_items_dict.values()), f, indent=4)

            logging.info("Successfully saved lists to file.")
        else:
            logging.error(f"No write access to the file: {self.downloaded_items_path}")


    def download_image(self, item):
        logging.info(f"considering {item['filename']}...")
        logging.info(f"MimeType: {item['mimeType']}")

        # Parse the creation time
        creation_time = parse(item['mediaMetadata']['creationTime']).astimezone(tzlocal())
        logging.info(f"Creation time: {creation_time}")

        # Convert the start and end dates to UTC
        start_datetime = datetime.strptime(self.start_date, "%Y-%m-%d").replace(tzinfo=tzutc())
        end_datetime = datetime.strptime(self.end_date, "%Y-%m-%d").replace(tzinfo=tzutc()) + timedelta(days=1, seconds=-1)
        logging.info(f"Start datetime: {start_datetime}")
        logging.info(f"End datetime: {end_datetime}")

        # Convert the creation time to UTC
        creation_time_utc = creation_time.astimezone(tzutc())

        # Skip the download if the item was already downloaded or if it's verified or if its outside the date range
        if item['status'] == 'downloaded' or item['status'] == 'verified' or creation_time_utc < start_datetime or creation_time_utc > end_datetime:
        #the date range is inclusive of the start and end dates, so if the creation time is equal to the start or end date, it should be downloaded.    
            return
        filename = item['filename']

        folder = os.path.join(self.backup_path, str(creation_time.year), str(creation_time.month))
        os.makedirs(folder, exist_ok=True)
        file_path = os.path.join(folder, filename)

        # Check if the file exists in the current folder
        if os.path.exists(file_path):
            item['status'] = 'verified'
            logging.info(f"File {file_path} already exists in path, verified")
            # Add the item to the all_media_items list if it's not already there
            if item not in self.all_media_items:
                self.all_media_items.append(item)
                logging.info(f"Added {file_path} to all_media_items")
  
        else:  

            session = requests.Session()
            for attempt in range(3):  # Retry up to 3 times
                while not rate_limiter.consume(): #calls new class TokenBucket
                    time.sleep(0.1)  # Wait for a short time if no tokens are available

                try:
                    
                    logging.info(f"About to make request to Google Photos API for item {item['id']}...")
                    image = self.photos_api.mediaItems().get(mediaItemId=item['id']).execute()
                    logging.info(f"Response from Google Photos API: {image}")
                    logging.info("Request to Google Photos API completed.")

                    is_video = 'video' in item['mimeType']
                    logging.info(f"Is the item a video? {is_video}")

                    if 'video' in item['mimeType']:  # Check if 'video' is in mimeType
                        image_url = image['baseUrl'] + '=dv'
                        logging.info(f"Video URL: {image_url}")
                    else:
                        image_url = image['baseUrl'] + '=d'
                        logging.info(f"Image URL: {image_url}")

                    logging.info(f"Attempting to download {image_url}...")  # Log a message before the download attempt
                    response = session.get(image_url, stream=True)
                    logging.info(f"Download attempt finished. Status code: {response.status_code}")  # Log a message after the download attempt

                    # Log the status code and headers
                    logging.info(f"Response status code: {response.status_code}")
                    logging.info(f"Response headers: {response.headers}")

            
                
                    with open(file_path, "wb") as f:
                        f.write(response.content)

                    item['file_path'] = file_path  # record the file path
                    item['file_size'] = os.path.getsize(file_path)  # record the file size
                    item['status'] = 'downloaded'  # record the status
                    print(f"Downloaded {file_path}")

                    break
                  
                except TimeoutError: #test
                    logging.error(f"Request to Google Photos API for item {item['id']} timed out.") #test
                    item['status'] = 'failed' #test
                    continue #test
                except ssl.SSLError as e:
                    item['status'] = 'failed'
                    logging.error(f"SSLError occurred while trying to get {image_url}: {e}")
                    logging.error(f"Traceback: {traceback.format_exc()}")
                    time.sleep(1)
                except requests.exceptions.RequestException as e:
                    item['status'] = 'failed'
                    logging.error(f"RequestException occurred while trying to get {image_url}: {e}")
                    logging.error(f"Traceback: {traceback.format_exc()}")
                    time.sleep(1)
                except Exception as e:
                    item['status'] = 'failed'
                    logging.error(f"An error occurred while trying to get {item['id']}: {e}")
                    if attempt < 2:  # If this was not the last attempt
                        logging.info(f"Retrying download of {item['id']}...")
                    else:  # If this was the last attempt
                        logging.error(f"Failed to download {item['id']} after 3 attempts.")

                

    def download_photos(self, all_media_items):
        print(f"Number of items in all_media_items: {len(self.all_media_items)}")
        print(f"Statuses of items in all_media_items: {[item['status'] for item in self.all_media_items.values()]}")

        try:
            logging.info("Downloading media...")

            with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
                executor.map(self.download_image, self.all_media_items.values())


        except Exception as e:
            logging.error(f"An unexpected error occurred in download_photos: {e}")
        finally:
            logging.info(f"All items processed, performing final checkpoint...")
            self.save_lists_to_file()
            self.cleanup()

if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(description='Google Photos Downloader')
        parser.add_argument('--start_date', type=str, required=True, help='Start date in the format YYYY-MM-DD')
        parser.add_argument('--end_date', type=str, required=True, help='End date in the format YYYY-MM-DD')
        parser.add_argument('--backup_path', type=str, required=True, help='Path to the folder where you want to save the backup')
        parser.add_argument('--num_workers', type=int, default=5, help='Number of worker threads for downloading images')
        parser.add_argument('--detect_missing', action='store_true', help='Detect and download missing files')

        args = parser.parse_args()

        log_filename = os.path.join(args.backup_path, 'google_photos_downloader.log')
        logging.basicConfig(filename=log_filename, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(formatter)
        logging.getLogger().addHandler(console_handler)

        downloader = GooglePhotosDownloader(args.start_date, args.end_date, args.backup_path, args.num_workers)
        downloader.download_photos()
        if args.detect_missing:
            missing_items = downloader.identify_missing_files()
            for item in missing_items:
                downloader.download_image(item)

    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
