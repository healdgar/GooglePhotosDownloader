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
import traceback
import re
import time
import threading
import pytz

def get_local_timezone():
    return pytz.timezone("America/Los_Angeles")  # Replace "Your_Local_Timezone" with your actual local time zone (e.g., "America/New_York")

def convert_utc_to_local(utc_time):
    local_tz = get_local_timezone()
    return local_tz.normalize(utc_time.replace(tzinfo=pytz.utc))

class TokenBucket: #this class is used to limit the rate of requests to the Google Photos API.  It is based on the example at https://www.geeksforgeeks.org/token-bucket-algorithm-implementation/
    def __init__(self, rate, capacity):
        self.rate = rate
        self.capacity = capacity
        self.tokens = capacity
        self.last_refill = time.monotonic()
        self.lock = threading.Lock()

    def refill(self):
        now = time.monotonic()
        elapsed = now - self.last_refill
        tokens_to_add = self.rate * elapsed
        self.tokens = min(self.tokens + tokens_to_add, self.capacity)
        self.last_refill = now

    def consume(self):
        with self.lock:
            self.refill()
            if self.tokens >= 1:
                self.tokens -= 1
                return True
            else:
                return False


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
        
        self.downloaded_items_path = os.path.normpath(os.path.join(self.backup_path, 'DownloadItems.json'))
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

        self.checkpoint_interval = checkpoint_interval #unused, for later implementation of a periodic save to file in case of interrupted downloads.
        self.all_media_items = {}  # Initialize all_media_items as an empty dictionary
        


    def get_all_media_items(self, filepaths_and_filenames):
            
        # Load existing media items in order to avoid re-downloading them
        self.all_media_items_path = os.path.normpath(os.path.join(self.backup_path, 'DownloadItems.json'))
        if os.path.exists(self.all_media_items_path):
            try:
                with open(self.all_media_items_path, 'r') as f:
                    self.all_media_items = json.load(f)
            except json.JSONDecodeError:
                print("There was an error decoding the JSON file. Please check the file format.")
            logging.info(f"Loaded {len(self.all_media_items)} existing media items")

        else:
            self.all_media_items = {}

        # Convert the start and end dates to UTC because the API requires UTC
        start_datetime = datetime.strptime(self.start_date, "%Y-%m-%d").replace(tzinfo=tzutc())
        end_datetime = datetime.strptime(self.end_date, "%Y-%m-%d").replace(tzinfo=tzutc())

        # Filter out any items that are outside the date range
        self.all_media_items = {
            id: item 
            for id, item in self.all_media_items.items() 
            if start_datetime <= datetime.strptime(item['mediaMetadata']['creationTime'], "%Y-%m-%dT%H:%M:%S%z") <= end_datetime} 
        logging.info(f"{len(self.all_media_items)} items are within the date range")

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
        page_counter = 0  # Initialize a page counter
        page_token = None
        kindexing_start_time = time.time()  # Record the starting time

        while True: # Loop until there are no more pages
            
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

            # Get all the filenames from the scan results
            existing_filenames = set(filepaths_and_filenames.values())
            for item in items:
                if item['id'] not in self.all_media_items: #if the item is not already in the index, add it.
                    filename_with_id = self.append_id_to_string(item['filename'], item['id'])
                    if filename_with_id in existing_filenames:
                        # If the filename already exists in the scan results, mark it as 'verified'
                        item['status'] = 'verified'
                    else:
                        # If the filename doesn't exist in the scan results, mark it as 'not downloaded'
                        item['status'] = 'not downloaded'
                    self.all_media_items[item['id']] = item

            page_token = results.get('nextPageToken')
            if not page_token:
                logging.info("No more pages")
                break

            page_counter += 1  # Increment the page counter

        # If 10 pages have been processed, report progress and estimate time to completion
        if page_counter % 10 == 0:
            elapsed_time = time.time() - kindexing_start_time  # Calculate elapsed time
            items_processed = len(self.all_media_items)  # Calculate number of items processed so far
            average_time_per_item = elapsed_time / items_processed  # Calculate average processing time per item
            estimated_remaining_time = average_time_per_item * (10000 - items_processed)  # Estimate remaining time based on average time per item
            logging.info(f"Processed {page_counter} pages and {items_processed} items in {elapsed_time:.2f} seconds. Estimated remaining time: {estimated_remaining_time:.2f} seconds.")

        self.save_lists_to_file(self.all_media_items)

    def append_id_to_string(self, string_to_append, item_id):
        """Append the last 14 characters of the ID to the filename if necessary."""
        # Extract the extension
        base, ext = os.path.splitext(string_to_append)

        # Check if the string already ends with the 14 characters from the ID
        if re.search(rf'{item_id[-14:]}$', base, re.IGNORECASE):
            return string_to_append

        # If not, append the 14 characters
        appended_string = f"{base}_{item_id[-14:]}{ext}"
        return appended_string

    def get_filepaths_and_filenames(self):
        """Get a dictionary of all filenames and filepaths in the backup folder."""
        filepaths_and_filenames = {}
        for root_subdir in os.listdir(self.backup_path):
            root_subdir_path = os.path.normpath(os.path.join(self.backup_path, root_subdir))
            if os.path.isdir(root_subdir_path):
                for dirpath, dirnames, filenames in os.walk(root_subdir_path):
                    for filename in filenames:
                        filepath = os.path.normpath(os.path.join(dirpath, filename))
                        filepaths_and_filenames[filepath] = filename

        print(f"Number of items loaded to all_media_items for get all filepaths: {len(self.all_media_items)}")
        for item in self.all_media_items.values():
            # Parse the creation time and convert to local time zone
            creation_time = parse(item['mediaMetadata']['creationTime']).astimezone(pytz.utc).replace(tzinfo=None)
            creation_time_local = convert_utc_to_local(creation_time)
            # Define the subdirectory based on the local time zone-adjusted creation time
            subdirectory = os.path.join(str(creation_time_local.year), str(creation_time_local.month))
            # Define the filename with the appended ID based on the local time zone-adjusted creation time
            filename_with_id = self.append_id_to_string(item['filename'], item['id'])
            # Combine everything to get the full file path
            convention_filepath = os.path.normpath(os.path.join(self.backup_path, subdirectory, filename_with_id))

            print(f"convention_filepath: {convention_filepath}")
            if convention_filepath in filepaths_and_filenames:
                item['file_path'] = convention_filepath
                item['file_size'] = os.path.getsize(convention_filepath)
                item['status'] = 'verified'
                print(f"File {item['file_path']} verified")

                current_filename = filepaths_and_filenames[convention_filepath]
                if item['filename'] != current_filename:
                    logging.info(f"Filename {item['filename']} does not match the convention. Renaming...")
                    # Rename the file
                    new_filename = self.append_id_to_string(item['filename'], item['id'])
                    new_filepath = os.path.normpath(os.path.join(dirpath, new_filename))
                    if not os.path.exists(new_filepath):
                        os.rename(convention_filepath, new_filepath)
                        # Update the filename in the item
                        item['filename'] = current_filename
                        # Update the filepath in the item and in the dictionary
                        item['file_path'] = new_filepath
                        filepaths_and_filenames[new_filepath] = current_filename
                        del filepaths_and_filenames[convention_filepath]
                    else:
                        logging.error(f"File already exists at {new_filepath}. Cannot rename {convention_filepath}.")                              
            else:
                item['status'] = 'missing'
                print(f"File {item['filename']} is missing")

        verified_count = len([item for item in self.all_media_items.values() if item['status'] == 'verified'])
        missing_count = len([item for item in self.all_media_items.values() if item['status'] == 'missing'])
        logging.info(f"SCANNER: Verified {verified_count} files and found {missing_count} missing files.")
        return filepaths_and_filenames


    def download_image(self, item):
        logging.info(f"considering {item['filename']}...")

        # Parse the creation time and convert to local time zone
        creation_time_local = convert_utc_to_local(parse(item['mediaMetadata']['creationTime']))
        # Convert the start and end dates to local time zone
        start_datetime_local = convert_utc_to_local(datetime.strptime(self.start_date, "%Y-%m-%d").replace(tzinfo=tzutc()))
        end_datetime_local = convert_utc_to_local(datetime.strptime(self.end_date, "%Y-%m-%d").replace(tzinfo=tzutc()) + timedelta(days=1, seconds=-1))
        
        # Compare creation_time_local with start_datetime_local and end_datetime_local
        is_status_downloaded = item['status'] == 'downloaded'
        is_status_verified = item['status'] == 'verified'
        is_before_start_date = creation_time_local < start_datetime_local
        is_after_end_date = creation_time_local > end_datetime_local

        if is_status_downloaded or is_status_verified or is_before_start_date or is_after_end_date or item['status'] == 'failed':
            return

        file_path = item['file_path']
        logging.info(f"File path: {file_path}")
        # Get the correct creation year from the 'creationTime' metadata
        creation_time_year = convert_utc_to_local(parse(item['mediaMetadata']['creationTime'])).year
        # Update the subdirectory to use the correct creation year
        subdirectory = os.path.join(str(creation_time_year), str(creation_time_local.month))
        # Define the filename with the appended ID based on the local time zone-adjusted creation time
        filename_with_id = self.append_id_to_string(item['filename'], item['id'])
        # Combine everything to get the full file path
        convention_file_path = os.path.normpath(os.path.join(self.backup_path, subdirectory, filename_with_id))
        convention_filename = self.append_id_to_string(item['filename'], item['id'])
        
        # if the file exists at either the original or the convention path, check if the filename matches the convention.
        if os.path.exists(file_path):
            # if the filename doesn't match the convention, rename the file, update the path, and mark it verified, and do not download it.
            if item['filename'] != convention_filename:
                logging.info(f"Filename {item['filename']} does not match the convention. Renaming...")                
                # Determine the current file path
                current_file_path = file_path if os.path.exists(file_path) else convention_file_path
                # Rename the file
                os.rename(current_file_path, convention_file_path)

                # Update path and mark it verified
                item['filename'] = convention_filename
                item['file_path'] = convention_file_path
                item['file_size'] = os.path.getsize(convention_file_path)
                item['status'] = 'verified'
                logging.info(f"File {current_file_path} updated to {convention_file_path} and verified")
                return

            # If the filename exists at the convention path, mark it verified and do not download it.
            if item['file_path'] == convention_file_path:
                item['status'] = 'verified'
                logging.info(f"File {convention_file_path} already exists, verified")        
                return 

        # If the file cannot be found at either file_path, download it.
        logging.info(f" {file_path} and {convention_file_path} for current item...")
        if not os.path.exists(file_path) and not os.path.exists(convention_file_path):   
            logging.info(f"Neither {file_path} nor {convention_file_path} exists. Starting download...")
            session = requests.Session() #creates a new session for each download attempt.  This is to prevent the session from timing out and causing the download to fail.
            for attempt in range(3):  # Retry up to 3 times
                while not rate_limiter.consume(): #if the rate limiter is not ready, wait for a short time and try again.
                    time.sleep(0.1)  # Wait for a short time if no tokens are available
                try:                
                    logging.info(f"About to make request to Google Photos API for item {item['filename']}...")
                    image = self.photos_api.mediaItems().get(mediaItemId=item['id']).execute()
                    logging.info(f"Response from Google Photos API: {image}")
                    logging.info("Request to Google Photos API completed.")

                    if 'video' in item['mimeType']:  # Check if 'video' is in mimeType. need to account for motion photos and other media types.
                        image_url = image['baseUrl'] + '=dv'
                        logging.info(f"Video URLfound")
                    else:
                        image_url = image['baseUrl'] + '=d'
                        logging.info(f"Image URLfound")

                    logging.info(f"Attempting to download {convention_file_path}...")  # Log a message before the download attempt
                    response = session.get(image_url, stream=True)
                    logging.info(f"Download attempt finished. Status code: {response.status_code}")  # Log a message after the download attempt

                    # Log the status code and headers
                    logging.info(f"Response status code: {response.status_code}")
                    logging.info(f"Response headers: {response.headers}")
        
                    with open(convention_file_path, "wb") as f: 
                        f.write(response.content) #write the file to the backup folder

                    item['file_path'] = convention_file_path  # record the file path
                    item['file_size'] = os.path.getsize(convention_file_path)  # record the file size
                    item['status'] = 'downloaded'  # record the status
                    print(f"Downloaded {convention_file_path}")
                    break #if download is successful, break out of the retry loop and download the next item.
                
                except TimeoutError: #if the request times out, log an error and move on to the next item.
                    logging.error(f"Request to Google Photos API for item {item['id']} timed out.") #test
                    item['status'] = 'failed' #test
                    continue #test
                except ssl.SSLError as e: #if an SSL error occurs, log an error and move on to the next item.
                    item['status'] = 'failed'
                    logging.error(f"SSLError occurred while trying to get {image_url}: {e}")
                    logging.error(f"Traceback: {traceback.format_exc()}")
                    time.sleep(1)
                except requests.exceptions.RequestException as e: #if a request exception occurs, log an error and move on to the next item.
                    item['status'] = 'failed'
                    logging.error(f"RequestException occurred while trying to get {image_url}: {e}")
                    logging.error(f"Traceback: {traceback.format_exc()}")
                    time.sleep(1)
                except Exception as e: #if an unexpected exception occurs, log an error and try again up to 3 times.
                    item['status'] = 'failed'
                    logging.error(f"An error occurred while trying to get {item['id']}: {e}")
                    if attempt < 2:  # If this was not the last attempt, retry after a short wait
                        logging.info(f"Retrying download of {item['id']}...")
                    else:  # If this was the last attempt, log an error and move on to the next item
                        logging.error(f"Failed to download {item['id']} after 3 attempts.")

    def download_photos(self, all_media_items): #this function downloads all photos and videos in the all_media_items list.
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

    def report_stats(self): #this function reports the status of all items in the index.
        # Initialize counters
        total_size = 0
        total_files = 0
        total_images = 0
        total_videos = 0
        recent_changes = 0
        status_counts = {}

        # Get the current date and time
        now = datetime.now(timezone.utc)

        # Convert the start and end dates to UTC
        start_datetime = datetime.strptime(self.start_date, "%Y-%m-%d").replace(tzinfo=tzutc())
        end_datetime = datetime.strptime(self.end_date, "%Y-%m-%d").replace(tzinfo=tzutc()) + timedelta(days=1, seconds=-1)

        # Filter out any items that are outside the date range
        filtered_items = [item for item in self.all_media_items.values() if start_datetime <= datetime.strptime(item['mediaMetadata']['creationTime'], "%Y-%m-%dT%H:%M:%S%z") <= end_datetime]

        for item in self.all_media_items.values():
            # Update the total size
            if item.get('status') in ['downloaded', 'verified'] and 'file_size' in item:
                total_size += item['file_size']

            # Update the total number of files
            total_files += 1

            # Update the total number of images and videos
            if 'image' in item['mimeType']:
                total_images += 1
            elif 'video' in item['mimeType']:
                total_videos += 1

            # Check for recent changes
            creation_time = datetime.strptime(item['mediaMetadata']['creationTime'], "%Y-%m-%dT%H:%M:%S%z")
            if (now - creation_time).days <= 7:  # Change this to the desired number of days
                recent_changes += 1
            
            # Count the statuses
            status = item.get('status')
            if status not in status_counts:
                status_counts[status] = 1
            else:
                status_counts[status] += 1

        # Print the stats
        print(f"Total size: {total_size} bytes") #of downloaded or verified files.
        print(f"Total file records: {total_files}")
        print(f"Total image records: {total_images}")
        print(f"Total video records: {total_videos}")
        print(f"Recently created media: {recent_changes}")
         # Print the status counts
        for status, count in status_counts.items():
            print(f"Status field tallies '{status}': {count} items")

    def save_lists_to_file(self, all_items):
        logging.info("Starting to save lists to file...")

        if os.access(self.downloaded_items_path, os.W_OK):
            # Load existing items
            if os.path.exists(self.downloaded_items_path):
                with open(self.downloaded_items_path, 'r') as f:
                    existing_items_dict = json.load(f)
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
                json.dump(existing_items_dict, f, indent=4)

            logging.info("Successfully saved lists to file.")
        else:
            logging.error(f"No write access to the file: {self.downloaded_items_path}")  


