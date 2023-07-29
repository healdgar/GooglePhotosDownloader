# Google Photos Downloader

This script is a multi-threaded Google Photos Downloader. It downloads photos from your Google Photos account within a specified date range and saves them to a specified directory. It also logs the download process and saves the logs to a file.

## Requirements

- Python 3.6 or higher
- Google Photos API enabled on your Google Cloud Console
- OAuth 2.0 Client ID (saved as `client_secrets.json` in the same directory as the script)

## Dependencies

- google-auth
- google-auth-httplib2
- google-auth-oauthlib
- google-api-python-client
- requests
- python-dateutil

You can install these dependencies using pip:

\```bash
pip install google-auth google-auth-httplib2 google-auth-oauthlib google-api-python-client requests python-dateutil
\```

## Usage

\```bash
python google_photos_downloader.py --start_date START_DATE --end_date END_DATE --backup_path BACKUP_PATH --num_workers NUM_WORKERS
\```

- `START_DATE`: Start date in the format YYYY-MM-DD
- `END_DATE`: End date in the format YYYY-MM-DD
- `BACKUP_PATH`: Path to the folder where you want to save the backup
- `NUM_WORKERS`: Number of worker threads for downloading images (default is 5)
- 'REFRESH_INDEX': adds missing entries to the index to permit future downloads
- 'STATS_ONLY': reads the index and reports some basic stats on counts and filesize

## Logging

The script logs the download process and saves the logs to a file named `google_photos_downloader.log` in the backup directory. It logs the following information:

- Connection to Google server
- Downloading media
- Downloading each image
- Skipping each image if it already exists
- Any network or SSL errors that occur during the download
- Cleanup process
- Final download statistics (number of images downloaded, skipped, and failed to download; total file size downloaded)

## JSON FILE

The script also generates a JSON index named `DownloadItems.json` in the backup directory. This file typicall contains the following keys (which vary depending upon the media item):

- `index`: The index of the item
- `id`: The ID of the item
- `productUrl`: The URL of the item on Google Photos
- `baseUrl`: The base URL of the item
- `mimeType`: The MIME type of the item
- `mediaMetadata`: The metadata of the item
- `filename`: The filename of the item
- `status`: The status of the item (downloaded, skipped, or failed)
- 'filepath': the filepath to the downloaded copy

## Error Handling

The script retries up to 3 times if a network or SSL error occurs during the download. If an error occurs that is not a network or SSL error, the script does not retry and logs the error. 

## Known Issues

- the program will not download duplicate filenames that woudl be saved to a duplciate filepath (year/month) at this time as it does not rename files and this results in a filesystem rejection.

## Note

Before running the script, make sure you have enabled the Google Photos API on your Google Cloud Console and downloaded the OAuth 2.0 Client ID. Save the Client ID as `client_secrets.json` in the same directory as the script.

## License

This project is licensed under the terms of the MIT license.

