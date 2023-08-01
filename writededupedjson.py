import json

def remove_duplicates(json_file):
    with open(json_file, 'r') as f:
        data = json.load(f)

    # Create a new list with duplicates removed
    new_data = []
    seen_ids = set()
    for item in data:
        if item['id'] not in seen_ids:
            seen_ids.add(item['id'])
            new_data.append(item)

    # Write the new data to a new JSON file
    with open('DownloadItems.json', 'w') as f:
        json.dump(new_data, f, indent=4)

    print(f"Removed duplicates. The JSON file has been updated.")

# Replace 'your_file.json' with the path to your JSON file
remove_duplicates('c:\photos\DownloadItems.json')
