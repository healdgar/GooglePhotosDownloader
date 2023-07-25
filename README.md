# Google Photos Downloader

This project is a script to download your Google Photos between specified dates to a local directory. It uses the Google Photos Library API to access and download the photos.

## Features

- Downloads all photos between two specified dates
- Multithreaded downloading for faster performance
- Skips already downloaded photos to prevent duplicates
- Detailed logging of download progress and any errors

## Requirements

- Python 3
- Google Photos Library API credentials (client_secrets.json)

## Usage

1. Clone this repository to your local machine.
2. Install the required Python packages with `pip install -r requirements.txt`.
3. Run the script with `python google_photos_downloader.py --start_date YYYY-MM-DD --end_date YYYY-MM-DD --backup_path /path/to/backup`.

Replace `YYYY-MM-DD` with the start and end dates for the photos you want to download, and `/path/to/backup` with the directory where you want to save the photos.

## License

This project is licensed under the terms of the MIT license.
