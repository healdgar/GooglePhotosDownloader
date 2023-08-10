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
import random
from colorama import Fore, Style 

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

    def __init__(self, backup_path, start_date=None, end_date=None, num_workers=5, checkpoint_interval=25, auth_code=None):

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
        self.auth_code = auth_code  # New argument to store the authentication code
        self.MAX_RETRIES = 3  # Maximum number of retries for a download attempt       
        self.downloaded_items_path = os.path.normpath(os.path.join(self.backup_path, 'DownloadItems.json'))
        self.download_counter = 0
        self.progress_log_interval = 25

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

    def authenticate(self):
        """Perform the OAuth authentication using the provided auth_code."""
        flow = InstalledAppFlow.from_client_secrets_file('client_secrets.json', self.SCOPES)
        creds = flow.run_local_server(port=0, authorization_prompt_message='', authorization_code=self.auth_code)
        with open('token.pickle', 'wb') as token_file:
            pickle.dump(creds, token_file)

        self.photos_api = build('photoslibrary', 'v1', static_discovery=False, credentials=creds)
        logging.info("Connected to Google server.")   


    def get_all_media_items(self): #This method is used to fetch all media items from the Google Photos API
        #and store them in a dictionary.
        fetcher_start_time = time.time()  # Record the starting time    
        # Load existing media items in order to avoid re-downloading them 

        self.all_media_items = self.downloaded_items 
        # Convert the start and end dates to UTC because the API requires UTC (removing for test) 
        start_datetime = datetime.strptime(self.start_date, "%Y-%m-%d").replace(tzinfo=tzutc())
        end_datetime = datetime.strptime(self.end_date, "%Y-%m-%d").replace(tzinfo=tzutc()) + timedelta(days=1, seconds=-1)

        # Filter out any items that are outside the date range
        self.all_media_items = {
            id: item 
            for id, item in self.all_media_items.items() 
            if start_datetime <= datetime.strptime(item['mediaMetadata']['creationTime'], "%Y-%m-%dT%H:%M:%S%z") <= end_datetime} 
        logging.info(f"FETCHER: {len(self.all_media_items)} existing items are within the date range")
        
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
        indexing_start_time = time.time()  # Record the starting time
        items_processed = 0  # Initialize the items processed counter outside of the loop

        while True: # Loop until there are no more pages
            
            results = self.photos_api.mediaItems().search(
                body={
                    'pageToken': page_token,
                    'filters': date_filter,
                    'pageSize': 99  # Set the pageSize here  
                } 
            ).execute()

            items = results.get('mediaItems')
            if not items:
                logging.info("FETCHER: No more results")
                break

  
            for item in items:
                items_processed += 1  # Increment the items_processed counter
                if item['id'] not in self.all_media_items: #if the item is not already in the index, add it.
                    convention_filename = self.append_id_to_string(item['filename'], item['id'])
                    convention_filename = convention_filename.replace('\\', '-').replace('/', '-') #avoid slashes in filenames
                    # If the filename doesn't exist in the scan results, mark it as 'not downloaded'
                    item['status'] = 'fetched' #fetched but not verified by scan.
                    self.all_media_items[item['id']] = item #add the item to the index.

            page_token = results.get('nextPageToken')
            if not page_token:
                logging.info("FETCHER: No more pages")
                break

            page_counter += 1  # Increment the page counter

            # If 10 pages have been processed, report progress and estimate time to completion
            if page_counter % 10 == 0:                
                elapsed_indexing_time = time.time() - indexing_start_time  # Calculate elapsed time
                self.save_index_to_file(self.all_media_items)  # Save the index to file   

                # Check if items_processed is zero         
                if  items_processed == 0:
                    average_time_per_item = 0
                else:                    
                    average_time_per_item = items_processed / elapsed_indexing_time # Calculate average processing time per item

                    
                logging.info(f"FETCHER: Processed {page_counter} pages and {items_processed} items averaging {average_time_per_item} per second. Estimated remaining time, WTH knows.")

        self.all_item_count = len(self.all_media_items)
        self.fetcher_elapsed_time = time.time() - fetcher_start_time  # Calculate elapsed time
        logging.info(f"FETCHER: Total time to fetch index: {time.time() - fetcher_start_time} seconds. ({average_time_per_item} p/sec)")
        self.save_index_to_file(self.all_media_items)  # Save the index to file

    def append_id_to_string(self, string_to_append, item_id):
        # this method is used to append the last 14 digits of the Google Photos ID to a string (usually a file_path or filename)
        # Extract the extension
        base, ext = os.path.splitext(string_to_append)

        # Check if the string already ends with the 14 characters from the ID
        if re.search(rf'{item_id[-14:]}$', base, re.IGNORECASE):
            return string_to_append

        # If not, append the 14 characters
        appended_string = f"{base}_{item_id[-14:]}{ext}"
        return appended_string

    def scandisk_and_get_filepaths_and_filenames(self): #scans drive for filenames and filepaths and returns a dictionary of all filenames and filepaths in the backup folder.
        scanner_start_time = time.time()
        # loop through all files in the backup folder and create a dictionary of all filenames and filepaths.
        filepaths_and_filenames = {}
        for root_subdir in os.listdir(self.backup_path):
            root_subdir_path = os.path.normpath(os.path.join(self.backup_path, root_subdir))
            if os.path.isdir(root_subdir_path):
                for dirpath, dirnames, filenames in os.walk(root_subdir_path):
                    for filename in filenames:
                        filename = filename.replace('\\', '-').replace('/', '-') #some weird filenames contain slashes.  Replace them with dashes.
                        filepath = os.path.normpath(os.path.join(dirpath, filename))
                        filepaths_and_filenames[filepath] = filename

        # Load existing media items in case method is called without get_all_media_items.
        #should possibly be moved to a separate method, because it is repeated.  Possibly a load_index_from_file method.
        if len(self.all_media_items) == 0:
            self.load_index_from_file()
            logging.info("SCANNER: No media items in memory, loading from file.")
            
        #loop through all items in the index and update the file path and status.  Possibly move to a separate method called update_index.
        logging.info(f"SCANNER: Number of items loaded to all_media_items for get all filepaths: {len(self.all_media_items)}")
        logging.info(f"SCANNER: Scanning repository...")
        verified_count = 0
        moved_count = 0
        renamed_count = 0
        filepath_added_count = 0

        for item in self.all_media_items.values():
            # Parse the creation time and convert to local time zone
            creation_time = parse(item['mediaMetadata']['creationTime']).astimezone(pytz.utc).replace(tzinfo=None)
            creation_time_local = convert_utc_to_local(creation_time)
            # Define the subdirectory based on the local time zone-adjusted creation time
            subdirectory = os.path.join(str(creation_time_local.year), str(creation_time_local.month))
            # Define the filename with the appended ID based on the local time zone-adjusted creation time
            convention_filename = self.append_id_to_string(item['filename'], item['id'])
            # Combine everything to get the full file path
            convention_filename = convention_filename.replace('\\', '-').replace('/', '-')
            convention_filepath = os.path.normpath(os.path.join(self.backup_path, subdirectory, convention_filename))

            
            if convention_filepath in filepaths_and_filenames: #update the filepath in the index if it exists in the dictionary.
                item['file_path'] = convention_filepath #add file repository metadata to the index.
                item['file_size'] = os.path.getsize(convention_filepath)
                item['filename'] = convention_filename
                item['status'] = 'verified' #mark the item as verified if the file exists.
                verified_count =+ 1   
                          
                
            if item['filename'] in filepaths_and_filenames.values():
                #possibly should be a separate method called organize_files.  This is the main loop to organize files.
                current_filepaths = [path for path, name in filepaths_and_filenames.items() if name == convention_filename] #get a list of all filepaths with the same filename.
                #first subloop to move files to the correct location if they are named correctly.
                for current_filepath in current_filepaths:
                    # If the file is properly named but not in the correct location, move it
                    if current_filepath and current_filepath != convention_filepath:
                        # Create the directory if it doesn't exist
                        os.makedirs(os.path.dirname(convention_filepath), exist_ok=True)
                        # Only move the file if it does not already exist at the destination
                        if not os.path.exists(convention_filepath):
                            logging.info(f"SCANNER: Moving {current_filepath} to {convention_filepath}")
                            os.rename(current_filepath, convention_filepath)
                            # Update the filepath in the item and in the dictionary
                            item['file_path'] = convention_filepath
                            item['status'] = 'verified'
                            filepaths_and_filenames[convention_filepath] = item['filename']
                            del filepaths_and_filenames[current_filepath]
                            moved_count += 1
                            
                        else:
                            # If a file already exists at the convention_filepath, check if it is the correct file
                            if os.path.basename(convention_filepath) != item['filename']:
                                # If it is not the correct file, move it to the backup directory
                                backup_dir = os.path.join(os.path.dirname(convention_filepath), 'backup')
                                os.makedirs(backup_dir, exist_ok=True)
                                backup_filepath = os.path.join(backup_dir, os.path.basename(convention_filepath))
                                if not os.path.exists(backup_filepath):  # Check if the file already exists in the backup directory
                                    logging.info(f"SCANNER: Moving existing file at {convention_filepath} to backup directory {backup_filepath}")
                                    os.rename(convention_filepath, backup_filepath)
                                else:
                                    logging.info(f"SCANNER: File already exists in the backup directory. Skipping move.")


                # Second subloop to rename files if they are not named correctly.  possibly should be a separate method called rename_files.
                if convention_filepath in filepaths_and_filenames:
                    if item['filename'] != filepaths_and_filenames[convention_filepath]:
                        logging.info(f"SCANNER: Filename {filepaths_and_filenames[convention_filepath]} does not match the convention. Renaming to {convention_filename}")
                        os.rename(convention_filepath, os.path.join(os.path.dirname(convention_filepath), convention_filename))
                        # Update the filename in the item and in the dictionary
                        item['filename'] = convention_filename
                        filepaths_and_filenames[convention_filepath] = convention_filename
                        item['status'] = 'verified' #mark the item as verified if the file exists.
                        renamed_count += 1
                else:
                    item['status'] = 'missing'
                    logging.info(f"SCANNER: File {item['filename']} is missing")
                    missing_count =+ 1

                #third subloop to loop to look for items in the index that only have source filename,
                #and add any missing file_path or file_size or status values to the index.
                #possibly should be a separate method called add_missing_filepaths.
                if not item.get('file_path'):
                    # file path is missing or None: 
                    logging.info(f"SCANNER: File {convention_filepath} exists, adding file_path to index.")
                    item['file_size'] = os.path.getsize(convention_filepath)
                    item['file_path'] = convention_filepath
                    filepath_added_count += 1
                    #update filename to convention_filename if it doesn't match.
                    if item['filename'] != convention_filename:
                        logging.info(f"SCANNER: Filename {item['filename']} does not match the convention. Renaming filename and adding status and filename to index.")
                        item['filename'] = convention_filename
                        filepaths_and_filenames[convention_filepath] = convention_filename
                        os.rename(convention_filepath, os.path.join(os.path.dirname(convention_filepath), convention_filename))
                        item['status'] = 'verified'
                    else: #ensure the status and filename exist in the record if the stray file is correctly named, in the index, but doesn't have this info.
                        logging.info(f"SCANNER: Filename {item['filename']} matches the convention. Updating index status and filename.")
                        item['filename'] = convention_filename
                        item['status'] = 'verified'  
                        filepaths_and_filenames[convention_filepath] = convention_filename                            
            logging.info(f"SCANNER: #{verified_count} File {convention_filepath} verified")
        scanner_end_time = time.time()
        
        logging.info(f"SCANNER: Verified {verified_count} files.")
                      #and found {missing_count or 0} missing files.  Renamed {renamed_count or 0} files and moved {moved_count or 0} files.  Added filepaths to {filepath_added_count or 0} files.")
        self.scanner_elapsed_time = scanner_end_time - scanner_start_time
        logging.info(f"SCANNER: Validator completed processing in {scanner_end_time - scanner_start_time} seconds.")
        time.sleep(1.5)
        self.save_index_to_file(self.all_media_items)
        return filepaths_and_filenames

    def validate_repository(self): #this method is used to validate the repository by checking the index against the actual files in the repository.
        validator_start_time = time.time()

        self.all_media_items_path = os.path.normpath(os.path.join(self.backup_path, 'DownloadItems.json'))
        if os.path.exists(self.all_media_items_path):
            self.all_media_items = {}
            try:
                with open(self.all_media_items_path, 'r') as f:
                    self.all_media_items = json.load(f)
            except json.JSONDecodeError:
                logging.info("VALIDATOR: There was an error decoding the JSON file. Please check the file format.")
            logging.info(f"Loaded {len(self.all_media_items)} existing media items from file.")

        else:
            logging.info("VALIDATOR: No existing media items found.")

        logging.info(f"VALIDATOR: Number of items loaded to all_media_items for checking existing file paths in index: {len(self.all_media_items)}")

        missing_count = 0
        validated_count = 0
        validated_files = []
        missing_files = []
      
        for item in self.all_media_items.values():
            if item.get('file_path') is not None:
                file_path_to_verify = os.path.normpath(item['file_path'])

                try:
                    if file_path_to_verify is not None and os.path.exists(file_path_to_verify):
                        validated_count += 1
                        validated_files.append(file_path_to_verify)
                    else:
                        missing_count += 1
                        missing_files.append(file_path_to_verify)
                except:
                    logging.info(f"Error verifying file {file_path_to_verify}")
                    continue

        logging.info(f"VALIDATOR: Verified {validated_count} indexed file paths and found {missing_count} missing files.")
        logging.info(f'VALIDATOR: The last validated file path was {file_path_to_verify}')

        with open('validated_files.txt', 'w') as f:
            for item in validated_files:
                f.write("%s\n" % item)

        with open('missing_files.txt', 'w') as f:
            for item in missing_files:
                f.write("%s\n" % item)
        # Now let's find extraneous files  This should possibly be the a separate method called find_extraneous_files
        # or part of the scandisk_and_get_filepaths_and_filenames method.
        extraneous_files = []
        for root, dirs, files in os.walk(self.backup_path):
            # If the current directory is the root of the backup directory, skip it
            if os.path.normpath(root) == os.path.normpath(self.backup_path):
                continue
            for file in files:
                file_path = os.path.join(root, file)
                normalized_file_path = os.path.normpath(file_path)
                if normalized_file_path not in validated_files:
                    extraneous_files.append(normalized_file_path)

        # Log the number of extraneous files
        logging.info(f"VALIDATOR: Found {len(extraneous_files)} extraneous files.")

        # Save the list of extraneous files to a file
        with open('extraneous_files.txt', 'w') as f:
            for file in extraneous_files:
                f.write("%s\n" % file)
        if len(extraneous_files) == 0:
            return
        #ask user whether to delete, relocate or leave files alone
        user_input = input("Would you like to delete, relocate or leave alone the extraneous files? (d/r/l): ")
        if user_input == 'd':
            for file in extraneous_files:
                os.remove(file)
            logging.info("Extraneous files deleted")
        elif user_input == 'r':
            # ask user for new directory
            new_directory = input("Enter the new directory: ")
            for file in extraneous_files:
                # Get the relative path of the file
                rel_path = os.path.relpath(file, self.backup_path)
                # Create the new path for the file
                new_filepath = os.path.join(new_directory, rel_path)
                # Create any necessary directories
                os.makedirs(os.path.dirname(new_filepath), exist_ok=True)
                # Move the file
                os.rename(file, new_filepath)
            logging.info(f"Extraneous files moved to {new_directory}")

        elif user_input == 'l':
            logging.info("Leaving files alone")
        else:
            logging.info("Invalid input. Leaving files alone")
            
        validator_end_time = time.time()
        self.validator_elapsed_time = validator_end_time - validator_start_time
        logging.info(f"VALIDATOR: Total time to validate repository: {self.validator_elapsed_time} seconds")
        time.sleep(1.5)

    def download_image(self, item):
        logging.info(f"DOWNLOADER: considering {item['filename']}...")
        
        # Parse the creation time and convert to local time zone
        creation_time_local = convert_utc_to_local(parse(item['mediaMetadata']['creationTime']))

        # Get the correct creation year from the 'creationTime' metadata
        creation_time_year = convert_utc_to_local(parse(item['mediaMetadata']['creationTime'])).year
        # Update the subdirectory to use the correct creation year
        subdirectory = os.path.join(str(creation_time_year), str(creation_time_local.month))
        # Define the filename with the appended ID based on the local time zone-adjusted creation time
        convention_filename = self.append_id_to_string(item['filename'], item['id'])
        # Combine everything to get the full file path
        convention_filename = convention_filename.replace('\\', '-').replace('/', '-') #avoid slashes in filenames
        convention_file_path = os.path.normpath(os.path.join(self.backup_path, subdirectory, convention_filename))
        
        # If the file cannot be found at either file_path, download it.
        
        
        logging.info(f"DOWNLOADER: Starting download request for {convention_file_path}")
        session = requests.Session() #creates a new session for each download attempt.  This is to prevent the session from timing out and causing the download to fail.
        for attempt in range(self.MAX_RETRIES):  # Retry up to MAX_RETRIES times.  Part of exponential backoff.
            while not rate_limiter.consume(): #if the rate limiter is not ready, wait for a short time and try again.
                time.sleep(0.1)  # Wait for a short time if no tokens are available
            try:                
                image = self.photos_api.mediaItems().get(mediaItemId=item['id']).execute()
                #logging.info(f"DOWNLOADER: Response from Google Photos API: {image}")

                if 'video' in item['mimeType']:  # Check if 'video' is in mimeType. need to account for motion photos and other media types.
                    image_url = image['baseUrl'] + '=dv' #motion videos also dowlnoad as =dv. Stil testing.
                if 'image' in item['mimeType']:
                    image_url = image['baseUrl'] + '=d'
                else:
                    image_url = image['baseUrl'] + '=d'

                logging.info(f"DOWNLOADER: Attempting to download {convention_file_path}...")  # Log a message before the download attempt
                response = session.get(image_url, stream=True)
                logging.info(f"DOWNLOADER: Download attempt finished. Status code: {response.status_code}")  # Log a message after the download attempt
                self.download_counter += 1
                # Log the status code and headers
                logging.info(f"DOWNLOADER: Response headers: {response.headers}")
                os.makedirs(os.path.dirname(convention_file_path), exist_ok=True)
                with open(convention_file_path, "wb") as f: 
                    f.write(response.content) #write the file to the backup folder

                item['file_path'] = convention_file_path  # record the file path
                item['file_size'] = os.path.getsize(convention_file_path)  # record the file size
                item['status'] = 'downloaded'  # record the status
                item['filename'] = convention_filename #record the filename
                logging.info(f"DOWNLOADER: Downloaded {convention_file_path}")
                
                if self.download_counter % self.progress_log_interval == 0:
                    percent_complete = (self.download_counter / self.potential_job_size) * 100
                    download_progress_timestamp = time.time()
                    download_elapsed_time = download_progress_timestamp - self.download_start_timestamp
                    download_rate = self.download_counter / download_elapsed_time
                    download_ETR = (self.potential_job_size - self.download_counter) / download_rate
                    logging.info(Fore.GREEN + f"Progress: {percent_complete:.2f}% complete. ETR {download_ETR/60} minutes" + Style.RESET_ALL)
                    logging.info(Fore.CYAN + f"DOWNLOADER: Processed {self.download_counter} files out of {self.potential_job_size} files at {download_rate} files/sec." + Style.RESET_ALL)
                    # Save the index to file after every progress_log_interval downloads
                    self.save_index_to_file(self.all_media_items)

                break #if download is successful, break out of the retry loop and download the next item.
            
            except TimeoutError: #if the request times out, log an error and move on to the next item.
                logging.error(f"DOWNLOADER: FAILED Request to Google Photos API for item {item['id']} timed out.") #test
                self.download_counter += 1
                continue #test
            except requests.exceptions.RequestException as e: #if a request exception occurs, log an error and move on to the next item.
                logging.error(f"DOWNLOADER: FAILED RequestException occurred while trying to get {image_url}: {e}")
                logging.error(f"DOWNLOADER: Traceback: {traceback.format_exc()}")
                self.download_counter += 1
                time.sleep(1)
            except (requests.exceptions.RequestException, ssl.SSLError) as e:
                if attempt < self.MAX_RETRIES - 1:
                    logging.error(f"DOWNLOADER: Error occurred while trying to get {image_url}: {e}. Retrying...")
                    wait_time = (2 ** attempt) + random.random()  # Exponential backoff with jitter
                    time.sleep(wait_time)
                else:
                    logging.error(f"DOWNLOADER: Failed to download {item['id']} after {self.MAX_RETRIES} attempts.")
                    item['status'] = 'failed'
                    self.download_counter += 1
                    break


    def download_photos(self, all_media_items): #this function downloads all photos and videos in the all_media_items list.
        self.download_start_timestamp = time.time()  # Record the starting time
        logging.info(f"DOWNLOADER: Total index size: {len(all_media_items)}")
        self.potential_job_size = len([item for item in all_media_items.values() if item.get('status') not in ['downloaded', 'verified']])
        downloader_start_time = time.time()
        try:
            logging.info(f"DOWNLOADER: Downloading {self.potential_job_size} files...") #might remove subsequent date filter.
            time.sleep(1.5)
            with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
                executor.map(self.download_image, all_media_items.values())

        except Exception as e:
            logging.error(f"DOWNLOADER: An unexpected error occurred in download_photos: {e}")
        finally:
            logging.info(f"DOWNLOADER: All items processed, performing final checkpoint...")
            self.save_index_to_file(all_media_items)
            downloader_end_time = time.time()
            self.downloader_elapsed_time = downloader_end_time - downloader_start_time
            logging.info(f"DOWNLOADER: Total time to download photos: {downloader_end_time - downloader_start_time} seconds")
            logging.info(f"DOWNLOADER: Download rate: {self.potential_job_size / (downloader_end_time - downloader_start_time)} files per second")
            logging.info(f"DOWNLOADER: Rate limiter stats: {rate_limiter}")
            

    def report_stats(self): #this function reports the status of all items in the index.
        # Initialize counters
        total_size = 0
        total_files = 0
        total_images = 0
        total_videos = 0
        recent_changes = 0
        status_counts = {}
        now = datetime.now(timezone.utc)

        # Load existing media items in case method is called without get_all_media_items
        self.load_index_from_file()

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
        logging.info(f"Total size: {total_size/1024/1024/1024} megabytes") #of downloaded or verified files.
        logging.info(f"Total file records: {total_files}")
        logging.info(f"Total image records: {total_images}")
        logging.info(f"Total video records: {total_videos}")
        logging.info(f"Recently created media: {recent_changes}")
         # Print the status counts
        for status, count in status_counts.items():
            logging.info(f"Status field tallies '{status}': {count} items")

    def save_index_to_file(self, all_items):
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

            logging.info("INDEX UPDATER: Successfully saved lists to file.")
        else:
            logging.error(f"INDEX UPDATER: No write access to the file: {self.downloaded_items_path}")  

    def load_index_from_file(self): #to implement throughout.
        all_media_items_path = os.path.normpath(os.path.join(args.backup_path, 'DownloadItems.json'))
        if os.path.exists(all_media_items_path):
            self.all_media_items = {}
            try:
                with open(all_media_items_path, 'r') as f:
                    self.all_media_items = json.load(f)
                print(f"Loaded {len(self.all_media_items)} existing media items from file.")
            except json.JSONDecodeError:
                logging.info("There was an error decoding the JSON file. Please check the file format.")

