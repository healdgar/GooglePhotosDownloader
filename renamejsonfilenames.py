import os
import json

# Load the media items data from the JSON file
with open('c:\photos\DownloadItems.json', 'r') as f:
    media_items = json.load(f)

# Iterate over the media items
for item in media_items:
    # Extract the filename and ID from the item
    filename = item['filename']
    id = item['id']

    # Check if filename contains a period
    if '.' in filename:
        # Construct the new filename with 14 digits of id
        new_filename = filename.rsplit('.', 1)[0] + '_' + id[-14:] + '.' + filename.rsplit('.', 1)[1]
    else:
        # If the filename does not contain a period, just append the ID
        new_filename = filename + '_' + id[-14:]

    # Check if 'file_path' key exists in the item
    if 'file_path' in item:
        # Extract the file path from the item
        file_path = item['file_path']

        # Construct the new file path
        directory = os.path.dirname(file_path)
        new_filepath = os.path.join(directory, new_filename)

        # Update the file path in the item
        item['file_path'] = new_filepath.replace('\\', '/')

    # Update the filename in the item
    item['filename'] = new_filename

# Save the updated media items data to the JSON file
with open('c:\photos\DownloadItems(updated).json', 'w') as f:
    json.dump(media_items, f, indent=4)
