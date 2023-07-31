import os
import json

# Load the media items data from the JSON file
with open('c:\\photos\\DownloadItems.json', 'r') as f:
    media_items = json.load(f)

# Prepare a dictionary of id and filename for quick lookup
id_filename_dict = {item['id']: item['filename'] for item in media_items}

# Root directory from where to start renaming files
root_directory = 'c:\\photos\\'

# Walk through root directory, and its all subdirectories, and list all files
for foldername, subfolders, filenames in os.walk(root_directory):
    for filename in filenames:
        old_filepath = os.path.join(foldername, filename)

        # check if the file id is in the id_filename_dict dictionary
        for id, original_filename in id_filename_dict.items():
            if original_filename in old_filepath:
                # Check if filename contains a period
                if '.' in original_filename:
                    # Split the filename at the period and construct the new filename
                    new_filename = original_filename.rsplit('.', 1)[0] + '_' + id[-14:] + '.' + original_filename.rsplit('.', 1)[1]
                    new_filepath = old_filepath.replace(original_filename, new_filename)
                    
                    # Rename the file only if it exists and is in the index
                    if os.path.exists(old_filepath):
                        os.rename(old_filepath, new_filepath)