if __name__ == "__main__":
    try:
        parser = argparse.ArgumentParser(description='Google Photos Downloader')
        subparsers = parser.add_subparsers(dest='command')

        # Sub-parser for fetch_only
        fetch_parser = subparsers.add_parser('fetch_only', help='Refresh the index by fetching a new one from the server')
        fetch_parser.add_argument('--start_date', type=str, default='1800-01-01', required=True, help='Start date in the format YYYY-MM-DD')
        fetch_parser.add_argument('--end_date', type=str, default=datetime.now(timezone.utc).strftime('%Y-%m-%d'), required=True, help='End date in the format YYYY-MM-DD')#default end_date now
        fetch_parser.add_argument('--backup_path', type=str, required=True, help='Path to the folder where you want to save the backup')

        # Sub-parser for download_missing
        download_parser = subparsers.add_parser('download_missing', help='Download all missing items')
        download_parser.add_argument('--backup_path', type=str, required=True, help='Path to the folder where you want to save the backup')
        download_parser.add_argument('--num_workers', type=int, default=5, help='Number of worker threads for downloading images')

        # Sub-parser for stats_only, validate_only, scan_only, auth
        for command in ['stats_only', 'validate_only', 'scan_only', 'auth']:
            command_parser = subparsers.add_parser(command)
            command_parser.add_argument('--backup_path', type=str, required=True, help='Path to the folder where you want to save the backup')
        
        # Sub-parser for run_all
        run_all_parser = subparsers.add_parser('run_all', help='Run scan, fetch, download, validate, and report stats in sequence')
        run_all_parser.add_argument('--start_date', type=str, default='1800-01-01', required=True, help='Start date in the format YYYY-MM-DD')
        run_all_parser.add_argument('--end_date', type=str, default=datetime.now(timezone.utc).strftime('%Y-%m-%d'), required=True, help='End date in the format YYYY-MM-DD')#default end_date now
        run_all_parser.add_argument('--backup_path', type=str, required=True, help='Path to the folder where you want to save the backup')
        run_all_parser.add_argument('--num_workers', type=int, default=2, help='Number of worker threads for downloading images')

        args = parser.parse_args()

        log_filename = os.path.join(args.backup_path, 'google_photos_downloader.log')
        logging.basicConfig(filename=log_filename, level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        console_handler.setFormatter(formatter)
        logging.getLogger().addHandler(console_handler)

        rate_limiter = TokenBucket(rate=1, capacity=2)  # You can adjust these numbers based on the rate limits 

        if args.command == 'auth':
            downloader = GooglePhotosDownloader(args.backup_path)
            downloader.authenticate()

        elif args.command == 'stats_only':
            downloader = GooglePhotosDownloader(args.backup_path)
            downloader.report_stats()

        elif args.command == 'validate_only':
            downloader = GooglePhotosDownloader(args.backup_path)
            downloader.validate_repository()

        elif args.command == 'scan_only':
            downloader = GooglePhotosDownloader(args.backup_path)
            downloader.scandisk_and_get_filepaths_and_filenames()

        elif args.command == 'download_missing':
            downloader = GooglePhotosDownloader(args.backup_path, num_workers=args.num_workers)
            missing_media_items = {id: item for id, item in downloader.downloaded_items.items() if item.get('status') not in ['downloaded', 'verified']}
            downloader.download_photos(missing_media_items)

        elif args.command == 'fetch_only':
            downloader = GooglePhotosDownloader(args.start_date, args.end_date, args.backup_path)
            downloader.get_all_media_items()
        
        elif args.command == 'run_all':
            downloader = GooglePhotosDownloader(args.start_date, args.end_date, args.backup_path, num_workers=args.num_workers)
            downloader.scandisk_and_get_filepaths_and_filenames()
            downloader.get_all_media_items()
            missing_media_items = {id: item for id, item in downloader.downloaded_items.items() if item.get('status') not in ['downloaded', 'verified']}
            downloader.download_photos(missing_media_items)
            downloader.save_index_to_file(missing_media_items)
            downloader.validate_repository()
            downloader.report_stats()

        else:
            downloader = GooglePhotosDownloader(args.backup_path)
            downloader.report_stats()

    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")
        traceback.print_exc()


    #sample usage: 
#python google_photos_downloader.py fetch_only --start_date 2023-01-01 --end_date 2023-12-31 --backup_path C:\users\alexw\onedrive\gphotos
#python google_photos_downloader.py download_missing --backup_path C:\users\alexw\onedrive\gphotos --num_workers 5
#python google_photos_downloader.py stats_only --backup_path C:\users\alexw\onedrive\gphotos
#python google_photos_downloader.py validate_only --backup_path C:\users\alexw\onedrive\gphotos
#python google_photos_downloader.py scan_only --backup_path C:\users\alexw\onedrive\gphotos
#python google_photos_downloader.py auth --backup_path C:\users\alexw\onedrive\gphotos
#python google_photos_downloader.py run_all --start_date 2023-01-01 --end_date 2023-12-31 --backup_path C:\users\alexw\onedrive\gphotos --num_workers 5


