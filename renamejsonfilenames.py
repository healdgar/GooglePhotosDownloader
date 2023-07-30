import json

# Load the media items data from the JSON file
with open('your_json_file.json', 'r') as f:
    media_items = json.load(f)

# Iterate over the media items
for item in media_items:
    # Extract the filename and ID from the item
    filename = item['filename']
    id = item['id']

    # Construct the new filename
    new_filename = filename.rsplit('.', 1)[0] + '_' + id[-10:] + '.' + filename.rsplit('.', 1)[1]

    # Update the filename in the item
    item['filename'] = new_filename

# Save the updated media items data to the JSON file
with open('your_json_file.json', 'w') as f:
    json.dump(media_items, f, indent=4)
