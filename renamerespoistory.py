import os
import json

# Load the media items data from the JSON file
with open('your_json_file.json', 'r') as f:
    media_items = json.load(f)

# Iterate over the media items
for item in media_items:
    # Extract the filename and ID from the item
    filename = item['filename']
    id = item['id']

    # Construct the old and new filepaths
    old_filepath = os.path.join('c:\\photos\\', filename)
    new_filename = filename.rsplit('.', 1)[0] + '_' + id[-10:] + '.' + filename.rsplit('.', 1)[1]
    new_filepath = os.path.join('c:\\photos\\', new_filename)

    # Rename the file
    if os.path.exists(old_filepath):
        os.rename(old_filepath, new_filepath)
