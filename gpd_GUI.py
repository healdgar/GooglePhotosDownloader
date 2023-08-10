import tkinter as tk
from tkinter import filedialog
from google_photos_downloader import GooglePhotosDownloader
import logging

class TextHandler(logging.Handler):
    def __init__(self, text_widget):
        logging.Handler.__init__(self)
        self.text_widget = text_widget

    def emit(self, record):
        log_entry = self.format(record)
        self.text_widget.insert(tk.END, log_entry + '\n')

def setup_logging(log_text_widget):
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    handler = TextHandler(log_text_widget)
    logger.addHandler(handler)
    return logger

def run_command():
    command = command_var.get()
    backup_path = backup_path_entry.get()
    start_date = start_date_entry.get()
    end_date = end_date_entry.get()
    num_workers_str = num_workers_entry.get()

    # Check if num_workers is empty and set a default value if needed
    num_workers = int(num_workers_str) if num_workers_str else 2  # You can set the default value as needed

    # Create an instance of your downloader class
    #downloader = GooglePhotosDownloader(start_date, end_date, backup_path, num_workers=num_workers)

    # Run the selected command
    if command == 'auth':
        downloader = GooglePhotosDownloader(backup_path)
        downloader.authenticate()
    elif command == 'stats_only':
        downloader = GooglePhotosDownloader(backup_path)
        downloader.report_stats()
    elif command == 'validate_only':
        downloader = GooglePhotosDownloader(backup_path)
        downloader.validate_repository()
    elif command == 'scan_only':
        downloader = GooglePhotosDownloader(backup_path)
        downloader.scandisk_and_get_filepaths_and_filenames()
    elif command == 'download_missing':
        downloader = GooglePhotosDownloader(backup_path, num_workers)
        downloader.load_index_from_file()
        missing_media_items = {id: item for id, item in downloader.all_media_items.items() if item.get('status') not in ['downloaded', 'verified']}
        downloader.download_photos(missing_media_items)
    elif command == 'fetch_only':
        downloader = GooglePhotosDownloader(start_date, end_date, backup_path)
        downloader.get_all_media_items()
    # Add other commands here...

def select_backup_path():
    backup_path = filedialog.askdirectory()
    backup_path_entry.delete(0, tk.END)
    backup_path_entry.insert(0, backup_path)

root = tk.Tk()
root.title("Google Photos Downloader")

# Command selection
command_var = tk.StringVar()
command_var.set('auth')  # Default value
command_menu = tk.OptionMenu(root, command_var, 'auth', 'stats_only', 'validate_only', 'scan_only', 'download_missing', 'fetch_only', 'run_all')
command_menu.pack()

# Backup path entry
backup_path_label = tk.Label(root, text="Backup Path:")
backup_path_label.pack()
backup_path_entry = tk.Entry(root)
backup_path_entry.pack()
backup_path_button = tk.Button(root, text="Select Backup Path", command=select_backup_path)
backup_path_button.pack()

# Start date entry
start_date_label = tk.Label(root, text="Start Date (YYYY-MM-DD):")
start_date_label.pack()
start_date_entry = tk.Entry(root)
start_date_entry.pack()

# End date entry
end_date_label = tk.Label(root, text="End Date (YYYY-MM-DD):")
end_date_label.pack()
end_date_entry = tk.Entry(root)
end_date_entry.pack()

# Number of workers entry
num_workers_label = tk.Label(root, text="Number of Workers:")
num_workers_label.pack()
num_workers_entry = tk.Entry(root)
num_workers_entry.pack()

# Run button
run_button = tk.Button(root, text="Run Command", command=run_command)
run_button.pack()

# Create a text widget for displaying log messages
log_text = tk.Text(root, wrap=tk.WORD)
log_text.pack(fill=tk.BOTH, expand=1)

# Configure the logging system
logger = setup_logging(log_text)
logger.info("Application started.")

# Run button
run_button = tk.Button(root, text="Run Command", command=run_command)
run_button.pack()

root.mainloop()

def main():
    root = tk.Tk()
    log_text = tk.Text(root, wrap=tk.WORD)  # Create a text widget
    log_text.pack(fill=tk.BOTH, expand=1)

    # Configure logging to use the TextHandler
    logger = setup_logging(log_text)

    # Example log messages
    logger.info("This is an info message.")
    logger.warning("This is a warning message.")

    root.mainloop()

if __name__ == "__main__":
    main()









