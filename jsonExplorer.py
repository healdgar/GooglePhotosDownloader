# This script is a utility to explore the structure of a JSON file and tally values or search by regex
# It is useful for when a JSON file is too large to open in a text editor

import json
import re
from collections import defaultdict, OrderedDict
import tkinter as tk
from tkinter import filedialog

data = {}
reverse_sort_order = False
selected_key = ''  # Variable to store the selected key
selected_key_var = ''


def load_json(file_path):
    with open(file_path, 'r') as file:
        return json.load(file)


def collect_keys(data, path='', keys=set()):
    if isinstance(data, dict):
        for key, value in data.items():
            new_path = f"{path}.{key}" if path else key
            keys.add(new_path)
            collect_keys(value, new_path, keys)
    elif isinstance(data, list):
        for index, item in enumerate(data):
            new_path = f"{path}[{index}]" if path else f"[{index}]"
            collect_keys(item, new_path, keys)
    return keys


def display_keys():
    keys_listbox.delete(0, tk.END)
    unique_keys = set()
    for item in data.values():  # Start from the values of the top-level dictionary
        collect_keys(item, path='', keys=unique_keys)
    for key in sorted(unique_keys):
        keys_listbox.insert(tk.END, key)


def load_file():
    file_path = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
    global data
    data = load_json(file_path)
    display_keys()
    update_fields_listbox()  # Add this line


def update_selected_key():
    global selected_key
    selection = keys_listbox.curselection()
    if selection:
        selected_key = keys_listbox.get(selection)
        selected_key_var.set(selected_key)  # Update the StringVar with the selected key
        update_fields_listbox()


def update_fields_listbox():
    global selected_key
    fields_listbox.delete(0, tk.END)
    if not selected_key:  # Check if the selected_key is empty
        return
    keys = selected_key.split('.')  # Split the key path into individual keys

    unique_fields = set()

    for item_id, item in data.items():
        sub_data = item
        try:
            for key in keys[1:]:  # Start from the second key to ignore the first level
                if isinstance(sub_data, list):  # Handle list indices in key path
                    index = int(key[1:-1])  # Extract index from key (e.g., "[0]" -> 0)
                    sub_data = sub_data[index]
                else:
                    sub_data = sub_data[key]  # Navigate through the nested structure
            if isinstance(sub_data, dict):  # If the value is a dictionary, collect fields
                unique_fields.update(sub_data.keys())
        except (KeyError, IndexError, ValueError):
            pass  # Skip if the key or index is not found

    for field in sorted(unique_fields):
        fields_listbox.insert(tk.END, field)



def tally_values_gui():
    global reverse_sort_order
    key = selected_key
    value_tally_result = tally_values(data, key)
    if reverse_sort_order:
        value_tally_result = OrderedDict(reversed(list(value_tally_result.items())))
    result_text.delete(1.0, tk.END)
    result_text.insert(tk.END, f"Tally result for key '{key}':\n")
    for value, count in value_tally_result.items():
        result_text.insert(tk.END, f"  Value: {value} - Count: {count}\n")


def search_values_gui():
    key = selected_key_var.get()  # Use the value of the StringVar
    selected_fields = [fields_listbox.get(idx) for idx in fields_listbox.curselection()]
    pattern = pattern_entry.get()
    matching_values = search_values(data, key, pattern, selected_fields)
    result_text.delete(1.0, tk.END)
    result_text.insert(tk.END, f"Found {len(matching_values)} matching values:\n")
    for item_id, file_path, value, extra_fields in matching_values:
        extra_info = ' - '.join([f"{field}: {extra_fields[field]}" for field in extra_fields])
        result_text.insert(tk.END, f"  - File: {file_path} - Value: {value} - {extra_info}\n")



def toggle_sort_order():
    global reverse_sort_order
    reverse_sort_order = not reverse_sort_order
    tally_values_gui()  # Refresh the display


def tally_values(data, key_path):
    value_tally = defaultdict(int)
    keys = key_path.split('.')  # Split the key path into individual keys

    for item_id, item in data.items():
        value = item
        try:
            for key in keys:
                if isinstance(value, list):  # Handle list indices in key path
                    index = int(key[1:-1])  # Extract index from key (e.g., "[0]" -> 0)
                    value = value[index]
                else:
                    value = value[key]  # Navigate through the nested structure
            if isinstance(value, dict):  # Skip if the value is a dictionary
                continue
            value_tally[value] += 1
        except (KeyError, IndexError, ValueError):
            pass  # Skip if the key or index is not found

    # Sort by count, most common to least common
    sorted_tally = OrderedDict(sorted(value_tally.items(), key=lambda x: x[1], reverse=True))
    return sorted_tally


def search_values(data, key_path, pattern, selected_fields=[]):
    matching_values = []
    keys = key_path.split('.')  # Split the key path into individual keys

    try:
        regex = re.compile(pattern)
    except re.error:
        print(f"Invalid regex pattern: {pattern}")
        return matching_values

    for item_id, item in data.items():
        value = item
        try:
            for key in keys:
                if isinstance(value, list):  # Handle list indices in key path
                    index = int(key[1:-1])  # Extract index from key (e.g., "[0]" -> 0)
                    value = value[index]
                else:
                    value = value[key]  # Navigate through the nested structure
            if isinstance(value, dict):  # Skip if the value is a dictionary
                continue
            if regex.search(str(value)):
                extra_fields = {field: item.get(field, 'N/A') for field in selected_fields}
                matching_values.append((item_id, item.get('file_path', 'N/A'), value, extra_fields))
        except (KeyError, IndexError, ValueError):
            pass  # Skip if the key or index is not found

    return matching_values




root = tk.Tk()
root.title("JSON Explorer")
selected_key_var = tk.StringVar()  # StringVar to store the selected key
selected_key_var.set(selected_key)  # Initialize the StringVar with the temporary variable


load_button = tk.Button(root, text="Load JSON File", command=load_file)
load_button.pack(fill=tk.X)

keys_listbox = tk.Listbox(root)
keys_listbox.bind('<<ListboxSelect>>', lambda event: update_selected_key())
keys_listbox.pack(fill=tk.X)

tally_button = tk.Button(root, text="Tally Values", command=tally_values_gui)
tally_button.pack(fill=tk.X)

reverse_sort_button = tk.Button(root, text="Reverse Sort Order", command=toggle_sort_order)
reverse_sort_button.pack(fill=tk.X)

pattern_label = tk.Label(root, text="Regex Pattern:")
pattern_label.pack(fill=tk.X)

pattern_entry = tk.Entry(root)
pattern_entry.pack(fill=tk.X)

search_button = tk.Button(root, text="Search by Regex", command=search_values_gui)
search_button.pack(fill=tk.X)

fields_listbox_label = tk.Label(root, text="Select Fields to Display:")
fields_listbox_label.pack(fill=tk.X)

fields_listbox = tk.Listbox(root, selectmode=tk.MULTIPLE)
fields_listbox.pack(fill=tk.X)

result_text = tk.Text(root, wrap=tk.WORD)
result_text.pack(fill=tk.BOTH, expand=1)

root.mainloop()
