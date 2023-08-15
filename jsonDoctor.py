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
# Global variable to store the file path
file_path = ''


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
    global data, file_path
    file_path = filedialog.askopenfilename(filetypes=[("JSON files", "*.json")])
    data = load_json(file_path)
    display_keys()
    update_fields_listbox()  # Add this line

def save_file():
    global data, file_path
    with open(file_path, 'w') as file:
        json.dump(data, file)
    result_text.delete(1.0, tk.END)
    result_text.insert(tk.END, "Changes saved to file.\n")

def save_file_as():
    global data
    new_file_path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON files", "*.json")])
    if new_file_path:  # Check if a file path was selected
        with open(new_file_path, 'w') as file:
            json.dump(data, file)
        result_text.delete(1.0, tk.END)
        result_text.insert(tk.END, f"Changes saved to file: {new_file_path}\n")

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

def replace_values_gui():
    key = selected_key_var.get()  # Use the value of the StringVar
    selected_fields = [fields_listbox.get(idx) for idx in fields_listbox.curselection()]
    pattern = pattern_entry.get()
    replacement = replace_entry.get()  # Get the replacement text
    replace_values(data, key, pattern, replacement, selected_fields)
    result_text.delete(1.0, tk.END)
    result_text.insert(tk.END, "Replacement completed.\n")

def replace_values(data, key_path, pattern, replacement, selected_fields=[]): #note, this will replace values at only 1 level.  YOu cannot replace the first level primary key yet.
    keys = key_path.split('.')  # Split the key path into individual keys

    try:
        regex = re.compile(pattern)
    except re.error:
        print(f"Invalid regex pattern: {pattern}")
        return

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
                new_value = regex.sub(replacement, str(value))  # Perform the replacement
                # Update the value in the data (you'll need to navigate to the value again)
                sub_data = item
                for sub_key in keys[:-1]:
                    if isinstance(sub_data, list):
                        index = int(sub_key[1:-1])
                        sub_data = sub_data[index]
                    else:
                        sub_data = sub_data[sub_key]
                final_key = keys[-1]
                if isinstance(sub_data, list):
                    index = int(final_key[1:-1])
                    sub_data[index] = new_value
                else:
                    sub_data[final_key] = new_value
        except (KeyError, IndexError, ValueError):
            pass  # Skip if the key or index is not found

def rename_key(data, old_key_path, new_key_name):
    keys = old_key_path.split('.')  # Split the key path into individual keys
    for item_id, item in data.items():
        sub_data = item
        try:
            # Navigate to the parent of the target key
            for key in keys[:-1]:
                if isinstance(sub_data, list):
                    index = int(key[1:-1])
                    sub_data = sub_data[index]
                else:
                    sub_data = sub_data[key]
            # Rename the target key
            old_key = keys[-1]
            sub_data[new_key_name] = sub_data.pop(old_key)
        except (KeyError, IndexError, ValueError):
            pass  # Skip if the key or index is not found

def rename_key_gui():
    old_key_path = old_key_entry.get()
    new_key_name = new_key_entry.get()
    rename_key(data, old_key_path, new_key_name)
    display_keys()  # Refresh the keys display
    result_text.delete(1.0, tk.END)
    result_text.insert(tk.END, f"Renamed key '{old_key_path}' to '{new_key_name}'.\n")


root = tk.Tk()
root.title("JSON Doctor")
root.resizable(True, True)
selected_key_var = tk.StringVar()  # StringVar to store the selected key
selected_key_var.set(selected_key)  # Initialize the StringVar with the temporary variable

frame1 = tk.Frame(root)
frame1.pack(fill=tk.X)
load_button = tk.Button(frame1, text="Load JSON File", command=load_file)
load_button.pack(side=tk.LEFT)
save_button = tk.Button(frame1, text="Save Changes", command=save_file)
save_button.pack(side=tk.LEFT)
save_as_button = tk.Button(frame1, text="Save As", command=save_file_as)
save_as_button.pack(side=tk.LEFT)

keys_listbox = tk.Listbox(root)
keys_listbox.bind('<<ListboxSelect>>', lambda event: update_selected_key())
keys_listbox.pack(fill=tk.X)

tally_frame = tk.Frame(root)
tally_frame.pack(fill=tk.X)
tally_button = tk.Button(tally_frame, text="Tally Values", command=tally_values_gui)
tally_button.pack(side=tk.LEFT)
reverse_sort_button = tk.Button(tally_frame, text="Reverse Sort Order", command=toggle_sort_order)
reverse_sort_button.pack(side=tk.LEFT)

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

replace_label = tk.Label(root, text="Replace With:")
replace_label.pack(fill=tk.X)
replace_entry = tk.Entry(root)
replace_entry.pack(fill=tk.X)
replace_button = tk.Button(root, text="Replace by Regex", command=replace_values_gui)
replace_button.pack(fill=tk.X)

frame2 = tk.Frame(root)
frame2.pack(fill=tk.X)
old_key_label = tk.Label(frame2, text="Old Key Name/Path:")
old_key_label.grid(row=0, column=0)
old_key_entry = tk.Entry(frame2)
old_key_entry.grid(row=0, column=1)
new_key_label = tk.Label(frame2, text="New Key Name:")
new_key_label.grid(row=1, column=0)
new_key_entry = tk.Entry(frame2)
new_key_entry.grid(row=1, column=1)
rename_button = tk.Button(frame2, text="Rename Key", command=rename_key_gui)
rename_button.grid(row=2, columnspan=2)
frame2.grid_columnconfigure(1, weight=1)  # Make the second column expandable

scrollbar = tk.Scrollbar(root)
scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
result_text = tk.Text(root, wrap=tk.WORD, yscrollcommand=scrollbar.set)
result_text.pack(fill=tk.BOTH, expand=1)
scrollbar.config(command=result_text.yview)

root.mainloop()
