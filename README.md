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

## Logging

The script logs the download process and saves the logs to a file named `google_photos_downloader.log` in the backup directory. It logs the following information:

- Connection to Google server
- Downloading media
- Downloading each image
- Skipping each image if it already exists
- Any network or SSL errors that occur during the download
- Cleanup process
- Final download statistics (number of images downloaded, skipped, and failed to download; total file size downloaded)

## CSV File

The script also generates a CSV file named `DownloadItems.csv` in the backup directory. This file contains the following columns:

- `index`: The index of the item
- `id`: The ID of the item
- `productUrl`: The URL of the item on Google Photos
- `baseUrl`: The base URL of the item
- `mimeType`: The MIME type of the item
- `mediaMetadata`: The metadata of the item
- `filename`: The filename of the item
- `status`: The status of the item (downloaded, skipped, or failed)

## Error Handling

The script retries up to 3 times if a network or SSL error occurs during the download. If an error occurs that is not a network or SSL error, the script does not retry and logs the error. The script also performs a cleanup at the end to retry downloading any items that failed to download.

## Note

Before running the script, make sure you have enabled the Google Photos API on your Google Cloud Console and downloaded the OAuth 2.0 Client ID. Save the Client ID as `client_secrets.json` in the same directory as the script.

## License

This project is licensed under the terms of the MIT license.