if __name__ == "__main__": #this is the main function that runs when the script is executed.
    try:
        parser = argparse.ArgumentParser(description='Google Photos Downloader')
        parser.add_argument('--start_date', type=str, required=True, help='Start date in the format YYYY-MM-DD')
        parser.add_argument('--end_date', type=str, required=True, help='End date in the format YYYY-MM-DD')
        parser.add_argument('--backup_path', type=str, required=True, help='Path to the folder where you want to save the backup')
        parser.add_argument('--num_workers', type=int, default=5, help='Number of worker threads for downloading images')
        parser.add_argument('--refresh_index', action='store_true', help='Refresh the index by fetching a new one from the server')
        parser.add_argument('--stats_only', action='store_true', help='Only report status of items in the index')
        parser.add_argument('--download_missing', action='store_true', help='Download all missing items')

        args = parser.parse_args()

        if args.stats_only:
            downloader = GooglePhotosDownloader(args.start_date, args.end_date, args.backup_path, args.num_workers)
            downloader.report_stats()
            exit()

        log_filename = os.path.join(args.backup_path, 'google_photos_downloader.log')
        logging.basicConfig(filename=log_filename, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(formatter)
        logging.getLogger().addHandler(console_handler)

        rate_limiter = TokenBucket(rate=1, capacity=2)  # You can adjust these numbers based on the rate limits 
        #of the Google Photos API and the requirements of your application. For example, 
        #if the API allows 10 requests per second and a maximum of 100 requests 
        # per 10 seconds, you could set rate=10 and capacity=100.

        downloader = GooglePhotosDownloader(args.start_date, args.end_date, args.backup_path, args.num_workers) #creates a new instance of the GooglePhotosDownloader class.
        

        if args.refresh_index:
            filepaths_and_filenames = downloader.get_filepaths_and_filenames()  # First get the scan results
            downloader.get_all_media_items(filepaths_and_filenames)  # Then refresh the index, using the scan results for comparison
        else:
            # Check if the file exists
            if not os.path.exists(downloader.downloaded_items_path):
                # If it doesn't exist, create a new JSON file
                with open(downloader.downloaded_items_path, 'w') as f:
                    # Initialize the JSON file with an empty dictionary
                    json.dump({}, f, indent=4)
            else:
                # If it exists, load the existing data from the JSON file
                with open(downloader.downloaded_items_path, 'r') as f:
                    downloader.all_media_items = json.load(f)

        downloader.get_filepaths_and_filenames()  #obtains a list of all filepaths in the backup folder
        downloader.download_photos(downloader.all_media_items) #download all photos and videos in the index.
        downloader.save_lists_to_file(downloader.all_media_items) #save the index to the JSON index file.
        downloader.report_stats() #report the status of all items in the index.

    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        traceback.print_exc()  # This will print the traceback

    #sample usage: 
    # python google_photos_downloader.py --start_date 1999-05-01 --end_date 1999-05-31 --backup_path C:\photos --num_workers 1
